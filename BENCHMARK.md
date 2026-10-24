# Benchmark command

From the repository root, with dependencies installed:

```bash
uv sync
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --name final-dev
```

The command reads each building directory, writes answers, and does not persist what-if edits. Expected labels are for scoring only. The starter agent remains the runner default; this command selects `final_agent` explicitly.

A Sunday submission uses the same entry point against the organizer input when that schema is announced:

```bash
uv run --env-file .env python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --submission-csv team_answers.csv
```

Do not commit `.env`. Live runs need configured model credentials and spend API credits.
