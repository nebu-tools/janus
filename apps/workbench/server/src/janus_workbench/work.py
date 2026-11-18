"""What runs in a worker process. Each function calls one `janus_pdf` function on one PDF.

The arguments are paths the server built from hashes, and plain numbers.
"""

from pathlib import Path

import janus_pdf


def count_pages(pdf: str) -> int:
    return janus_pdf.page_count(Path(pdf))


def read_layer(pdf: str, cache: str, layers: str) -> dict:
    """Read the PDF and write its layer to `layers`, named by the layer's ID. Pages are kept in
    `cache` as they are read, so a read that was stopped goes on from there."""
    layer = janus_pdf.read(Path(pdf), janus_pdf.PyMuPDFParser(cache=cache))
    path = Path(layers) / f"{layer.id}.json"
    partial = path.with_suffix(".part")
    partial.write_text(layer.model_dump_json())
    partial.replace(path)
    return {"layer": layer.id, "engine": layer.recipe.engine, "tables": len(layer.tables)}


def render_page(pdf: str, page: int, scale: int) -> bytes:
    return janus_pdf.render_png(Path(pdf).read_bytes(), page, scale)
