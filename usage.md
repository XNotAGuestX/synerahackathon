# Usage

Run from the repo root. Commands marked *paid* call Claude and need credentials
(`ANTHROPIC_API_KEY` or `ant auth login`).

## Normal mode

**Chat** (*paid*): `uv run python -m final_agent data/dev/<building>`
- `--output DIR`: where route images and edits go (default `agent_output`)

**Benchmark** (*paid*): `uv run python -m benchmark.evaluate data/dev`
- `--per-kind N`: sample N questions per kind (default: all)
- `--kinds K ...`: only these kinds
- `--agent M:F`: `final_agent.benchmark:answer` (default, uses the run library) or
  `final_agent.benchmark:answer_without_examples`
- `--name NAME`: replies saved to `agent_output/benchmark/NAME.jsonl`
- `--submission-csv PATH`: also write `question_id,answer`

**Warm-up check** (free): `uv run python -m final_agent.evaluate data/dev --oracle`
- `--limit N`: first N questions only

## Training (build the run library)

**Build** (*paid*): `uv run python -m final_agent.train_runs`

It answers labelled questions and stores them in `final_agent/run_library.jsonl`. Correct
answers become examples for the benchmark agent. Questions that are already accepted are
skipped.

- default: 1 question per kind from `data/train` (9 questions)
- `--full`: every pending question; asks you to type `yes` first
- `--all`: also use `data/dev`. Don't use it if you measure on dev.
- `--model M`: default `claude-sonnet-5-5`
- `--library PATH`: default `final_agent/run_library.jsonl`

The first run with examples downloads the embedding model (~67 MB) to `~/.cache/fastembed`.
