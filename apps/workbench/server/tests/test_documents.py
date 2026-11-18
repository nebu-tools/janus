"""Uploading, reading and removing documents, including files meant to break the reader."""

import hashlib
import http.client
import json
import multiprocessing
import re
import socket
import threading
import time
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from conftest import INVOICE, PARTS, PDF, live, serve, settled, upload, wait_until
from janus_workbench import reading, work
from janus_workbench import store as store_module
from janus_workbench.jobs import Jobs
from janus_workbench.reading import Reader
from janus_workbench.settings import Settings
from janus_workbench.store import Store, Unknown, _checked

# Not found, no such method on what the path decodes to, or not the pattern.
REFUSED = (404, 405, 422)


def test_an_uploaded_pdf_is_read_and_listed_with_what_was_found(client, read):
    row = read(client, INVOICE, "invoice.pdf")
    assert row["id"] == hashlib.sha256(INVOICE.read_bytes()).hexdigest()
    assert (row["status"], row["name"], row["size"]) == (
        "ready",
        "invoice.pdf",
        INVOICE.stat().st_size,
    )
    assert (row["pages"], row["pages_read"], row["engine"]) == (1, 1, "pymupdf")
    assert row["tables"] == 0 and row["read_seconds"] > 0 and row["error"] is None
    parts = read(client, PARTS, "parts.pdf")
    assert (parts["pages"], parts["pages_read"], parts["tables"]) == (3, 3, 3)
    assert [r["name"] for r in client.get("/api/documents").json()] == ["parts.pdf", "invoice.pdf"]


def names(client) -> list[str]:
    return [r["name"] for r in client.get("/api/documents").json()]


def test_the_last_upload_comes_first_also_after_a_restart(settings, read):
    other = INVOICE.read_bytes() + b"\n%another copy\n"  # still a PDF, other bytes
    with serve(settings) as client:
        a, b = read(client, INVOICE, "a.pdf"), read(client, PARTS, "b.pdf")
        assert names(client) == ["b.pdf", "a.pdf"] and b["order"] > a["order"]
        assert client.delete(f"/api/documents/{b['id']}").status_code == 204
    # The last key given out is kept on disk, so a key is never given out twice, even when
    # the row that had it is gone.
    with serve(settings) as client:
        c = read(client, other, "c.pdf")
        assert c["order"] > b["order"]
        assert names(client) == ["c.pdf", "a.pdf"]


def test_the_same_file_sent_again_stays_one_row_in_its_place(client, read):
    first = read(client, INVOICE, "a.pdf")
    read(client, PARTS, "b.pdf")
    again = upload(client, INVOICE.read_bytes(), "c.pdf")
    assert (again["id"], again["order"], again["status"]) == (first["id"], first["order"], "ready")
    assert names(client) == ["b.pdf", "a.pdf"]  # the name it was first sent with stays


def test_two_uploads_of_the_same_file_at_once_make_one_row(settings, monkeypatch):
    """The first upload stops in the middle of `Store.add`, after it took its order key and
    before its row exists. The second must wait for it. Without the lock it would find no row,
    take a second key and write a second row."""
    store = Store(settings.data_dir)
    data = INVOICE.read_bytes()
    document = hashlib.sha256(data).hexdigest()
    inside, waiting, go = threading.Semaphore(0), threading.Event(), threading.Event()
    write = store_module._write

    def write_slowly(path, content):
        if path.name == "order":
            inside.release()
            assert go.wait(30)
        write(path, content)

    class Watched:
        """The store's lock; it says when someone has to wait for it."""

        def __init__(self, lock) -> None:
            self.lock = lock

        def __enter__(self):
            if not self.lock.acquire(blocking=False):
                waiting.set()
                self.lock.acquire()

        def __exit__(self, *_):
            self.lock.release()

    monkeypatch.setattr(store_module, "_write", write_slowly)
    monkeypatch.setattr(store, "_lock", Watched(store._lock))
    rows = []

    def send(name: str) -> None:
        upload = store.incoming / name
        upload.write_bytes(data)
        rows.append(store.add(upload, document, name, len(data)))

    first = threading.Thread(target=send, args=("first.pdf",))
    first.start()
    assert inside.acquire(timeout=30)
    second = threading.Thread(target=send, args=("second.pdf",))
    second.start()
    # The second upload either waits for the lock, or it is inside `add` beside the first.
    wait_until(lambda: waiting.is_set() or inside.acquire(blocking=False), "at the lock")
    alone = waiting.is_set()
    go.set()
    first.join()
    second.join()
    assert alone, "two uploads were inside Store.add at once"
    assert [(row.order, row.name) for row in rows] == [(0, "first.pdf")] * 2
    assert (settings.data_dir / "order").read_text() == "1"
    assert [d.name for d in store.documents.iterdir()] == [document]
    assert list(store.incoming.iterdir()) == []


def post(address: tuple[str, int], body: bytes, name: str = "document.pdf") -> tuple[int, dict]:
    connection = http.client.HTTPConnection(*address, timeout=60)
    try:
        connection.request("POST", f"/api/documents?name={name}", body=body, headers=PDF)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_a_file_that_is_not_a_pdf_is_refused_and_not_kept(client, read, settings):
    letter = client.post(
        "/api/documents",
        params={"name": "letter.pdf"},
        content=b"Dear reader, this is a letter and no PDF.",
        headers=PDF,
    )
    assert letter.status_code == 422
    assert letter.json()["detail"] == "the file is not a PDF: it does not start with %PDF-"
    assert client.get("/api/documents").json() == []
    assert list((settings.data_dir / "incoming").iterdir()) == []
    assert list((settings.data_dir / "documents").iterdir()) == []
    broken = read(client, b"%PDF-1.7\nnothing that follows is a PDF", "broken.pdf")
    assert broken["status"] == "failed" and "cannot be opened" in broken["error"]
    # A failed document has nothing to inspect.
    assert client.get(f"/api/documents/{broken['id']}/inspect").status_code == 409


EMPTY_PDF = (
    b"%PDF-1.4\n1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
    b"2 0 obj <</Type /Pages /Kids [] /Count 0>> endobj\n"
    b"trailer <</Root 1 0 R>>\n%%EOF\n"
)


def test_a_pdf_with_no_pages_fails_with_a_plain_reason(client, read):
    row = read(client, EMPTY_PDF, "empty.pdf")
    assert (row["status"], row["error"]) == ("failed", "the PDF has no pages")


def test_an_encrypted_pdf_fails_with_a_plain_reason(client, read):
    with pymupdf.open(INVOICE) as doc:
        locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    row = read(client, locked, "locked.pdf")
    assert row["status"] == "failed"
    assert row["error"] == "the PDF is encrypted and needs a password to open"


def test_an_upload_over_the_limit_is_refused_and_nothing_is_kept(settings):
    with serve(replace(settings, max_upload_bytes=1000)) as client:
        declared = client.post("/api/documents", content=INVOICE.read_bytes(), headers=PDF)
        assert declared.status_code == 413
        assert "larger than the limit of 1000 bytes" in declared.json()["detail"]

        def chunks():  # no Content-Length, so the server has to count as it reads
            data = INVOICE.read_bytes()
            for i in range(0, len(data), 300):
                yield data[i : i + 300]

        streamed = client.post("/api/documents", content=chunks(), headers=PDF)
        assert streamed.status_code == 413
        assert client.get("/api/documents").json() == []
        assert list((settings.data_dir / "incoming").iterdir()) == []
        assert list((settings.data_dir / "documents").iterdir()) == []


def request_head(length: str) -> bytes:
    return (
        "POST /api/documents HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Content-Type: application/pdf\r\n{length}\r\n\r\n"
    ).encode()


def answer_to(sock: socket.socket) -> bytes:
    """The whole answer on `sock`: its head, and a body of the length the head gives."""
    answer = b""
    while b"\r\n\r\n" not in answer or len(answer.partition(b"\r\n\r\n")[2]) < int(
        re.search(rb"content-length: (\d+)", answer, re.IGNORECASE)[1]  # ty: ignore[not-subscriptable]
    ):
        received = sock.recv(4096)
        assert received, answer  # the server closed the connection before it answered
        answer += received
    return answer


def test_an_upload_over_the_limit_is_answered_while_it_is_still_being_sent(settings):
    incoming = settings.data_dir / "incoming"
    with live(replace(settings, max_upload_bytes=1000)) as address:
        with socket.create_connection(address, timeout=60) as sock:
            sock.sendall(request_head("Transfer-Encoding: chunked"))
            for n in range(4):  # 1 200 bytes, and the body never ends
                chunk = (b"%PDF-" if n == 0 else b"") + b"x" * (300 - (5 if n == 0 else 0))
                sock.sendall(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            answer = answer_to(sock)
            assert answer.startswith(b"HTTP/1.1 413 "), answer
            assert b"larger than the limit of 1000 bytes" in answer
        wait_until(lambda: not any(incoming.iterdir()), "the partial upload deleted")
    assert list((settings.data_dir / "documents").iterdir()) == []


def test_an_upload_the_client_hangs_up_on_leaves_no_file(settings):
    incoming = settings.data_dir / "incoming"
    with live(settings) as address:
        with socket.create_connection(address, timeout=60) as sock:
            sock.sendall(request_head("Content-Length: 100000") + b"%PDF-" + b"x" * 20000)
            wait_until(lambda: any(incoming.iterdir()), "the upload started")
        # The connection is closed with most of the body still to come.
        wait_until(lambda: not any(incoming.iterdir()), "the partial upload deleted")
        assert list((settings.data_dir / "documents").iterdir()) == []


def test_an_upload_must_be_sent_as_a_pdf_and_have_a_body(client):
    as_text = client.post(
        "/api/documents", content=b"%PDF-", headers={"content-type": "text/plain"}
    )
    assert as_text.status_code == 415
    assert client.post("/api/documents", content=b"", headers=PDF).status_code == 400


def test_a_document_with_more_pages_than_the_limit_fails(settings):
    with serve(replace(settings, max_pages=2)) as client:
        row = settled(client, upload(client, PARTS.read_bytes())["id"])
        assert row["status"] == "failed"
        assert row["error"] == "the PDF has 3 pages and the limit is 2"


def test_a_read_that_outlives_its_deadline_fails_and_the_server_goes_on(settings):
    with serve(replace(settings, read_deadline=0.001)) as client:
        row = settled(client, upload(client, PARTS.read_bytes())["id"])
        assert row["status"] == "failed"
        assert row["error"] == "reading took longer than the limit of 0.001 seconds"
        assert client.get("/api/documents").status_code == 200


def test_sending_a_failed_document_again_reads_it_again(settings):
    with serve(replace(settings, read_deadline=0.001)) as client:
        row = settled(client, upload(client, INVOICE.read_bytes())["id"])
        assert row["status"] == "failed"
    with serve(settings) as client:
        assert client.get("/api/documents").json()[0]["status"] == "failed"
        assert settled(client, upload(client, INVOICE.read_bytes())["id"])["status"] == "ready"


def keep(store: Store, data: bytes, name: str = "document.pdf") -> str:
    """Hand bytes to the store as an upload would, and return the document's hash."""
    document = hashlib.sha256(data).hexdigest()
    path = store.incoming / name
    path.write_bytes(data)
    store.add(path, document, name, len(data))
    return document


def test_reads_cut_off_by_a_stop_are_finished_at_the_next_start(settings):
    data = PARTS.read_bytes()
    store = Store(settings.data_dir)
    document = keep(store, data, "parts.pdf")
    waiting = keep(store, INVOICE.read_bytes(), "invoice.pdf")
    assert store.claim() == document
    store.update(document, pages=3)
    # Two of three pages were read before the stop.
    from janus_pdf.document import engines

    pages = engines._PageStore(store.page_cache(document), data, engines.PyMuPDFParser().recipe)
    with pymupdf.open(PARTS) as doc:
        for index in (0, 1):
            pages.put(engines.pymupdf_page_input(doc[index]))
    assert store.row(document).pages_read == 2

    with serve(settings) as client:
        row = settled(client, document)
        assert (row["status"], row["pages_read"], row["tables"]) == ("ready", 3, 3)
        assert not store.page_cache(document).exists()  # the cache has done its work
        assert settled(client, waiting)["status"] == "ready"


def test_a_row_is_ready_only_once_its_page_cache_is_gone(settings, monkeypatch):
    store = Store(settings.data_dir)
    document = keep(store, INVOICE.read_bytes())
    seen = []
    rmtree = store_module.shutil.rmtree

    def watched(path, ignore_errors=False):
        if Path(path) == store.page_cache(document):
            # What anyone who lists the documents would see while the cache is deleted.
            (row,) = store.rows()
            seen.append((row.status, Path(path).is_dir()))
        rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(store_module.shutil, "rmtree", watched)
    reader = Reader(store, Jobs(), settings)
    reader.start()
    try:
        wait_until(lambda: store.row(document).status == "ready", "read")
    finally:
        reader.close()
    assert seen == [("reading", True)]
    assert not store.page_cache(document).exists()


def test_a_start_deletes_the_page_cache_of_every_document_not_waiting_to_be_read(settings):
    store = Store(settings.data_dir)
    ready, failed, queued = (keep(store, INVOICE.read_bytes() + bytes([n])) for n in range(3))
    store.finish(ready, status="ready")
    store.finish(failed, status="failed", error="no")
    for document in (ready, failed, queued):
        store.page_cache(document).mkdir()
        (store.page_cache(document) / "left-over.json").write_text("{}")
    store = Store(settings.data_dir)
    assert [store.page_cache(d).exists() for d in (ready, failed, queued)] == [False, False, True]


def test_the_end_of_a_read_takes_the_parts_a_killed_writer_left(settings):
    store = Store(settings.data_dir)
    done, broken = (keep(store, INVOICE.read_bytes() + bytes([n])) for n in range(2))
    for document in (done, broken):
        store.page_cache(document).mkdir()
        (store.page_cache(document) / f".{'0' * 64}-abc.part").write_bytes(b"half a page")
    store.finish(done, status="ready")
    store.finish(broken, status="failed", error="no")
    assert not store.page_cache(done).exists()
    assert not store.page_cache(broken).exists()


class FakeJobs:
    """Reads that take no time, except that each waits for `gate`. Records what it read."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.started = threading.Event()
        self.read: list[str] = []
        self.at_once = self.most_at_once = 0
        self._lock = threading.Lock()

    def run(self, fn, pdf, *_args, **_limits):
        if fn is work.count_pages:
            return 1
        with self._lock:
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
        self.started.set()
        self.gate.wait()
        with self._lock:
            self.at_once -= 1
            self.read.append(Path(pdf).parent.name)
        return {"layer": "0" * 64, "engine": "fake", "tables": 0}


def queue_up(settings: Settings, count: int) -> tuple[Store, list[str]]:
    store = Store(settings.data_dir)
    documents = [keep(store, f"%PDF-{n}".encode(), f"{n}.pdf") for n in range(count)]
    return store, documents


def held_by_the_reader(settings: Settings, count: int) -> int:
    """Bytes the reading module holds while `count` uploads wait behind one read."""
    store, documents = queue_up(settings, count)
    jobs = FakeJobs()
    tracemalloc.start()
    try:
        reader = Reader(store, jobs, replace(settings, read_workers=1))  # ty: ignore[invalid-argument-type]
        reader.start()
        jobs.started.wait(30)
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    jobs.gate.set()
    wait_until(lambda: len(jobs.read) == count, "all read")
    reader.close()
    assert jobs.read == documents and jobs.most_at_once == 1
    held = snapshot.filter_traces([tracemalloc.Filter(True, reading.__file__)])
    return sum(stat.size for stat in held.statistics("filename"))


def test_a_thousand_uploads_wait_on_disk_and_are_read_one_by_one_in_order(tmp_path):
    few = held_by_the_reader(Settings(data_dir=tmp_path / "few", read_workers=1), 10)
    many = held_by_the_reader(Settings(data_dir=tmp_path / "many", read_workers=1), 1000)
    assert many - few < 1024, (few, many)  # nothing is held per waiting upload


def test_removing_a_waiting_document_takes_it_out_of_the_queue(settings):
    store, (first, second, third) = queue_up(settings, 3)
    jobs = FakeJobs()
    reader = Reader(store, jobs, replace(settings, read_workers=1))  # ty: ignore[invalid-argument-type]
    reader.start()
    jobs.started.wait(30)
    reader.remove(second)
    jobs.gate.set()
    wait_until(lambda: store.row(third).status == "ready", "read")
    reader.close()
    assert jobs.read == [first, third]
    assert not (settings.data_dir / "documents" / second).exists()


class SlowJobs(Jobs):
    """Every job is a worker process that sleeps for a minute."""

    def run(self, fn, *args, deadline, cancel=None):  # noqa: ARG002
        return super().run(time.sleep, 60, deadline=deadline, cancel=cancel)


def test_removing_a_document_being_read_kills_its_worker_process(settings):
    store = Store(settings.data_dir)
    document = keep(store, INVOICE.read_bytes())
    reader = Reader(store, SlowJobs(), settings)
    reader.start()
    try:
        wait_until(lambda: multiprocessing.active_children(), "a worker started")
        (worker,) = multiprocessing.active_children()
        started = time.monotonic()
        reader.remove(document)
        assert time.monotonic() - started < 30  # far less than the minute the worker sleeps
        assert not worker.is_alive() and worker.exitcode is not None  # killed and reaped
        assert store.rows() == []
        assert not (settings.data_dir / "documents" / document).exists()
    finally:
        reader.close()


@pytest.mark.parametrize(
    "document",
    [
        "abc",
        "A" * 64,  # upper case is not what the server computes
        "g" * 64,
        "0" * 63,
        "0" * 65,
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f" + "0" * 55,
        "0" * 64 + "%00",
    ],
)
def test_a_hash_that_is_not_a_hash_is_refused(client, document):
    for path in ("/inspect", "/pages/1", "/pages/1/image"):
        assert client.get(f"/api/documents/{document}{path}").status_code in REFUSED
    assert client.delete(f"/api/documents/{document}").status_code in REFUSED
    assert (
        client.post(f"/api/documents/{document}/extract", json={"spec": "x"}).status_code in REFUSED
    )


def test_no_path_is_built_from_anything_but_a_hash(settings):
    store = Store(settings.data_dir)
    for bad in ("", "..", "../" + "0" * 61, "0" * 64 + "/..", "0" * 63 + "\n", "A" * 64, None):
        with pytest.raises(Unknown):
            _checked(bad)  # ty: ignore[invalid-argument-type]
        with pytest.raises(Unknown):
            store.pdf(bad)  # ty: ignore[invalid-argument-type]
    assert store.pdf("0" * 64).parent.parent == settings.data_dir / "documents"


def test_an_unknown_document_is_not_found(client):
    unknown = "0" * 64
    assert client.get(f"/api/documents/{unknown}/inspect").status_code == 404
    assert client.get(f"/api/documents/{unknown}/pages/1/image").status_code == 404
    assert client.delete(f"/api/documents/{unknown}").status_code == 404


def test_removing_a_document_removes_its_files(client, read, settings):
    row = read(client, INVOICE)
    client.get(f"/api/documents/{row['id']}/pages/1/image")
    layer = settings.data_dir / "documents" / row["id"] / "layer.json"
    assert layer.is_file() and json.loads(layer.read_text())["document_hash"] == row["id"]
    assert client.delete(f"/api/documents/{row['id']}").status_code == 204
    assert client.get("/api/documents").json() == []
    assert not layer.exists()
    assert list((settings.data_dir / "documents").iterdir()) == []


@pytest.mark.parametrize(
    ("sent", "shown"),
    [
        ("../../outside.pdf", "outside.pdf"),
        ("a/b/outside.pdf", "outside.pdf"),
        ("a\\b\\outside.pdf", "outside.pdf"),
        ("..", "document.pdf"),
        ("dir/..", "document.pdf"),
        ("", "document.pdf"),
        ("out\x00side\n\x1b[31m.pdf", "outside[31m.pdf"),
        ("o" * 4000, "o" * 200),
    ],
)
def test_the_name_sent_with_a_file_is_shown_and_never_becomes_a_path(
    client, read, settings, tmp_path, sent, shown
):
    row = read(client, INVOICE, sent)
    assert row["name"] == shown
    assert list(tmp_path.iterdir()) == [settings.data_dir]  # nothing outside the data directory
    files = {p.relative_to(settings.data_dir).as_posix() for p in settings.data_dir.rglob("*")}
    assert files == {
        "order",
        "incoming",
        "specs",
        "documents",
        f"documents/{row['id']}",
        f"documents/{row['id']}/document.pdf",
        f"documents/{row['id']}/row.json",
        f"documents/{row['id']}/layer.json",
    }
