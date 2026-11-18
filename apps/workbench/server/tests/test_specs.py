"""Saved specs: text kept under its hash, with names in an index."""

import hashlib


def test_a_spec_is_saved_listed_read_replaced_and_deleted(client, settings):
    text = "fields:\n  number: { label: Invoice No. }\n"
    saved = client.put("/api/specs/Supplier invoice", json={"text": text}).json()
    assert saved["name"] == "Supplier invoice"
    assert saved["hash"] == hashlib.sha256(text.encode()).hexdigest()
    client.put("/api/specs/a parts list", json={"text": "fields: {}\n"})
    assert [s["name"] for s in client.get("/api/specs").json()] == [
        "a parts list",
        "Supplier invoice",
    ]
    assert client.get("/api/specs/Supplier invoice").json() == {
        "name": "Supplier invoice",
        "text": text,
    }

    directory = settings.data_dir / "specs"
    assert (directory / f"{saved['hash']}.yaml").read_text() == text
    client.put("/api/specs/Supplier invoice", json={"text": text + "# more\n"})
    assert not (directory / f"{saved['hash']}.yaml").exists()  # no name points to it any more
    assert client.get("/api/specs/Supplier invoice").json()["text"].endswith("# more\n")

    assert client.delete("/api/specs/Supplier invoice").status_code == 204
    assert client.delete("/api/specs/Supplier invoice").status_code == 404
    assert client.get("/api/specs/Supplier invoice").status_code == 404
    assert [p.name for p in directory.glob("*.yaml")] == [
        hashlib.sha256(b"fields: {}\n").hexdigest() + ".yaml"
    ]


def test_a_spec_that_does_not_load_can_still_be_saved(client):
    assert client.put("/api/specs/draft", json={"text": "fields: [oops"}).status_code == 200
    assert client.get("/api/specs/draft").json()["text"] == "fields: [oops"


def test_a_spec_name_is_a_key_and_never_a_file_name(client, settings):
    for name in ("..%2F..%2Foutside", "a%2Fb", "a%5Cb", "x" * 81, "bad%00name", "line%0Abreak"):
        response = client.put(f"/api/specs/{name}", json={"text": "fields: {}\n"})
        assert response.status_code in (404, 405, 422), name
    assert client.put("/api/specs/..", json={"text": "fields: {}\n"}).status_code in (200, 404, 405)
    client.put("/api/specs/index.json", json={"text": "fields: {}\n"})
    files = {p.name for p in (settings.data_dir / "specs").iterdir()}
    assert all(name == "index.json" or len(name) == 69 for name in files), files
    assert not (settings.data_dir / "outside").exists()
