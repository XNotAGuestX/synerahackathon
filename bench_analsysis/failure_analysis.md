# Eight rejected training runs: cause and requirements

Verified on 25 October 2026 against the current working tree and
[`final_agent/run_library.jsonl`](../final_agent/run_library.jsonl).

The eight rejections have two causes: **three correct answers declare the wrong
question kind; five requests do not uniquely identify the room**. No deterministic
calculation failure was found in these eight cases. This library supplies retrieved
worked examples; it is not model-weight training.

## What was actually checked

- The library contains 519 records: all 517 train questions and two dev questions.
  There are 511 accepted records (509 train, two dev) and eight rejected records,
  all from train.
- Re-scoring every saved reply with the unchanged official scorer gives 514/519
  correct answers, including 512/517 train answers. All 519 stored acceptance
  flags agree with the current acceptance rule.
- All eight rejected cases pass their existing tool wrappers and the official
  scorer when supplied the labelled, resolved inputs. Source building files remain
  byte-for-byte unchanged. These are offline component checks, not fresh model runs.
- For the three classification cases, passing the saved reply and tool calls to
  `make_run` with only the first recall declaration corrected makes acceptance true.
  This was an in-memory diagnostic; the library was not altered.
- The existing representative runner also passes 71/71 cases and 6/6 formatting
  checks. No paid API calls were made for this diagnosis.

The acceptance rule in [`train_runs.py`](../final_agent/train_runs.py#L37) requires
all three: a nonblank semantic translation, the correct first declared kind, and
a reply accepted by `benchmark.score.score_reply`. Thus “rejected” does not always
mean the numerical answer was wrong. Rejected records are excluded from retrieval.

## Each rejected case

| Question | Why it was rejected | What it needs to succeed |
| --- | --- | --- |
| [`proc-campus-train-001-H03`](../data/train/proc-campus-train-001/questions.jsonl#L3) | Saved `Answer: 7` is correct. Declared `step_free_reachable_count` instead of `wide_delivery_count`. | First recall must declare `wide_delivery_count`; retain the existing step-free, 1.0 m width and entrance constraints. No numerical change needed. |
| [`proc-campus-train-019-H03`](../data/train/proc-campus-train-019/questions.jsonl#L3) | Saved `Answer: 10` is correct. Same kind mismatch. | Declare `wide_delivery_count`; retain the existing constrained calculation. |
| [`resplan-6565-H01`](../data/train/resplan-6565/questions.jsonl#L1) | Saved `Answer: 5` is correct. Same kind mismatch. | Declare `wide_delivery_count`; retain the existing constrained calculation, including the entrance room in the count. |
| [`osm-way37850565-H02`](../data/train/osm-way37850565/questions.jsonl#L2) | “Büro (Ground floor)” matches refs 0.10, 0.11 and 0.12. Agent correctly asks which room. | Specify **Büro 0.11**, ID `osm-way37850565-F0-S011`; `find_stacked_room(..., direction="above")` returns **Büro 1.02**. |
| [`osm-way37850565-H03`](../data/train/osm-way37850565/questions.jsonl#L3) | Exactly the same question text as H02, but a different intended source room and mutually conflicting answer label. | Specify **Büro 0.10**, ID `osm-way37850565-F0-S010`; the room above is **Büro 1.03**. |
| [`osm-way37850565-H04`](../data/train/osm-way37850565/questions.jsonl#L4) | “Büro (Floor 1)” matches nine rooms. Agent asks for a ref; possible wall counts differ. | Specify **Büro 1.10**, ID `osm-way37850565-F1-S010`; `count_shared_walls` returns **3**. |
| [`osm-way52060470-H06`](../data/train/osm-way52060470/questions.jsonl#L6) | Two Floor 1 rooms are named “Genusswerk”: refs 1.34 and 1.46. They produce different distances. | Specify **Genusswerk 1.34**, ID `osm-way52060470-F1-S034`; distance to `osm-way52060470-F-1-S014` is **159.874708… m**, within the 159.87 m label’s tolerance. Ref 1.46 gives 142.702166… m. |
| [`osm-way58216509-H04`](../data/train/osm-way58216509/questions.jsonl#L4) | Two Floor 2 spaces have both name “Generic room N2135” and ref “N2135”. Agent computes both alternatives and asks which applies. | Identify **`osm-way58216509-F2-S070`**, through a map selection, stable ID or unique contents. `plan_errand` returns **106.53 m**, via `F2-S012` to `F0-S008`. The other N2135 (`F2-S160`) gives **146.97 m**. Adding the same room ref alone cannot disambiguate this case. |

## Why retrying the five ambiguous requests cannot reliably fix them

H02 and H03 provide the answer callable with the same building and exactly the
same question text. H02 accepts `1.02` and rejects `1.03`; H03 accepts `1.03` and
rejects `1.02`. One answer to that identical input cannot satisfy both labels.
The intended source IDs exist only in the labelled `inputs`, which the production
answer path must not read.

The other ambiguities also materially change the result. Floor 1 Büro rooms have
shared-wall counts from 1 to 3; the two Genusswerk distances differ by about 17 m;
the two N2135 errands differ by about 40 m. Choosing the first search result or
copying a training answer would conceal missing input rather than resolve it.
Current clarification behavior agrees with the application's ambiguity rule.

## Smallest useful follow-up changes

1. **Explain the kind distinction at recall time.** Extend the description of
   `recall_examples` in [`tools.py`](../final_agent/tools.py#L752), or the
   [`EXAMPLES_PROMPT`](../final_agent/agent.py#L214): an explicit minimum door/load
   width means `wide_delivery_count`, even though the route is also step-free.
   `step_free_reachable_count` covers the lift-outage reachability questions.
   Both use `reachable_rooms`, so the shared calculation tool does not identify
   the question kind. Then retry the three affected runs; keep the declaration
   check in `make_run` intact.
2. **Make ambiguous source questions uniquely identify their rooms.** Report the
   five source defects upstream. Corrected development fixtures can include refs
   where unique, and stable IDs or unique contextual descriptions where refs also
   collide. Preserve the supplied official data and scorer; do not feed labelled
   `inputs` into production answers. Retain clarification for the original texts.
3. **Log why training rejected a run.** Print separate `answer_correct`,
   `kind_matches` and `translation_present` results. Distinguish ambiguity from a
   calculation error so repeated paid builds do not obscure the real blocker.
   The current trainer retries every rejected run, and its small sample does not
   guarantee selecting these three; a question-ID retry filter would make a
   targeted verification inexpensive.

The three kind changes can recover three accepted examples. The remaining five
require disambiguating information or an explicit clarification outcome in a
development evaluation; another model or additional examples cannot supply a
missing fact in these unchanged questions. Do not mark a run accepted just to
hide the distinction.

## Reproduction

The following uses labelled inputs exclusively for offline diagnosis. Run from
the repository root with the existing environment; no credentials are required:

```bash
MPLCONFIGDIR=/tmp/benchmark-diagnosis-mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from benchmark.evaluate import load_questions
from benchmark.score import score_reply
from bench_analsysis.run_tests import component_case

questions = {
    q["id"]: (directory, q)
    for directory, q in load_questions(Path("data/train"))
}
for line in Path("final_agent/run_library.jsonl").read_text().splitlines():
    run = json.loads(line)
    if run["accepted"]:
        continue
    directory, question = questions[run["question_id"]]
    with TemporaryDirectory() as output:
        status, reply = component_case(directory, question, Path(output))
    print(run["question_id"],
          "saved_answer_correct=", score_reply(question["answer"], run["reply"]),
          "kind_matches=", run["declared_kind"] == question["kind"],
          "resolved_tool=", status, reply)
PY
```

The broader check actually run was:

```bash
MPLCONFIGDIR=/tmp/benchmark-diagnosis-mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python bench_analsysis/run_tests.py --results /tmp/benchmark-diagnosis-components.json
```

Existing `bench_analsysis/results.json` and its historical README counts were not
overwritten. This diagnosis changes documentation only; prompts, training
records, model settings, supplied questions and scoring remain as inspected.
