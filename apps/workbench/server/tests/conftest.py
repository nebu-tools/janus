import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from janus_workbench.app import create_app
from janus_workbench.settings import Settings

EXAMPLES = Path(__file__).parents[4] / "examples"
INVOICE = EXAMPLES / "invoice" / "document.pdf"
PARTS = EXAMPLES / "parts-list" / "document.pdf"  # three pages
PDF = {"content-type": "application/pdf"}


def serve(settings: Settings, **options) -> TestClient:
    return TestClient(create_app(settings, static=None, **options), base_url="http://127.0.0.1")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", read_deadline=60.0, read_workers=1)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with serve(settings) as client:
        yield client


def upload(client: TestClient, pdf: bytes, name: str = "document.pdf") -> dict:
    response = client.post("/api/documents", params={"name": name}, content=pdf, headers=PDF)
    assert response.status_code == 201, response.text
    return response.json()


def settled(client: TestClient, document: str, seconds: float = 30.0) -> dict:
    """The document's row once it is ready or failed."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        (row,) = [r for r in client.get("/api/documents").json() if r["id"] == document]
        if row["status"] in ("ready", "failed"):
            return row
        time.sleep(0.02)
    raise AssertionError(f"still {row['status']} after {seconds} seconds")


@pytest.fixture
def read() -> Callable[..., dict]:
    def read(client: TestClient, pdf: bytes | Path, name: str = "document.pdf") -> dict:
        data = pdf.read_bytes() if isinstance(pdf, Path) else pdf
        return settled(client, upload(client, data, name)["id"])

    return read
