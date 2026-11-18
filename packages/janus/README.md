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
      stop: [Subtotal] # the table ends at this row
      skip: [Carried forward] # this row is left out wherever it appears
      continues: header # the table runs on over pages that open with its header
      filled: { first: [qty, amount] } # a line without them wraps the record above
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

`pages: 2` or `pages: 2-4` keeps any field to those pages. Nothing on the other pages exists for
that field: no labels, tables, headings or suggestions.

A `region` takes exactly the words whose box centre lies inside it, in reading order, so a word
that straddles the edge goes to the side that holds more than half of it. A `label` drops a
colon or a dash with a space after it, and nothing else, so `Amount: -123` reads -123.

A `records` field reads one table: the one under the header printed first in reading order,
ruled or not. A table without rules runs while its lines fit its columns,
each cell starting, ending or centred where its column's header or an earlier cell does. It ends
at the first line that does not fit, at a row `stop:` names, or at the end of the page. Spacing
between lines and the words in a row never end it. A subtotal, total or "carried forward" row
reads as a record unless `stop:` ends the table there or `skip:` leaves the row out. The message
lists each row `skip:` leaves out with its page.

A row is the header when each declared header is the whole text of a cell of its own: a cell
of a ruled table, or, without rules, a line of the PDF's text in that row. The header's words
inside a longer cell, as in a row "Item Qty adapter | 2", do not make it a header, and neither
does a row that prints one header text as a label, such as "Qty | 3". The header printed again
must also put each header in the column the first one set; "Qty | Item" is a row. A header
printed over two lines, such as "Item" with "description" under it, is two rows: declare the
texts of one line as the header and leave the other out with `skip:`.

The table ends where the header is printed again: lower on the same page, on a later page, or
over a table of the other kind. The page does not say whether that goes on with the same table
or heads another, so the field is `ambiguous`, and the message gives the page, until the spec
says which:

- `continues: none` says each header printed again heads another table. The field is the first
  table, on its own page.
- `skip: [Item]` leaves the header printed again out as a line of the same table, when the table
  read reaches it and both are of the same kind.
- `stop: [Item]` ends the field at the header printed again.
- `continues: header` and `continues: rows`, below, read a header at the top of the next page
  as the same table.
- `pages:` keeps the field to the pages before it.

No key reads a ruled table and a table without rules as one, or two tables printed apart on one
page. Declare a field for each.

A table is on one page unless `continues:` says how it runs on. If a later page of the field
opens with rows on the same column edges, the field is `incomplete` until the spec says which:

- `continues: header` follows the table only to pages that open with the same header text, and
  ends it at the first page that does not.
- `continues: rows` follows the table to pages that open with rows on the same column edges, and
  leaves out a header that opens them, with a note. This form asserts that what is aligned at
  the top of the next page belongs to the table.
- `continues: none` or `pages: 1` keeps the field to one page.

Each record keeps its page. In a table that runs over pages, running heads and feet are left out
and the message lists each one with its pages. Any other line above the table on a continued
page, such as "Table 3 (continued)", makes the field `incomplete` until `skip:` names it.

Janus looks for another table's header inside the table, on a continued page or further down a
page. A line set like the header (bold, or in another size) where the header is set differently
from the rows makes the field `incomplete`. A cell that does not read as its column's declared
type makes the field `invalid`. Either message quotes the line and names `stop:` and `pages:`.

In a table without rules, a line that leaves a column empty may wrap the record above or start a
new one. Janus does not guess: the field is `ambiguous` and the message quotes the line, until
`filled: {first: [qty]}` says every record fills `qty` on its first line (other lines join the
record above), or `filled: {last: [qty]}` says it fills `qty` on its last line (other lines join
the record below). `filled` applies only to tables without rules; on a ruled table, where each
cell is bounded, it is ignored and the message says so. Such tables are read along the text on
pages the viewer turns.

### Limits

What a page does not show, Janus cannot see. A `records` field can be wrong in these cases:

- Another table's header that is set like the body and the columns are untyped text reads as a
  record. Under `continues: rows` a table on the next page with columns on the same edges is
  read as part of the table. Name its first line in `stop:`, type a column, or use
  `continues: header` or `pages:`.
- With `filled`, a line after the table that prints in one of its columns, such as a footer
  under the description column, joins the last record unless `stop:` or `skip:` names it.
  Without `filled` such a line makes the field `ambiguous`.
- A cell aligned with neither the left, the right nor the centre of its column ends the table
  there, and the message quotes the line.
- Without rules, a cell is a line of the PDF's text. A PDF that prints two headers as one line
  of text, with spaces between them, has no header row there, and the field is `missing`.
- The rows' set is taken from the first record. Under a header set like the rows, such as a
  bold header over bold rows, the set gives no evidence. A first record set unlike the rest,
  such as a bold first row under a regular header, makes the field `incomplete`.

A `section` runs to the next heading of its rank or to the end of the field's pages, with a note
when the text may go on past them. Across a page break its running heads and feet are left out
and listed in a note.

Types include `text`, `integer`, `decimal`, `percent`, `date`, `money`, `count_percent`,
`mean_sd`, `estimate_interval` and `p_value`. A date such as `11/04/2026` needs a declared
format, because the page does not say which number is the day. A number may be signed or in
parentheses, which reads as negative. `percent` is a share from 0 to 100; `percent any` is a
change that can take a sign and any size, such as `-2.5%` or `150%`.

A spec is checked as it loads. A wrong key, a value of the wrong kind, or a spec that
contradicts itself raises a `SpecError` that names the field and the key. So does any text the
spec compares with the page (a label, a header, a `stop:` or `skip:` row, a section, a row or
column name) that is empty once spaces and a trailing colon are dropped, such as `":"`, and two
headers of one table that name the same printed text.

## Use the command

```sh
janus inspect invoice.pdf --find "Total due"   # what the locators see
janus extract invoice.yaml invoice.pdf          # each field and its status
janus compare invoice.yaml invoice.pdf expected.json
```

Add `--json` before the command for JSON output. `extract` and `compare` exit with 0 when every
field is extracted or every check matches, 1 when one is not, and 2 on bad input: a spec that
does not load, a file that is not a whole PDF, or reference data or rules that do not parse. A
fault in Janus itself exits with 3. Either way the error is one line, never a traceback.

## Use the library

```python
import janus_pdf

layer = janus_pdf.read("invoice.pdf")
extraction = janus_pdf.extract(layer, janus_pdf.load_spec("invoice.yaml"))

extraction.data["total"]  # {"amount": "627.00", "currency": "GBP"}
result = extraction.result("total")
result.anchors[0].boxes[0]  # the page and box of "£627.00"

janus_pdf.compare(extraction, {"total": {"amount": "627.00"}})
```

Each field gets one status:

| Status        | Meaning                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| `extracted`   | found in one place, or in several places that print the same value       |
| `missing`     | not found; close labels come back as suggestions, never as values        |
| `ambiguous`   | found in places that disagree, or a table whose end the page leaves open |
| `incomplete`  | records the page shows may go on, or may hold another table              |
| `invalid`     | found, but the text does not read as the type                            |
| `unconfirmed` | a proposer gave a value that the page does not confirm                   |

"The same value" follows the type: `4.60` and `4.6` are the same decimal, but `001` and `1` are
different text, while `a b` and `a  b` are the same text. `compare` checks reference data with
the same rule: values are compared by their type's equality; `casefold: true` loosens text,
`tolerance:` loosens numbers, nothing else does.

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
