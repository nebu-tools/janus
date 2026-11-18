"""The queue that reads uploaded documents, a few at a time, each in a worker process."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from janus_workbench import work
from janus_workbench.jobs import JobCancelled, JobFailed, Jobs
from janus_workbench.settings import Settings
from janus_workbench.store import Store


class Reader:
    def __init__(self, store: Store, jobs: Jobs, settings: Settings) -> None:
        self._store = store
        self._jobs = jobs
        self._settings = settings
        self._pool = ThreadPoolExecutor(settings.read_workers, thread_name_prefix="read")
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def resume(self) -> None:
        """Queue every document whose read was cut off when the server last stopped."""
        for row in self._store.rows():
            if row.status in ("queued", "reading"):
                self.submit(row.id)

    def submit(self, document: str) -> None:
        cancel = threading.Event()
        with self._lock:
            self._cancels[document] = cancel
        self._store.update(document, status="queued", error=None)
        self._pool.submit(self._read, document, cancel)

    def cancel(self, document: str) -> None:
        with self._lock:
            cancel = self._cancels.pop(document, None)
        if cancel is not None:
            cancel.set()

    def close(self) -> None:
        """Stop every read. Rows stay queued or reading on disk, so the next start resumes."""
        with self._lock:
            for cancel in self._cancels.values():
                cancel.set()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _read(self, document: str, cancel: threading.Event) -> None:
        store, limit = self._store, self._settings.read_deadline
        started = time.monotonic()
        try:
            if cancel.is_set():
                return
            store.update(document, status="reading")
            pdf = str(store.pdf(document))
            pages = self._jobs.run(work.count_pages, pdf, deadline=limit, cancel=cancel)
            if pages > self._settings.max_pages:
                raise JobFailed(
                    f"the PDF has {pages} pages and the limit is {self._settings.max_pages}"
                )
            store.update(document, pages=pages)
            left = max(limit - (time.monotonic() - started), 0.0)
            cache = str(store.page_cache(document))
            summary = self._jobs.run(
                work.read_layer, pdf, cache, str(store.layers), deadline=left, cancel=cancel
            )
        except JobCancelled:
            return
        except JobFailed as failure:
            message = str(failure)
            if message.startswith("it took longer"):
                message = f"reading took longer than the limit of {limit:g} seconds"
            store.update(document, status="failed", error=message)
            return
        except Exception as exc:
            store.update(document, status="failed", error=f"reading failed ({type(exc).__name__})")
            raise
        finally:
            with self._lock:
                if self._cancels.get(document) is cancel:
                    del self._cancels[document]
        seconds = round(time.monotonic() - started, 2)
        store.update(document, status="ready", read_seconds=seconds, **summary)
        store.drop_page_cache(document)
