"""Every malformed spec fails as it loads, with a SpecError naming the field and the key."""

import copy

import pytest

from janus_pdf import SpecError, load_spec

# A valid field for each locator, using every key it takes.
VALID = {
    "label": {"label": "Total", "column": "Site A", "type": "decimal", "pages": 1},
    "cell": {"cell": {"table": 1, "row": 0, "column": "Qty"}, "type": "integer", "pages": "1-2"},
    "records": {
        "records": {"header": {"qty": "Qty", "d": "Description"}, "stop": "Total", "filled": "qty"},
        "columns": {"qty": "integer"},
        "pages": 2,
    },
    "section": {"section": "Findings", "under": "North", "pages": 1},
    "region": {"region": {"page": 1, "box": [0, 0, 10, 10]}, "type": "text", "pages": 1},
    "typed": {
        "label": "Date",
        "type": {
            "kind": "date",
            "numbers": "1,234.56",
            "formats": "D MMMM YYYY",
            "locale": "en",
            "currency": "EUR",
            "pick": "amount",
            "absent": ["n/a"],
            "bounds": "share",
        },
    },
}

# A value of the wrong kind for each key: (path of keys, value, key as the message names it).
WRONG = [
    ("label", ("label",), 123, "label"),
    ("label", ("label",), [], "label"),
    ("label", ("column",), 5, "column"),
    ("label", ("type",), 5, "type"),
    ("label", ("pages",), [1], "pages"),
    ("label", ("pages",), 0, "pages"),
    ("cell", ("cell",), 3, "cell"),
    ("cell", ("cell", "table"), [1], "cell.table"),
    ("cell", ("cell", "table"), "table one", "cell.table"),
    ("cell", ("cell", "table"), 0, "cell.table"),
    ("cell", ("cell", "row"), 1.5, "cell.row"),
    ("cell", ("cell", "row"), -1, "cell.row"),
    ("cell", ("cell", "column"), True, "cell.column"),
    ("cell", ("type",), [], "type"),
    ("cell", ("pages",), {}, "pages"),
    ("records", ("records",), "Qty", "records"),
    ("records", ("records", "header"), ["Qty"], "records.header"),
    ("records", ("records", "header"), {}, "records.header"),
    ("records", ("records", "header", "qty"), 7, "records.header.qty"),
    ("records", ("records", "stop"), 5, "records.stop"),
    ("records", ("records", "filled"), 5, "records.filled"),
    ("records", ("columns",), ["integer"], "columns"),
    ("records", ("columns", "qty"), 5, "columns.qty"),
    ("records", ("pages",), 2.5, "pages"),
    ("section", ("section",), {"a": 1}, "section"),
    ("section", ("under",), 9, "under"),
    ("section", ("pages",), "two", "pages"),
    ("region", ("region",), [1, 2], "region"),
    ("region", ("region", "page"), "two", "region.page"),
    ("region", ("region", "page"), 0, "region.page"),
    ("region", ("region", "box"), "0 0 10 10", "region.box"),
    ("region", ("region", "box"), [0, 0, 10], "region.box"),
    ("region", ("region", "box"), [0, 0, "10", 10], "region.box"),
    ("region", ("type",), True, "type"),
    ("region", ("pages",), None, "pages"),
    ("typed", ("label",), {"x": 1}, "label"),
    ("typed", ("type",), 1.5, "type"),
    ("typed", ("type", "kind"), 5, "type.kind"),
    ("typed", ("type", "numbers"), 1234.56, "type.numbers"),
    ("typed", ("type", "formats"), 5, "type.formats"),
    ("typed", ("type", "locale"), ["en"], "type.locale"),
    ("typed", ("type", "currency"), 978, "type.currency"),
    ("typed", ("type", "pick"), 1, "type.pick"),
    ("typed", ("type", "absent"), "n/a", "type.absent"),
    ("typed", ("type", "bounds"), "all", "type.bounds"),
]


def _with(body, keys, value):
    body = copy.deepcopy(body)
    node = body
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return body


def test_the_valid_fields_load():
    valid = {k: v for k, v in VALID.items() if k != "typed"}
    assert len(load_spec({"fields": valid}).fields) == 5


def test_every_key_of_every_locator_is_covered():
    def keys(node, prefix=()):
        for k, v in node.items():
            yield (*prefix, k)
            if isinstance(v, dict) and k not in ("header", "columns"):
                yield from keys(v, (*prefix, k))

    covered = {(locator, keys) for locator, keys, _, _ in WRONG}
    for locator, body in VALID.items():
        for path in keys(body):
            assert (locator, path) in covered, (locator, path)


@pytest.mark.parametrize(("locator", "keys", "value", "named"), WRONG)
def test_a_wrong_value_names_the_field_and_the_key(locator, keys, value, named):
    body = _with(VALID[locator], keys, value)
    with pytest.raises(SpecError) as info:
        load_spec({"fields": {"x": body}})
    message = str(info.value)
    assert message.startswith("x: ")
    assert named in message, message


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"cell": 3}, "bad: cell: expected a mapping with table, row and column, not 3"),
        ({"fields": None}, "bad: fields: no value given"),
        ({"label": 123}, "bad: label: expected a label or a list of labels, not 123"),
        ({"label": "X", "colum": "Y"}, "bad: unknown key colum"),
        ({"cell": {"table": 1, "row": 0}}, "bad: cell needs column"),
        ({"region": {"page": 1, "box": [0, 0, 1]}}, "bad: region.box: expected four numbers"),
        ({"label": "X", "type": {"kind": "date", "lokale": "de"}}, "bad: unknown key type.lokale"),
        ({"label": "X", "pages": "3-1"}, "bad: pages: '3-1' is not a range of pages from 1"),
        ({"label": "X", "type": "percent all"}, "bad: type: cannot read 'all'"),
        (
            {"label": "X", "type": {"kind": "integer", "bounds": "any"}},
            "bad: type: bounds goes with percent",
        ),
    ],
)
def test_malformed_specs(body, message):
    with pytest.raises(SpecError) as info:
        load_spec({"fields": {"bad": body}})
    assert str(info.value).startswith(message), str(info.value)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (None, "the spec: expected a mapping, not null"),
        ({"name": 5, "fields": {"x": {"label": "X"}}}, "the spec: name: expected text, not 5"),
        ({"fields": []}, "the spec: fields: expected a mapping of fields"),
        ("fields: [", "the spec is not YAML or JSON"),
        ({"fields": {"g": {"fields": {"x": {"label": 1}}}}}, "g/x: label: expected"),
    ],
)
def test_malformed_spec_documents(source, message):
    with pytest.raises(SpecError) as info:
        load_spec(source)
    assert str(info.value).startswith(message), str(info.value)
