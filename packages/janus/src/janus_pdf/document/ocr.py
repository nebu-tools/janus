"""OCRmyPDF for pages without a usable text layer.

OCRmyPDF writes Tesseract's words back into the PDF as an invisible text layer, so a scan goes
through the same PyMuPDF reading as a born-digital file. Only pages that triage marks `ocr` or
`broken_encoding` are OCRed. Needs the `ocrmypdf` and `tesseract` executables; without them
`ocr_available()` is False and `OcrMyPdfParser` refuses to start.
"""

import shutil
import subprocess

import pymupdf

from janus_pdf.document.engines import pymupdf_page_input
from janus_pdf.document.layout import ASSEMBLY_VERSION, assemble
from janus_pdf.document.model import ParserRecipe, RawLayer
from janus_pdf.document.tables import TABLES_VERSION
from janus_pdf.document.triage import triage


class OcrUnavailable(RuntimeError):
    """`ocrmypdf` or `tesseract` is not installed."""


def ocr_available() -> bool:
    """Whether the `ocrmypdf` and `tesseract` executables are on the PATH."""
    return shutil.which("ocrmypdf") is not None and shutil.which("tesseract") is not None


def _version(command: str) -> str:
    out = subprocess.run([command, "--version"], capture_output=True, text=True, check=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


class OcrMyPdfParser:
    """PyMuPDF reading after OCRmyPDF has given scanned and broken pages a text layer."""

    def __init__(self, languages: tuple[str, ...] = ("eng", "deu")) -> None:
        if not ocr_available():
            raise OcrUnavailable("install ocrmypdf and tesseract to OCR scanned pages")
        self._languages = languages
        self.recipe = ParserRecipe(
            engine="ocrmypdf+pymupdf",
            engine_version=(
                f"{_version('ocrmypdf')}; {_version('tesseract')}; pymupdf {pymupdf.VersionBind}"
            ),
            settings=(
                ("assembly", ASSEMBLY_VERSION),
                ("tables", TABLES_VERSION),
                ("languages", "+".join(languages)),
                ("pages", "triage:ocr,broken_encoding"),
            ),
        )

    def parse(self, pdf: bytes) -> RawLayer:
        pages = triage(pdf)
        todo = [p.page for p in pages if p.kind != "text"]
        source = pdf
        if todo:
            done = subprocess.run(
                [
                    "ocrmypdf",
                    "--force-ocr",
                    "--pages",
                    ",".join(str(p) for p in todo),
                    "-l",
                    "+".join(self._languages),
                    "--output-type",
                    "pdf",
                    "--optimize",
                    "0",
                    "-",
                    "-",
                ],
                input=pdf,
                capture_output=True,
                check=True,
            )
            source = done.stdout
        with pymupdf.open(stream=source, filetype="pdf") as doc:
            inputs = []
            for page in doc:
                page_input = pymupdf_page_input(page)
                page_input.triage = pages[page_input.number - 1]
                inputs.append(page_input)
        return assemble(inputs)
