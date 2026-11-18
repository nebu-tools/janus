"""Run one function in a process of its own, with a deadline.

A PDF that crashes the parser or never finishes costs that one process. The caller gets a
`JobFailed` with a plain message and the server carries on.
"""

import multiprocessing
import sys
import threading
import time
import traceback
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import janus_pdf


class JobFailed(Exception):
    """The job gave no result. The message is fit to show to the person who sent the file."""


class JobCancelled(Exception):
    """The caller stopped the job."""


def _entry(conn: Connection, fn: Callable[..., Any], args: tuple) -> None:
    try:
        message = ("ok", fn(*args))
    except janus_pdf.UnreadablePdf as exc:
        message = ("failed", str(exc))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        message = ("failed", f"Janus failed on this file ({type(exc).__name__})")
    conn.send(message)
    conn.close()


class Jobs:
    """Processes forked from a server that has `janus_pdf` loaded, so starting one is cheap."""

    def __init__(self) -> None:
        self._context = multiprocessing.get_context("forkserver")
        self._context.set_forkserver_preload(["janus_workbench.work"])

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        deadline: float,
        cancel: threading.Event | None = None,
    ) -> Any:
        """The result of `fn(*args)`, run in its own process. Blocks, so call it from a thread.

        Raises `JobFailed` when the process dies, the function fails or `deadline` seconds pass,
        and `JobCancelled` when `cancel` is set. Either way the process is gone on return.
        """
        receiver, sender = self._context.Pipe(duplex=False)
        process = self._context.Process(target=_entry, args=(sender, fn, args), daemon=True)
        process.start()
        sender.close()
        end = time.monotonic() + deadline
        try:
            while not receiver.poll(0.05):
                if cancel is not None and cancel.is_set():
                    raise JobCancelled
                if time.monotonic() >= end:
                    raise JobFailed(f"it took longer than the limit of {deadline:g} seconds")
            try:
                status, value = receiver.recv()
            except (EOFError, OSError):
                raise JobFailed("the worker process stopped while it worked on it") from None
        finally:
            if process.is_alive():
                process.kill()
            process.join()
            receiver.close()
        if status != "ok":
            raise JobFailed(value)
        return value
