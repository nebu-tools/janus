# Janus

<img align="right" src="assets/branding/janus-logo.webp" alt="Janus logo: a badger with round spectacles lifts a number seven off a sheet of paper and drops it into a jam jar labelled seven" width="160" height="160">

Janus reads values from PDFs: dates, amounts, counts and the rows of tables. You write a short
YAML file, the spec, that names each value, says where it is printed and gives its type. Janus
returns each value with the page and the box it was printed in, so a person or a program can
check it against the page. When a value is not printed in exactly one place, or does not read as
its type, Janus gives no value and says why.

<br clear="right">

## Status

| Part | State |
| --- | --- |
| The library `janus_pdf` | Works. It reads PDFs that have a text layer, extracts by spec and compares with reference data. |
| The command `janus` | Works: `inspect`, `extract` and `compare`. |
| The workbench, a web app for writing specs against the page | Being rebuilt. Nothing of it is in this repository yet. |
| PyPI | Not published. Install from this repository. |

Scanned pages need `ocrmypdf` installed, and tables without rules in complex layouts need the
`docling` extra. Both are optional.

## Install

Janus needs Python 3.13 or later. With [uv](https://docs.astral.sh/uv/):

```sh
# the command
uv tool install "janus-pdf @ git+https://github.com/nebu-tools/janus#subdirectory=packages/janus"

# the library, in a project
uv add "janus-pdf @ git+https://github.com/nebu-tools/janus#subdirectory=packages/janus"
```

## A first spec

[examples/invoice/document.pdf](examples/invoice/document.pdf) is a one-page invoice. This spec,
[examples/invoice/spec.yaml](examples/invoice/spec.yaml), reads its number, its dates, its line
items and its totals:

```yaml
name: Workshop invoice
fields:
  number: { label: "Invoice No." }
  date: { label: Date, type: date }
  customer: { label: Customer }
  due: { label: Due, type: date DD/MM/YYYY }
  lines:
    records:
      header: { description: Description, qty: Qty, unit_price: Unit price, amount: Amount }
      stop: [Subtotal]
    columns: { qty: integer, unit_price: money GBP, amount: money GBP }
  subtotal: { label: Subtotal, type: money GBP }
  vat: { label: VAT (20%), type: money GBP }
  total: { label: Total due, type: money GBP }
```

From a clone of this repository:

```console
$ janus extract examples/invoice/spec.yaml examples/invoice/document.pdf
extracted   number                     p1   "LC-2026-0318"
extracted   date                       p1   "2026-05-14"
extracted   customer                   p1   "Tern Street Riders"
extracted   due                        p1   "2026-06-13"
extracted   lines                      p1   [{"description": "Wheel truing", "qty": 4, "unit_price": {"…
                                            4 rows under the header on page 1
extracted   subtotal                   p1   {"amount": "326.00", "currency": "GBP"}
extracted   vat                        p1   {"amount": "65.20", "currency": "GBP"}
extracted   total                      p1   {"amount": "391.20", "currency": "GBP"}
24 extracted
```

`--cells` lists every cell of the line items, and `--json` before the command prints every value
with its boxes. `compare` checks the extraction against reference data. Its last lines:

```console
$ janus compare examples/invoice/spec.yaml examples/invoice/document.pdf examples/invoice/reference.json | tail -n 3
match         total/amount                   expected "391.20", got "391.20"  difference 0.00, tolerance 0
match         total/currency                 expected "GBP", got "GBP"
26 match
```

[examples](examples/README.md) has two more documents, one of them a table that runs over three
pages, and shows `inspect`.

## Reference

- [packages/janus/README.md](packages/janus/README.md): the spec format, the locators, the value
  types, the command and the library.
- [DESIGN.md](DESIGN.md): how Janus reads a page, the rule a value must meet to count as
  extracted, and the plan for the workbench.

## Development

CI runs these checks. Run them before you push.

```sh
cd packages/janus
uv sync --locked --extra triage
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run ty check src tests scripts
uv run pytest

cd ../..
uv run --project packages/janus ruff format --check --config packages/janus/pyproject.toml examples
uv run --project packages/janus ruff check --config packages/janus/pyproject.toml examples
uv run --project packages/janus python examples/check_readme.py README.md examples/README.md
```

The last command runs every command this README and the examples README show and fails when the
output differs from what they print.

## Name and logo

Janus is the Roman god with two faces. One looks at the page and one at the data. The logo is a
stand-in sketch until a hand-painted one replaces it.

## Licence

[AGPL-3.0-or-later](LICENSE).
