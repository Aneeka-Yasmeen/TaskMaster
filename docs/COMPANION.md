# TaskMaster desktop companion (Windows)

The companion is an optional Windows helper. It lets you:

- open a compact TaskMaster window from any app with a keyboard shortcut (**Ctrl+Alt+T** by default);
- optionally watch your connected Git repositories for new commits;
- optionally show Windows notifications for deadlines, stale projects and commits to review.

**Background monitoring and notifications are off until you turn them on.** The companion needs no extra software:
it uses Python's standard library and Microsoft Edge, which is included with Windows.

---

## Start and stop

Run it with Windows Python (not inside WSL), from the TaskMaster folder:

```bat
python -m statetrace companion
```

To use a specific workspace, put `--db` before `companion`:

```bat
python -m statetrace --db asic.db companion
```

You can also double-click `scripts\TaskMaster-Companion.cmd`, which uses `demo.db`. For another workspace, run
`set TASKMASTER_DB=asic.db` and then `scripts\TaskMaster-Companion.cmd` in the same Command Prompt window.

The companion starts TaskMaster if it isn't already running, or connects to the copy that is. Starting it a second
time just brings its window to the front.

| Option | Effect |
|---|---|
| `--port 8765` | Port of the TaskMaster server to use or start |
| `--hotkey ctrl+alt+k` | Use a different shortcut for this run |
| `--no-hotkey` | Don't register a shortcut |
| `--no-popup` | Don't open the compact window at start |

**To stop** TaskMaster and the companion together, use **Ctrl+Q**, **Quit** in the compact window,
**Settings → Quit TaskMaster**, `python -m statetrace stop`, or Ctrl+C in the window that started it.
Closing the compact window does not stop anything. Nothing starts automatically with Windows.

---

## The compact window

Press the shortcut from any app to see the active project's:

- Nemotron's latest verdict and top suggestion;
- blocker and next step;
- latest change and next deadline.

It also has quick buttons: *Where did I leave off?*, *What's blocking me?*, *What should I do next?*, *Add update*,
*Review Git imports*, *Open full dashboard* and *Quit*.

---

## Changing the shortcut

- In **Settings → Desktop companion**, change *Global hotkey*, then restart the companion. For a single run, use
  `--hotkey`.
- A shortcut must include Ctrl, Alt or Win, plus a letter, digit, `space` or `f1`–`f12`.
- If another program already uses the shortcut, the companion says so in its window and in Settings, and doesn't
  register it. Choose a different one.
- To turn it off, untick *Global hotkey* or start with `--no-hotkey`.

---

## Background monitoring and notifications

**Background monitoring** follows **Settings → Assistant → Autonomy**:

- **Off** (default): nothing runs in the background.
- **Selected projects** or **All projects**: while the companion runs, it checks those projects' Git repositories
  every 15 minutes (adjustable from 5 minutes to 24 hours). New commits are **only added to the Inbox for review**,
  never accepted automatically. It also creates deadline and stale-project reminders.

**Windows notifications** are turned on in **Settings → Desktop companion** and need background monitoring. You get
one notification per issue:

- a deadline reminder is due, or a milestone is overdue;
- a project has gone stale;
- new commits are waiting for review.

Notifications respect quiet hours, never include commit messages or project details, and open the relevant page
when clicked. They appear as coming from **Windows PowerShell**, which is how Windows shows apps without an
installer. Use **Send test notification** in Settings to check they work.

**To turn everything off**, set Autonomy to **Off**, untick *Windows notifications*, or click **Pause all**. Or just
don't run the companion: when it isn't running, nothing happens in the background.

---

## Privacy

- Only Git repositories you add are read: commit hash, date, author, branch, message and line counts. Never file
  contents.
- No keystroke logging (the shortcut is a single registered key combination), no screen capture and no folder
  scanning.
- Your API key is never passed to the companion, the browser or notifications.
- Everything runs on your computer (`127.0.0.1`).

---

## WSL users

Run the companion on Windows. Repositories inside WSL can still be added: in the project's Inbox, tick
*Repository lives inside WSL2*. If you run `python -m statetrace serve` inside WSL instead, start the companion on
Windows with the same `--port` and it will connect to it.

---

## Known limitations

- Windows only.
- Tested on Windows 11 with Python 3.13. The shortcut, window, single-instance behaviour, Git staging and quiet
  hours were checked. Clicking a notification to open a page has not been tested.
- Ctrl+C does not stop it from Git Bash; use **Quit** or `python -m statetrace stop`.
