# TaskMaster: complete guide

TaskMaster answers **"Where did I leave my project?"** It keeps an evidence log for each project,
reconstructs what is currently true from that evidence, and uses **NVIDIA Nemotron** (via Nebius
Token Factory) as an assistant that reasons, compares and suggests. **It never acts on its own.**

---

## 1. Start and stop

| What | How |
|---|---|
| **Start** | `python -m statetrace serve`, then open http://127.0.0.1:8765 |
| Start with the Windows hotkey helper | Double-click `scripts\TaskMaster-Companion.cmd`, or `python -m statetrace --db demo.db companion` (see [COMPANION.md](COMPANION.md)) |
| Open the full dashboard | http://127.0.0.1:8765 in any browser, or the ↗ icon / *Open full dashboard* in the compact window |
| Open the compact window | **Ctrl+Alt+T** from any app (while the companion runs) |
| **Quit** | **Ctrl+Q** in the dashboard or compact window, **Settings → Quit TaskMaster**, **Quit** in the compact window's footer, or `python -m statetrace stop`, or Ctrl+C / close the console window that started it |

- Closing the compact window or a browser tab does **not** quit TaskMaster.
- Ctrl+C works only in a real Windows console (PowerShell, cmd, Windows Terminal, the `.cmd` window).
  It doesn't reach Windows Python from Git Bash, and it can't stop a copy started from somewhere else.
  In those cases use Quit or `stop`.
- Your data is always saved; quitting never loses anything.

Use one database per purpose, e.g. `--db demo.db` for trying things and `--db asic.db` for your real ASIC project.
A new database starts empty: click **Load sample project** (no API key needed) or add your first update.

---

## 2. Screen map

```
┌───────────── sidebar ─────────────┬──────────────────── top bar ────────────────────────────┐
│ ✓ TaskMaster                      │ Today › …        [Nemotron ready] [Simple|Detailed] 🕓 [+ Add update N] │
│ ◎ Today                (T)        ├──────────────────────────────────────────────────────────┤
│ ▢ Projects                         │                                                          │
│ ⚡ Ask Nemotron          (/)        │                     main screen                          │
│ PROJECT  [ project switcher ▾ ]    │                                                          │
│ ◎ Current state                    │                                                          │
│ ▤ Evidence                         │                                                          │
│ ≡ Inbox                            │                                                          │
│ ▸ More: Decisions · Questions · Activity                                                      │
│ WORKSPACE  ⚙ Settings              │                                                          │
│ [Keyboard shortcuts ?]             │                                                          │
│ ● nemotron-3-super… Nebius         │                                                          │
└───────────────────────────────────┴──────────────────────────────────────────────────────────┘
```

| Screen | Where / how to open | What it does |
|---|---|---|
| **Today** | Sidebar *Today*, or **T** | The **Focus now** card: the most urgent project, *why* it's first, its deadline countdown, blocker, next step and Nemotron's verdict. Buttons: Open project, Ask Nemotron, Add update, Review with Nemotron. Below: **Up next**, the other projects ranked with their reasons. Detailed layout adds upcoming deadlines, health numbers and all project cards |
| **Projects** | Sidebar *Projects* | Table of all projects: health, blocker, next step, evidence count, confidence, last update |
| **Project → Current state** | Click a project anywhere, or sidebar *Current state* | Header with a **Priority** selector (High/Normal/Low). **Nemotron's review** (verdict, going well, concerns, suggestions with *Use as update* / *Make milestone*). State cards: **Current blocker**, **Next step** (*proposed from evidence* or *committed* with due date), **Last action**, **Confidence**. Then contradictions (*Needs verification*), Milestones, and *Show all details*. Detailed adds the status table, time-travel slider, latest before/after change, timeline, decisions and questions |
| **Evidence** | Sidebar *Evidence* | Every piece of evidence (searchable; artifacts vs reports), the claims each one supports, and the beliefs it made obsolete. Nothing here can be edited or deleted |
| **Inbox** | Sidebar *Inbox* (shows "N new") | Connect a Git repository (Windows or WSL), *Scan now*, review staged commits, **Accept** or **Skip**, retry failed ones |
| **Decisions** | Sidebar *More → Decisions* | Decision history (active / superseded / reversed, with reason and tradeoff) and what was tried |
| **Questions** | *More → Questions* | Open → Investigating → Resolved; resolved only by evidence |
| **Activity** | *More → Activity* | Every update across all projects by day; click one to see the state change it caused |
| **Ask Nemotron** | Sidebar, or **/** | Ask anything. Nemotron answers first, citing evidence; the badge says *Nemotron* or *Stored state*. *Compare with the stored-state answer* shows the no-model version |
| **Settings** | Sidebar *Settings* | Assistant & **Autonomy**, desktop companion (notifications, hotkey, pause, **Quit**), Display (text size, layout, theme), Reminders (quiet hours), Evidence sources, Trust rules |
| **Reminders (bell 🕓)** | Top bar | Deadline, stale-project and new-commit reminders, each shown once, with *Dismiss* |
| **Status chip** | Top bar | *Nemotron ready*, *Nemotron offline*, or *N waiting for Nemotron · Sync now* |
| **Compact window** | **Ctrl+Alt+T** | Active project: Nemotron's verdict and top suggestion, blocker, next step (proposed/committed), latest change, next deadline. Quick buttons: Where did I leave off?, What's blocking me?, What should I do next?, Add update, Review Git imports, Open full dashboard, Quit |
| **Why?** panels | *Why?* on any claim, or click any evidence chip (E12) | The evidence behind a belief, earlier beliefs it replaced, and related contradictions |

### Keyboard shortcuts (press **?** to see them in the app)

| Key | Action |
|---|---|
| **Ctrl+Alt+T** | Open/focus the compact window from any app |
| **N** | Add an update to the current project |
| **/** | Ask Nemotron |
| **R** | Ask Nemotron to review the current project |
| **T** | Go to Today |
| **D** | Switch Simple ↔ Detailed |
| **?** | Show shortcuts |
| **Ctrl+Enter** | Submit an update |
| **Esc** | Close a panel/dialog |
| **Ctrl+Q** | Quit TaskMaster (asks first; data is saved) |

---

## 3. From a new project to a reconstructed state

1. **Create the project.** Press **N** (or *+ Add update*). In *Project*, choose **+ New project…** and
   type a name (e.g. "RISC-V ASIC"). The project is created immediately; it needs no model.
2. **First update: the goal.** For example: *"Goal: 32-bit RISC-V core in sky130 with OpenLane, 50 MHz,
   area < 1 mm², tape-out shuttle deadline Dec 15."* Choose **Note** (people's statements) or
   **Artifact** (a log or report pasted in: sim log, synthesis/timing report, test output).
3. **Update project.** Steps you'll see:
   - *Reading evidence*;
   - *Comparing with the previous state*: Nemotron proposes changes;
   - *Checking for contradictions*;
   - *Updating project state*: the validator applies only what passes the rules.

   The result shows before → after, plus anything the validator **held back**.
4. **Set priority and deadlines.** On the project page set **Priority: High** and *Add milestone*
   (e.g. "GDS ready for shuttle", due Dec 15, remind 1 week and 1 day before). TaskMaster never invents
   dates.
5. **Ask Nemotron to review** (**R** or *Review now*). It compares the evidence with the goal and
   deadlines and returns a verdict and suggestions.
6. **Keep adding evidence** as you work: notes, pasted Yosys `stat` output, OpenLane metrics, sim
   results, commits from the Inbox. Artifacts make claims **verified**; notes stay **reported**.
7. **Come back days later:** open Today, or press Ctrl+Alt+T and click *Where did I leave off?*.

---

## 4. What Nemotron does, and what it doesn't

Nemotron (`nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory) has three jobs:

1. **State engine proposer.** For every update, it reads the current claims plus the new evidence and
   proposes operations: add, update, invalidate, contradict, resolve. A deterministic **validator**
   applies only the operations that pass the trust rules. You can see exactly what Nemotron proposed
   versus what was applied: click any timeline event → *Raw operations*.
2. **Assistant for your questions.** *Where did I leave off?* and any other question go to Nemotron
   **first**, grounded in the validated state, the evidence log, deadlines and the stored-state answer.
   Its citations are checked; invented ones are marked `(?)`. If Nebius is unreachable, you get the
   stored-state answer, clearly labelled.
3. **Reviewer.** It compares where the evidence says you are with your goal and deadlines, then gives
   a verdict (on track, at risk, off track, blocked), what's going well, concerns, up to 3 suggestions
   and open questions.

**What it never does:**
- change a project by itself (reviews are stored separately and are never claims or evidence);
- accept commits;
- create deadlines;
- mark something verified without an artifact.

When you like a suggestion, *Use as update* or *Make milestone* sends it through the normal path, and
you click to confirm.

**Autonomy** (Settings → Assistant):

| Level | What happens without you asking |
|---|---|
| **Off** (default) | Nothing. Nemotron runs only when you add an update, ask, or click Review |
| **Selected projects** | For ticked projects: Nemotron reviews after every new update, and the companion watches their Git sources |
| **All projects** | The same for every project |

Each model call costs Nebius credits. With Autonomy off, only your actions cause calls.

**Offline.** Updates are always saved locally first. If Nebius can't be reached, the update is stored
and shown as *waiting for Nemotron*. The server checks every minute and applies waiting updates,
oldest first, when it's back (or press *Sync now*). Viewing state, the stored-state answers, milestones
and evidence all work offline.

---

## 5. How data is stored

Everything lives in one SQLite file per workspace (e.g. `demo.db`) in the TaskMaster folder.

| Table | Contents |
|---|---|
| `events` | The **evidence log**: every update, with source, time it happened, time recorded, and reference. **Append-only**: database triggers refuse edits and deletes |
| `state_versions` | A snapshot of the reconstructed state after each update (time travel, diffs, rebuild) |
| `transitions` | For each update: what Nemotron proposed, what was applied, rejected or repaired, latency, errors |
| `assistant_reviews` | Nemotron's reviews: opinions per state version, kept apart from the state |
| `milestones` / `notices` | Your deadlines and the deduplicated reminders |
| `sources` / `import_items` | Connected Git repositories and staged commits (pending, accepted, skipped, failed) |
| `projects` | Names and your priority (High/Normal/Low) |
| `settings` | Autonomy, companion, reminder and quiet-hour settings |

- The API key lives only in `.env`, read by the local server. It never reaches the browser, exports or
  logs.
- The server listens on 127.0.0.1 only and refuses requests from other websites.

---

## 6. Monitoring

- **What's monitored:** only Git repositories you connect in a project's **Inbox**, for projects
  Autonomy allows, and only while the companion runs.
  - Windows path: `C:\work\asic`.
  - WSL path: `/home/you/asic`, with *Repository lives inside WSL2* ticked (uses `wsl git`).
- **What is read:** commit hash, date, author, branch, message and line counts. No diffs, no file
  contents.
- **What happens:**
  1. New commits are **staged** in the Inbox. Nothing changes until you **Accept**.
  2. Accepted commits go through Nemotron and the validator like any update.
  3. A commit can show that a change was made, but never that tests pass or timing is met; that needs a
     log or report artifact.
- **Not monitored:** your terminal, keystrokes, screen, arbitrary folders, GitHub/GitLab. To feed
  results in today, paste a report into *Add update → Artifact*, or from the CLI:
  `python -m statetrace -p asic add -s timing_report -f runs/run1/final/metrics.csv "OpenLane run 1"`.

---

## 6b. Synthesis runs (Yosys skill)

Open a project → sidebar **Synthesis (Yosys)** (or the *Synthesis runs* card on the project page, or
*Synthesis runs* in the compact window).

1. **Import** a Yosys report: text `stat` output (`tee -o report.rpt stat` after `synth`) or `stat -json`,
   up to 2 MB. TaskMaster hashes it (sha256), parses it as data (never instructions), and records it as a
   `synthesis_report` **evidence** item, so its measurements are *verified*. Importing identical content
   again creates nothing new; a new run never overwrites an older one.
2. **Review** the extracted metrics: totals exactly as reported, the cell-type breakdown, and counts
   *derived from cell names* (flip-flops, LUTs, DSP, memory primitives), which are always labelled
   derived. Anything the report doesn't contain is simply absent. Unreadable lines and ambiguities
   (e.g. several modules without a hierarchy summary) are listed, not guessed.
3. **Choose a baseline** run and **Compare**. TaskMaster computes absolute and % changes (undefined % when
   the baseline is 0), new and disappeared cell types, and **limitations** (different libraries, scopes
   or top modules; cell counts are not timing, power or physical area). Optional **limits** (max cells,
   flip-flops, LUTs, chip area) are flagged only when the report measures them.
4. **Explain with Nemotron.** Nemotron receives the computed comparison and project context (never the
   raw file) and returns observations, hypotheses with confidence, evidence that would settle them, and
   one next experiment. Citations are checked. The explanation is labelled *interpretation, not
   evidence* and never changes the project. If Nebius is down, the comparison stays and the explanation
   says it's unavailable.
5. **Accept the next experiment** with *Accept as update* or *Make milestone*. Nothing happens until you
   click.

CLI: `synth-import FILE`, `synth-runs`, `synth-compare RUN BASELINE`, `synth-explain COMPARISON`.

## 7. Alerts and reminders

| Alert | When | Where you see it |
|---|---|---|
| **Deadline reminder** | At the offsets you chose (default 1 day and 2 hours before) | Bell; toast in the dashboard; Windows notification if enabled |
| **Overdue** | After the due time, once | Same |
| **Stale project** | No new evidence for 7+ days, once per stale period | Same |
| **Commits waiting for review** | A background scan staged new commits | Same (companion + Autonomy on) |
| **At-risk flag** | Deadline ≤72 h, or within 7 days while blocked/contested, or within 14 days while stale | On the milestone, the Focus card and in Up next, with the reason |

- **Rules:**
  - each issue is reported **once** (rescheduling re-arms it);
  - quiet hours (default 22:00–08:00) hold back pop-ups;
  - Windows notifications are **off by default** and need Autonomy on;
  - notifications never include commit messages or blocker text.
- **Configure:** Settings → Reminders (quiet hours, defaults) and Settings → Desktop companion
  (Windows notifications, test notification).

---

## 8. Priority: why a project is first

The score is deterministic, and the reasons are shown next to the project:

- overdue deadline **100**; due ≤3 days **80**; ≤7 days **60**; ≤14 days **30**
- High priority **+40** (Low −30)
- blocked **+20**; unresolved contradiction **+15**
- updates waiting to sync **+10**; stale **+10**; commits to review **+5**
- Nemotron's latest verdict: off track or blocked **+15**, at risk **+8**

Set a project's priority in its header.

---

## 9. Trust rules (enforced in code)

1. Every claim cites real evidence; invented citations are removed.
2. **Verified** needs an artifact (log, report, test, CI). Notes and chats are **reported**.
3. A commit proves a change happened, not that something passes or works.
4. Weaker evidence can't overwrite a verified fact; it opens a **contradiction** (*Needs verification*).
5. Old evidence can't overwrite or contest newer beliefs.
6. Nothing is deleted. Beliefs are superseded or invalidated with the evidence that ended them.
7. Nemotron advises; the validator decides; you act.
