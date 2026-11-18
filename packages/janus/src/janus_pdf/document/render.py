"""Page images for the workbench viewer and the inspect view.

Pages render unrotated, in the frame the layer's boxes use, so a viewer can lay word boxes over the
image by multiplying with the scale and turn the whole page by `Page.rotation` itself.
"""

import pymupdf

RENDERER = f"pymupdf {pymupdf.VersionBind} unrotated png"
MIN_SCALE = 0.25
MAX_SCALE = 4.0


def render_png(pdf: bytes, page: int, scale: float) -> bytes:
    """A PNG of one page (1-based) at `scale` pixels per PDF point."""
    if not MIN_SCALE <= scale <= MAX_SCALE:
        raise ValueError(f"scale must be between {MIN_SCALE} and {MAX_SCALE}")
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if not 1 <= page <= doc.page_count:
            raise IndexError(f"page {page} is outside 1..{doc.page_count}")
        p = doc[page - 1]
        p.set_rotation(0)
        return p.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
