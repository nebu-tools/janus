"""Everything the workbench keeps, as files under one directory. There is no database.

    order                                      the next order key, a number
    documents/<document hash>/document.pdf     the upload
    documents/<document hash>/row.json         its row in the documents list
    documents/<document hash>/pages/           pages read so far (janus_pdf writes these)
    documents/<document hash>/layer.json       the layer, once read
    documents/<document hash>/images/<key>.png
    specs/<hash of the text>.yaml              a saved spec
    specs/index.json                           spec names and the hash each one points to

Every file name is a SHA-256 the server computed. `_checked` refuses anything else before a path
is built, so no text from a request reaches the file system. A spec's name is a key in the
index and never part of a path.

The rows are the reading queue too: a row with status `queued` waits to be read, and `claim`
hands out the one sent first.
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
    """Write a whole file or nothing: a reader never sees half of it. Callers hold the lock."""
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    partial.replace(path)


class DocumentRow(BaseModel):
    """One document in the list, and how far reading it has come."""

    id: str  # the SHA-256 of the PDF
    order: int  # larger for a later upload; the list is sorted by it, the queue too
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
    """The files, and the rows in memory. Every change to a row holds one lock."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.documents = root / "documents"
        self._specs = root / "specs"
        self.incoming = root / "incoming"
        for directory in (self.documents, self._specs):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.incoming, ignore_errors=True)  # uploads cut off by a stop
        self.incoming.mkdir()
        self._lock = threading.RLock()
        self._rows: dict[str, DocumentRow] = {}
        for directory in self.documents.iterdir():
            row = self._load_row(directory)
            if row is None:
                shutil.rmtree(directory, ignore_errors=True)  # an upload cut off by a stop
                continue
            if row.status == "reading":
                row = row.model_copy(update={"status": "queued"})  # cut off; it goes on
                self._save(row)
            if row.status != "queued":
                shutil.rmtree(self.page_cache(row.id), ignore_errors=True)
            self._rows[row.id] = row
        try:
            stored = int((root / "order").read_text())
        except (OSError, ValueError):
            stored = 0
        self._next = max([stored, *(r.order + 1 for r in self._rows.values())])
        self.layer = lru_cache(maxsize=3)(self._load_layer)

    @staticmethod
    def _load_row(directory: Path) -> DocumentRow | None:
        try:
            row = DocumentRow.model_validate_json((directory / "row.json").read_bytes())
        except (OSError, ValueError):
            return None
        return row if row.id == directory.name and _HASH.fullmatch(row.id) else None

    # --- Paths, each from a checked hash ---------------------------------------------------------

    def _dir(self, document: str) -> Path:
        return self.documents / _checked(document)

    def pdf(self, document: str) -> Path:
        return self._dir(document) / "document.pdf"

    def page_cache(self, document: str) -> Path:
        return self._dir(document) / "pages"

    def layer_path(self, document: str) -> Path:
        return self._dir(document) / "layer.json"

    def image(self, document: str, page: int, scale: int, renderer: str) -> Path:
        return self._dir(document) / "images" / f"{key(document, page, scale, renderer)}.png"

    # --- Documents -------------------------------------------------------------------------------

    def rows(self) -> list[DocumentRow]:
        """Every document, the last one sent first. A document being read says how many pages
        are done. A row and its page cache are read under the lock that `finish` holds, so a
        row is never `ready` while its cache is still there."""
        with self._lock:
            rows = sorted(self._rows.values(), key=lambda r: r.order, reverse=True)
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
        if row.status != "reading":
            return row
        cache = self.page_cache(row.id)
        done = sum(1 for _ in cache.glob("*.json")) if cache.is_dir() else 0
        return row.model_copy(update={"pages_read": min(done, row.pages or done)})

    def add(self, upload: Path, document: str, name: str, size: int) -> DocumentRow:
        """Keep an uploaded file under its hash, queued to be read, and return its row.

        Bytes that are kept already change nothing: the upload is deleted and the row stays as
        it is, in its place. Bytes of a document that failed are a new upload: they are queued
        again with a new order key, so the row moves to the top."""
        with self._lock:
            row = self._rows.get(_checked(document))
            if row is not None and row.status != "failed":
                upload.unlink()
                return row
            directory = self._dir(document)
            directory.mkdir(exist_ok=True)
            upload.replace(self.pdf(document))
            order = self._next
            self._next += 1
            _write(self.root / "order", str(self._next).encode())
            row = DocumentRow(id=document, order=order, name=name, size=size, added=_now())
            self._save(row)
            return row

    def claim(self) -> str | None:
        """Mark the queued document sent first as `reading` and return it, or None."""
        with self._lock:
            queued = [r for r in self._rows.values() if r.status == "queued"]
            if not queued:
                return None
            row = min(queued, key=lambda r: r.order)
            self._save(row.model_copy(update={"status": "reading"}))
            return row.id

    def update(self, document: str, **changes: object) -> bool:
        """Change a row. A document removed in the meantime stays removed: False."""
        with self._lock:
            row = self._rows.get(document)
            if row is not None:
                self._save(row.model_copy(update=changes))
            return row is not None

    def finish(self, document: str, **changes: object) -> bool:
        """End a read: delete the page cache, then change the row, so no one ever sees a row
        that is no longer `reading` beside a cache. False when the document was removed."""
        with self._lock:
            if document not in self._rows:
                return False
            shutil.rmtree(self.page_cache(document), ignore_errors=True)
            return self.update(document, **changes)

    def _save(self, row: DocumentRow) -> None:
        self._rows[row.id] = row
        _write(self._dir(row.id) / "row.json", row.model_dump_json().encode())

    def take(self, document: str) -> DocumentRow:
        """Take a row out of the list and the queue. Its files stay until `delete`."""
        with self._lock:
            row = self._rows.pop(_checked(document), None)
            if row is None:
                raise Unknown("no such document")
            (self._dir(document) / "row.json").unlink(missing_ok=True)
            return row

    def delete(self, document: str) -> None:
        """Delete the files of a document that `take` took. When the same bytes were sent again
        in the meantime, the files belong to that upload and stay."""
        with self._lock:
            if document not in self._rows:
                shutil.rmtree(self._dir(document), ignore_errors=True)
            self.layer.cache_clear()

    def _load_layer(self, document: str) -> Layer:
        try:
            return Layer.model_validate_json(self.layer_path(document).read_bytes())
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
