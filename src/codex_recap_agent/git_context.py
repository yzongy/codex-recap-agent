from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Iterable, List


def collect_git_summaries(cwds: Iterable[str], limit: int = 12) -> List[Dict[str, object]]:
    summaries: List[Dict[str, object]] = []
    seen = set()
    for cwd in cwds:
        if not cwd or cwd in seen:
            continue
        seen.add(cwd)
        if len(summaries) >= limit:
            break
        path = Path(cwd).expanduser()
        if not path.exists() or not path.is_dir():
            continue
        result = _git_status(path)
        if result:
            summaries.append(result)
    return summaries


def _git_status(path: Path) -> Dict[str, object] | None:
    try:
        root = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if root.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "cwd": str(path),
        "repo_root": root.stdout.strip(),
        "changed_files": len(lines),
        "sample": lines[:8],
    }
