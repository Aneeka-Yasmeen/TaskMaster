# TaskMaster user guide

TaskMaster answers one question: **"Where did I leave my project?"** It keeps a log of evidence for each project
(notes, logs, reports, commits), works out what is currently true from that evidence, and shows what every statement
is based on. **NVIDIA Nemotron** (through Nebius Token Factory) reads the evidence and suggests changes; TaskMaster
checks them before anything is saved.

For installation, see the [README](../README.md).

---

## 1. Start and stop

| To… | Do this |
|---|---|
| Start | `python -m statetrace serve`, then open http://127.0.0.1:8765 |
| Start with the Windows hotkey window | `python -m statetrace companion` (see [COMPANION.md](COMPANION.md)) |
| Use a separate workspace | Add `--db name.db`, e.g. `python -m statetrace --db asic.db serve` |
| Stop | **Ctrl+Q** in the app, **Settings → Quit TaskMaster**, `python -m statetrace stop`, or **Ctrl+C** in the terminal |

- Everything is saved automatically. Closing a browser tab does not stop TaskMaster.
- A new workspace starts empty. Click **Load sample project** to explore an example (no API key needed), or add
  your first update.
- Ctrl+C works in PowerShell, cmd and Windows Terminal, but not in Git Bash. Use **Quit** or
  `python -m statetrace stop` there.

---

## 2. The screens

| Screen | How to open | What it shows |
|---|---|---|
| **Today** | Sidebar, or **T** | The project that needs attention first and why, then the others in order |
| **Projects** | Sidebar | All projects with their health, blocker and next step |
| **Current state** | Click a project | The **Where you left off** card, blocker, next step, milestones and contradictions |
| **Evidence** | Sidebar | Every piece of evidence and the claims it supports. Evidence can't be edited or deleted |
| **Inbox** | Sidebar | Git commits waiting for your review |
| **Synthesis (Yosys)** | Sidebar | Imported Yosys reports, comparisons and proposed changes |
| **Decisions, Questions, Activity** | Sidebar → *More* | Decision history, open questions, and every update across projects |
| **Ask Nemotron** | Sidebar, or **/** | Ask a question in plain English |
| **Settings** | Sidebar | Assistant, desktop companion, display, reminders, evidence sources |

Two layouts are available: **Simple** (the essentials) and **Detailed** (history, time travel, decisions and
questions). Switch with **D** or the buttons in the top bar.

### Keyboard shortcuts

| Key | Action |
|---|---|
| **N** | Add an update |
| **C** | Ask Nemotron where you left off (rebuilds the catch-up card) |
| **R** | Ask Nemotron to review the project |
| **/** | Ask a question |
| **T** | Go to Today |
| **D** | Switch Simple / Detailed |
| **?** | Show all shortcuts |
| **Ctrl+Enter** | Submit an update |
| **Esc** | Close a panel |
| **Ctrl+Q** | Quit TaskMaster |
| **Ctrl+Alt+T** | Open the compact window from any app (desktop companion only) |

---

## 3. Your first project

1. **Create it.** Press **N**. Under *Project*, choose **+ New project…** and type a name.
2. **Add the goal.** For example: *"Goal: 32-bit RISC-V core in sky130, 50 MHz, area under 1 mm², shuttle deadline
   Dec 15."* Choose a source:
   - **Note**, **chat**, **meeting**: something a person said. These stay **reported**.
   - **Sim log**, **test output**, **synthesis report**, **timing report**…: an artifact. These can make a claim
     **verified**.
3. **Submit.** Nemotron reads the update and proposes changes; TaskMaster checks them and saves what passes. The
   result shows what changed, and anything that was held back.
4. **Add a deadline.** On the project page, click **Add milestone**. TaskMaster never invents dates.
5. **Keep adding evidence** as you work: notes, pasted logs, reports, commits from the Inbox.
6. **Come back later.** Open the project, or press **Ctrl+Alt+T** if the companion is running. The **Where you left
   off** card is at the top.

---

## 4. Reading the "Where you left off" card

The card lists the next action, where things stand, what is established, blockers, uncertain items and open
contradictions.

| Label | Meaning |
|---|---|
| **Verified** | Backed by a log, test or report |
| **Reported** | A person said so; nothing confirms it yet |
| **Contested** | Evidence conflicts; it needs to be settled |
| **Nemotron's inference** | Nemotron's reading, not supported by any recorded claim |
| **Nemotron's suggestion** | A next action Nemotron proposed that isn't recorded in the evidence |

- Every labelled statement is the recorded claim itself, not Nemotron's wording. Click an evidence chip (e.g.
  **E8**) to read the source, or **Why?** to see why the claim is believed.
- Without an API key, the card is built directly from the recorded claims and says *Stored state only*.
- With a key, press **C** to have Nemotron organise it. The result is saved for that version of the project, so
  opening the project again doesn't call the model.

---

## 5. What Nemotron does

Nemotron (`nvidia/nemotron-3-super-120b-a12b`) does the reading and reasoning:

1. **Turns each update into changes**: which claims to add, update, close or flag as conflicting.
2. **Writes the catch-up** card and **answers questions**, citing evidence.
3. **Reviews a project** against its goal and deadlines: on track, at risk, off track or blocked, with suggestions.
4. **Explains Yosys comparisons** and suggests the next experiment.

What it can't do:
- Mark something verified (only artifacts can).
- Change a project on its own. Reviews and suggestions are advice; **Use as update** or **Make milestone** puts a
  suggestion through the normal steps.
- Accept commits or create deadlines.

**Autonomy** (Settings → Assistant) controls what happens without you asking:

| Setting | Effect |
|---|---|
| **Off** (default) | Nemotron runs only when you add an update, ask, or click Review |
| **Selected projects** | Chosen projects are reviewed after each update, and the companion watches their Git sources |
| **All projects** | The same for every project |

Each Nemotron call uses Nebius credits and takes about 4–30 seconds.

**Offline:** updates are always saved first. If Nebius can't be reached, they wait (*waiting for Nemotron*) and are
applied in order once it is back, or straight away with **Sync now**.

---

## 6. Yosys synthesis reports

Open a project, then **Synthesis (Yosys)** in the sidebar.

1. **Import** a report: Yosys `stat` output as text (e.g. `tee -o report.rpt stat`) or `stat -json`, up to 2 MB.
   Example reports are in `demo/yosys/`. Importing the same file twice creates nothing new.
2. **Review the proposed change.** Nemotron suggests how the report changes the project, and you see a before/after
   comparison. Click **Apply to project state** or **Discard proposal**. The report is kept as evidence either way.
   Without an API key, the report is still saved and can be compared.
3. **Check the numbers**: total cells, cell types, and counts derived from cell names (flip-flops, LUTs and so on,
   always marked *derived*).
4. **Compare** two runs. TaskMaster calculates the differences itself and lists what the comparison can't tell you
   (cell counts are not timing, power or area). Optional limits, such as maximum cells, are flagged when exceeded.
5. **Explain with Nemotron** (needs a key): observations, possible causes and one next experiment. The explanation is
   marked *interpretation, not evidence*, and **Accept as update** adds it only if you choose.

---

## 7. Git commits

1. Open a project's **Inbox** and add a repository: a Windows path (`C:\work\asic`), or a WSL path
   (`/home/name/asic`) with *Repository lives inside WSL2* ticked.
2. Click **Scan now**. New commits are listed for review.
3. **Accept** the ones that matter, or skip them. Nothing changes until you accept.

Only the commit hash, date, author, branch, message and line counts are read, never file contents. A commit shows
that a change was made, not that tests pass. That needs a log or report.

---

## 8. Deadlines, reminders and priority

**Reminders** appear in the bell in the top bar (and as Windows notifications if the companion is set up):

| Reminder | When |
|---|---|
| Deadline | 1 day and 2 hours before, by default (changeable per milestone) |
| Overdue | Once, after the due time |
| Stale project | No new evidence for 7 days |
| Commits to review | After a background scan finds new commits |

Each reminder appears once. Quiet hours (22:00–08:00 by default) hold back pop-ups. Change these in
**Settings → Reminders**.

A milestone is marked **at risk**, with the reason, when it is due within 72 hours, due within 7 days while the
project is blocked or contested, or due within 14 days while the project is stale.

**Priority** decides which project appears first on Today. The reasons are always shown:

| Reason | Points |
|---|---|
| Overdue deadline | 100 |
| Deadline in ≤3 / ≤7 / ≤14 days | 80 / 60 / 30 |
| Marked High / Low priority | +40 / −30 |
| Blocked | +20 |
| Unresolved contradiction | +15 |
| Nemotron's review: off track or blocked / at risk | +15 / +8 |
| Updates waiting to sync | +10 |
| Stale | +10 |
| Commits to review | +5 |

Set a project's priority from its page header.

---

## 9. Your data and privacy

- Each workspace is one file (`statetrace.db` by default) in the TaskMaster folder. It stays on your computer.
- Evidence is never edited or deleted. Older beliefs are kept and marked as replaced, so you can always see what
  changed and why.
- The API key stays in `.env` and is only read by the local server. It never reaches the browser.
- TaskMaster runs on your computer only (`127.0.0.1`) and refuses requests from other websites.
- Nothing is monitored except Git repositories you add, and only when Autonomy allows it and the companion is
  running. There is no screen, keyboard or folder monitoring.
