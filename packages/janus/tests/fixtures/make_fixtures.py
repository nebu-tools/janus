"""Build the test PDFs in this directory: a survey report, an invoice, a purchase order, an
inspection report and a stock ledger.

    uv run python tests/fixtures/make_fixtures.py

Every document is invented. Text goes in Liberation Sans (SIL Open Font License 1.1), embedded
and subset, because PDF's built-in Helvetica has no euro sign or en dash and no ToUnicode map. The script
looks for the fonts in the usual Linux places or in $JANUS_FONT_DIR; they come with most Linux
distributions and from https://github.com/liberationfonts/liberation-fonts/releases. The fonts
themselves are not committed, only the PDFs that embed them.

The output is deterministic for a given PyMuPDF: fixed metadata, no timestamps, no random IDs.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
_FONT_DIRS = (
    os.environ.get("JANUS_FONT_DIR", ""),
    "/usr/share/fonts/liberation",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/liberation-sans",
    "/usr/share/fonts/TTF",
)
WIDTH, HEIGHT = 595.0, 842.0  # A4
MARGIN = 56.0
GUTTER = WIDTH / 2  # between the two columns of page 2
COLUMN = (MARGIN, GUTTER - 10.0), (GUTTER + 10.0, WIDTH - MARGIN)
BODY, LEADING = 9.5, 12.5
REGULAR, BOLD = "F1", "F2"


def _font(name: str) -> str:
    for directory in _FONT_DIRS:
        path = Path(directory) / name
        if directory and path.is_file():
            return str(path)
    sys.exit(f"{name} not found; install Liberation Sans or set JANUS_FONT_DIR")


@dataclass
class Writer:
    """Places text and rules on pages, top-left origin, y the baseline."""

    doc: pymupdf.Document = field(default_factory=pymupdf.open)
    regular: str = field(default_factory=lambda: _font("LiberationSans-Regular.ttf"))
    bold: str = field(default_factory=lambda: _font("LiberationSans-Bold.ttf"))

    def page(self) -> pymupdf.Page:
        page = self.doc.new_page(width=WIDTH, height=HEIGHT)
        page.insert_font(fontname=REGULAR, fontfile=self.regular)
        page.insert_font(fontname=BOLD, fontfile=self.bold)
        return page

    def text(
        self, page: pymupdf.Page, x: float, y: float, text: str, size=BODY, bold=False
    ) -> float:
        """Write one line; return its right edge."""
        font = BOLD if bold else REGULAR
        page.insert_text((x, y), text, fontname=font, fontsize=size)
        return x + self.width(text, size, bold)

    def width(self, text: str, size=BODY, bold=False) -> float:
        return pymupdf.Font(fontfile=self.bold if bold else self.regular).text_length(
            text, fontsize=size
        )

    def lines(
        self, page: pymupdf.Page, x: float, y: float, lines: list[str], fit=0.0, **kw
    ) -> float:
        """Write lines one under another; return the baseline after the last. With `fit`, every
        line must be narrower than that, so a column's lines never reach into the next one."""
        for line in lines:
            right = self.text(page, x, y, line, **kw)
            if fit and right - x > fit:
                sys.exit(f"{line!r} is wider than {fit} points")
            y += LEADING
        return y

    def rule(self, page: pymupdf.Page, x0: float, x1: float, y: float, width=0.6) -> None:
        page.draw_line((x0, y), (x1, y), width=width)

    def vrule(self, page: pymupdf.Page, x: float, y0: float, y1: float) -> None:
        page.draw_line((x, y0), (x, y1), width=0.6)

    def save(self, path: Path, title: str) -> None:
        self.doc.subset_fonts()
        self.doc.set_metadata(
            {"title": title, "author": "Janus test fixtures", "producer": "", "creator": ""}
        )
        self.doc.save(path, garbage=4, deflate=True, no_new_id=True)
        print(f"wrote {path.relative_to(HERE.parent.parent)} ({path.stat().st_size} bytes)")


# --- The survey report --------------------------------------------------------------------------

REPORT = "Stream Invertebrate Survey 2026"
GROUP = "Northfield Ecology Group"

# Page 2: a paragraph that runs from the foot of the left column to the top of the right one,
# hyphenated at a line break on the way.
COLUMN_BREAK = [
    "Abundance estimates were directionally consis-",
    "tent across both sites and agreed with the",
]
COLUMN_TOP = ["counts from the earlier survey of the same", "streams in the winter of 2024."]
COLUMN_BREAK_QUOTE = (
    "Abundance estimates were directionally consistent across both sites and agreed with the "
    "counts from the earlier survey of the same"
)
# Page 2: "residing" broken with a soft hyphen (U+00AD), not a printed one.
SOFT_HYPHEN = ["Most mayfly nymphs were found under stones, resid­", "ing in the fastest riffles."]
SOFT_HYPHEN_QUOTE = "under stones, residing in the fastest"


def _furniture(w: Writer, page: pymupdf.Page, number: int, pages: int) -> None:
    """The running head and footer every page carries."""
    w.text(page, MARGIN, 36, f"{GROUP}  |  {REPORT}", size=7.5)
    w.text(page, WIDTH - MARGIN - w.width("Report NEG-2026-04", 7.5), 36, "Report NEG-2026-04", 7.5)
    w.rule(page, MARGIN, WIDTH - MARGIN, 42, width=0.3)
    w.text(page, MARGIN, 812, "Northfield Ecology Group, 4 Mill Lane, Northfield", size=7.5)
    label = f"Page {number} of {pages}"
    w.text(page, WIDTH - MARGIN - w.width(label, 7.5), 812, label, size=7.5)


def _h1(w: Writer, page: pymupdf.Page, x: float, y: float, text: str) -> float:
    w.text(page, x, y, text, size=12, bold=True)
    return y + 18


def _h2(w: Writer, page: pymupdf.Page, x: float, y: float, text: str) -> float:
    w.text(page, x, y, text, size=10.5, bold=True)
    return y + 15


def _page1(w: Writer) -> None:
    page = w.page()
    x = MARGIN
    w.text(page, x, 90, REPORT, size=18, bold=True)
    w.text(page, x, 110, GROUP, size=11)
    y = w.lines(
        page,
        x,
        134,
        [
            "Report date: 14 March 2026",
            "Survey period: 03/02/2026 to 28/02/2026",
            "Lead surveyor: R. Okafor",
        ],
    )
    y = _h1(w, page, x, y + 14, "1 Introduction")
    y = w.lines(
        page,
        x,
        y,
        [
            "This report describes the winter survey of benthic invertebrates in two chalk streams",
            "north of Northfield. Site A lies upstream of the sewage works and Site B lies 2 km",
            "downstream of it. The survey repeats the methods of the 2024 survey so that the two",
            "years can be compared directly.",
        ],
    )
    y = _h1(w, page, x, y + 14, "2 Methods")
    y = _h2(w, page, x, y, "2.1 Sampling")
    y = w.lines(
        page,
        x,
        y,
        [
            "Three-minute kick samples were taken with a 1 mm mesh net at riffles, pools and runs.",
            "Each site was visited on four mornings between 03/02/2026 and 28/02/2026, and 120",
            "samples were taken at each site in total.",
        ],
    )
    y = _h2(w, page, x, y + 8, "2.2 Laboratory analysis")
    w.lines(
        page,
        x,
        y,
        [
            "Samples were sorted under a stereo microscope and identified to family level. Body",
            "length was measured on the first 20 individuals of each family in each sample.",
        ],
    )


def _page2(w: Writer) -> None:
    page = w.page()
    (lx, lr), (rx, rr) = COLUMN
    left, right = lr - lx, rr - rx
    y = _h1(w, page, lx, 80, "3 Results")
    y = _h2(w, page, lx, y, "3.1 Sampling")
    y = w.lines(
        page,
        lx,
        y,
        [
            "All 240 planned samples were taken. Two",
            "samples at Site B were taken again on the",
            "following morning after the net tore.",
        ],
        fit=left,
    )
    y = _h2(w, page, lx, y + 8, "3.2 Abundance")
    y = w.lines(
        page,
        lx,
        y,
        [
            "Site A held more taxa per sample than Site",
            "B in every habitat (Table 1). The difference",
            "was largest in riffles and smallest in pools.",
            *SOFT_HYPHEN,
        ],
        fit=left,
    )
    # Fill the left column so the quote's first lines sit at its foot.
    filler = [
        "Counts are given per sample unless a table",
        "says otherwise. Families with fewer than",
        "five individuals in the whole survey are",
        "pooled as other taxa in every table.",
    ]
    k = 0
    while y < 740 - 3 * LEADING:
        y = w.lines(page, lx, y, [filler[k % len(filler)]], fit=left)
        k += 1
    w.lines(page, lx, y, ["Sorting errors were below 5% in every batch.", *COLUMN_BREAK], fit=left)

    y = w.lines(page, rx, 80, COLUMN_TOP, fit=right)
    y = _h2(w, page, rx, y + 8, "3.3 Water chemistry")
    w.lines(
        page,
        rx,
        y,
        [
            "Nitrate was higher at Site B on every visit",
            "(Table 2). Conductivity (EC) followed the",
            "same pattern; pH did not differ by site.",
        ],
        fit=right,
    )


# Table 1: three rules, nested headers (a row-spanning "Measure", "Site A" and "Site B" each over
# three habitats), and compound values. "1.0 (1.0, 2.0)" is printed three times in one row.
TABLE1_HEAD = ["Riffle", "Pool", "Run"]
TABLE1_ROWS = [
    ("Samples, n", ["40", "40", "40", "40", "40", "40"]),
    ("Taxa per sample, mean (SD)", ["14.2 (3.1)", "11.8 (2.7)", "13.0 (3.0)", "12.6 (2.9)", "10.4 (2.2)", "11.5 (2.7)"]),
    ("EPT individuals, n (%)", ["412 (34.5%)", "298 (27.1%)", "355 (30.2%)", "260 (22.4%)", "201 (19.8%)", "233 (21.0%)"]),
    ("Length, mm, mean ± SD", ["4.6 ± 1.2", "3.9 ± 1.0", "4.2 ± 1.1", "4.1 ± 1.3", "3.5 ± 0.9", "3.8 ± 1.0"]),
    ("Abundance ratio (95% CI)", ["1.0 (1.0, 2.0)", "1.0 (1.0, 2.0)", "1.0 (1.0, 2.0)", "0.8 (0.6, 1.1)", "0.7 (0.5, 1.0)", "0.9 (0.7, 1.2)"]),
]  # fmt: skip


def _page3(w: Writer) -> None:
    page = w.page()
    x0, x1 = MARGIN, WIDTH - MARGIN
    w.text(page, x0, 80, "Table 1 Invertebrates per sample by site and habitat", bold=True)
    top = 88.0
    w.rule(page, x0, x1, top)
    first = 170.0
    col = (x1 - first) / 6
    xs = [first + i * col for i in range(6)]
    w.text(page, x0, top + 13, "Measure", bold=True)
    for group, start in (("Site A (n = 120)", 0), ("Site B (n = 120)", 3)):
        w.text(page, xs[start], top + 13, group, bold=True)
        w.rule(page, xs[start], xs[start] + 3 * col - 8, top + 17, width=0.4)
    for i, head in enumerate(TABLE1_HEAD * 2):
        w.text(page, xs[i], top + 29, head, bold=True)
    w.rule(page, x0, x1, top + 34)
    y = top + 48
    for label, values in TABLE1_ROWS:
        w.text(page, x0, y, label, size=8.5)
        for xv, value in zip(xs, values, strict=True):
            w.text(page, xv, y, value, size=8.5)
        y += 15
    w.rule(page, x0, x1, y - 9)
    w.lines(
        page,
        x0,
        y + 8,
        [
            "EPT: mayflies, stoneflies and caddisflies. The abundance ratio compares each habitat",
            "with riffles at Site A.",
        ],
        size=8,
    )

    y = _h1(w, page, x0, y + 50, "4 Discussion")
    w.lines(
        page,
        x0,
        y,
        [
            "The lower counts at Site B match the higher nitrate there. The 2024 survey found the",
            "same pattern, so the difference is unlikely to be a single bad winter.",
        ],
    )


# Table 2: fully ruled, its first row a title across every column, so the header is row 2.
TABLE2_HEAD = ["Site", "Visit date", "pH", "EC, µS/cm", "Nitrate, mg/L"]
TABLE2_ROWS = [
    ["Site A", "03/02/2026", "7.9", "512", "4.1"],
    ["Site A", "17/02/2026", "8.0", "498", "3.8"],
    ["Site B", "03/02/2026", "7.8", "604", "7.6"],
    ["Site B", "17/02/2026", "7.9", "611", "8.2"],
]
# Table 3: three rules; "Measure" and "Habitat" span both header rows, "Difference between sites"
# spans two columns, and the values are estimates with intervals and p-values.
TABLE3_ROWS = [
    ("Taxa per sample", "Riffle", "14.2 (3.1)", "12.6 (2.9)", "1.6 (0.9, 2.3)", "P < 0.001"),
    ("", "Pool", "11.8 (2.7)", "10.4 (2.2)", "1.4 (0.6, 2.2)", "P = 0.002"),
    ("Body length, mm", "Riffle", "4.6 (1.2)", "4.1 (1.3)", "0.5 (0.1, 0.9)", "P = 0.03"),
    ("", "Pool", "3.9 (1.0)", "3.5 (0.9)", "0.4 (-0.1, 0.9)", "P = 0.12"),
]


def _page4(w: Writer) -> None:
    page = w.page()
    x0, x1 = MARGIN, WIDTH - MARGIN
    w.text(page, x0, 80, "Table 2 Water chemistry at each visit", bold=True)
    widths = [90.0, 90.0, 60.0, 120.0]
    xs = [x0]
    for width in widths:
        xs.append(xs[-1] + width)
    xs.append(x1)
    top, row = 88.0, 16.0
    rows = 2 + len(TABLE2_ROWS)
    bottom = top + rows * row
    for r in range(rows + 1):
        w.rule(page, x0, x1, top + r * row)
    for i, x in enumerate(xs):
        # The title row has no inner verticals.
        w.vrule(page, x, top if i in (0, len(xs) - 1) else top + row, bottom)
    w.text(page, x0 + 4, top + 11.5, "Water chemistry, February 2026", bold=True)
    for xv, head in zip(xs, TABLE2_HEAD, strict=False):
        w.text(page, xv + 4, top + row + 11.5, head, size=8.5, bold=True)
    for r, values in enumerate(TABLE2_ROWS, start=2):
        for xv, value in zip(xs, values, strict=False):
            w.text(page, xv + 4, top + r * row + 11.5, value, size=8.5)

    y = bottom + 40
    w.text(page, x0, y, "Table 3 Differences between sites by habitat", bold=True)
    top = y + 8
    w.rule(page, x0, x1, top)
    xs = [x0, x0 + 95, x0 + 160, x0 + 225, x0 + 290, x0 + 400]
    w.text(page, xs[0], top + 13, "Measure", bold=True)
    w.text(page, xs[1], top + 13, "Habitat", bold=True)
    w.text(page, xs[2], top + 13, "Site A", bold=True)
    w.text(page, xs[3], top + 13, "Site B", bold=True)
    w.text(page, xs[4], top + 13, "Difference between sites", bold=True)
    w.rule(page, xs[4], x1, top + 17, width=0.4)
    w.text(page, xs[2], top + 29, "mean (SD)", size=8.5, bold=True)
    w.text(page, xs[3], top + 29, "mean (SD)", size=8.5, bold=True)
    w.text(page, xs[4], top + 29, "Estimate (95% CI)", size=8.5, bold=True)
    w.text(page, xs[5], top + 29, "P value", size=8.5, bold=True)
    w.rule(page, x0, x1, top + 34)
    y = top + 48
    for values in TABLE3_ROWS:
        for xv, value in zip(xs, values, strict=True):
            if value:
                w.text(page, xv, y, value, size=8.5)
        y += 15
    w.rule(page, x0, x1, y - 9)

    # A borderless list of sampling visits: aligned columns, no rules, no caption.
    y = _h2(w, page, x0, y + 40, "Sampling visits")
    xs = [x0, x0 + 80, x0 + 210, x0 + 300]
    for values in (
        ("Site", "Date", "Start", "Samples"),
        ("Site A", "3 February 2026", "09:40", "30"),
        ("Site B", "3 February 2026", "11:15", "30"),
        ("Site A", "17 February 2026", "09:35", "30"),
        ("Site B", "17 February 2026", "11:05", "30"),
    ):
        for xv, value in zip(xs, values, strict=True):
            w.text(page, xv, y, value, bold=values[0] == "Site")
        y += LEADING


def report() -> None:
    w = Writer()
    for make in (_page1, _page2, _page3, _page4):
        make(w)
    for index in range(len(w.doc)):
        number, page = index + 1, w.doc[index]
        _furniture(w, page, number, len(w.doc))
    w.save(HERE / "survey-report.pdf", REPORT)


# --- The invoice --------------------------------------------------------------------------------

SELLER = "Hollin Tool Supply Ltd"
# Description, quantity, unit price, amount. The amounts add up to the subtotal.
INVOICE_ROWS = [
    ("Steel widget, 40 mm", "120", "£1.25", "£150.00"),
    ("Brass hinge, pair", "40", "£3.50", "£140.00"),
    ("Hex bolt M8, box of 50", "6", "£9.25", "£55.50"),
    ("Assembly, hours", "6", "£29.50", "£177.00"),
]


def _right(w: Writer, page: pymupdf.Page, x1: float, y: float, text: str, **kw) -> None:
    w.text(page, x1 - w.width(text, kw.get("size", BODY), kw.get("bold", False)), y, text, **kw)


def invoice() -> None:
    """One page, no rules: labels set off by a colon or a column gap, and borderless line items
    followed by totals."""
    w = Writer()
    page = w.page()
    x0, x1 = MARGIN, WIDTH - MARGIN
    w.text(page, x0, 80, SELLER, size=16, bold=True)
    w.lines(page, x0, 98, ["12 Forge Street, Hollin", "accounts@hollin-tools.example"], size=8.5)
    _right(w, page, x1, 80, "INVOICE", size=16, bold=True)
    y = 150.0
    for label, value in (("Invoice No.", "2026-0451"), ("Date", "12 March 2026")):
        w.text(page, x0, y, label, bold=True)
        w.text(page, x0 + 90, y, value)
        y += LEADING
    w.lines(page, x0, y, ["Customer: Blue Fern Studio", "Due: 11/04/2026"])

    cols = [x0, x0 + 250, x0 + 330]  # description, qty, unit price; amount is right-aligned
    y = 240.0
    for x, head in zip(cols, ("Description", "Qty", "Unit price"), strict=True):
        w.text(page, x, y, head, bold=True)
    _right(w, page, x1, y, "Amount", bold=True)
    y += 16
    for description, qty, unit, amount in INVOICE_ROWS:
        for x, value in zip(cols, (description, qty, unit), strict=True):
            w.text(page, x, y, value)
        _right(w, page, x1, y, amount)
        y += LEADING
    y += 6
    for label, amount, bold in (
        ("Subtotal", "£522.50", False),
        ("VAT (20%)", "£104.50", False),
        ("Total due: £627.00", "", True),
    ):
        w.text(page, cols[2], y, label, bold=bold)
        if amount:
            _right(w, page, x1, y, amount)
        y += LEADING
    w.lines(page, x0, y + 30, ["Payment within 30 days to the account shown on our website."])
    w.save(HERE / "invoice.pdf", f"{SELLER} invoice 2026-0451")


# --- The purchase order -------------------------------------------------------------------------

# Code, description, quantity, unit price, amount, in German number format.
ORDER_ROWS = [
    ("TR-220", "Torque wrench", "2", "412,25 €", "824,50 €"),
    ("TR-118", "Pipe threader", "1", "1.085,50 €", "1.085,50 €"),
    ("CB-005", "Cable box", "10", "12,40 €", "124,00 €"),
    ("SV-CAL", "Calibration service", "1", "350,00 €", "350,00 €"),
]


def purchase_order() -> None:
    """One page with a fully ruled table whose first row is a title, so the header is row 2."""
    w = Writer()
    page = w.page()
    x0, x1 = MARGIN, WIDTH - MARGIN
    w.text(page, x0, 80, "Kestrel Fabrication GmbH", size=16, bold=True)
    w.lines(
        page,
        x0,
        110,
        ["Order date 9 March 2026", "Due date 11 April 2026", "Supplier: " + SELLER],
    )
    xs = [x0, x0 + 70, x0 + 230, x0 + 280, x0 + 380, x1]
    top, row = 170.0, 16.0
    rows = 2 + len(ORDER_ROWS)
    bottom = top + rows * row
    for r in range(rows + 1):
        w.rule(page, x0, x1, top + r * row)
    for i, x in enumerate(xs):
        w.vrule(page, x, top if i in (0, len(xs) - 1) else top + row, bottom)
    w.text(page, x0 + 4, top + 11.5, "Purchase order PO-7731", bold=True)
    for x, head in zip(xs, ("Code", "Description", "Qty", "Unit price", "Amount"), strict=False):
        w.text(page, x + 4, top + row + 11.5, head, size=8.5, bold=True)
    for r, values in enumerate(ORDER_ROWS, start=2):
        for x, value in zip(xs, values, strict=False):
            w.text(page, x + 4, top + r * row + 11.5, value, size=8.5)
    y = bottom + 24
    for label, amount in (
        ("Net total", "2.384,00 €"),
        ("VAT 19%", "452,96 €"),
        ("Amount due", "2.836,96 €"),
    ):
        w.text(page, xs[3], y, label, bold=label == "Amount due")
        _right(w, page, x1, y, amount)
        y += LEADING
    w.save(HERE / "purchase-order.pdf", "Purchase order PO-7731")


# --- The inspection report ----------------------------------------------------------------------

# Element, condition, rating. A rating the inspector could not give is printed "n/a".
CONDITION_ROWS = [
    ("Bearings", "Light corrosion", "3"),
    ("Deck joint", "Not reachable", "n/a"),
    ("Parapet", "Sound", "1"),
]


def inspection_report() -> None:
    """One page whose sections repeat an unnumbered heading, "Findings", under two parents, and
    whose ruled condition table prints "n/a" for one rating."""
    w = Writer()
    page = w.page()
    x0, x1 = MARGIN, WIDTH - MARGIN
    w.text(page, x0, 80, "Mill Lane Footbridge Inspection", size=16, bold=True)
    y = w.lines(page, x0, 104, ["Inspection date: 2 March 2026", "Inspected by: J. Marsh"])
    for side, finding in (
        ("North abutment", "Hairline cracks in the wing wall, no wider than 0.2 mm."),
        ("South abutment", "Scour below the toe, about 150 mm deep at the downstream corner."),
    ):
        y = _h1(w, page, x0, y + 14, side)
        y = w.lines(page, x0, y, ["The abutment was inspected from the bank and from a ladder."])
        y = _h2(w, page, x0, y + 8, "Findings")
        y = w.lines(page, x0, y, [finding])
    y = _h1(w, page, x0, y + 14, "Condition ratings")
    xs = [x0, x0 + 140, x0 + 320, x1]
    top, row = y, 16.0
    rows = 1 + len(CONDITION_ROWS)
    for r in range(rows + 1):
        w.rule(page, x0, x1, top + r * row)
    for x in xs:
        w.vrule(page, x, top, top + rows * row)
    for x, head in zip(xs, ("Element", "Condition", "Rating"), strict=False):
        w.text(page, x + 4, top + 11.5, head, size=8.5, bold=True)
    for r, values in enumerate(CONDITION_ROWS, start=1):
        for x, value in zip(xs, values, strict=False):
            w.text(page, x + 4, top + r * row + 11.5, value, size=8.5)
    w.save(HERE / "inspection-report.pdf", "Mill Lane Footbridge Inspection")


# --- The stock ledger ----------------------------------------------------------------------------

# Item, description, qty. The table runs over three pages: page 2 repeats the header, page 3
# does not; each page break has a carried-forward line above it and a brought-forward line below.
LEDGER_PAGES = [
    [(f"SK-{100 + i}", f"Shelf bracket, size {i + 1}", str(10 + i)) for i in range(40)],
    [(f"SK-{140 + i}", f"Wall anchor, pack {i + 1}", str(50 + i)) for i in range(40)],
    [(f"SK-{180 + i}", f"Hinge pin, set {i + 1}", str(5 + i)) for i in range(6)],
]


def stock_ledger() -> None:
    """A ruled table of 86 items over three pages, with a page footer on every page."""
    w = Writer()
    x0, x1 = MARGIN, WIDTH - MARGIN
    xs = [x0, x0 + 90, x0 + 360, x1]
    row = 16.0
    for number, items in enumerate(LEDGER_PAGES, start=1):
        page = w.page()
        top = 70.0
        lines: list[tuple[tuple[str, ...], bool]] = []
        if number == 1:
            w.text(page, x0, 52, "Juniper Row Stores: stock ledger", size=14, bold=True)
            top = 70.0
        if number < 3:
            lines.append((("Item", "Description", "Qty"), True))
        if number > 1:
            lines.append((("Brought forward", "", ""), False))
        lines += [(item, False) for item in items]
        if number < 3:
            lines.append((("Carried forward", "", ""), False))
        else:
            lines.append((("Total", "", "86 lines"), True))
        bottom = top + len(lines) * row
        for r in range(len(lines) + 1):
            w.rule(page, x0, x1, top + r * row)
        for x in xs:
            w.vrule(page, x, top, bottom)
        for r, (values, bold) in enumerate(lines):
            for x, value in zip(xs, values, strict=False):
                if value:
                    w.text(page, x + 4, top + r * row + 11.5, value, size=8.5, bold=bold)
        w.text(page, x0, HEIGHT - 30, f"Stock ledger, page {number} of 3", size=8)
    w.save(HERE / "stock-ledger.pdf", "Juniper Row Stores stock ledger")


# --- The packing list ---------------------------------------------------------------------------


def _printed(w: Writer, page: pymupdf.Page, y: float, rows: list[tuple[str, str]]) -> float:
    """Item and Qty printed without rules from baseline `y`, the first row bold."""
    for i, (item, qty) in enumerate(rows):
        w.text(page, MARGIN, y, item, bold=i == 0)
        w.text(page, MARGIN + 240, y, qty, bold=i == 0)
        y += 18
    return y


def _ruled(w: Writer, page: pymupdf.Page, top: float, rows: list[tuple[str, str]]) -> float:
    """Item and Qty in a ruled grid from `top`, the first row bold."""
    x0, x1, row = MARGIN, MARGIN + 340, 20.0
    for r in range(len(rows) + 1):
        w.rule(page, x0, x1, top + r * row)
    for x in (x0, x0 + 230, x1):
        w.vrule(page, x, top, top + len(rows) * row)
    for r, (item, qty) in enumerate(rows):
        w.text(page, x0 + 6, top + r * row + 14, item, bold=r == 0)
        w.text(page, x0 + 236, top + r * row + 14, qty, bold=r == 0)
    return top + len(rows) * row


def packing_list() -> None:
    """The header Item / Qty printed again, once on each page: under a printed table by a
    ruled one (page 1), twice in one printed table (page 2), under a ruled table by a printed
    one (page 3), and at the top of the next page (pages 4 and 5)."""
    w = Writer()
    head = ("Item", "Qty")
    page = w.page()
    w.text(page, MARGIN, 60, "Packing list", size=14, bold=True)
    y = _printed(w, page, 100, [head, ("Apple", "1"), ("Pear", "2")])
    _ruled(w, page, y + 30, [head, ("Plum", "3")])
    page = w.page()
    _printed(w, page, 100, [head, ("Fig", "4"), head, ("Kiwi", "5")])
    page = w.page()
    bottom = _ruled(w, page, 90, [head, ("Lime", "6")])
    _printed(w, page, bottom + 40, [head, ("Date", "7")])
    page = w.page()
    _printed(w, page, 100, [head, ("Nut", "8")])
    page = w.page()
    _printed(w, page, 100, [head, ("Oat", "9")])
    w.save(HERE / "packing-list.pdf", "Packing list")


# --- Rows that hold the header's words ----------------------------------------------------------


def header_cells() -> None:
    """Body rows that print the header's words without being the header Item / Qty: the words
    inside a longer cell, without rules (page 1) and ruled (page 2); the header's texts in
    swapped columns, without rules (page 3) and ruled (page 4); a row labelled with one header
    text beside a number, and a total row (page 5). Page 6 prints a header over two lines:
    "Item" with "description" under it, beside "Qty"."""
    w = Writer()
    head = ("Item", "Qty")
    words = [head, ("Apple", "1"), ("Item Qty adapter", "2"), ("Pear", "3"), ("Total", "6")]
    swapped = [head, ("Apple", "1"), ("Qty", "Item"), ("Pear", "2")]
    _printed(w, w.page(), 100, words)
    _ruled(w, w.page(), 90, words)
    _printed(w, w.page(), 100, swapped)
    _ruled(w, w.page(), 90, swapped)
    _printed(w, w.page(), 100, [head, ("Apple", "1"), ("Qty", "3"), ("Item", "2"), ("Total", "6")])
    page = w.page()
    w.text(page, MARGIN, 100, "Item", bold=True)
    w.text(page, MARGIN + 240, 100, "Qty", bold=True)
    w.text(page, MARGIN, 100 + LEADING, "description", bold=True)
    _printed(w, page, 100 + 2 * LEADING + 6, [("Apple", "1"), ("Pear", "2")])
    w.save(HERE / "header-cells.pdf", "Header cells")


if __name__ == "__main__":
    report()
    invoice()
    purchase_order()
    inspection_report()
    stock_ledger()
    packing_list()
    header_cells()
