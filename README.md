# Codex Recap Agent

Codex Recap Agent is a local-first CLI for turning Codex session logs into daily Markdown recaps.

It reads your local Codex data from `~/.codex/sessions`, `history.jsonl`, `session_index.jsonl`, and `shell_snapshots`, then builds a searchable local ledger and a daily report under `reports/`.

The main goal is to improve how you collaborate with Codex through natural-language input. Tool failures, token use, and git state are still shown as context, but the daily score focuses on what you can control: goal clarity, context, output constraints, completion standards, and follow-up rhythm.

## Features

- Ingest recent Codex session logs into a local SQLite database.
- Generate daily Markdown recaps with session summaries, input-quality scoring, concrete examples, prompt rewrites, token counts, git context, and follow-up suggestions.
- Keep tool and environment failures as background. They are not scored as user mistakes.
- Preserve token statistics in a dedicated report section.
- Install the `codex-collaboration-coach` skill so Codex can guide future work before the recap happens.
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

## Install the Codex Skill

The repo includes a companion skill:

```text
skills/codex-collaboration-coach/
```

Install or update it into Codex:

```bash
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/codex-collaboration-coach
cp -R skills/codex-collaboration-coach ~/.codex/skills/codex-collaboration-coach
```

This skill helps Codex start broad tasks with a short brief, keep one active goal, checkpoint progress, diagnose repeated failures, and close with verification.

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

## Report Sections

Daily reports are written to `reports/YYYY-MM-DD.md` and include:

- `输入质量评分`: a 100-point score based only on natural-language input quality.
- `Token 统计`: input, output, and total token counts.
- `今日摘要`: recent Codex sessions and workspaces.
- `今天的具体例子`: concrete examples from the day, including progressive follow-ups and strong input examples.
- `逐句改写`: short prompt rewrites showing how the same request could be clearer next time.
- `今天和你讨论`: questions Codex can use to start the next recap conversation.
- `复盘建议`: background signals such as tool friction, model usage, shell snapshots, and thread titles.
- `下一步`: 1-3 concrete habits to try tomorrow.

The input score intentionally ignores tool failures, environment errors, and token volume. Those numbers still matter for debugging and cost awareness, but they should not be treated as feedback on your prompting.

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

If you also want Codex to proactively discuss the report after it is generated, create a thread heartbeat in Codex for around 21:40 that reads the latest Markdown report and talks through the input-quality score, one good habit, one prompt rewrite, and one improvement for tomorrow.

## Update an Existing Install

If another Codex installation already has this repo and skill, ask that Codex to run:

```text
Please update codex-recap-agent and the codex-collaboration-coach skill to the latest version.

1. Enter the existing codex-recap-agent repo, or clone it if missing:
   git clone https://github.com/yzongy/codex-recap-agent.git
2. Pull the latest source:
   git pull
3. Reinstall the CLI:
   python3 -m pip install -e .
4. Reinstall the skill:
   mkdir -p ~/.codex/skills
   rm -rf ~/.codex/skills/codex-collaboration-coach
   cp -R skills/codex-collaboration-coach ~/.codex/skills/codex-collaboration-coach
5. Verify:
   codex-recap status
   codex-recap report --date today
6. If the daily automation is already in use, refresh it:
   codex-recap setup-automation

When finished, report the current git commit, whether codex-recap runs, and whether the skill exists at ~/.codex/skills/codex-collaboration-coach.
```

## Output

Reports are written to:

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
