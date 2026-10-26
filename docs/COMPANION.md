# TaskMaster desktop companion (Windows)

A small, opt-in Windows helper that opens a compact TaskMaster window from any app, and
optionally watches your connected Git sources and shows Windows notifications.
**Background monitoring and Windows notifications are both off by default.**

## Architecture

```
 python -m statetrace companion          (one Windows process, Python stdlib only)
 ├─ backend: uses the TaskMaster server already running on 127.0.0.1:<port>,
 │           or hosts one in-process (never a detached duplicate)
 ├─ hotkey thread: RegisterHotKey (default Ctrl+Alt+T) → open or focus the compact window
 ├─ compact window: Edge in --app mode, /companion.html, dedicated browser profile
 └─ monitor loop (every 30 s): heartbeat always; only if Background monitoring is on and not paused:
      scan enabled Git sources (staged imports only) → server generates notices with its existing
      reminder rules → if Windows notifications are on: show each deliverable notice once
```

- **One state engine.** The companion only calls the existing HTTP API. All rules stay in the server:
  reminder timing, quiet hours, deduplication, stale detection, Git staging, validation.
- **No new dependencies.** It uses `ctypes` (RegisterHotKey, a named mutex, window focus) and
  `subprocess` (Edge, and Windows PowerShell for toasts). It was tested with Python 3.13 on Windows 11.
- **Why a helper process at all:** a web page can't register a system-wide hotkey or show OS
  notifications when it isn't open. The helper does only those two things plus the opt-in loop.

### Files

| File | Purpose |
|---|---|
| `statetrace/companion.py` | lifecycle, backend connect-or-host, popup open/focus, monitor tick, heartbeat |
| `statetrace/winapi.py` | ctypes: single-instance mutex, hotkey thread, find/focus window, Edge app window, toast |
| `statetrace/monitoring.py` | companion settings (persisted in the workspace DB), status, popup brief, deliverable notices |
| `statetrace/static/companion.html`, `static/js/companion.js` | compact view (reuses the dashboard's drawers, "Why?" and Add-update) |
| `scripts/TaskMaster-Companion.cmd` | double-click launcher |
| `tests/test_companion.py` | 15 tests of the platform-independent logic |

## Install and launch

Run on **Windows Python** (not inside WSL): hotkeys and notifications are Windows APIs.

```bat
cd taskmaster
python -m statetrace --db demo.db companion
```

Or double-click `scripts\TaskMaster-Companion.cmd`. Set `TASKMASTER_DB` first to choose the workspace; the default is `demo.db`.

| Option | Effect |
|---|---|
| `--port 8765` | server port (reuses a TaskMaster server already running there) |
| `--hotkey ctrl+alt+k` | use another shortcut for this run (overrides the saved setting) |
| `--no-hotkey` | don't register any global shortcut |
| `--no-popup` | don't open the compact window at start |

**WSL2:** keep repositories wherever you like. Add WSL repos as sources with `--wsl` (they are read
with `wsl git`), but run the companion itself on Windows. If you prefer to run `serve` inside WSL, WSL2
forwards `localhost`, so the Windows companion connects to it (start it with the same `--port`).

**Lifecycle**
- Closing the compact window changes nothing else.
- Running the command again while the companion is running only focuses its window, then exits.
- **To quit TaskMaster** (server and companion together), use any of:
  - **Ctrl+Q** in the dashboard or compact window, **Settings → Quit TaskMaster**, or **Quit** in the compact window's footer;
  - `python -m statetrace stop` from any terminal;
  - Ctrl+C in the console that started it, or closing that console window.
- Ctrl+C only works in a real Windows console (PowerShell, cmd, Windows Terminal, or the `.cmd`
  launcher's window). It does **not** reach Windows Python from Git Bash/mintty, and it can't stop a
  copy started elsewhere (e.g. by Claude Code). Use Quit or `stop` in those cases.
- Evidence is in SQLite and survives any stop. A forced kill during testing left the database with
  `integrity_check = ok`.
- Nothing starts with Windows.

## The hotkey

- The default is **Ctrl+Alt+T** (changed from Ctrl+Alt+Space, which another program owned on this machine). If another program already owns it, the companion says so in its
  console and in Settings, registers nothing, and pressing the keys does nothing in TaskMaster.
- **On this machine Ctrl+Alt+Space was already taken by another program.** The companion detected this
  at startup. A likely candidate is the Claude desktop app's quick-entry shortcut, but this was not
  verified.
- To use something else:
  - In Settings → Desktop companion, change *Global hotkey* (e.g. `ctrl+alt+t`), then restart the companion.
  - Or, for one run: `--hotkey ctrl+alt+k`.
- A combination must include Ctrl, Alt or Win (a bare key is refused). Keys can be letters, digits,
  `space`, or `f1`–`f12`.
- To disable it: untick *Global hotkey* in Settings, or start with `--no-hotkey`.

## Background monitoring and Windows notifications

Background monitoring follows **Settings → Assistant → Autonomy**; notifications are set in **Settings →
Desktop companion**. Both are persisted in the workspace database.

- **Background monitoring = Autonomy (Off by default).** *Off*: nothing in the background. *Selected
  projects* / *All projects*: while the companion runs, it scans the *enabled* Git
  sources every 5 min – 4 h (you choose), using the existing staged-import workflow. Paused or removed
  sources are skipped. New commits are **only staged** for review, never accepted, even on a source
  with auto-accept turned on. It also lets the server generate deadline and stale-project notices.
  **Pause all monitoring** stops all of this without losing your choices.
- **Windows notifications (off by default; need monitoring).** You get one notification per issue:
  - a milestone reminder is due or overdue;
  - a project goes stale;
  - new commits are waiting for review.

  Rules:
  - Quiet hours and the reminder switch apply.
  - Notices created before you turned monitoring on are never pushed (no backlog flood).
  - Text is short and never includes commit messages, blocker text or evidence.
  - Clicking a notification opens the relevant project or Inbox in your default browser.
  - Blocker and contradiction changes are not notified: in the background the companion never changes
    the state (it only stages), so they only happen while you're using TaskMaster.
- Notifications are shown as coming from **Windows PowerShell**. That is the identity an unpackaged app
  can use without an installer. You can turn them off per-app in Windows Settings → Notifications,
  which the companion detects and reports.

### Turn everything off

- Settings → Assistant: set Autonomy to **Off**. Settings → Desktop companion: untick *Windows
  notifications*, or press *Pause all background activity*.
- Or simply don't run the companion: with it stopped there is no background activity at all.

## Privacy and security

- Git monitoring reads commit metadata and messages only, never diffs or file contents, and only from
  repositories you added as sources.
- There is no keystroke monitoring (the hotkey is one registered combination), no screen capture, and
  no filesystem crawling.
- The API key stays in `.env`, read by the server. It is not passed to the companion, the browser,
  notifications or logs.
- The server binds to 127.0.0.1. Its state-changing endpoints require JSON from the same origin.
  `POST /api/open` only opens TaskMaster dashboard paths, and only on a loopback server.
- The compact window is excluded from static exports.

## Verification status

**Automated (any OS):** `python -m unittest discover -s tests` passes 133 tests (2026-10-25). The 15 companion
tests cover:
- defaults off; settings persist across a restart; validation (including the hotkey);
- monitoring on/off and *Pause all*; paused and removed sources not scanned;
- background scans never accepting, even with auto-accept;
- repeated scans creating no duplicate imports or notices;
- quiet hours suppressing; existing reminder dedupe intact; failed notifications retried and then
  delivered exactly once; no backlog;
- project isolation and empty, missing, stale or contested state in the popup;
- a model outage keeping state intact; closing the UI keeping the backend; no duplicate servers;
- a foreign port refused; backend-down reported.

**On Windows, on this machine (Windows 11, 2026-10-12).** The hotkey checks used keypresses synthesized
with `SendInput`, which go through Windows' real hotkey dispatch but are not a person pressing keys.

| # | Check | Result |
|---|---|---|
| 1 | Register Ctrl+Alt+Space | **Conflict detected**: already registered by another program. Reported clearly; nothing registered |
| 1b | Register an alternative (Ctrl+Alt+T) | Registered |
| 2 | Open the popup while another app is focused | Synthesized Ctrl+Alt+T while the Claude window was focused: window opened and came to the front |
| 3 | Repeated presses | Focused the existing window; window count stayed 1 |
| 3b | Launch the companion a second time | "already running; focused", exited, no second server |
| 4 | Hotkey conflict | See 1 |
| 5 | Enable/disable monitoring | Enabled through the API: a scan staged 2 commits, nothing accepted, one "imports" notice |
| 6 | Windows notification | Windows accepted the toast (no error, notice marked delivered once, not re-sent after a restart). **Whether it appeared on screen was not observed** |
| 7 | Quiet hours | At 02:02 (inside 22:00–08:00) nothing was delivered; reason "quiet hours" |
| 8 | Clicking a notification opens the project | **Not tested** (needs a person to click) |
| 9 | Clean exit | Forced stop left the DB intact. **Ctrl+C in a real console not tested** (covered by unit tests of `stop()`) |

### Manual checklist (please run once)

1. Start the companion: `python -m statetrace --db demo.db companion`. Read its console: does it say the
   hotkey is registered or taken?
2. Focus another app (e.g. VS Code) and press the hotkey. The compact window should appear in front.
3. Press it again two or three times. Still one window, brought to the front.
4. If Ctrl+Alt+T is taken: pick another in Settings → Desktop companion (e.g. `ctrl+alt+k`), restart, and repeat 2–3.
5. In Settings, tick *Background monitoring*, then *Pause all monitoring*, then resume. The status badges follow.
6. Tick *Windows notifications* and press *Send test notification*. A toast should appear within 30 s.
7. Set quiet hours that include now, then add a milestone due in 30 min with a 1-hour reminder: no toast
   appears, and the dashboard bell still lists it. (*Send test notification* deliberately ignores quiet
   hours, because you asked for it.)
8. Click a milestone or Inbox notification. The right project or Inbox should open in your browser.
9. Close the compact window: the dashboard still works. Press Ctrl+C in the companion console: it says
   it stopped, and the server it hosted stops.
