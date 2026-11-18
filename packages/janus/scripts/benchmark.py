"""Time the steps DESIGN.md sets targets for, on generated documents, and print them beside the
targets.

    uv run python scripts/benchmark.py [--pages 100]

The document is invented, like the test fixtures: a numbered report whose pages carry headings,
body text, labelled values and a ruled table. Times on a shared or busy machine vary a lot; run
it twice and read the second run.
"""

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass

import pymupdf

from janus_pdf import PdfiumParser, PyMuPDFParser, extract, load_spec, read
from janus_pdf._index import Index, index_of

WIDTH, HEIGHT, MARGIN = 595.0, 842.0, 56.0
BODY = (
    "The inspection covered the deck, the bearings and both abutments. Readings were taken "
    "at the same points as in the previous year, so that the two sets can be compared."
)


def document(pages: int) -> bytes:
    """A born-digital report of `pages` pages."""
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.insert_text((MARGIN, 70), f"Section {n}", fontname="hebo", fontsize=13)
        y = 95.0
        for _ in range(6):
            page.insert_textbox(
                pymupdf.Rect(MARGIN, y, WIDTH - MARGIN, y + 60), BODY, fontname="helv", fontsize=9.5
            )
            y += 50
        page.insert_text((MARGIN, y), f"Reading ref.: R-{n:04d}", fontname="helv", fontsize=9.5)
        y += 30
        xs = [MARGIN, 200.0, 320.0, 440.0, WIDTH - MARGIN]
        for r, row in enumerate(
            [("Point", "Load, kN", "Strain", "Status")]
            + [(f"P{n}-{i}", f"{10 + i}.5", f"0.{i}2", "pass") for i in range(1, 7)]
        ):
            top = y + r * 16
            page.draw_line((xs[0], top), (xs[-1], top), width=0.6)
            for x, value in zip(xs, row, strict=False):
                page.insert_text((x + 4, top + 11.5), value, fontname="helv", fontsize=8.5)
        bottom = y + 7 * 16
        page.draw_line((xs[0], bottom), (xs[-1], bottom), width=0.6)
        for x in xs:
            page.draw_line((x, y), (x, bottom), width=0.6)
        page.insert_text((MARGIN, 812), f"Page {n} of {pages}", fontname="helv", fontsize=7.5)
    data = doc.tobytes(garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return data


SPECS = [
    {
        "fields": {
            "first": {"label": "Reading ref.", "pages": 1},
            "last_load": {"cell": {"table": 1, "row": 6, "column": "Load, kN"}, "type": "decimal"},
            "intro": {"section": "Section 1"},
            "points": {
                "records": {"header": {"point": "Point", "load": "Load, kN"}},
                "columns": {"load": "decimal"},
                "pages": 1,  # every page prints its own table under the same header
            },
            "absent": {"label": "Inspector"},  # missing: builds the suggestion table
        }
    },
    {"fields": {"ref": {"label": "Reading ref.", "pages": 2}, "s": {"section": "Section 2"}}},
]


@dataclass(frozen=True)
class Timing:
    """One step's time beside its target."""

    step: str
    seconds: float
    target: float  # seconds

    @property
    def ratio(self) -> float:
        """The time as a multiple of the target."""
        return self.seconds / self.target


def _time[T](run: Callable[[], T]) -> tuple[float, T]:
    start = time.perf_counter()
    value = run()
    return time.perf_counter() - start, value


def measure(pages: int = 100) -> list[Timing]:
    """Time reading, indexing and extraction on a generated document of `pages` pages."""
    pdf, small = document(pages), document(10)
    first, later = (load_spec(s) for s in SPECS)
    seconds, layer = _time(lambda: read(pdf, PyMuPDFParser()))
    out = [Timing("Read, PyMuPDF, per page", seconds / pages, 0.25)]
    seconds, _ = _time(lambda: read(pdf, PdfiumParser()))
    out.append(Timing("Read, PDFium, per page", seconds / pages, 0.1))
    steps: list[tuple[str, Callable[[], object], float]] = [
        (f"Build the index, {pages} pages", lambda: Index(layer), 0.5),
        (f"Extract one spec, {pages} pages, first", lambda: extract(layer, first), 0.5),
        (f"Extract one spec, {pages} pages, later", lambda: extract(layer, later), 0.1),
    ]
    for i, (step, run, target) in enumerate(steps):
        if i == 1:
            index_of(layer)  # extraction times exclude the index, which was timed on its own
        out.append(Timing(step, _time(run)[0], target))
    small_layer = read(small, PyMuPDFParser())
    seconds, _ = _time(lambda: extract(small_layer, first))
    out.append(Timing("Extract one spec, 10 pages, index included", seconds, 0.2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=int, default=100)
    args = parser.parse_args()
    print(f"{'step':<42} {'time':>10} {'target':>10}")
    for t in measure(args.pages):
        print(f"{t.step:<42} {t.seconds * 1000:>7.0f} ms {t.target * 1000:>7.0f} ms")


if __name__ == "__main__":
    main()
