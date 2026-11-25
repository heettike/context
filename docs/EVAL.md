# Answer quality: how it is measured

This page holds the method, and results on made-up data only.
Numbers measured on a real person's archive are not kept in this repo. They live under `CTX_HOME/eval` on that person's Mac.

## Run it yourself

| command | what it does | model calls |
|---|---|---|
| `python3 scripts/eval_retrieval.py` | made-up rows and questions in a temp folder: how often each kind of search puts the right row in front of the model | none |
| `python3 scripts/eval_answers.py` | the made-up set with a stand-in for the model: checks the harness itself | none |
| `python3 scripts/eval_answers.py --live` | the made-up set through the real model | yes, on your plan |
| `python3 scripts/eval_build.py draft`, `show`, `keep`, `harden` | draft a private set of questions with known answers from your own archive. you read each one before it is kept | yes |
| `python3 scripts/eval_answers.py --set F` | your own set on your own archive | yes |
| `python3 scripts/eval_whole.py --gold`, then with no flag | whole-archive questions (how many, who most), gold computed by code | yes |
| `python3 scripts/eval_voice.py --hold`, `--run` | the blind test of writing in your voice | yes |

Every script prints numbers and question ids only: no question, no answer, no row text.

## The set

A set is built per archive, by its owner.

- Lookups, by kind: links, people, dates, what was agreed or said last, saved posts, the owner's own opinions, questions in a second language, and things that are not in the archive.
- Analysis questions, graded by a rubric.
- A hard tier: kept lookups asked again from half a memory (no names, a vague time, other words).
- Present-state questions, where the answer by the last 30 days differs from the all-time one. Gold is computed by code.
- Whole-archive questions: counts, rankings, absence. Gold is computed, not written.

A model drafts each question from sampled rows. A person reads it against its rows before it is kept.
A good question is one the owner would really ask, names enough to have one answer, and shares few words with the rows that answer it.

## Grading

- One strong-model call per answer, against the gold answer and its rows: correct, partly, missed (said it is not there), wrong (a hedged other answer), bluffed (false or unsupported, stated as fact).
- Each cited row is checked: does it support the sentence it is attached to.
- Analysis: a rubric from 0 to 8, and a count of factual claims with no row behind them.
- Whole-archive and present-state questions are graded by code: a number within tolerance, a named item, or the share of the gold's first names the answer gives.

Known limits of the method:

- Standard lookups name people and rough dates, so they are easier than real questions. The hard tier is the better guide.
- Analysis rubric points come from the read-through's pages, not from rows.
- One grader, no second opinion. A difference of one or two answers is noise.
- Seconds depend on the tool cache and on how many questions run side by side. Compare times only between runs made the same way.

## Ways of answering

- fixed: planner, word and meaning search, a model pick, one answering call.
- route (the default): a kept answer for a repeated question; else one local search and one small call with no tools, which answers or says "not settled"; else a second, wider look; else the tool loop with a small budget.
- deep: the tool loop with a large budget and the analysis model.
- two-pass (analysis): the everyday model gathers message ids with a note each, the analysis model writes from that list and from the wiki's paragraphs on the question.

Targets: standard lookups 96% right by the route and 99% deep; hard lookups 75% and 88%; no bluffs; analysis 6.5 of 8 with under 0.5 unsupported claims per answer, in 45 seconds.

## Results on made-up data

`python3 scripts/eval_retrieval.py`, 55 made-up questions over 95 made-up rows, each a paraphrase that shares few words with its row. recall@20 (and recall@5):

| | english | second language, romanised | chat lines | saved posts | all |
|---|---|---|---|---|---|
| keyword | 0.00 (0.00) | 0.33 (0.27) | 0.07 (0.07) | 0.00 (0.00) | 0.11 (0.09) |
| meaning | 0.53 (0.47) | 0.60 (0.40) | 0.67 (0.53) | 0.40 (0.40) | 0.56 (0.45) |
| fused | 0.53 (0.47) | 0.60 (0.40) | 0.67 (0.47) | 0.40 (0.40) | 0.56 (0.44) |

Run with the built-in embedder, no planner call. Word matching alone finds about one paraphrase in ten; search by meaning finds over half.

`python3 scripts/eval_answers.py` with the stand-in model checks that the harness runs, grades and prints. Its figures say nothing about answer quality.

## Where it stands

No result from a real archive is kept here. Run the scripts above on your own archive to get yours.

- Writing in the owner's voice has a blind test. **It has not passed.** A draft meets every check a program can run and is still told apart from the owner's own text.
- A quick answer to a lookup has a ceiling of 40 seconds on the whole of it. One that runs out says so and shows the closest messages.
- Tables pulled from the read-through's cards are not exact. A count from them is an "at least".
- Whole-archive questions are checked on a fixed set of phrasings only.

Rules of method:

- Sort every wrong answer by cause before changing anything: the right conversation never opened, opened but the right stretch never read, read and misread.
- Guess how the real lines read (other wordings, the owner's other language), rank conversations first and stretches second, and read the stretches before the loop runs.
- Wiki paragraphs on the question are chosen by code and handed to the model, not left for it to fetch with a tool.
- A sentence that states a fact with no row marked is taken out by code. A mark written after the full stop must stay with its sentence.
- The model's CLI gives up on a stdin that says nothing for three seconds. The question is written at once.
- The clock that ends a run counts time awake, not time asleep.
- Style bands are taken from a person's last two years of posts, not from everything: habits change.
- With no rule saved, the rules layer changes no evidence, row for row. This is checked by code.

## Not done

- A full re-run of the route and of deep, a second grader, and a run for variance.
- The hard tier and deep under the 40-second ceiling and the recency lift.
- Recency on questions that carry no time word.
- Analysis: paragraphs chosen by meaning, and a second pass that asks what is missing.
- Whole-archive questions asked in other words.
- Voice: a second judge, a person reading the drafts, and a test where the judge sees one text at a time.
- The Codex CLI as a tool loop.
