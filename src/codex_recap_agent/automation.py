from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


AUTOMATION_ID = "codex-collaboration-recap"


def ensure_daily_automation_script(repo_root: Path) -> Path:
    automation_dir = Path.home() / ".codex" / "automations" / AUTOMATION_ID
    automation_dir.mkdir(parents=True, exist_ok=True)
    toml = automation_dir / "automation.toml"
    memory = automation_dir / "memory.md"
    if not toml.exists():
        toml.write_text(
            "\n".join(
                [
                    'version = 1',
                    f'id = "{AUTOMATION_ID}"',
                    'kind = "cron"',
                    'name = "Codex collaboration recap"',
                    'prompt = "Run `codex-recap report --date today` in the workspace, generate or refresh the daily Markdown recap, and summarize any failure reason concisely. Keep the previous report if the run fails."',
                    'status = "ACTIVE"',
                    'rrule = "FREQ=DAILY;BYHOUR=21;BYMINUTE=30"',
                    'model = "gpt-5.4-mini"',
                    'reasoning_effort = "low"',
                    'execution_environment = "local"',
                    f'cwds = ["{repo_root}"]',
                    f'created_at = {int(datetime.now(timezone.utc).timestamp() * 1000)}',
                    f'updated_at = {int(datetime.now(timezone.utc).timestamp() * 1000)}',
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not memory.exists():
        memory.write_text(
            "Daily recap automation for Codex collaboration.\n\nLast run status: not yet run.\n",
            encoding="utf-8",
        )
    return automation_dir
