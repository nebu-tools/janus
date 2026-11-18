"""Everything the workbench keeps, as files under one directory. There is no database.

    documents/<document hash>/document.pdf    the upload
    documents/<document hash>/row.json        its row in the documents list
    documents/<document hash>/pages/          pages read so far (janus_pdf writes these)
    documents/<document hash>/images/<key>.png
    layers/<layer id>.json                    a layer, as janus_pdf read it
    specs/<hash of the text>.yaml             a saved spec
    specs/index.json                          spec names and the hash each one points to

Every file name is a SHA-256 the server computed. `_checked` refuses anything else before a path
is built, so no text from a request reaches the file system. A spec's name is a key in the
index and never part of a path.
"""

import hashlib
import json
import re
import shutil
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from janus_pdf import Layer

_HASH = re.compile(r"[0-9a-f]{64}")
HASH_PATTERN = "^[0-9a-f]{64}$"
SPEC_NAME_PATTERN = r"^[^\x00-\x1f\x7f/\\]{1,80}$"


class Unknown(LookupError):
    """Nothing is kept under that hash or name."""


def _checked(value: str) -> str:
    """`value` if it is a SHA-256 in lower-case hex. Nothing else may name a file."""
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise Unknown("not a SHA-256 hash")
    return value


def key(*parts: object) -> str:
    """A file name for something identified by several values: the SHA-256 of them all."""
    return hashlib.sha256("\x00".join(str(p) for p in parts).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write(path: Path, data: bytes) -> None:
    """Write a whole file or nothing: a reader never sees half of it."""
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    partial.replace(path)


class DocumentRow(BaseModel):
    """One document in the list, and how far reading it has come."""

    id: str  # the SHA-256 of the PDF
    name: str  # the file name it was sent with; shown, never used as a path
    size: int  # bytes
    added: str
    status: Literal["queued", "reading", "ready", "failed"] = "queued"
    pages: int | None = None
    pages_read: int = 0
    engine: str | None = None
    tables: int | None = None
    read_seconds: float | None = None
    error: str | None = None
    layer: str | None = None  # the layer's ID, once read


class SpecRow(BaseModel):
    name: str
    hash: str
    saved: str


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.documents = root / "documents"
        self.layers = root / "layers"
        self._specs = root / "specs"
        self.incoming = root / "incoming"
        for directory in (self.documents, self.layers, self._specs):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.incoming, ignore_errors=True)  # uploads cut off by a stop
        self.incoming.mkdir()
        self._lock = threading.RLock()
        self._rows: dict[str, DocumentRow] = {}
        for path in self.documents.glob("*/row.json"):
            try:
                row = DocumentRow.model_validate_json(path.read_bytes())
            except ValueError:
                continue
            if row.id == path.parent.name and _HASH.fullmatch(row.id):
                self._rows[row.id] = row
        self.layer = lru_cache(maxsize=3)(self._load_layer)

    # --- Paths, each from a checked hash ---------------------------------------------------------

    def _dir(self, document: str) -> Path:
        return self.documents / _checked(document)

    def pdf(self, document: str) -> Path:
        return self._dir(document) / "document.pdf"

    def page_cache(self, document: str) -> Path:
        return self._dir(document) / "pages"

    def image(self, document: str, page: int, scale: int, renderer: str) -> Path:
        return self._dir(document) / "images" / f"{key(document, page, scale, renderer)}.png"

    def _layer_path(self, layer: str) -> Path:
        return self.layers / f"{_checked(layer)}.json"

    # --- Documents -------------------------------------------------------------------------------

    def rows(self) -> list[DocumentRow]:
        """Every document, newest first. A document being read says how many pages are done."""
        with self._lock:
            rows = sorted(self._rows.values(), key=lambda r: r.added, reverse=True)
        return [self._with_progress(r) for r in rows]

    def row(self, document: str) -> DocumentRow:
        with self._lock:
            row = self._rows.get(_checked(document))
        if row is None:
            raise Unknown("no such document")
        return self._with_progress(row)

    def _with_progress(self, row: DocumentRow) -> DocumentRow:
        if row.status == "ready":
            return row.model_copy(update={"pages_read": row.pages or 0})
        cache = self.page_cache(row.id)
        done = sum(1 for _ in cache.glob("*.json")) if cache.is_dir() else 0
        return row.model_copy(update={"pages_read": min(done, row.pages or done)})

    def add(self, upload: Path, document: str, name: str, size: int) -> tuple[DocumentRow, bool]:
        """Keep an uploaded file under its hash. Returns its row and whether it needs reading:
        a new document does, and so does one that failed before."""
        with self._lock:
            row = self._rows.get(_checked(document))
            if row is not None and row.status != "failed":
                upload.unlink()
                return row, False
            directory = self._dir(document)
            directory.mkdir(exist_ok=True)
            upload.replace(self.pdf(document))
            row = DocumentRow(id=document, name=name, size=size, added=_now())
            self._save(row)
            return row, True

    def update(self, document: str, **changes: object) -> None:
        """Change a row. A document removed in the meantime stays removed."""
        with self._lock:
            row = self._rows.get(document)
            if row is not None:
                self._save(row.model_copy(update=changes))

    def _save(self, row: DocumentRow) -> None:
        self._rows[row.id] = row
        _write(self._dir(row.id) / "row.json", row.model_dump_json().encode())

    def remove(self, document: str) -> None:
        with self._lock:
            row = self._rows.pop(_checked(document), None)
            if row is None:
                raise Unknown("no such document")
            shutil.rmtree(self._dir(document), ignore_errors=True)
            if row.layer:
                self._layer_path(row.layer).unlink(missing_ok=True)

    def drop_page_cache(self, document: str) -> None:
        shutil.rmtree(self.page_cache(document), ignore_errors=True)

    def _load_layer(self, layer: str) -> Layer:
        try:
            return Layer.model_validate_json(self._layer_path(layer).read_bytes())
        except OSError:
            raise Unknown("no such layer") from None

    # --- Specs -----------------------------------------------------------------------------------

    def _index(self) -> dict[str, SpecRow]:
        try:
            raw = json.loads((self._specs / "index.json").read_bytes())
        except (OSError, ValueError):
            return {}
        return {name: SpecRow(name=name, **body) for name, body in raw.items()}

    def specs(self) -> list[SpecRow]:
        with self._lock:
            return sorted(self._index().values(), key=lambda s: s.name.casefold())

    def spec_text(self, name: str) -> str:
        with self._lock:
            row = self._index().get(name)
            if row is None:
                raise Unknown("no such spec")
            return (self._specs / f"{_checked(row.hash)}.yaml").read_text()

    def save_spec(self, name: str, text: str) -> SpecRow:
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._lock:
            index = self._index()
            _write(self._specs / f"{digest}.yaml", text.encode())
            index[name] = SpecRow(name=name, hash=digest, saved=_now())
            self._save_index(index)
            return index[name]

    def delete_spec(self, name: str) -> None:
        with self._lock:
            index = self._index()
            if index.pop(name, None) is None:
                raise Unknown("no such spec")
            self._save_index(index)

    def _save_index(self, index: dict[str, SpecRow]) -> None:
        """Write the index, then delete spec texts no name points to any more."""
        body = {name: {"hash": s.hash, "saved": s.saved} for name, s in index.items()}
        _write(self._specs / "index.json", json.dumps(body, indent=2).encode())
        kept = {s.hash for s in index.values()}
        for path in self._specs.glob("*.yaml"):
            if path.stem not in kept:
                path.unlink()
