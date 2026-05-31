from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    repo_root: Path

    @property
    def codex_home(self) -> Path:
        return Path.home() / ".codex"

    @property
    def db_path(self) -> Path:
        return self.repo_root / "data" / "recap.db"

    @property
    def reports_dir(self) -> Path:
        return self.repo_root / "reports"

    @property
    def sessions_dir(self) -> Path:
        return self.codex_home / "sessions"

    @property
    def archived_sessions_dir(self) -> Path:
        return self.codex_home / "archived_sessions"

    @property
    def history_path(self) -> Path:
        return self.codex_home / "history.jsonl"

    @property
    def session_index_path(self) -> Path:
        return self.codex_home / "session_index.jsonl"

    @property
    def shell_snapshots_dir(self) -> Path:
        return self.codex_home / "shell_snapshots"


def get_app_paths() -> AppPaths:
    return AppPaths(repo_root=Path(__file__).resolve().parents[2])
