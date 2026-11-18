"""Page images for the workbench viewer and the inspect view.

Pages render as displayed, after /Rotate, which is the frame the layer's boxes use: a viewer lays
word boxes over the image by multiplying them with the scale.
"""

import pymupdf

RENDERER = f"pymupdf {pymupdf.VersionBind} displayed png"
MIN_SCALE = 0.25
MAX_SCALE = 4.0


def render_png(pdf: bytes, page: int, scale: float) -> bytes:
    """A PNG of one page (1-based) at `scale` pixels per PDF point."""
    if not MIN_SCALE <= scale <= MAX_SCALE:
        raise ValueError(f"scale must be between {MIN_SCALE} and {MAX_SCALE}")
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if not 1 <= page <= doc.page_count:
            raise IndexError(f"page {page} is outside 1..{doc.page_count}")
        return (
            doc[page - 1]
            .get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            .tobytes("png")
        )
