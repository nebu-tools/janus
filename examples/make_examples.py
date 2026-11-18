"""Build the example PDFs: an invoice, a purchase order and a parts list.

    uv run --project packages/janus python examples/make_examples.py

Every document is invented. Text is set in Liberation Sans (SIL Open Font License 1.1), embedded
and subset. The script looks for the fonts in the usual Linux places or in $JANUS_FONT_DIR. The
output is the same on every run for a given PyMuPDF: fixed metadata, no timestamps, no random IDs.

The parts list's reference data is written from the same rows the PDF is printed from, so
`janus compare` checks every row of the table against data that never passed through Janus.
"""

import json
import os
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
FONT_DIRS = (
    os.environ.get("JANUS_FONT_DIR", ""),
    "/usr/share/fonts/liberation",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/liberation-sans",
    "/usr/share/fonts/TTF",
)
WIDTH, HEIGHT = 595.0, 842.0  # A4
LEFT, RIGHT = 56.0, WIDTH - 56.0
BODY, LEADING, ROW = 9.5, 12.5, 16.0


def _font(name: str) -> str:
    for directory in FONT_DIRS:
        path = Path(directory) / name
        if directory and path.is_file():
            return str(path)
    sys.exit(f"{name} not found; install Liberation Sans or set JANUS_FONT_DIR")


class Sheet:
    """A document under construction. Positions count from the top left; y is the baseline."""

    def __init__(self) -> None:
        self.doc = pymupdf.open()
        self.files = {
            False: _font("LiberationSans-Regular.ttf"),
            True: _font("LiberationSans-Bold.ttf"),
        }
        self.fonts = {bold: pymupdf.Font(fontfile=file) for bold, file in self.files.items()}
        self.page: pymupdf.Page

    def new_page(self) -> None:
        self.page = self.doc.new_page(width=WIDTH, height=HEIGHT)
        for bold, file in self.files.items():
            self.page.insert_font(fontname="F2" if bold else "F1", fontfile=file)

    def text(self, x: float, y: float, text: str, size: float = BODY, bold: bool = False) -> None:
        self.page.insert_text((x, y), text, fontname="F2" if bold else "F1", fontsize=size)

    def right(self, x1: float, y: float, text: str, size: float = BODY, bold: bool = False) -> None:
        """Write `text` so that it ends at `x1`."""
        self.text(x1 - self.fonts[bold].text_length(text, fontsize=size), y, text, size, bold)

    def grid(self, xs: list[float], top: float, rows: int, title_rows: int = 0) -> None:
        """Rule a table of `rows` rows. A title row has no rules between its columns."""
        for r in range(rows + 1):
            self.page.draw_line((xs[0], top + r * ROW), (xs[-1], top + r * ROW), width=0.6)
        for i, x in enumerate(xs):
            inner = 0 < i < len(xs) - 1
            start = top + (title_rows * ROW if inner else 0)
            self.page.draw_line((x, start), (x, top + rows * ROW), width=0.6)

    def row(self, xs: list[float], top: float, r: int, values: tuple[str, ...], bold=False) -> None:
        for x, value in zip(xs, values, strict=False):
            self.text(x + 4, top + r * ROW + 11.5, value, size=8.5, bold=bold)

    def save(self, name: str, title: str) -> None:
        path = HERE / name / "document.pdf"
        path.parent.mkdir(exist_ok=True)
        self.doc.subset_fonts()
        self.doc.set_metadata(
            {"title": title, "author": "Janus examples", "producer": "", "creator": ""}
        )
        self.doc.save(path, garbage=4, deflate=True, no_new_id=True)
        print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size} bytes)")


# --- The invoice ---------------------------------------------------------------------------------

# Description, quantity, unit price, amount.
INVOICE_ROWS = [
    ("Wheel truing", "4", "£18.00", "£72.00"),
    ("Brake cable, 1.6 mm", "12", "£3.25", "£39.00"),
    ("Chain, 9 speed", "5", "£21.40", "£107.00"),
    ("Workshop time, hours", "3", "£36.00", "£108.00"),
]


def invoice() -> None:
    """One page without rules: labels, line items in aligned columns, then totals."""
    s = Sheet()
    s.new_page()
    s.text(LEFT, 80, "Larkfield Cycle Works", size=16, bold=True)
    s.text(LEFT, 98, "3 Canal Yard, Larkfield", size=8.5)
    s.text(LEFT, 109, "accounts@larkfield-cycles.example", size=8.5)
    s.right(RIGHT, 80, "INVOICE", size=16, bold=True)
    y = 150.0
    for label, value in (("Invoice No.", "LC-2026-0318"), ("Date", "14 May 2026")):
        s.text(LEFT, y, label, bold=True)
        s.text(LEFT + 90, y, value)
        y += LEADING
    s.text(LEFT, y, "Customer: Tern Street Riders")
    s.text(LEFT, y + LEADING, "Due: 13/06/2026")

    cols = [LEFT, LEFT + 250, LEFT + 330]
    y = 240.0
    for x, head in zip(cols, ("Description", "Qty", "Unit price"), strict=True):
        s.text(x, y, head, bold=True)
    s.right(RIGHT, y, "Amount", bold=True)
    y += ROW
    for description, qty, unit, amount in INVOICE_ROWS:
        for x, value in zip(cols, (description, qty, unit), strict=True):
            s.text(x, y, value)
        s.right(RIGHT, y, amount)
        y += LEADING
    y += 6
    for label, amount in (("Subtotal", "£326.00"), ("VAT (20%)", "£65.20")):
        s.text(cols[2], y, label)
        s.right(RIGHT, y, amount)
        y += LEADING
    s.text(cols[2], y, "Total due: £391.20", bold=True)
    s.text(LEFT, y + 40, "Payment within 30 days to the account printed on our letterhead.")
    s.save("invoice", "Larkfield Cycle Works invoice LC-2026-0318")


# --- The purchase order --------------------------------------------------------------------------

# Code, description, quantity, unit price, amount, in German number format.
ORDER_ROWS = [
    ("GL-040", "Greenhouse glass, 4 mm", "24", "18,50 €", "444,00 €"),
    ("AL-112", "Aluminium glazing bar, 2 m", "36", "9,75 €", "351,00 €"),
    ("VT-007", "Roof vent opener", "4", "62,00 €", "248,00 €"),
    ("SV-FIT", "Fitting, per day", "2", "1.150,00 €", "2.300,00 €"),
]


def purchase_order() -> None:
    """One page with a ruled table. Its first row is a title, so the header is the second row."""
    s = Sheet()
    s.new_page()
    s.text(LEFT, 80, "Dornbach Gartenbau GmbH", size=16, bold=True)
    for i, line in enumerate(
        ("Order date 9 March 2026", "Deliver by 20 April 2026", "Supplier: Halde Glas und Metall")
    ):
        s.text(LEFT, 110 + i * LEADING, line)
    xs = [LEFT, LEFT + 60, LEFT + 240, LEFT + 285, LEFT + 380, RIGHT]
    top = 170.0
    rows = 2 + len(ORDER_ROWS)
    s.grid(xs, top, rows, title_rows=1)
    s.text(LEFT + 4, top + 11.5, "Purchase order PO-5520", bold=True)
    s.row(xs, top, 1, ("Code", "Description", "Qty", "Unit price", "Amount"), bold=True)
    for r, values in enumerate(ORDER_ROWS, start=2):
        s.row(xs, top, r, values)
    y = top + rows * ROW + 24
    for label, amount in (
        ("Net total", "3.343,00 €"),
        ("VAT 19%", "635,17 €"),
        ("Amount due", "3.978,17 €"),
    ):
        s.text(xs[3], y, label, bold=label == "Amount due")
        s.right(RIGHT, y, amount)
        y += LEADING
    s.save("purchase-order", "Purchase order PO-5520")


# --- The parts list ------------------------------------------------------------------------------

PART_KINDS = (
    ("BR", "Bearing, sealed", "mm bore"),
    ("SP", "Spacer ring", "mm"),
    ("PN", "Dowel pin", "mm"),
    ("GK", "Gasket, cork", "mm"),
)
ROWS_PER_PAGE = 40


def _parts() -> list[dict]:
    """94 parts. Sizes, quantities and weights follow a fixed rule, so every run gives the same."""
    parts = []
    for i in range(94):
        code, name, unit = PART_KINDS[i % len(PART_KINDS)]
        size = 6 + 2 * (i // len(PART_KINDS))
        grams = 12 + (i * 37) % 480
        parts.append(
            {
                "part": f"{code}-{1000 + i}",
                "description": f"{name}, {size} {unit}",
                "qty": 2 + (i * 7) % 48,
                "weight": f"{grams // 10}.{grams % 10}",
            }
        )
    return parts


def parts_list() -> None:
    """A ruled table of 94 parts over three pages. Every page prints the header again and
    carries a running head and foot."""
    s = Sheet()
    parts = _parts()
    pages = [parts[i : i + ROWS_PER_PAGE] for i in range(0, len(parts), ROWS_PER_PAGE)]
    xs = [LEFT, LEFT + 80, LEFT + 330, LEFT + 390, RIGHT]
    for number, rows in enumerate(pages, start=1):
        s.new_page()
        s.text(LEFT, 36, "Wrenfield Pump Co.  |  Parts list PL-88", size=7.5)
        s.text(LEFT, 812, f"Page {number} of {len(pages)}", size=7.5)
        top = 60.0
        if number == 1:
            s.text(LEFT, 76, "Parts list for the W40 hand pump", size=14, bold=True)
            s.text(LEFT, 100, "List number: PL-88")
            s.text(LEFT, 100 + LEADING, "Issued: 2 February 2026")
            s.text(LEFT, 100 + 2 * LEADING, "Parts listed: 94")
            top = 140.0
        s.grid(xs, top, 1 + len(rows))
        s.row(xs, top, 0, ("Part", "Description", "Qty", "Weight, g"), bold=True)
        for r, part in enumerate(rows, start=1):
            s.row(xs, top, r, (part["part"], part["description"], str(part["qty"]), part["weight"]))
    s.save("parts-list", "Parts list PL-88")
    reference = {
        "list_number": "PL-88",
        "issued": "2026-02-02",
        "parts_listed": 94,
        "parts": parts,
    }
    (HERE / "parts-list" / "reference.json").write_text(json.dumps(reference, indent=2) + "\n")


if __name__ == "__main__":
    invoice()
    purchase_order()
    parts_list()
