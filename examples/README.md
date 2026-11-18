# Examples

Three invented documents. Each folder holds the PDF (`document.pdf`), a spec (`spec.yaml`) and
reference data for `janus compare` (`reference.json`).

| Example                          | Shows                                                               |
| -------------------------------- | ------------------------------------------------------------------- |
| [invoice](invoice)               | labels, dates, money, and line items in a table without rules       |
| [purchase-order](purchase-order) | a ruled table under a title row, a cell by row label, German money  |
| [parts-list](parts-list)         | a ruled table of 94 rows over three pages that repeat the header    |

The commands below run from this folder, with `janus` installed as the
[README](../README.md#install) describes. CI runs each one and fails when its output differs
from what is printed here.

## Invoice

`inspect` shows what the locators see. `--find` lists each place a phrase is printed and whether
a `label` would accept it there.

```console
$ janus inspect invoice/document.pdf --find "Total due"
document 628db0ae1c87  layer 397ad300b78c  engine pymupdf
page   1  text               70 words

headings
  p1    16.0 pt bold  Larkfield Cycle Works
  p1    16.0 pt bold  INVOICE
  p1     9.5 pt bold  Description

found
  p1   (386, 328)     label ok  Total due: £391.20
```

`extract` prints one line per field.

```console
$ janus extract invoice/spec.yaml invoice/document.pdf
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

`compare` checks the reference data against the extraction. The last lines:

```console
$ janus compare invoice/spec.yaml invoice/document.pdf invoice/reference.json | tail -n 4
match         vat/currency                   expected "GBP", got "GBP"
match         total/amount                   expected "391.20", got "391.20"  difference 0.00, tolerance 0
match         total/currency                 expected "GBP", got "GBP"
26 match
```

## Purchase order

The header of the table is its second row, under the title "Purchase order PO-5520". The field
`fitting_days` reads one cell by its row label and column header.

```console
$ janus extract purchase-order/spec.yaml purchase-order/document.pdf
extracted   order_date                 p1   "2026-03-09"
extracted   deliver_by                 p1   "2026-04-20"
extracted   supplier                   p1   "Halde Glas und Metall"
extracted   items                      p1   [{"code": "GL-040", "description": "Greenhouse glass, 4 mm"…
                                            4 rows under the header on page 1
extracted   fitting_days               p1   2
extracted   net                        p1   {"amount": "3343.00", "currency": "EUR"}
extracted   vat                        p1   {"amount": "635.17", "currency": "EUR"}
extracted   due                        p1   {"amount": "3978.17", "currency": "EUR"}
28 extracted
$ janus compare purchase-order/spec.yaml purchase-order/document.pdf purchase-order/reference.json | tail -n 1
26 match
```

## Parts list

The table runs over three pages. `continues: header` in the spec follows it to each page that
opens with the same header. Without that key the field is `ambiguous`, and the message says why.

```console
$ janus inspect parts-list/document.pdf --rows 2
document 7b69f57fdc2a  layer 21f62164c2cb  engine pymupdf
page   1  text              323 words  tables p1t0
page   2  text              306 words  tables p2t0
page   3  text              118 words  tables p3t0

table p1t0 (page 1, 41 x 4)
  r0: Part | Description | Qty | Weight, g
  r1: BR-1000 | Bearing, sealed, 6 mm bore | 2 | 1.2

table p2t0 (page 2, 41 x 4)
  r0: Part | Description | Qty | Weight, g
  r1: BR-1040 | Bearing, sealed, 26 mm bore | 42 | 5.2

table p3t0 (page 3, 15 x 4)
  r0: Part | Description | Qty | Weight, g
  r1: BR-1080 | Bearing, sealed, 46 mm bore | 34 | 9.2

headings
  p1    14.0 pt bold  Parts list for the W40 hand pump
  p1     9.5 pt       List number: PL-88
$ janus extract parts-list/spec.yaml parts-list/document.pdf
extracted   list_number                p1   "PL-88"
extracted   issued                     p1   "2026-02-02"
extracted   parts_listed               p1   94
extracted   parts                      p1   [{"part": "BR-1000", "description": "Bearing, sealed, 6 mm …
                                            94 rows under the header on pages 1, 2, 3; left out the header printed again on pages 2, 3
380 extracted
$ janus compare parts-list/spec.yaml parts-list/document.pdf parts-list/reference.json | tail -n 3
match         parts/93/qty                   expected 29, got 29  difference 0, tolerance 0
match         parts/93/weight                expected "9.3", got "9.3"  difference 0.0, tolerance 0
379 match
```

## Rebuild the PDFs

```sh
uv run --project ../packages/janus python make_examples.py
```

The script writes the three PDFs and the parts list's reference data. It needs the Liberation
Sans fonts; the PDFs it writes are committed, so running it is only needed after changing it.
