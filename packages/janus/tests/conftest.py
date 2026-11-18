import pytest

from janus_pdf.document import Layer, PdfiumParser, PyMuPDFParser, read
from support import INSPECTION, INVOICE, ORDER, REPORT


@pytest.fixture(scope="session")
def report_pdf() -> bytes:
    return REPORT.read_bytes()


@pytest.fixture(scope="session")
def report(report_pdf: bytes) -> Layer:
    """The survey report read with PyMuPDF, once per session."""
    return read(report_pdf, PyMuPDFParser())


@pytest.fixture(scope="session")
def report_pdfium(report_pdf: bytes) -> Layer:
    """The survey report read with PDFium, once per session."""
    return read(report_pdf, PdfiumParser())


@pytest.fixture(scope="session")
def invoice() -> Layer:
    return read(INVOICE)


@pytest.fixture(scope="session")
def order() -> Layer:
    return read(ORDER)


@pytest.fixture(scope="session")
def inspection() -> Layer:
    return read(INSPECTION)
