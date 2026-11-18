"""Build the example PDFs: an invoice, a purchase order and a parts list.

    uv run --project packages/janus python examples/make_examples.py

Every document is invented. Text is set in Liberation Sans (SIL Open Font License 1.1, see
fonts/LICENSE), embedded and subset. The fonts are committed beside this script, so the output is
the same on every machine for a given PyMuPDF: fixed metadata, no timestamps, no random IDs.

Each document is drawn from typed values: dates, decimal amounts and counts. The same values
give each example's reference.json, so `janus compare` checks the extraction against data that
never passed through Janus. Nothing here reads a PDF.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
FONTS = {
    False: HERE / "fonts" / "LiberationSans-Regular.ttf",
    True: HERE / "fonts" / "LiberationSans-Bold.ttf",
}
WIDTH, HEIGHT = 595.0, 842.0  # A4
LEFT, RIGHT = 56.0, WIDTH - 56.0
BODY, LEADING, ROW = 9.5, 12.5, 16.0


class Sheet:
    """A document under construction. Positions count from the top left; y is the baseline."""

    def __init__(self) -> None:
        self.doc = pymupdf.open()
        self.fonts = {bold: pymupdf.Font(fontfile=str(file)) for bold, file in FONTS.items()}
        self.page: pymupdf.Page

    def new_page(self) -> None:
        self.page = self.doc.new_page(width=WIDTH, height=HEIGHT)
        for bold, file in FONTS.items():
            self.page.insert_font(fontname="F2" if bold else "F1", fontfile=str(file))

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

    def save(self, name: str, title: str, reference: dict) -> None:
        """Write the PDF and the reference data drawn from the same values."""
        folder = HERE / name
        folder.mkdir(exist_ok=True)
        self.doc.subset_fonts()
        self.doc.set_metadata(
            {"title": title, "author": "Janus examples", "producer": "", "creator": ""}
        )
        self.doc.save(folder / "document.pdf", garbage=4, deflate=True, no_new_id=True)
        text = json.dumps(reference, indent=2, ensure_ascii=False) + "\n"
        (folder / "reference.json").write_text(text)
        for path in (folder / "document.pdf", folder / "reference.json"):
            print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size} bytes)")


# --- Values, as printed and as reference data ----------------------------------------------------


def long_date(day: date) -> str:
    """14 May 2026"""
    return f"{day.day} {day:%B %Y}"


def gbp(amount: Decimal) -> str:
    """£1,234.56"""
    return f"£{amount:,.2f}"


def eur(amount: Decimal) -> str:
    """1.234,56 €"""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".") + " €"


def money(amount: Decimal, currency: str) -> dict:
    return {"amount": str(amount), "currency": currency}


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


# --- The invoice ---------------------------------------------------------------------------------

INVOICE = {
    "number": "LC-2026-0318",
    "date": date(2026, 5, 14),
    "customer": "Tern Street Riders",
    "due": date(2026, 6, 13),
}
# Description, quantity, unit price.
INVOICE_ROWS = [
    ("Wheel truing", 4, Decimal("18.00")),
    ("Brake cable, 1.6 mm", 12, Decimal("3.25")),
    ("Chain, 9 speed", 5, Decimal("21.40")),
    ("Workshop time, hours", 3, Decimal("36.00")),
]
INVOICE_VAT = Decimal("0.20")


def invoice() -> None:
    """One page without rules: labels, line items in aligned columns, then totals."""
    lines = [
        {"description": d, "qty": qty, "unit_price": unit, "amount": unit * qty}
        for d, qty, unit in INVOICE_ROWS
    ]
    subtotal = sum((line["amount"] for line in lines), Decimal(0))
    vat = cents(subtotal * INVOICE_VAT)
    total = subtotal + vat
    s = Sheet()
    s.new_page()
    s.text(LEFT, 80, "Larkfield Cycle Works", size=16, bold=True)
    s.text(LEFT, 98, "3 Canal Yard, Larkfield", size=8.5)
    s.text(LEFT, 109, "accounts@larkfield-cycles.example", size=8.5)
    s.right(RIGHT, 80, "INVOICE", size=16, bold=True)
    y = 150.0
    for label, value in (("Invoice No.", INVOICE["number"]), ("Date", long_date(INVOICE["date"]))):
        s.text(LEFT, y, label, bold=True)
        s.text(LEFT + 90, y, value)
        y += LEADING
    s.text(LEFT, y, f"Customer: {INVOICE['customer']}")
    s.text(LEFT, y + LEADING, f"Due: {INVOICE['due']:%d/%m/%Y}")

    cols = [LEFT, LEFT + 250, LEFT + 330]
    y = 240.0
    for x, head in zip(cols, ("Description", "Qty", "Unit price"), strict=True):
        s.text(x, y, head, bold=True)
    s.right(RIGHT, y, "Amount", bold=True)
    y += ROW
    for line in lines:
        printed = (line["description"], str(line["qty"]), gbp(line["unit_price"]))
        for x, value in zip(cols, printed, strict=True):
            s.text(x, y, value)
        s.right(RIGHT, y, gbp(line["amount"]))
        y += LEADING
    y += 6
    for label, amount in (("Subtotal", subtotal), (f"VAT ({INVOICE_VAT:.0%})", vat)):
        s.text(cols[2], y, label)
        s.right(RIGHT, y, gbp(amount))
        y += LEADING
    s.text(cols[2], y, f"Total due: {gbp(total)}", bold=True)
    s.text(LEFT, y + 40, "Payment within 30 days to the account printed on our letterhead.")
    reference = {
        "number": INVOICE["number"],
        "date": INVOICE["date"].isoformat(),
        "customer": INVOICE["customer"],
        "due": INVOICE["due"].isoformat(),
        "lines": [
            {
                "description": line["description"],
                "qty": line["qty"],
                "unit_price": money(line["unit_price"], "GBP"),
                "amount": money(line["amount"], "GBP"),
            }
            for line in lines
        ],
        "subtotal": money(subtotal, "GBP"),
        "vat": money(vat, "GBP"),
        "total": money(total, "GBP"),
    }
    s.save("invoice", f"Larkfield Cycle Works invoice {INVOICE['number']}", reference)


# --- The purchase order --------------------------------------------------------------------------

ORDER = {
    "order_date": date(2026, 3, 9),
    "deliver_by": date(2026, 4, 20),
    "supplier": "Halde Glas und Metall",
}
# Code, description, quantity, unit price. Amounts are printed in German number format.
ORDER_ROWS = [
    ("GL-040", "Greenhouse glass, 4 mm", 24, Decimal("18.50")),
    ("AL-112", "Aluminium glazing bar, 2 m", 36, Decimal("9.75")),
    ("VT-007", "Roof vent opener", 4, Decimal("62.00")),
    ("SV-FIT", "Fitting, per day", 2, Decimal("1150.00")),
]
ORDER_VAT = Decimal("0.19")


def purchase_order() -> None:
    """One page with a ruled table. Its first row is a title, so the header is the second row."""
    items = [
        {"code": c, "description": d, "qty": qty, "unit_price": unit, "amount": unit * qty}
        for c, d, qty, unit in ORDER_ROWS
    ]
    net = sum((item["amount"] for item in items), Decimal(0))
    vat = cents(net * ORDER_VAT)
    due = net + vat
    s = Sheet()
    s.new_page()
    s.text(LEFT, 80, "Dornbach Gartenbau GmbH", size=16, bold=True)
    for i, line in enumerate(
        (
            f"Order date {long_date(ORDER['order_date'])}",
            f"Deliver by {long_date(ORDER['deliver_by'])}",
            f"Supplier: {ORDER['supplier']}",
        )
    ):
        s.text(LEFT, 110 + i * LEADING, line)
    xs = [LEFT, LEFT + 60, LEFT + 240, LEFT + 285, LEFT + 380, RIGHT]
    top = 170.0
    rows = 2 + len(ORDER_ROWS)
    s.grid(xs, top, rows, title_rows=1)
    s.text(LEFT + 4, top + 11.5, "Purchase order PO-5520", bold=True)
    s.row(xs, top, 1, ("Code", "Description", "Qty", "Unit price", "Amount"), bold=True)
    for r, item in enumerate(items, start=2):
        printed = (item["code"], item["description"], str(item["qty"]))
        s.row(xs, top, r, (*printed, eur(item["unit_price"]), eur(item["amount"])))
    y = top + rows * ROW + 24
    for label, amount in (
        ("Net total", net),
        (f"VAT {ORDER_VAT:.0%}", vat),
        ("Amount due", due),
    ):
        s.text(xs[3], y, label, bold=label == "Amount due")
        s.right(RIGHT, y, eur(amount))
        y += LEADING
    fitting = next(item for item in items if item["code"] == "SV-FIT")
    reference = {
        "order_date": ORDER["order_date"].isoformat(),
        "deliver_by": ORDER["deliver_by"].isoformat(),
        "supplier": ORDER["supplier"],
        "items": [
            {
                **{key: item[key] for key in ("code", "description", "qty")},
                "unit_price": money(item["unit_price"], "EUR"),
                "amount": money(item["amount"], "EUR"),
            }
            for item in items
        ],
        "fitting_days": fitting["qty"],
        "net": money(net, "EUR"),
        "vat": money(vat, "EUR"),
        "due": money(due, "EUR"),
    }
    s.save("purchase-order", "Purchase order PO-5520", reference)


# --- The parts list ------------------------------------------------------------------------------

PART_KINDS = (
    ("BR", "Bearing, sealed", "mm bore"),
    ("SP", "Spacer ring", "mm"),
    ("PN", "Dowel pin", "mm"),
    ("GK", "Gasket, cork", "mm"),
)
ROWS_PER_PAGE = 40
PARTS_LIST = {"list_number": "PL-88", "issued": date(2026, 2, 2)}


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
        s.text(LEFT, 36, f"Wrenfield Pump Co.  |  Parts list {PARTS_LIST['list_number']}", size=7.5)
        s.text(LEFT, 812, f"Page {number} of {len(pages)}", size=7.5)
        top = 60.0
        if number == 1:
            s.text(LEFT, 76, "Parts list for the W40 hand pump", size=14, bold=True)
            s.text(LEFT, 100, f"List number: {PARTS_LIST['list_number']}")
            s.text(LEFT, 100 + LEADING, f"Issued: {long_date(PARTS_LIST['issued'])}")
            s.text(LEFT, 100 + 2 * LEADING, f"Parts listed: {len(parts)}")
            top = 140.0
        s.grid(xs, top, 1 + len(rows))
        s.row(xs, top, 0, ("Part", "Description", "Qty", "Weight, g"), bold=True)
        for r, part in enumerate(rows, start=1):
            s.row(xs, top, r, (part["part"], part["description"], str(part["qty"]), part["weight"]))
    reference = {
        "list_number": PARTS_LIST["list_number"],
        "issued": PARTS_LIST["issued"].isoformat(),
        "parts_listed": len(parts),
        "parts": parts,
    }
    s.save("parts-list", f"Parts list {PARTS_LIST['list_number']}", reference)


if __name__ == "__main__":
    invoice()
    purchase_order()
    parts_list()
