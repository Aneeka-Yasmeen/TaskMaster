# TaskMaster

**Where did I leave my project?** TaskMaster is an evidence-backed project state engine for engineers. It turns scattered updates (notes, sim logs, synthesis reports, commits, experiment logs) into a living current state for each project: what was done, what is blocked, what was decided, what to do next, and the evidence behind every one of those claims.

Built for the Nebius × NVIDIA hackathon. The state engine uses **NVIDIA Nemotron** (`nvidia/nemotron-3-super-120b-a12b`) through **Nebius Token Factory**. The Python package and CLI are called `statetrace`.

> TaskMaster doesn't just remember what happened. It reconstructs what is true about your project now.

**Who it's for:** hardware and ML engineers juggling several long-running projects (RTL, synthesis, experiments) who lose
a day re-reading logs and chats every time they switch back. **The aha moment:** open a project you haven't touched in
two weeks, and the first thing you see is *Where you left off & what to do next*: the blocker, the next action, what
is established (verified by artifacts), what is only reported, and the open contradictions, each linked to its evidence.

### 90-second demo

```bash
python -m statetrace --db demo.db serve        # http://127.0.0.1:8765 (live Nemotron if NEBIUS_API_KEY is set)
```

1. **Today (10 s):** the first-run card explains the idea. The *Focus now* project is ranked by stated reasons. All
   demo projects carry a **Sample data** badge: they are synthetic.
2. **MAC Unit (Yosys) → "Where you left off" (25 s):** press **C** (or *Ask Nemotron again*). The elapsed time
   counts up (~20 s). Nemotron's reconstruction appears with each item labelled **Verified / Reported / Contested /
   Nemotron's inference**. These labels and the evidence chips are derived from validated claims, not from the
   model. Click **E8** for the failing sim log.
3. **The contradiction (15 s):** a chat message says "all 256 vectors pass", but the verified sim log says 6 fail. The
   validator refused to let the chat clear the blocker and opened **X2**. Nobody "believes" the chat until a re-run.
4. **Yosys review-before-commit (30 s):** Synthesis (Yosys) → import `demo/yosys/mac_v2_xilinx_stat.rpt` (the FPGA-mapped run; `mac_v3_hier_stat.rpt` is already in demo.db). TaskMaster
   parses and hashes it, Nemotron proposes a state change, and the validator dry-runs it. You see the before/after
   diff and **Apply** or **Discard** it. Nothing changes until you choose; discarding keeps the evidence. Then compare
   it with v2 and *Explain with Nemotron*.
5. **History (10 s):** Detailed layout (**D**) → What changed → click an event to see exactly what it changed.

No API key? Start with an empty `--db` and click **Load sample project**: it replays recorded operations (clearly
labelled "not live Nemotron") so you can explore the UI offline.

---

## Why this isn't "AI memory"

| Failure of a running summary | What TaskMaster does instead |
|---|---|
| A blocker fixed last week is still "the blocker" | Claims are superseded or invalidated by newer evidence, with the reason recorded |
| "It works on the board" in a chat becomes a fact | Only artifacts make a claim **verified**; notes stay **reported** |
| Conflicting evidence is blended into one sentence | **Contradictions are surfaced** and stay open until evidence settles them |
| "Why do you think that?" has no answer | Every claim cites evidence ids; the UI opens the source in one click |

## How it works

```
 evidence (note · log · report · commit)
        │  append-only SQLite log (triggers forbid UPDATE/DELETE)
        ▼
 Nemotron via Nebius Token Factory ── proposes operations only:
        │                              ADD · UPDATE · INVALIDATE · CONTRADICT · RESOLVE · NOOP
        ▼
 deterministic validator ── decides what is applied (rules below); logs everything it rejects
        ▼
 versioned project state ── a snapshot per version; diff any two; rebuild from the log
        ▼
 TaskMaster UI · CLI · "Where did I leave off?" · "Why do you believe this?"
```

### Trust rules (enforced in `statetrace/validator.py`, not by the prompt)

1. Every claim cites evidence that exists. Invented ids are stripped and counted; the triggering evidence is always cited.
2. **Verified needs an artifact.** Notes, chats, meetings, emails and issues can only produce *reported* claims.
3. **A commit only proves a change.** A claim that states a result (pass/fail/met/works/WNS/slack/`12/12`…) whose only verifying evidence is a commit is downgraded to *reported*.
4. **Verified facts can't be overwritten by weaker evidence.** A verified status item (test result, timing, utilization) can only be replaced by another verified claim. A verified blocker can't be cleared by commits alone. Weaker evidence opens a **contradiction** ("Needs verification") instead. A person may still clear a blocker (e.g. "we abandoned that design"), but this is logged. A person **asserting a result** ("fixed, all vectors pass") can neither clear a verified blocker nor resolve a contradiction involving verified evidence: that needs a re-run (found in a live run, 2026-10-25).
5. **Old evidence can't overwrite or contest newer beliefs.** Late-arriving evidence cannot supersede, invalidate or contradict a claim established after it happened.
6. Contradictions stay open until evidence resolves them. Contradictions whose claims are all gone close as *moot*. One piece of evidence conflicting with several claims is one contradiction.
7. Nothing is deleted: beliefs are superseded or invalidated, with the evidence that ended them.
8. Model slips are repaired rather than silently dropped, and every repair is logged: a wrong `field` name, a superseded or wrong-field target id, or `[open]` written into question text.

### Where you left off (catch-up)

`assistant.catch_up` asks Nemotron for a structured reconstruction (`left_off`, `established`, `blockers`,
`uncertain`, `next_action`, `missing_evidence`). Each item must reference **claim ids**. TaskMaster then:
- drops references to claims that don't exist or are no longer current, and lists every adjustment;
- displays each item as the **stored text of the referenced claims**, with the support label and evidence taken from
  them (the weakest wins; contested beats all). Nemotron's sentence appears only as a labelled, unbadged note, and is
  hidden if it adds numbers or result words (pass, closed, fixed…) the claim doesn't contain;
- shows an item with no valid claim as **Nemotron's inference, not established**, and a next action that isn't a
  recorded next step as **Nemotron's suggestion**, listing the claims it was based on;
- moves anything not verified out of "Established";
- says plainly when there is **no defensible next action**;
- falls back to a deterministic reconstruction from the claims if Nemotron is unreachable or its reply is malformed,
  labelled "stored state" (never presented as a model answer);
- caches the result per state version. Opening a project never calls the model; asking does.

### Review before commit (Yosys imports)

Importing a synthesis report in the UI appends the evidence, then asks Nemotron for operations and **dry-runs them
through the validator without committing**. The proposal is stored as a transition marked `[awaiting review]`, so
it survives restarts and is never applied by sync or retry. **Apply** re-validates the *same* stored operations
against the *current* state (it may have moved on) and commits state and transition atomically, with no second
model call. **Discard** records `[rejected by user]`; the report stays in the evidence log. Both outcomes are
visible in history.

### Claims vs commitments

Next steps come from evidence and are **proposals**. A **milestone** is a user commitment with an optional deadline, kept outside the evidence-derived state. "Commit…" on a proposed next step turns it into a milestone. TaskMaster never invents deadlines. A date suggested from evidence would be stored as `origin: inferred`, unconfirmed and never reminded about (no automatic inference exists yet).

## Features

- **Projects:** overview with health (active / blocked / updated today / needs review, each from a stated rule), upcoming deadlines with at-risk reasons, project cards.
- **Project state:** blocker / next step (proposed or committed) / last action / confidence cards; a claim legend; status by subject; a time-travel slider over versions; the latest before/after diff; a "What changed" timeline; contradictions; stale-state banner; milestones; decisions; questions.
- **Evidence library:** shows what each item supports and what it made obsolete. **Decisions** (reason, tradeoff, reversed). **Questions** (open / investigating / resolved). **Activity.** **Ask** (answers beside their evidence).
- **Inbox: local Git evidence.** Connect a repository (Windows path, or a WSL2 repo via WSL's git). Scans stage commits (hash, date, author, branch, message, line counts; no diffs or file contents) for review. Nothing affects the state until you **accept**. Re-scans don't duplicate; commits already recorded by hand are skipped; failed state updates keep their evidence and can be retried; sources can be paused or removed; auto-accept is opt-in. The ingest interface (`validate` + `scan`) is ready for GitHub/CI/test-report sources.
- **Milestones and reminders:** due dates, per-milestone reminder offsets, quiet hours, deduplicated notices (each issue reported once; re-armed if rescheduled), stale-project alerts, and at-risk flags with explicit reasons (overdue, due within 72 h, blocked or contested within 7 days, stale within 14 days). No completion probabilities.
- **Settings:** engine status, evidence sources (pause/resume), reminder preferences, trust rules, theme.

- **Nemotron as an assistant (advises, never acts):**
  - Questions go to **Nemotron first**, grounded in the validated state and evidence, with citations
    checked. If Nebius can't be reached, you get the stored-state answer, labelled as such.
  - **Reviews:** Nemotron compares the evidence with your goal and deadlines, gives a verdict (on track /
    at risk / off track / blocked), and makes concrete suggestions. Reviews are opinions stored apart from
    the state; turning a suggestion into an update or milestone is always your click.
  - **Autonomy** (Settings): Off / Selected projects / All projects controls automatic reviews and
    background monitoring. It never lets Nemotron change state.
- **Yosys synthesis skill:** import Yosys `stat` reports (text or JSON) as verified evidence (hashed,
  deduplicated, never overwritten), compare any run against a baseline with deterministic deltas and
  stated limitations, check optional limits, and ask Nemotron to explain the changes and propose one next
  experiment. Its explanation is labelled as interpretation and never becomes evidence. Demo designs and
  real Yosys 0.9 reports are in `demo/yosys/`.
- **Offline-first:** updates are always saved locally. If Nebius is unreachable they queue ("waiting for
  Nemotron") and are applied automatically, oldest first, when it's back.
- **Priority:** Today puts the most urgent project first, using a stated score (deadlines, your
  High/Normal/Low priority, blockers, contradictions, staleness, Nemotron's verdict) and shows the reasons.
- **Simple / Detailed layout and Large text** (defaults: Simple, Large). Press **?** for shortcuts.
  [docs/GUIDE.md](docs/GUIDE.md) walks through the whole app.
- **Desktop companion (Windows, opt-in):** `python -m statetrace companion` adds a global hotkey (default Ctrl+Alt+T) that opens a compact window with the active project's blocker, next step (proposed or committed), latest change, next deadline and quick answers. Background monitoring and Windows notifications are separate settings, **both off by default**. Monitoring only stages Git commits for review (never accepts them), and notifications reuse the reminder rules: one per issue, quiet hours respected. See [docs/COMPANION.md](docs/COMPANION.md) for setup, privacy, and what was and wasn't verified on Windows.

Without the companion, reminders appear in the dashboard bell while TaskMaster is open, and nothing runs in the background.

## Quick start

Python 3.10+, no dependencies. `git` is optional (only for the Git importer).

```bash
cp .env.example .env                       # then put NEBIUS_API_KEY in .env (never in .env.example)
python -m statetrace models                # check the key
python -m statetrace --db demo.db seed     # 5 sample projects through Nemotron (~49 calls; skips existing ones)
python -m statetrace --db demo.db serve    # http://127.0.0.1:8765
```

Real work goes in its own database, so demo and real data never mix: `python -m statetrace --db my.db serve`.
`python -m statetrace --db X.db -p ID sample [--off]` labels a project as sample data (or real).

Version control: this folder is not yet a Git repository. Before submitting, run `git init`, check that
`git status` does not list `.env` or any `*.db` file (both are git-ignored), then commit.

### CLI

```bash
python -m statetrace -p my-proj add "tried retiming the ROM output, no change"
python -m statetrace -p my-proj add -s synthesis_report -f build/timing_summary.rpt "post-route timing"
python -m statetrace -p my-proj ask "Where did I leave off?"
python -m statetrace -p my-proj why current_blocker
python -m statetrace -p my-proj history
python -m statetrace -p my-proj diff 8 12
python -m statetrace -p my-proj rebuild
# local Git evidence
python -m statetrace -p my-proj git-add C:\code\my-proj            # or: git-add /home/me/proj --wsl
python -m statetrace -p my-proj scan                               # stage new commits (no state change)
python -m statetrace -p my-proj imports --status pending
python -m statetrace -p my-proj accept all                         # runs the state engine
python -m statetrace -p my-proj skip 3 4
python -m statetrace -p my-proj retry-imports all
# milestones
python -m statetrace -p my-proj milestone "Tapeout review" --due 2026-11-01T17:00 --remind 1440 120
python -m statetrace -p my-proj milestone                          # list with at-risk reasons
# Windows desktop companion (hotkey popup; monitoring/notifications are opt-in in Settings)
python -m statetrace --db my.db companion                          # --hotkey ctrl+alt+t | --no-hotkey
```

## Security and privacy

- The API key is read from `.env` by the local server only. It is never sent to the browser, logged, or written into static exports. `.env` is git-ignored, and `.env.example` holds placeholders only.
- The server binds to `127.0.0.1`. POST requests must be `application/json` with a same-origin `Origin`, and Host headers are checked when bound to loopback. This blocks other websites (and DNS rebinding) from driving your local instance or spending your credits.
- Git sources read commit metadata and messages only, never diffs or file contents. Commit messages become evidence (and are sent to the model) only when you accept them.
- `serve --read-only` and the static export disable every write and every model call.
- Destructive actions (removing a source, deleting a milestone, enabling auto-accept) ask for confirmation. Evidence can never be deleted.

## Hosting the demo

| Option | Use it for |
|---|---|
| **Local** (`serve`) | Recording the demo video: live updates, Ask, imports, milestones |
| **Static snapshot on Vercel** | A public read-only link. No API key, no server, no costs |

```bash
python -m statetrace --db demo.db export-static --out site --workspace "TaskMaster demo"
npx vercel deploy site --prod
```

The snapshot contains evidence text, claims, versions, diffs, milestones and pre-computed answers. It does not contain sources, repository paths, imports, reminders or credentials. Imported commits include the author's name in their evidence text, so review before publishing.

## Evaluation

```bash
python -m statetrace eval --baseline --runs 3
```

The FFT scenario (`demo/fft_scenario.json`, the only scenario with ground truth) has 16 events and 37 checks at 7 checkpoints. It covers state accuracy, evidence attribution, contradiction detection, staleness, hallucinated progress and recovery after inactivity. `--baseline` uses the same model but rewrites the whole state each event, with no validator. Reports go to `eval_results/` with per-checkpoint tables, latency and vacuous-pass counts.

**Results, 2026-10-09** (`nvidia/nemotron-3-super-120b-a12b`, 3 runs each, 0 model-call errors; report `eval_results/eval-20261009-141758.md`):

| category | TaskMaster | Rewrite baseline |
|---|---|---|
| accuracy | 42/45 | 40/45 |
| attribution | 15/15 | 14/15 |
| contradiction | 9/9 | 9/9 |
| staleness | **27/27** | 21/27 |
| hallucination | 12/12 | 12/12 |
| recovery | 3/3 | 3/3 |
| **overall** | **108/111 (36, 36, 36)** | **99/111 (32, 34, 33)** |
| median latency per update | 7.5–7.9 s | 8.6–10.8 s |

How to read this honestly:
- The difference comes almost entirely from **staleness**: the baseline kept obsolete results such as a superseded post-synthesis WNS, or "backpressure tests fail" after they passed. On this scenario, the hallucination and contradiction checks did **not** separate the two approaches; the model didn't over-claim in either mode.
- TaskMaster's one failure in every run was at E14: a chat message ("works on the board") led Nemotron to invalidate the DSP48 next step. That is a model judgement error.
- In run 1, a late-arriving note opened a contradiction that stayed open. The validator now rejects that (rule 5). **These results were measured before** rules 3, 4, 5 and target-following were added, so re-run to measure the current code.
- 0 unsupported "verified" claims for TaskMaster is guaranteed by construction, not earned by the model.
- This is one scenario, 3 runs, with checks written by the same author. Checks match keywords against claim text, and "vacuous" passes (nothing recorded) are counted in the report. Treat this as a smoke-level comparison, not a benchmark.

`--offline eval` (hand-written operations) scores 37/37. That only shows the checks are wired correctly; it is not a model score.

## Tests

```bash
python -m unittest discover -s tests -v
```

133 tests (all passing on 2026-10-25, Windows, Python 3.13). `tests/test_trust.py` covers the trust boundary:
model-claimed support labels are ignored, unsupported items become "inference", invented or superseded claim refs
are dropped, malformed or offline model output falls back to a *labelled* stored-state answer, catch-ups never change
state, proposals don't commit until applied, apply re-validates against a newer state, discard keeps evidence,
pending proposals are never auto-applied, citations can't cross projects, and the sample loads without a key.
They also include regression tests that **replay Nemotron's recorded output from the first live run** (`tests/fixtures/live_run_nemotron.json`) to pin down observed failures: field-name slips, superseded target ids, duplicate contradictions, contradictions that must close as moot, and a stale blocker that the evaluator must catch. Also covered:
- verification rules: commits can't verify results; weaker evidence can't overwrite verified facts; late evidence can't contradict;
- the Git importer against a throwaway repository;
- milestones and reminders: dedupe, re-arming, quiet hours, inferred dates, at-risk reasons;
- HTTP behaviour: cross-site refusal, read-only mode, project isolation, readable errors.

## Configuration

| Variable | Default |
|---|---|
| `NEBIUS_API_KEY` | required for live mode (keep it in `.env` only) |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` |
| `NEBIUS_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| `NEBIUS_EXTRA_BODY` | optional JSON merged into each request |
| `STATETRACE_DB` / `STATETRACE_PROJECT` | `statetrace.db` / `fft-accel` |

## Layout

```
statetrace/
  schema.py store.py llm.py prompts.py validator.py engine.py
  summary.py      health, confidence, diffs, evidence index (rule-based)
  assistant.py    Nemotron answers, reviews and the catch-up (opinions; never state)
  proposals.py    review-before-commit: propose, preview, apply, discard
  synthesis.py skills/yosys.py   Yosys report import, compare, explain
  reminders.py    milestones, at-risk rules, deduplicated notices, quiet hours
  monitoring.py   companion settings/status, popup brief, deliverable notifications
  companion.py winapi.py   Windows desktop companion (stdlib ctypes)
  ingest/         staged evidence sources: __init__.py (workflow), git.py
  api.py server.py export.py view.py ask.py baseline.py evaluation.py cli.py
  static/         index.html, css/app.css, js/{app,api,ctx,ui,components,composer,milestones,assist,catchup}.js, js/views/*.js
demo/             fft_scenario.json (eval), scripted_ops.json (offline), workspace/*.json (sample projects), yosys/ (designs + real reports)
docs/COMPANION.md desktop companion: setup, privacy, verification
tests/            133 tests + recorded live-run fixture + real Yosys fixtures
scripts/          TaskMaster-Companion.cmd (Windows launcher)
```

## Limitations

- **The model still makes judgement errors.** It sometimes leaves `current_status` stale, and it ended a next step on the strength of a chat message. These stay visible as cited claims, but they aren't prevented.
- **Keyword rules are blunt.** The commit result-language rule (`RESULT_RE`) is a keyword list: it can downgrade a commit that merely mentions "timing", and can miss unusual phrasing.
- **"Verified" means backed by an artifact of a verifiable type.** Artifacts aren't parsed.
- **Desktop companion limits:** it is Windows-only; the default hotkey is Ctrl+Alt+T because Ctrl+Alt+Space was taken by another program on the development machine (change it with `--hotkey` or in Settings); notifications show as "Windows PowerShell"; nothing autostarts.
- **No GitHub/CI ingestion yet**, and there's no automatic deadline inference.
- **The check on Nemotron's wording is lexical.** Badged catch-up facts are always the claim's own text. Nemotron's
  extra wording is hidden only when it adds numbers or result words, so it can hide an accurate paraphrase, and
  it can't catch every subtle misstatement. Its notes are always labelled as Nemotron's.
- **Review-before-commit covers Yosys imports in the UI only.** Notes, Git accepts and CLI imports still commit
  after validation, as before.
- **Sample data is synthetic.** The MAC Unit's notes, commits and sim logs were written for the demo; its synthesis
  reports are real Yosys 0.9 output of synthetic designs. Nemotron latency is typically 4–20 s per call; the UI shows
  elapsed time, and results are saved if you navigate away.
