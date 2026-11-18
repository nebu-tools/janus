"""Uploading, reading and removing documents, including files meant to break the reader."""

import hashlib
import json
from dataclasses import replace

import pymupdf
import pytest

from conftest import INVOICE, PARTS, PDF, serve, settled, upload
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


def test_the_same_file_sent_twice_is_one_document(client, read):
    first = read(client, INVOICE, "a.pdf")
    again = upload(client, INVOICE.read_bytes(), "b.pdf")
    assert again["id"] == first["id"] and again["status"] == "ready"
    assert len(client.get("/api/documents").json()) == 1


def test_a_file_that_is_not_a_pdf_fails_with_a_plain_reason(client, read):
    row = read(client, b"Dear reader, this is a letter and no PDF.", "letter.txt")
    assert row["status"] == "failed"
    assert row["error"] == "the file does not start with %PDF-"
    broken = read(client, b"%PDF-1.7\nnothing that follows is a PDF", "broken.pdf")
    assert broken["status"] == "failed" and "cannot be opened" in broken["error"]
    # A failed document has nothing to inspect.
    assert client.get(f"/api/documents/{row['id']}/inspect").status_code == 409


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


def test_a_read_cut_off_by_a_stop_is_finished_at_the_next_start(settings):
    data = PARTS.read_bytes()
    document = hashlib.sha256(data).hexdigest()
    store = Store(settings.data_dir)
    upload_path = store.incoming / "upload"
    upload_path.write_bytes(data)
    store.add(upload_path, document, "parts.pdf", len(data))
    store.update(document, status="reading", pages=3)
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
    layer = settings.data_dir / "layers" / f"{row['layer']}.json"
    assert layer.is_file() and json.loads(layer.read_text())["document_hash"] == row["id"]
    assert client.delete(f"/api/documents/{row['id']}").status_code == 204
    assert client.get("/api/documents").json() == []
    assert not layer.exists()
    assert list((settings.data_dir / "documents").iterdir()) == []


def test_the_name_sent_with_a_file_is_shown_and_never_becomes_a_path(client, read, settings):
    row = read(client, INVOICE, "../../outside\x00.pdf")
    assert row["name"] == "../../outside.pdf"
    names = {p.name for p in settings.data_dir.rglob("*")}
    assert not any("outside" in name for name in names)
    assert not (settings.data_dir.parent / "outside.pdf").exists()
