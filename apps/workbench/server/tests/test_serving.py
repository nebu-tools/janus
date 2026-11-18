"""The worker processes, the command, the host check and the client's files."""

import json
import os
import signal
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import serve
from janus_workbench import cli
from janus_workbench.app import create_app
from janus_workbench.jobs import JobCancelled, JobFailed, Jobs


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


def test_serve_refuses_an_outside_address_without_the_flag(monkeypatch, capsys, tmp_path):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda _, **options: calls.append(options))
    monkeypatch.setenv("JANUS_DATA_DIR", str(tmp_path))
    for host in ("0.0.0.0", "192.168.1.20", "::", "example.org"):
        assert cli.main(["serve", "--host", host]) == 2
    assert calls == []
    assert "--listen-without-auth" in capsys.readouterr().err

    assert cli.main(["serve"]) == 0
    assert cli.main(["serve", "--host", "::1", "--port", "9000"]) == 0
    assert cli.main(["serve", "--host", "0.0.0.0", "--listen-without-auth"]) == 0
    assert [(c["host"], c["port"]) for c in calls] == [
        ("127.0.0.1", 8440),
        ("::1", 9000),
        ("0.0.0.0", 8440),
    ]


def test_openapi_prints_the_api(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("JANUS_DATA_DIR", str(tmp_path / "unused"))
    assert cli.main(["openapi"]) == 0
    paths = json.loads(capsys.readouterr().out)["paths"]
    assert "/api/documents/{document}/extract" in paths
    assert not (tmp_path / "unused").exists()


def test_a_request_under_another_host_name_is_refused(client, settings):
    assert client.get("/api/documents", headers={"host": "example.org"}).status_code == 400
    assert client.get("/api/documents", headers={"host": "localhost:8440"}).status_code == 200
    with serve(settings, any_host=True) as open_client:
        assert open_client.get("/api/documents", headers={"host": "example.org"}).status_code == 200


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
