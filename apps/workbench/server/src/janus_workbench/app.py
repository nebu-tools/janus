"""The HTTP API, and the built client served beside it.

Each endpoint answers from one `janus_pdf` function or from the store. Parsing and rendering
run in worker processes (`jobs`), never here.
"""

import hashlib
import mimetypes
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import janus_pdf
from janus_pdf import Box, Inspection, Line, SpecError, Table, TableCell
from janus_pdf.document.render import RENDERER
from janus_pdf.output import plain
from janus_workbench import work
from janus_workbench.jobs import JobFailed, Jobs
from janus_workbench.reading import Reader
from janus_workbench.settings import Settings
from janus_workbench.store import (
    HASH_PATTERN,
    SPEC_NAME_PATTERN,
    DocumentRow,
    SpecRow,
    Store,
    Unknown,
)

STATIC = Path(__file__).parent / "static"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
# On every response: another site's page may not embed it, and the browser takes its type as
# given.
SAFE_HEADERS = {
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}

DocumentId = Annotated[str, PathParam(pattern=HASH_PATTERN, description="SHA-256 of the PDF")]
SpecName = Annotated[str, PathParam(pattern=SPEC_NAME_PATTERN)]
PageNumber = Annotated[int, PathParam(ge=1)]


class WordOut(BaseModel):
    text: str
    box: Box


class PageLayout(BaseModel):
    """What the layer holds for one page: the boxes the Inspect screen draws."""

    page: int
    words: list[WordOut]
    lines: list[Line]
    tables: list[Table]
    cells: list[TableCell]


class CandidateOut(BaseModel):
    page: int
    printed: str
    boxes: list[Box]


class FieldOut(BaseModel):
    """One field's outcome. A record's cells follow it as `lines/0/qty` and so on."""

    path: str
    status: Literal["extracted", "missing", "ambiguous", "incomplete", "invalid", "unconfirmed"]
    value: Any = None
    printed: str | None = None
    message: str = ""
    suggestions: list[str] = []
    page: int | None = None
    boxes: list[Box] = []
    candidates: list[CandidateOut] = []


class SpecProblem(BaseModel):
    message: str
    line: int | None = None  # from 1; None when the error belongs to no one line


class ExtractIn(BaseModel):
    spec: str = Field(max_length=200_000, description="the spec's YAML text")


class ExtractOut(BaseModel):
    """Either the spec did not load (`problem`) or every field has a result."""

    problem: SpecProblem | None = None
    fields: list[FieldOut] = []


class SpecIn(BaseModel):
    text: str = Field(max_length=200_000)


class SpecOut(BaseModel):
    name: str
    text: str


def _boxes(anchors: Any) -> list[Box]:
    return [box for anchor in anchors for box in anchor.boxes]


def shown_name(name: str) -> str:
    """The file name a row shows: the last part of what was sent, without control characters,
    at most 200 characters. It is never part of a path."""
    printable = "".join(ch for ch in name if ch.isprintable())
    last = printable.replace("\\", "/").rsplit("/", 1)[-1].strip()[:200]
    return last if last not in ("", ".", "..") else "document.pdf"


class _SameOrigin:
    """Refuse a request whose `Origin` is not the server's own, and add `SAFE_HEADERS` to every
    response. A browser sends `Origin` with every request a page on another site makes that
    could change something, so such a request ends here."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and origin != f"{scope['scheme']}://{headers.get('host', '')}":
            refused = JSONResponse(
                {"detail": "the workbench answers only its own pages"},
                status_code=403,
                headers=SAFE_HEADERS,
            )
            await refused(scope, receive, send)
            return

        async def send_safe(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(SAFE_HEADERS)
            await send(message)

        await self.app(scope, receive, send_safe)


def _static_files(directory: Path) -> dict[str, Path]:
    """The client's files by URL path, listed once. A request is looked up here, so no path is
    ever built from a URL."""
    return {
        "/" + path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file()
    }


def create_app(
    settings: Settings,
    *,
    static: Path | None = STATIC,
    hosts: tuple[str, ...] | None = LOOPBACK_HOSTS,
    start: bool = True,
) -> FastAPI:
    """The workbench app. A request must name one of `hosts` in its `Host` header; None allows
    any. `start=False` builds it without touching the disk, for `openapi`."""
    store: Store
    reader: Reader
    jobs = Jobs()
    rendering = threading.BoundedSemaphore(4)
    by_page: dict[str, dict[int, PageLayout]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal store, reader
        store = Store(settings.data_dir)
        reader = Reader(store, jobs, settings)
        reader.start()
        try:
            yield
        finally:
            reader.close()

    app = FastAPI(
        title="Janus workbench",
        version="0.1.0",
        lifespan=lifespan if start else None,
        generate_unique_id_function=lambda route: route.name,
    )
    if hosts is not None:
        # A page on another site cannot reach the API by pointing a name of its own at 127.0.0.1.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    app.add_middleware(_SameOrigin)  # added last, so it runs first and covers every response

    @app.exception_handler(Unknown)
    async def unknown(_: Request, exc: Unknown) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    def ready(document: str) -> DocumentRow:
        row = store.row(document)
        if row.status != "ready" or row.layer is None:
            raise HTTPException(409, "the document is not read yet")
        return row

    def layout(row: DocumentRow) -> dict[int, PageLayout]:
        """The layer's words, lines, tables and cells by page, sorted once per layer."""
        layer_id = row.layer or ""
        if layer_id not in by_page:
            layer = store.layer(row.id)
            pages = {
                p.number: PageLayout(page=p.number, words=[], lines=[], tables=[], cells=[])
                for p in layer.pages
            }
            for w in layer.words:
                pages[w.box.page].words.append(WordOut(text=layer.text[w.start : w.end], box=w.box))
            for line in layer.lines:
                pages[line.box.page].lines.append(line)
            for table in layer.tables:
                pages[table.page].tables.append(table)
            for cell in layer.cells:
                pages[cell.box.page].cells.append(cell)
            if len(by_page) >= 3:
                by_page.pop(next(iter(by_page)))
            by_page[layer_id] = pages
        return by_page[layer_id]

    # --- Documents -------------------------------------------------------------------------------

    @app.get("/api/documents")
    def list_documents() -> list[DocumentRow]:
        """Every document with its status. The client polls this while any is being read."""
        return store.rows()

    @app.post(
        "/api/documents",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
        responses={413: {"description": "The file is larger than the limit"}},
    )
    async def add_document(request: Request, name: str = "document.pdf") -> DocumentRow:
        """Take a PDF as the request body and queue it for reading.

        A file that does not start as a PDF is refused. A PDF that cannot be read is kept, and
        its row says why it failed. The name is only shown; see `shown_name`.
        """
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/pdf":
            raise HTTPException(415, "send the file as application/pdf")
        limit = settings.max_upload_bytes
        too_large = HTTPException(413, f"the file is larger than the limit of {limit} bytes")
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise too_large
        digest, size, head = hashlib.sha256(), 0, b""
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=store.incoming, delete=False) as upload:
                path = Path(upload.name)
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise too_large
                    head = (head + chunk)[:5] if len(head) < 5 else head
                    digest.update(chunk)
                    upload.write(chunk)
            if size == 0:
                raise HTTPException(400, "the request has no body")
            if head != b"%PDF-":
                raise HTTPException(422, "the file is not a PDF: it does not start with %PDF-")
            row = await run_in_threadpool(
                store.add, path, digest.hexdigest(), shown_name(name), size
            )
            path = None  # the store has it now
        finally:
            # A client that hangs up, a file too large, not a PDF or any other failure: the
            # partial upload goes.
            if path is not None:
                path.unlink(missing_ok=True)
        reader.wake()
        return store.row(row.id)

    @app.delete("/api/documents/{document}", status_code=204)
    def delete_document(document: DocumentId) -> None:
        """Remove the document and its files. A read of it in progress is stopped first."""
        layer = store.row(document).layer
        reader.remove(document)
        by_page.pop(layer or "", None)

    @app.get("/api/documents/{document}/inspect")
    def inspect_document(
        document: DocumentId,
        find: Annotated[str | None, Query(max_length=500)] = None,
    ) -> Inspection:
        """Pages, tables with their first rows, headings, and where `find` is printed."""
        layer = store.layer(ready(document).id)
        return janus_pdf.inspect(layer, find=find or None)

    @app.get("/api/documents/{document}/pages/{page}")
    def page_layout(document: DocumentId, page: PageNumber) -> PageLayout:
        pages = layout(ready(document))
        if page not in pages:
            raise HTTPException(404, "no such page")
        return pages[page]

    @app.get(
        "/api/documents/{document}/pages/{page}/image",
        response_class=Response,
        responses={200: {"content": {"image/png": {}}}},
    )
    def page_image(
        document: DocumentId,
        page: PageNumber,
        scale: Annotated[int, Query(ge=1, le=3, description="pixels per point")] = 2,
    ) -> Response:
        row = store.row(document)
        if row.pages is None or page > row.pages:
            raise HTTPException(404, "no such page")
        path = store.image(document, page, scale, RENDERER)
        if not path.is_file():
            with rendering:
                try:
                    png = jobs.run(
                        work.render_page,
                        str(store.pdf(document)),
                        page,
                        scale,
                        deadline=settings.render_deadline,
                    )
                except JobFailed as failure:
                    raise HTTPException(422, f"the page cannot be drawn: {failure}") from None
            path.parent.mkdir(exist_ok=True)
            partial = path.with_suffix(f".{threading.get_ident()}.part")
            partial.write_bytes(png)
            partial.replace(path)
        # The URL names the document's hash, the page and the scale, so the image never changes.
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.post("/api/documents/{document}/extract")
    def extract_document(document: DocumentId, body: ExtractIn) -> ExtractOut:
        """Run a spec, given as text, against the document."""
        layer = store.layer(ready(document).id)
        try:
            # `load_spec` reads a one-line string as a file name when such a file exists. The
            # line break makes it text, so a request can never name a file on this machine.
            spec = janus_pdf.load_spec(body.spec + "\n")
        except SpecError as error:
            return ExtractOut(problem=SpecProblem(message=str(error), line=error.line))
        extraction = janus_pdf.extract(layer, spec)
        return ExtractOut(
            fields=[
                FieldOut(
                    path=r.path,
                    status=r.status,
                    value=plain(r.value),
                    printed=r.printed,
                    message=r.message,
                    suggestions=list(r.suggestions),
                    page=r.page,
                    boxes=_boxes(r.anchors),
                    candidates=[
                        CandidateOut(page=c.page, printed=c.printed, boxes=_boxes(c.anchors))
                        for c in r.candidates
                    ],
                )
                for r in extraction.fields
            ]
        )

    # --- Specs -----------------------------------------------------------------------------------

    @app.get("/api/specs")
    def list_specs() -> list[SpecRow]:
        return store.specs()

    @app.get("/api/specs/{name}")
    def get_spec(name: SpecName) -> SpecOut:
        return SpecOut(name=name, text=store.spec_text(name))

    @app.put("/api/specs/{name}")
    def save_spec(name: SpecName, body: SpecIn) -> SpecRow:
        """Save the text under the name, replacing what the name held. A spec that does not
        load can be saved too, so work in progress is not lost."""
        return store.save_spec(name, body.text)

    @app.delete("/api/specs/{name}", status_code=204)
    def delete_spec(name: SpecName) -> None:
        store.delete_spec(name)

    # --- The client ------------------------------------------------------------------------------

    files = _static_files(static) if static is not None and static.is_dir() else {}

    @app.get("/{path:path}", include_in_schema=False)
    def client(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404, "no such endpoint")
        file = files.get("/" + path) or files.get("/index.html")
        if file is None:
            return Response(
                "The client is not built. Run `pnpm build` in apps/workbench/web.\n",
                status_code=503,
                media_type="text/plain",
            )
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        # Vite names files under assets/ by their content, so they can be kept for good.
        cache = "max-age=31536000, immutable" if "/assets/" in file.as_posix() else "no-cache"
        return FileResponse(file, media_type=kind, headers={"Cache-Control": cache})

    return app
