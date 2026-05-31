# Codex Recap Agent

Codex Recap Agent is a small local CLI for turning Codex session logs into daily Markdown recaps.

It reads your local Codex data from `~/.codex/sessions`, `history.jsonl`, `session_index.jsonl`, and `shell_snapshots`, then builds a searchable local ledger and a daily report under `reports/`. The goal is simple: make it easy to review what Codex worked on, which workspaces were touched, where tool errors happened, and what deserves a follow-up.

## Features

- Ingest recent Codex session logs into a local SQLite database.
- Generate daily Markdown recaps with session summaries, tool counts, token counts, git context, and follow-up suggestions.
- Backfill previous days when setting up the tool for the first time.
- Install a Codex automation that runs the daily recap command on a schedule.
- Keep all data local. No network service is required.

## Install

```bash
git clone https://github.com/yzongy/codex-recap-agent.git
cd codex-recap-agent
python3 -m pip install .
```

For local development, use editable install:

```bash
python3 -m pip install -e .
```

## Usage

Generate today's recap:

```bash
codex-recap report --date today
```

Generate a recap for a specific date:

```bash
codex-recap report --date 2026-05-31
```

Backfill recent sessions:

```bash
codex-recap backfill --days 30
```

Check the local database status:

```bash
codex-recap status
```

## Codex Automation

Install the daily Codex automation:

```bash
codex-recap setup-automation
```

The automation runs:

```bash
codex-recap report --date today
```

By default, it writes an automation config under `~/.codex/automations/codex-collaboration-recap/`.

## Output

Daily reports are written to:

```text
reports/YYYY-MM-DD.md
```

The local database is written to:

```text
data/recap.db
```

Both paths are ignored by git because they contain machine-local recap state.

## Privacy

This tool reads local Codex logs and local git status. It does not send data to a remote service. Review generated reports before sharing them, because they may include workspace paths, thread names, command summaries, or other local context.

## Development

Run the test suite:

```bash
python3 -m pytest
```

Verify local installation:

```bash
python3 -m pip install . --target /tmp/codex-recap-install-test
```

## License

MIT
