# Usage

Run from the repo root. Commands marked *paid* call Claude and need credentials
(`ANTHROPIC_API_KEY` or `ant auth login`).

## Normal mode

Every paid command takes `--model opus|sonnet|haiku` (default `haiku`, i.e.
`claude-haiku-5-5`). Only the exact names are accepted. The benchmark and training
print the money spent so far after every question (an estimate at list prices).

**Chat** (*paid*): `uv run python -m final_agent data/dev/<building>`
- `--output DIR`: where route images and edits go (default `agent_output`)
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)

**Benchmark** (*paid*): `uv run python -m benchmark.evaluate data/dev`
- `--per-kind N`: sample N questions per kind (default: all)
- `--kinds K ...`: only these kinds
- `--agent M:F`: `final_agent.benchmark:answer` (default, uses the run library) or
  `final_agent.benchmark:answer_without_examples`
- `--name NAME`: replies saved to `agent_output/benchmark/NAME.jsonl`
- `--submission-csv PATH`: also write `question_id,answer`
- `--debug`: print each question, the agent's `recall_examples` declaration and the
  run-library questions it matched (similarity score, question ID, translation, question)
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)

**Warm-up check** (free): `uv run python -m final_agent.evaluate data/dev --oracle`
- `--limit N`: first N questions only
- without `--oracle` it runs the live agent (*paid*); `--model NAME` as above

## Training (build the run library)

**Build** (*paid*): `uv run python -m final_agent.train_runs`

It answers labelled questions and stores them in `final_agent/run_library.jsonl`. Correct
answers become examples for the benchmark agent. Questions that are already accepted are
skipped.

- default: 1 question per kind from `data/train` (9 questions)
- `--full`: every pending question; asks you to type `yes` first
- `--all`: also use `data/dev`. Don't use it if you measure on dev.
- `--model NAME`: `opus`, `sonnet` or `haiku` (default)
- `--library PATH`: default `final_agent/run_library.jsonl`

The first run with examples downloads the embedding model (~67 MB) to `~/.cache/fastembed`.
