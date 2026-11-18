"""The janus command.

    janus inspect report.pdf --find "Total due"
    janus extract invoice.yaml report.pdf
    janus compare invoice.yaml report.pdf expected.json --rules rules.yaml

`extract` exits 0 when every field was extracted and 1 otherwise; `compare` exits 0 when every
check matched and 1 otherwise; both exit 2 on bad input (a spec that does not load, a file
that is not a PDF, reference or rules that do not parse) and 3 on a fault in janus itself. Either
way the error is printed on one line, never as a traceback.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from janus_pdf.compare import compare
from janus_pdf.document import Layer, PdfiumParser, PyMuPDFParser, read
from janus_pdf.extract import extract
from janus_pdf.inspect import inspect
from janus_pdf.output import checks_text, extraction_text, inspection_text, to_json
from janus_pdf.spec import load

ENGINES = {"pymupdf": PyMuPDFParser, "pdfium": PdfiumParser}


def _layer(path: str, engine: str) -> Layer:
    return read(Path(path), ENGINES[engine]())


def _data(path: str) -> Any:
    text = Path(path).read_text()
    try:
        return json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"{path}: {' '.join(str(exc).split())}") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="janus", description="Typed values from PDFs.")
    parser.add_argument("--engine", choices=sorted(ENGINES), default="pymupdf")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("inspect", help="pages, tables, headings, and where a phrase is")
    p.add_argument("pdf")
    p.add_argument("--page", type=int)
    p.add_argument("--find")
    p.add_argument("--rows", type=int, default=4, help="table rows to preview")

    p = commands.add_parser("extract", help="extract a spec's fields from a PDF")
    p.add_argument("spec")
    p.add_argument("pdf")
    p.add_argument("--cells", action="store_true", help="list every record cell")

    p = commands.add_parser("compare", help="extract, then compare with reference data")
    p.add_argument("spec")
    p.add_argument("pdf")
    p.add_argument("reference", help="JSON or YAML shaped like the extraction's data")
    p.add_argument("--rules", help="YAML or JSON mapping path patterns to tolerances")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line in `argv` and return the exit status."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect(_layer(args.pdf, args.engine), args.page, args.find, args.rows)
            print(to_json(result) if args.json else inspection_text(result))
            return 0
        spec = load(Path(args.spec))
        extraction = extract(_layer(args.pdf, args.engine), spec)
        if args.command == "extract":
            print(to_json(extraction) if args.json else extraction_text(extraction, args.cells))
            return 0 if all(r.status == "extracted" for r in extraction.fields) else 1
        rules = _data(args.rules) if args.rules else None
        checks = compare(extraction, _data(args.reference), rules)
        print(to_json(checks) if args.json else checks_text(checks))
        return 0 if all(c.status == "match" for c in checks) else 1
    except (OSError, ValueError) as exc:
        print(f"janus: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # a fault in janus, reported without a traceback
        print(f"janus: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
