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
| The workbench, a web app for writing specs against the page | Works for one document at a time: Documents, Inspect and the spec editor. See [Workbench](#workbench) for what it lacks. |
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
34 match
```

[examples](examples/README.md) has two more documents, one of them a table that runs over three
pages, and shows `inspect`.

## Workbench

The workbench is a web app that runs on your own machine. It has three screens:

- Documents takes the PDFs you drop on it, reads them and lists each with its pages, tables,
  engine and read time.
- Inspect shows the pages with the words, lines, headings and tables Janus read drawn on them.
  A search box lists every place a phrase is printed and whether it begins its line or cell.
- The spec editor runs the spec against the open document as you type. Each field shows its
  status, value and message, and its boxes are drawn on the page.

Start it from a clone of this repository. It needs [uv](https://docs.astral.sh/uv/), Node 26
and [pnpm](https://pnpm.io/):

```sh
cd apps/workbench/web
pnpm install
pnpm build                      # writes the client into the server package
cd ../server
uv run janus-workbench serve    # http://127.0.0.1:8440
```

The server listens on 127.0.0.1 and has no sign-in, so anyone who can reach its address can read
and delete every document. It refuses any other address unless you pass `--listen-without-auth`.

Documents, page images and saved specs are files under `JANUS_DATA_DIR`, by default
`~/.local/share/janus-workbench`. `JANUS_MAX_UPLOAD_MB` (200), `JANUS_MAX_PAGES` (2000) and
`JANUS_READ_DEADLINE` (600 seconds) limit what one upload may cost.

The workbench does not have these yet:

- Click to locate: click a word on the page and get locators proposed for it.
- Runs: one spec over many documents.
- Compare: checking an extraction against reference data. The command `janus compare` does it.
- OCR and Docling. It reads every document with PyMuPDF, so a scanned page shows no words.

## Reference

- [packages/janus/README.md](packages/janus/README.md): the spec format, the locators, the value
  types, the command and the library.
- [DESIGN.md](DESIGN.md): how Janus reads a page, the rule a value must meet to count as
  extracted, and how the workbench is built.

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
uv sync --locked --project packages/janus   # without the extra, as the READMEs' output is
uv run --project packages/janus ruff format --check --config packages/janus/pyproject.toml examples
uv run --project packages/janus ruff check --config packages/janus/pyproject.toml examples
uv run --project packages/janus pytest examples
uv run --project packages/janus python examples/check_readme.py README.md examples/README.md
uvx --isolated --from ./packages/janus janus --help   # a clean install without extras

cd examples
uv run --project ../packages/janus python make_examples.py
git status --porcelain .   # empty when the committed examples are what the script writes

cd ../apps/workbench/server
uv sync --locked
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
uv run pytest

cd ../web
pnpm install --frozen-lockfile
pnpm check        # format, lint, types, unit tests, build
pnpm generate && git diff --exit-code -- src/api   # the API types match the server
pnpm exec playwright install --with-deps chromium
pnpm e2e          # the three screens in a browser, against the real server
```

`examples/check_readme.py` runs the commands this README and the examples README show. It fails
when a command prints something else, exits with another status, or when this block names a
command that CI does not run.

## Name and logo

Janus is the Roman god with two faces. One looks at the page and one at the data. The logo is a
stand-in sketch until a hand-painted one replaces it.

## Licence

[AGPL-3.0-or-later](LICENSE).
