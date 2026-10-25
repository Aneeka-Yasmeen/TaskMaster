# TaskMaster — Devpost submission

**Tagline:** Where did I leave my project? TaskMaster reconstructs what is true about an engineering project right now, from its evidence, and shows what each statement rests on.

**Built with:** NVIDIA Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) · Nebius Token Factory · Python (stdlib only) · SQLite · vanilla JS/CSS (no framework, no build step)

**Links:** video: _<YouTube link>_ · repo: _<GitHub link>_ · read-only snapshot: _<URL, if deployed>_

---

## The problem

Hardware and ML projects run for months, and their evidence is scattered: commits, Yosys reports, sim logs, experiment logs, chat messages, two-line notes. After a week or two away, getting back in means rereading all of it.

Asking an LLM to summarize doesn't fix this, because a running summary can't be trusted. It keeps fixed blockers as current, turns "should be fine now" in a chat into "tests pass", blends conflicting evidence into one confident sentence, and can't say why it believes anything.

## What it does

TaskMaster keeps an **append-only evidence log** and a **versioned project state** made of *claims*: goal, last action, current blocker, next step, decisions, attempts, open questions, and per-subject status (simulation, timing, utilization…). Every claim carries its evidence ids, a verification level (*verified* by an artifact such as a log, test or report, or only *reported* by a person), and timestamps.

### "Where did I leave off, and what should I do next?"

The first thing on each project page is a catch-up card: where you left off, the next action, what is established, the blockers, what is uncertain, the open contradictions, and what evidence would settle them.

- **Nemotron organizes the claims and the validated state supplies the facts.** Nemotron chooses and groups claims by id. Each displayed statement is the claim's own stored text, with its Verified / Reported / Contested label and evidence chips taken from the claim.
- Nemotron's wording is shown only as a labelled note, never with a badge, and it is hidden when it introduces numbers or result words ("pass", "closed", "fixed"…) that the claim doesn't contain.
- An item no claim supports is labelled **Nemotron's inference — not established**. A next action that isn't a recorded next step is labelled **Nemotron's suggestion** and lists the claims it was based on. When the evidence doesn't justify a next action, the card says so.
- If Nebius is unreachable or the reply is malformed, a deterministic reconstruction from the claims is shown, labelled "stored state". It is never presented as a model answer.
- Results are cached per state version, so opening a project never calls the model.

### The trust boundary: Nemotron proposes, code decides

For each new piece of evidence, Nemotron proposes a state transition (add, update, invalidate, contradict, resolve, no change). A deterministic validator decides what is applied, and logs everything it rejects, downgrades or repairs:
- Every claim must cite evidence that exists in this project.
- Notes and chats can never produce *verified* claims, and a commit message can't verify a result.
- Weaker evidence can't overwrite a verified fact; it opens a *Needs verification* contradiction instead.
- A person asserting a result ("fixed, all vectors pass") can't clear a blocker that a test, sim or report established, or settle a contradiction involving verified evidence; that needs a re-run. A person can still drop a blocker by decision.
- Older evidence can't overwrite or contest newer beliefs.
- Nothing is deleted. The state and its transition record are committed atomically, so a failure never leaves a half-applied update.

### Yosys workflow with review before commit

1. Import a Yosys `stat` report (text or JSON). TaskMaster hashes it (duplicates are refused), parses it as data and records it as artifact evidence.
2. Nemotron proposes the state change, and the validator dry-runs it **without committing**. You see a before/after diff, including anything the validator held back.
3. **Apply** re-validates the same stored operations against the current state (it may have moved on) and commits, with no second model call. **Discard** keeps the report as evidence and records the decision. Pending proposals are never applied by background sync.
4. Compare any two runs (deterministic cell, flip-flop and wire deltas, with their limitations stated), then ask Nemotron to explain the difference and suggest one next experiment. The explanation is labelled as interpretation and never becomes evidence.

### Also in the app

Why? on any claim, time travel through state versions, a before/after diff for every event, a stale-state warning, staged Git commit import (nothing applies until you accept it), milestones and reminders with stated at-risk reasons, Nemotron reviews (opinions, stored apart from the state), an offline queue that syncs when Nebius is back, a Simple/Detailed layout, keyboard shortcuts, and a Windows desktop companion (opt-in, hotkey popup). On first run there is a short intro and a **Load sample project** button that works without an API key. Sample projects replay hand-written operations and are labelled "Sample data" and "not live Nemotron" everywhere.

## How we built it

- **Model:** Nemotron 3 Super through Nebius Token Factory's OpenAI-compatible API (JSON mode with a tolerant parser). The engine prompt contains the active claims, a short window of recent evidence and the new evidence.
- **Validator and grounding:** pure deterministic Python. The validator applies operations to a copy of the state. Catch-up grounding derives every fact, label and evidence chip from validated claims.
- **Storage:** SQLite with triggers that make the events table append-only, a snapshot per state version, and a log of every transition: proposed vs. applied vs. rejected, plus proposals awaiting review and user rejections. Any state can be rebuilt by replaying the log.
- **Frontend:** ES-module views over a service layer with two backends: the local API, and a static read-only snapshot.

## Evaluation and testing

**Tests:** 133 unit and integration tests, all passing on 2026-10-25 (Windows, Python 3.13). They include:
- regression tests that replay Nemotron's recorded output from live runs;
- trust-boundary tests: model sentences that exaggerate or contradict their cited claim are not shown, unsupported next actions are labelled as suggestions, contested claims never appear as verified, offline and malformed replies fall back to the labelled stored state, proposals don't commit until applied, and citations can't cross projects.

**Ground-truth scenario:** a streaming FFT accelerator with 16 pieces of evidence over three weeks. It includes a note contradicting a report, a late-arriving outdated note, an unsupported "works on the board" chat, and a 3-week gap. At 7 checkpoints we compare TaskMaster with an ablation that uses the same model but rewrites the whole state each time.

Results from 3 runs each (Oct 9, 2026, 0 model-call errors):

| category | TaskMaster | Rewrite baseline |
|---|---|---|
| accuracy | 42/45 | 40/45 |
| attribution | 15/15 | 14/15 |
| contradiction | 9/9 | 9/9 |
| staleness | **27/27** | 21/27 |
| hallucination | 12/12 | 12/12 |
| recovery | 3/3 | 3/3 |
| **overall** | **108/111** | **99/111** |

What this does and doesn't show:
- The gap is almost entirely staleness. Hallucination and contradiction checks did not separate the approaches on this scenario.
- It is one scenario and 3 runs, with keyword-based checks we wrote ourselves.
- It was measured **before** several validator rules and the catch-up grounding were added, and hasn't been re-run since.

## Challenges we ran into

- **A citation doesn't make a sentence true.** Our first catch-up showed Nemotron's sentence with a badge taken from the claim it cited. In a live run, a sentence about one sim log was attached to a claim backed by a different one. Now the displayed fact is the claim's own text, and the model's sentence is shown only as a labelled note, or hidden if it adds numbers or results.
- **People claim results too.** In a live run on the demo MAC project, a chat message ("the failures are fixed, all 256 vectors pass") cleared a blocker that a failing sim log had established. The validator now turns that into a contradiction until a re-run settles it.
- **A commit message is not a test result.** In a live Git import, "all 14/14 tests pass" in a commit cleared a test-established blocker. Commits now only prove that a change exists.
- **Small schema drift.** Nemotron sometimes put status subjects in the wrong slot or targeted superseded claim ids. We added logged repairs (follow superseded ids, fix field names) instead of loosening the rules, and pinned the recorded outputs as tests.
- **Reasoning tokens.** Nemotron 3 Super spends thousands of reasoning tokens before answering. A 2,000-token limit returned empty content, which the catch-up correctly reported as malformed and fell back from. Limits are now sized for reasoning, and the UI shows elapsed time (calls take about 4–30 s).

## Accomplishments we're proud of

- The model can't make something *verified*. That depends on artifact type and the validator, and it is tested.
- Every catch-up statement with a badge is the stored text of a validated claim, one click from its evidence.
- Review before commit for imported reports, with the full proposal, decision and commit history kept.

## What we learned

Keep a hard line between what happened, what is currently believed, what supports it, and what has become obsolete or contested. Nemotron is good at choosing and explaining; the rules and the facts belong in code and in the evidence.

## Limitations

- The grounding check for Nemotron's wording is lexical (numbers and result words). It can hide an accurate paraphrase, and it can't catch every subtle misstatement. Badged facts are always the claim's own text.
- Review before commit covers Yosys imports in the web UI; notes, Git accepts and CLI imports commit right after validation.
- The demo projects are synthetic. The MAC Unit's synthesis reports are real Yosys 0.9 output of synthetic designs.
- The desktop companion is Windows-only.

## What's next

More evidence sources on the staged-import interface (GitHub, CI, Vivado/OpenLane reports), review before commit for every source, and re-running the evaluation on the current rules.

---

## Demo video script (about 2 minutes)

1. **0:00 Problem:** a project's evidence is scattered across logs, reports, commits and chats. A running summary would say "all tests pass". Watch what TaskMaster does instead.
2. **0:15 Today:** the first-run card, *Focus now* with its stated reasons, and the **Sample data** badges.
3. **0:25 MAC Unit (Yosys):** press **C**, with the elapsed time counting up. In the card, each statement is a validated claim with a Verified / Reported / Contested label, and Nemotron's wording is labelled separately. Click **E8**, the failing sim log.
4. **0:55 The contradiction:** the chat says "all 256 vectors pass"; the verified sim log says 6 fail. The validator refused to let the chat clear the blocker. The next action is the recorded one: re-run the testbench.
5. **1:15 Yosys review before commit:** import `mac_v2_xilinx_stat.rpt`. Nemotron proposes a change and the before/after diff appears; nothing is applied yet. Click **Apply**. Then compare the runs and choose *Explain with Nemotron*.
6. **1:45 History:** **D** for Detailed view, then *What changed*: every event's diff, including the proposal you just applied.
7. **1:55 Close:** "TaskMaster doesn't just remember what happened. It reconstructs what is true now, and shows why."
