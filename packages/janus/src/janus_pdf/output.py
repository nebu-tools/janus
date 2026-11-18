"""Plain data for results: JSON for files and pipes, short text for terminals."""

import dataclasses
import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from janus_pdf.compare import Check
from janus_pdf.extract import Extraction
from janus_pdf.inspect import Inspection


def plain(value: Any) -> Any:
    """Dataclasses, models, tuples and decimals as JSON-ready values."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
        if isinstance(value, Extraction):
            out = {"data": plain(value.data), **out}
        return out
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def to_json(value: Any) -> str:
    """`value` as indented JSON."""
    return json.dumps(plain(value), ensure_ascii=False, indent=2)


def _short(value: Any, width: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= width else text[: width - 1] + "…"


def extraction_text(ex: Extraction, cells: bool = False) -> str:
    """One line per field with its status, page and value; record cells only when `cells`."""
    lines = []
    for r in ex.fields:
        parts = r.path.split("/")
        if not cells and any(p.isdigit() for p in parts) and r.status == "extracted":
            continue
        page = f"p{r.page}" if r.page is not None else "  "
        lines.append(f"{r.status:<11} {r.path:<26} {page:<4} {_short(r.value)}")
        if r.message:
            lines.append(f"{'':11} {'':26} {'':4} {r.message}")
        for s in r.suggestions:
            lines.append(f"{'':11} {'':26} {'':4} did you mean {s}?")
    counts: dict[str, int] = {}
    for r in ex.fields:
        counts[r.status] = counts.get(r.status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    lines.append(summary)
    return _join(lines)


def checks_text(checks: tuple[Check, ...]) -> str:
    """One line per check, then a count of each status."""
    lines = [
        f"{c.status:<13} {c.path:<30} expected {_short(c.expected, 30)}, "
        f"got {_short(c.actual, 30)}  {c.message}"
        for c in checks
    ]
    counts: dict[str, int] = {}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    lines.append(", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    return _join(lines)


def inspection_text(ins: Inspection) -> str:
    """Pages, table previews, headings and search hits, as a terminal reads them."""
    out = [f"document {ins.document[:12]}  layer {ins.layer[:12]}  engine {ins.engine}"]
    for p in ins.pages:
        tables = f"  tables {', '.join(p.tables)}" if p.tables else ""
        out.append(f"page {p.number:>3}  {p.kind:<15} {p.words:>5} words{tables}")
    for t in ins.tables:
        out.append(f"\ntable {t.id} (page {t.page}, {t.rows} x {t.cols})")
        out += [f"  r{r}: " + " | ".join(row) for r, row in enumerate(t.preview)]
    if ins.headings:
        out.append("\nheadings")
        out += [
            f"  p{h.page:<3} {h.size:>5.1f} pt {'bold' if h.bold else '    '}  {h.text}"
            for h in ins.headings
        ]
    if ins.hits:
        out.append("\nfound")
        for h in ins.hits:
            where = h.cell or f"({h.box.x0:.0f}, {h.box.y0:.0f})"
            label = "label ok" if h.starts_line else "mid-line"
            out.append(f"  p{h.page:<3} {where:<14} {label:<9} {h.text[:80]}")
    return _join(out)


def _join(lines: list[str]) -> str:
    """The lines as one text. Padding for columns never leaves spaces at the end of a line."""
    return "\n".join(line.rstrip() for line in lines)
