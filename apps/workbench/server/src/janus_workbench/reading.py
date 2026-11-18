"""Reading uploaded documents, a few at a time, each in a worker process.

The queue is the rows on disk with status `queued`. `read_workers` threads each take the queued
row sent first, read it and take the next. Nothing is held in memory for a document that waits,
so the queue can be as long as the list.
"""

import logging
import threading
import time

from janus_workbench import work
from janus_workbench.jobs import JobCancelled, JobFailed, Jobs
from janus_workbench.settings import Settings
from janus_workbench.store import Store

log = logging.getLogger(__name__)


class Reader:
    def __init__(self, store: Store, jobs: Jobs, settings: Settings) -> None:
        self._store = store
        self._jobs = jobs
        self._settings = settings
        self._lock = threading.Condition()
        self._running: dict[str, threading.Event] = {}  # being read: at most read_workers
        self._closing = False
        self._threads = [
            threading.Thread(target=self._work, name=f"read-{n}", daemon=True)
            for n in range(settings.read_workers)
        ]

    def start(self) -> None:
        """Start the workers. Rows a stop cut off are queued already, so they are read first."""
        for thread in self._threads:
            thread.start()

    def wake(self) -> None:
        """A row was queued."""
        with self._lock:
            self._lock.notify_all()

    def remove(self, document: str) -> None:
        """Take the document out of the list and the queue. When it is being read, kill its
        worker process and wait until it is gone, then delete the files."""
        with self._lock:
            self._store.take(document)
            cancel = self._running.get(document)
            if cancel is not None:
                cancel.set()
            while document in self._running:
                self._lock.wait()
        self._store.delete(document)

    def close(self) -> None:
        """Stop every read and wait for the workers. Rows stay as they are on disk, so the next
        start reads them again."""
        with self._lock:
            self._closing = True
            for cancel in self._running.values():
                cancel.set()
            self._lock.notify_all()
        for thread in self._threads:
            if thread.is_alive():
                thread.join()

    def _work(self) -> None:
        while True:
            with self._lock:
                document = None
                while not self._closing and (document := self._store.claim()) is None:
                    self._lock.wait()
                if document is None:
                    return
                cancel = self._running[document] = threading.Event()
            try:
                self._read(document, cancel)
            except Exception:
                log.exception("reading %s failed", document)
            finally:
                with self._lock:
                    del self._running[document]
                    self._lock.notify_all()

    def _read(self, document: str, cancel: threading.Event) -> None:
        store, limit = self._store, self._settings.read_deadline
        started = time.monotonic()
        try:
            pdf = str(store.pdf(document))
            pages = self._jobs.run(work.count_pages, pdf, deadline=limit, cancel=cancel)
            if pages > self._settings.max_pages:
                raise JobFailed(
                    f"the PDF has {pages} pages and the limit is {self._settings.max_pages}"
                )
            store.update(document, pages=pages)
            left = max(limit - (time.monotonic() - started), 0.0)
            cache, layer = str(store.page_cache(document)), str(store.layer_path(document))
            summary = self._jobs.run(
                work.read_layer, pdf, cache, layer, deadline=left, cancel=cancel
            )
        except JobCancelled:
            return  # removed, or the server stops
        except JobFailed as failure:
            message = str(failure)
            if message.startswith("it took longer"):
                message = f"reading took longer than the limit of {limit:g} seconds"
            store.finish(document, status="failed", error=message)
            return
        except Exception as exc:
            store.finish(document, status="failed", error=f"reading failed ({type(exc).__name__})")
            raise
        seconds = round(time.monotonic() - started, 2)
        store.finish(document, status="ready", read_seconds=seconds, **summary)
