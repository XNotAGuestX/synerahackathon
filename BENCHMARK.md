# Running the benchmark

The project agent is `final_agent.benchmark:answer`. The runner defaults to the
starter agent, so always pass `--agent`. Each question gets a fresh answer from
the building files and the question text only; labels are never read by the agent.

## Setup

```bash
uv sync
cp .env.example .env          # then set ANTHROPIC_API_KEY=... in .env (never commit .env)
```

Python 3.12+. Without uv:

```bash
python -m venv .venv
.venv/bin/pip install anthropic matplotlib networkx shapely      # Windows: .venv\Scripts\pip
```

## One command: the public test set

```bash
uv run --env-file .env python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --name final-feature-handoff-test --submission-csv agent_output/submission.csv
```

Equivalent without uv (load the key into the environment first):

```bash
# bash / zsh
set -a; source .env; set +a
.venv/bin/python -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --name final-feature-handoff-test --submission-csv agent_output/submission.csv
```

```powershell
# PowerShell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { Set-Item "env:$($Matches[1].Trim())" $Matches[2].Trim() } }
.venv\Scripts\python.exe -m benchmark.evaluate data/test --agent final_agent.benchmark:answer --name final-feature-handoff-test --submission-csv agent_output/submission.csv
```

Then validate the file before submitting it:

```bash
uv run python -m final_agent.benchmark --check agent_output/submission.csv
```

The validator checks UTF-8, the exact `question_id,answer` header, exactly the 145 unique ids of
`data/test/submission_template.csv` (none missing, extra or duplicated), non-empty replies, an `Answer:`
line in every reply, normal CSV quoting and size (at most 5 MB). It prints every problem and exits
non-zero on failure. Use `--template` to point at a different template. A reply lost to an API error
is saved as empty and is reported here, so rerun those questions before submitting.

## Inputs and outputs

| | |
|---|---|
| Input | A split directory (`data/test`, `data/dev`, `data/train`): per building `building.json`, `equipment.csv` and `questions.jsonl`. The agent receives only the building directory and the question text. |
| Replies | `agent_output/benchmark/<name>.jsonl`: id, kind, correct (`null` on test), question, expected answer (dev only), full reply. Use a new `--name` per run; an existing name is overwritten. |
| Submission | `agent_output/submission.csv` with `question_id,answer`, the full multi-line reply, quoted the normal CSV way. |
| Scoring | Only the last line of a reply starting with `Answer:` counts (`benchmark/score.py`, unchanged). Dev runs print per-kind correctness; test runs have no labels and are graded by the judges. |

Every question is isolated: `answer()` loads a fresh map from disk, starts a new conversation and
writes edits and images into a temporary directory that is deleted afterwards. Closures, added
doors and routes from one question cannot reach another.

## Develop on dev first

```bash
# smoke test: one question per kind (9 scored kinds)
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --per-kind 1 --name final-dev-smoke
# all 138 dev questions
uv run --env-file .env python -m benchmark.evaluate data/dev --agent final_agent.benchmark:answer --name final-dev-full
```

The `tokens ... cost` line uses fixed price constants in `benchmark/evaluate.py`; it is an estimate,
not the configured model's billing. Live runs consume API credits.

## Free deterministic checks (no API calls)

```bash
uv run python -m unittest discover -s tests -v                       # unit + integration tests
uv run python -m final_agent.evaluate data/dev --oracle              # warm-up questions through the tools
uv run python bench_analsysis/run_tests.py --mode components --split data/dev     # scored kinds, tools only
uv run python bench_analsysis/run_tests.py --mode components --split data/train
```

The oracle and component runs read labelled dev/train inputs to prove that the tools can produce the
expected answers. They do not measure question interpretation, the prompt or formatting by the model,
so they are not a benchmark score.

## Status

- **Live runs: not executed in this environment** (no Anthropic credentials). No live accuracy,
  latency, token or cost figure exists for the project agent yet. `agent_output/submission.csv` has not been generated.
- Verified without credentials: the unit/integration tests, the oracle and the submission validator
  (on synthetic files, including broken ones). See the table for the component numbers.

| Check | Command | Result (coordinator to fill in) |
|---|---|---|
| Unit/integration tests | `python -m unittest discover -s tests` | _pending_ |
| Warm-up oracle (dev) | `python -m final_agent.evaluate data/dev --oracle` | _pending_ |
| Components, dev, per kind | `bench_analsysis/run_tests.py --mode components --split data/dev` | _pending_ |
| Components, train, per kind | `bench_analsysis/run_tests.py --mode components --split data/train` | _pending_ |
| Live dev smoke / full | `benchmark.evaluate ... --name final-dev-smoke / final-dev-full` | _not run_ |
| Live public test + validator | command above, then `--check` | _not run_ |

## Sunday benchmark

The organizer-dependent input/output format and release time are not announced in this repository.
This document covers the public CSV contract only; adapt it when the official schema is available.
