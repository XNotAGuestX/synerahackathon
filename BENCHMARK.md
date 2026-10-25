# Benchmark command

From the repository root, with dependencies installed:

```bash
uv sync
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --name final-dev
```

The command reads each building directory, writes answers, and does not persist what-if edits. Expected labels are for scoring only. `final_agent.benchmark:answer` is also the runner default and uses the retrieved run library. `answer_without_examples` preserves the model baseline without retrieval.

All benchmark answers use main's agent implementation and deterministic building tools. Claude calls use the standard SDK client; credentials remain in the environment.

A Sunday submission uses the same entry point against the organizer input when that schema is announced:

```bash
uv run --env-file .env python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --submission-csv team_answers.csv
```

Do not commit `.env`. Live runs need configured model credentials and spend API credits.

Sunday input uses a separate command. The organizers have not announced its schema, so the command exits without writing answers:

```bash
uv run python -m benchmark.sunday path/to/sunday_input
```

When the file is missing, or when it exists before the announced fields are recorded, the command prints what is missing and exits 1. Do not fill in a guessed answers file.
