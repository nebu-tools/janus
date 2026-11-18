# janus-pdf

Janus reads typed values from PDFs: dates, amounts, counts, table rows. Each value keeps the
page and the box it was printed in. If Janus cannot find a value in exactly one place, or the
text does not read as the type you declared, it does not guess. It reports what it found and
why the value is not extracted.

The distribution is `janus-pdf`, the import name is `janus_pdf` and the command is `janus`.
[DESIGN.md](../../DESIGN.md) gives the full design.

## Install

```sh
uv add "janus-pdf @ git+https://github.com/nebu-tools/janus#subdirectory=packages/janus"
```

Janus is not on PyPI yet. It needs Python 3.13 or later. The `triage` extra flags pages whose
text needs OCR.

## Write a spec

A spec is a YAML file. It names each value, tells Janus where the value is printed, and gives
its type:

```yaml
name: Supplier invoice
fields:
  number: { label: "Invoice No." }
  date: { label: Date, type: date }
  due: { label: Due, type: date DD/MM/YYYY }
  total: { label: Total due, type: money GBP }
  lines:
    records:
      header: { description: Description, qty: Qty, amount: Amount }
      stop: [Subtotal]
    columns: { qty: integer, amount: money GBP }
```

A field uses one of five locators:

| Locator   | Finds                                                        |
| --------- | ------------------------------------------------------------ |
| `label`   | the value after a printed label, or in the label's table row |
| `cell`    | a table cell, by position or by row label and column header  |
| `records` | one record for each row under a header, ruled or not         |
| `section` | the text under a heading; `under:` names its parent heading  |
| `region`  | the words inside a box on a page                             |

Types include `text`, `integer`, `decimal`, `percent`, `date`, `money`, `count_percent`,
`mean_sd`, `estimate_interval` and `p_value`. A date such as `11/04/2026` needs a declared
format, because the page does not say which number is the day.

## Use the command

```sh
janus inspect invoice.pdf --find "Total due"   # what the locators see
janus extract invoice.yaml invoice.pdf          # each field and its status
janus compare invoice.yaml invoice.pdf expected.json
```

Add `--json` before the command for JSON output. `extract` and `compare` exit with 0 when every
field is extracted or every check matches, 1 when one is not, and 2 on bad input.

## Use the library

```python
import janus_pdf

layer = janus_pdf.read("invoice.pdf")
extraction = janus_pdf.extract(layer, janus_pdf.load_spec("invoice.yaml"))

extraction.data["total"]  # {"amount": "627.00", "currency": "GBP"}
result = extraction.result("total")
result.anchor.boxes[0]  # the page and box of "£627.00"

janus_pdf.compare(extraction, {"total": {"amount": "627.00"}})
```

Each field gets one status:

| Status        | Meaning                                                            |
| ------------- | ------------------------------------------------------------------ |
| `extracted`   | found in one place, or in several places that print the same value |
| `missing`     | not found; close labels come back as suggestions, never as values  |
| `ambiguous`   | found in places that disagree; each place is listed                |
| `invalid`     | found, but the text does not read as the type                      |
| `unconfirmed` | a proposer gave a value that the page does not confirm             |

A proposer is your own code, for example a language model, that suggests a value for a field
Janus could not extract. Janus accepts the suggestion only when its quote is printed once and
reads as the suggested value. See "The proposer seam" in DESIGN.md.

## Develop

```sh
uv sync --extra triage
uv run pytest                          # the default suite
uv run pytest -m benchmark             # timings against the targets in DESIGN.md
uv run python scripts/benchmark.py     # the same timings, printed
uv run python tests/fixtures/make_fixtures.py   # rebuild the test PDFs
```

Every test PDF is invented and committed with the script that builds it.

## Licence

AGPL-3.0-or-later.
