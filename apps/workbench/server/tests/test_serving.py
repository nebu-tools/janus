"""The worker processes, the command, the host check and the client's files."""

import json
import os
import signal
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import INVOICE, serve, upload
from janus_workbench import cli
from janus_workbench.app import create_app
from janus_workbench.jobs import JobCancelled, JobFailed, Jobs
from janus_workbench.store import Store


def test_a_job_gives_its_result():
    assert Jobs().run(max, 2, 7, deadline=10) == 7


def test_a_worker_that_dies_costs_only_itself():
    jobs = Jobs()
    with pytest.raises(JobFailed, match="stopped"):
        jobs.run(os._exit, 3, deadline=10)
    with pytest.raises(JobFailed, match="stopped"):
        jobs.run(signal.raise_signal, signal.SIGKILL, deadline=10)
    assert jobs.run(max, 1, 2, deadline=10) == 2  # the next job runs as if nothing happened


def test_an_answer_after_the_deadline_does_not_count():
    with pytest.raises(JobFailed, match="longer than the limit of 0 seconds"):
        Jobs().run(max, 1, 2, deadline=0)


def test_a_worker_that_hangs_is_killed_at_the_deadline():
    started = time.monotonic()
    with pytest.raises(JobFailed, match=r"longer than the limit of 0\.2 seconds"):
        Jobs().run(time.sleep, 60, deadline=0.2)
    assert time.monotonic() - started < 5


def test_a_job_can_be_cancelled():
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    with pytest.raises(JobCancelled):
        Jobs().run(time.sleep, 60, deadline=30, cancel=cancel)


def test_a_failure_inside_the_job_is_reported_without_its_details():
    with pytest.raises(JobFailed, match=r"Janus failed on this file \(FileNotFoundError\)"):
        Jobs().run(os.stat, "/nonexistent/secret/path", deadline=10)


def resolver(names: dict[str, list[str]]):
    """A resolver that knows `names` and resolves a literal address as the system does."""

    def resolve(host, port, **_):
        if host in names:
            return [
                (socket.AF_INET6 if ":" in a else socket.AF_INET, 1, 6, "", (a, port))
                for a in names[host]
            ]
        return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)

    return resolve


def test_serve_listens_only_on_loopback_addresses_without_the_flag(monkeypatch, capsys, tmp_path):
    import uvicorn

    from janus_workbench import app

    calls, hosts = [], []
    monkeypatch.setattr(uvicorn, "run", lambda _, **options: calls.append(options))
    create_app = app.create_app
    monkeypatch.setattr(
        app, "create_app", lambda *a, **kw: hosts.append(kw["hosts"]) or create_app(*a, **kw)
    )
    monkeypatch.setenv("JANUS_DATA_DIR", str(tmp_path))
    resolve = resolver(
        {
            "localhost": ["127.0.0.1", "::1"],
            "dev.example": ["127.0.0.1"],
            "mixed.example": ["127.0.0.1", "192.0.2.7"],  # one of its addresses is another machine
            "far.example": ["192.0.2.7"],
        }
    )

    def serve(*args: str) -> int:
        return cli.main(["serve", *args], resolve=resolve)

    for host in ("0.0.0.0", "::", "192.0.2.7", "mixed.example", "far.example"):
        assert serve("--host", host) == 2, host
    assert calls == []
    assert "--listen-without-auth" in capsys.readouterr().err

    assert serve() == 0
    assert serve("--host", "localhost") == 0
    assert serve("--host", "::1", "--port", "9000") == 0
    assert serve("--host", "dev.example") == 0
    assert serve("--host", "0.0.0.0", "--listen-without-auth") == 0
    assert serve("--host", "::", "--listen-without-auth") == 0
    # It listens on the address it checked, never on a name looked up again.
    assert [(c["host"], c["port"]) for c in calls] == [
        ("127.0.0.1", 8440),
        ("127.0.0.1", 8440),
        ("::1", 9000),
        ("127.0.0.1", 8440),
        ("0.0.0.0", 8440),
        ("::", 8440),
    ]
    assert "dev.example" in hosts[3] and hosts[4] is None and hosts[5] is None


def test_serve_says_so_when_a_name_does_not_resolve(capsys):
    def resolve(*_, **__):
        raise socket.gaierror("Name or service not known")

    assert cli.main(["serve", "--host", "nowhere.example"], resolve=resolve) == 2
    assert "cannot resolve nowhere.example" in capsys.readouterr().err


def test_openapi_prints_the_api(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("JANUS_DATA_DIR", str(tmp_path / "unused"))
    assert cli.main(["openapi"]) == 0
    paths = json.loads(capsys.readouterr().out)["paths"]
    assert "/api/documents/{document}/extract" in paths
    assert not (tmp_path / "unused").exists()


def test_a_request_under_another_host_name_is_refused(client, settings):
    assert client.get("/api/documents", headers={"host": "example.org"}).status_code == 400
    assert client.get("/api/documents", headers={"host": "localhost:8440"}).status_code == 200
    assert client.get("/api/documents", headers={"host": "[::1]:8440"}).status_code == 200
    with serve(settings, hosts=None) as open_client:
        assert open_client.get("/api/documents", headers={"host": "example.org"}).status_code == 200


FOREIGN = {"origin": "https://elsewhere.example"}


def test_a_request_from_a_page_on_another_site_is_refused(client, read):
    row = read(client, INVOICE)
    image = f"/api/documents/{row['id']}/pages/1/image"
    assert client.get(image).status_code == 200
    assert client.get(image, headers={"origin": "http://127.0.0.1"}).status_code == 200
    assert client.get(image, headers=FOREIGN).status_code == 403
    assert client.get(image, headers={"origin": "null"}).status_code == 403
    form = client.post(
        "/api/documents",
        content=b"name=x",
        headers={**FOREIGN, "content-type": "application/x-www-form-urlencoded"},
    )
    assert form.status_code == 403
    plain = client.post(
        f"/api/documents/{row['id']}/extract",
        content='{"spec": "fields: {}"}',
        headers={**FOREIGN, "content-type": "text/plain"},
    )
    assert plain.status_code == 403
    assert plain.json() == {"detail": "the workbench answers only its own pages"}
    delete = client.delete(f"/api/documents/{row['id']}", headers=FOREIGN)
    assert delete.status_code == 403
    assert len(client.get("/api/documents").json()) == 1


def test_every_answer_may_be_used_only_by_the_workbench_s_own_pages(client):
    row = upload(client, INVOICE.read_bytes())
    answers = [
        client.get("/api/documents"),
        client.get(f"/api/documents/{row['id']}/pages/1/image"),
        client.get("/api/nothing"),
        client.get("/api/documents", headers={"host": "example.org"}),
        client.get("/api/documents", headers=FOREIGN),
        client.get("/"),
    ]
    for answer in answers:
        assert answer.headers["cross-origin-resource-policy"] == "same-origin", answer.url
        assert answer.headers["x-content-type-options"] == "nosniff", answer.url


def safe(answer) -> bool:
    return (
        answer.headers.get("cross-origin-resource-policy") == "same-origin"
        and answer.headers.get("x-content-type-options") == "nosniff"
    )


def test_an_unhandled_error_is_answered_500_with_the_same_headers(settings, monkeypatch):
    def broken(_):
        raise OSError("the disk failed")

    monkeypatch.setattr(Store, "rows", broken)
    app = create_app(settings, static=None)
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        answer = client.get("/api/documents")
        assert answer.status_code == 500 and safe(answer), dict(answer.headers)
        assert "disk" not in answer.text
        refused = client.get("/api/documents", headers=FOREIGN)
        assert refused.status_code == 403 and safe(refused)


def test_a_client_file_and_an_unknown_path_carry_the_headers(settings, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>Janus</title>")
    (static / "assets" / "app-1a2b.js").write_text("console.log(1)")
    with TestClient(create_app(settings, static=static), base_url="http://127.0.0.1") as client:
        script = client.get("/assets/app-1a2b.js")
        assert script.status_code == 200 and safe(script)
        page = client.get("/nothing/here")  # the page fallback
        assert page.status_code == 200 and safe(page)
        unknown = client.get("/api/nothing/here")
        assert unknown.status_code == 404 and safe(unknown)
        wrong = client.post("/api/specs")
        assert wrong.status_code == 405 and safe(wrong)


def test_the_client_is_served_from_a_list_of_its_own_files(settings, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>Janus</title>")
    (static / "assets" / "app-1a2b.js").write_text("console.log(1)")
    (tmp_path / "outside.txt").write_text("not the client's")
    app = create_app(settings, static=static)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").text == "<title>Janus</title>"
        assert client.get("/d/" + "0" * 64).text == "<title>Janus</title>"  # a client route
        script = client.get("/assets/app-1a2b.js")
        assert script.text == "console.log(1)" and "javascript" in script.headers["content-type"]
        assert "immutable" in script.headers["cache-control"]
        for path in ("/../outside.txt", "/%2e%2e/outside.txt", "/assets/..%2F..%2Foutside.txt"):
            assert "not the client's" not in client.get(path).text
        assert client.get("/api/nothing").status_code == 404


def test_without_a_built_client_the_page_says_how_to_build_it(client):
    response = client.get("/")
    assert response.status_code == 503 and "pnpm build" in response.text
