"""What can be set from the environment, with defaults that suit one person's machine."""

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "janus-workbench"


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path  # JANUS_DATA_DIR: documents, layers and specs are kept here
    max_upload_bytes: int = 200 * 1024 * 1024  # JANUS_MAX_UPLOAD_MB
    max_pages: int = 2000  # JANUS_MAX_PAGES
    read_deadline: float = 600.0  # JANUS_READ_DEADLINE, seconds for one document
    read_workers: int = 2  # JANUS_READ_WORKERS, documents read at the same time
    render_deadline: float = 30.0  # seconds for one page image

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            data_dir=Path(env.get("JANUS_DATA_DIR") or _default_data_dir()).expanduser(),
            max_upload_bytes=int(float(env.get("JANUS_MAX_UPLOAD_MB", "200")) * 1024 * 1024),
            max_pages=int(env.get("JANUS_MAX_PAGES", "2000")),
            read_deadline=float(env.get("JANUS_READ_DEADLINE", "600")),
            read_workers=max(1, int(env.get("JANUS_READ_WORKERS", "2"))),
        )
