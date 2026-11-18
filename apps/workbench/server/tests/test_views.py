"""Inspecting a document, its page layout and images, and running a spec against it."""

from conftest import EXAMPLES, INVOICE, PARTS

SPEC = (EXAMPLES / "invoice" / "spec.yaml").read_text()


def test_inspect_gives_pages_tables_headings_and_where_a_phrase_is(client, read):
    row = read(client, PARTS)
    seen = client.get(f"/api/documents/{row['id']}/inspect", params={"find": "Parts list"}).json()
    assert [(p["number"], p["width"], p["height"]) for p in seen["pages"]] == [
        (n, 595.0, 842.0) for n in (1, 2, 3)
    ]
    assert [t["id"] for t in seen["tables"]] == ["p1t0", "p2t0", "p3t0"]
    assert seen["tables"][0]["preview"][0] == ["Part", "Description", "Qty", "Weight, g"]
    heading = seen["headings"][0]
    assert heading["text"] == "Parts list for the W40 hand pump" and heading["box"]["page"] == 1
    starts = {(h["page"], h["text"]): h["starts_line"] for h in seen["hits"]}
    assert starts[(1, "Parts list for the W40 hand pump")] is True
    assert starts[(1, "Wrenfield Pump Co. | Parts list PL-88")] is False
    assert client.get(f"/api/documents/{row['id']}/inspect").json()["hits"] == []


def test_a_page_layout_holds_that_page_and_no_other(client, read):
    row = read(client, PARTS)
    page = client.get(f"/api/documents/{row['id']}/pages/2").json()
    assert page["page"] == 2 and [t["id"] for t in page["tables"]] == ["p2t0"]
    boxes = [w["box"] for w in page["words"]] + [x["box"] for x in page["lines"] + page["cells"]]
    assert boxes and {b["page"] for b in boxes} == {2}
    assert "BR-1040" in {w["text"] for w in page["words"]}
    assert client.get(f"/api/documents/{row['id']}/pages/4").status_code == 404
    assert client.get(f"/api/documents/{row['id']}/pages/0").status_code == 422


def test_a_page_image_is_a_png_drawn_once_and_then_kept(client, read, settings, monkeypatch):
    row = read(client, INVOICE)
    url = f"/api/documents/{row['id']}/pages/1/image"
    first = client.get(url, params={"scale": 1})
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert first.content.startswith(b"\x89PNG") and "immutable" in first.headers["cache-control"]
    (kept,) = (settings.data_dir / "documents" / row["id"] / "images").iterdir()
    assert len(kept.stem) == 64 and kept.read_bytes() == first.content

    from janus_workbench import work

    monkeypatch.setattr(work, "render_page", None)  # a second request must not draw again
    assert client.get(url, params={"scale": 1}).content == first.content
    assert client.get(url, params={"scale": 5}).status_code == 422
    assert client.get(f"/api/documents/{row['id']}/pages/2/image").status_code == 404


def test_a_spec_is_run_and_each_field_says_where_its_value_is_printed(client, read):
    row = read(client, INVOICE)
    out = client.post(f"/api/documents/{row['id']}/extract", json={"spec": SPEC}).json()
    assert out["problem"] is None
    fields = {f["path"]: f for f in out["fields"]}
    total = fields["total"]
    assert total["status"] == "extracted" and total["value"] == {
        "amount": "391.20",
        "currency": "GBP",
    }
    assert total["page"] == 1 and total["boxes"][0]["page"] == 1
    assert fields["lines/0/qty"]["value"] == 4


def test_a_field_that_is_not_found_says_so_and_suggests(client, read):
    row = read(client, INVOICE)
    spec = "fields:\n  customer: { label: Custmer }\n"
    (field,) = client.post(f"/api/documents/{row['id']}/extract", json={"spec": spec}).json()[
        "fields"
    ]
    assert field["status"] == "missing" and field["value"] is None and field["boxes"] == []
    assert field["suggestions"][0].startswith("'Customer: Tern Street Riders' on page 1")


def test_a_spec_that_does_not_load_comes_back_with_its_line(client, read):
    row = read(client, INVOICE)
    url = f"/api/documents/{row['id']}/extract"
    spec = "name: Invoice\nfields:\n  number: { label: No. }\n  total:\n    label: Total due\n    typ: money\n"
    out = client.post(url, json={"spec": spec}).json()
    assert out == {"problem": {"message": "total: unknown key typ", "line": 6}, "fields": []}
    broken = client.post(url, json={"spec": "fields:\n  a: { label: [ }\n"}).json()
    assert broken["problem"]["line"] == 2 and "not YAML" in broken["problem"]["message"]
    empty = client.post(url, json={"spec": ""}).json()
    assert empty["problem"]["line"] is None and empty["fields"] == []


def test_a_spec_is_text_and_never_the_name_of_a_file(client, read, tmp_path):
    row = read(client, INVOICE)
    secret = tmp_path / "private.yaml"
    secret.write_text("fields:\n  number: { label: Invoice No. }\n")
    out = client.post(f"/api/documents/{row['id']}/extract", json={"spec": str(secret)}).json()
    assert out["fields"] == [] and out["problem"] is not None


def test_a_spec_over_the_size_limit_is_refused(client, read):
    row = read(client, INVOICE)
    out = client.post(f"/api/documents/{row['id']}/extract", json={"spec": "#" * 200_001})
    assert out.status_code == 422
