# TaskMaster

**Where did I leave my project?** TaskMaster keeps an evidence log for each engineering project (notes, sim logs,
Yosys reports, commits) and reconstructs what is currently true: the blocker, the next step, what is verified, what
is only reported, and what conflicts. Every statement links to the evidence behind it.

It uses **NVIDIA Nemotron** through **Nebius Token Factory** to propose state changes and to explain them. A
deterministic validator decides what is applied, so the model can't mark anything as verified on its own.

## Features

- **"Where you left off & what to do next"** on every project: the next action, blockers, verified facts,
  uncertain items and open contradictions, each with its evidence.
- **Verified vs. reported:** only artifacts (logs, tests, reports) can verify a claim. Notes and chats stay "reported".
  Conflicting evidence is flagged instead of silently overwritten.
- **History:** every update shows exactly what it changed; earlier states can be viewed at any time.
- **Yosys synthesis reports:** import `stat` reports, compare runs, and review a proposed state change before it is applied.
- **Git commits, milestones and reminders**, plus a Windows desktop companion (optional).
- **Works without an API key** for exploring a sample project; Nemotron features need a Nebius key.

## Requirements

- Python 3.10 or newer (tested on Windows with 3.10, 3.12 and 3.13). No packages to install.
- A web browser.
- Optional: a Nebius Token Factory API key for live Nemotron features; `git` for importing commits; Windows for the
  desktop companion.

## Quick start (no API key needed)

```bash
git clone https://github.com/Aneeka-Yasmeen/taskmaster.git
cd taskmaster
python -m statetrace serve
```

Open **http://127.0.0.1:8765**. (On Windows, use `py` if `python` isn't found; on macOS/Linux you may need `python3`.)

Your data is stored in `statetrace.db` in the same folder. To stop TaskMaster, press **Ctrl+C** in that terminal, or
run `python -m statetrace stop` from another terminal.

### Explore the sample project

1. On the start page, click **Load sample project**.
2. *FFT Accelerator* opens. It is synthetic data, marked **Sample data**, built from recorded operations (not a live
   model run).
3. Read the **Where you left off** card. Each item has a label (**Verified**, **Reported**, **Contested**) and
   evidence chips such as **E16**. Click a chip to read the evidence, or **Why?** to see why a claim is believed.
4. Press **D** for the detailed view: the full state, history, decisions and questions. Click any event to see what it
   changed.
5. Open **Synthesis (Yosys)** and import `demo/yosys/mac_v1_stat.rpt`, then `demo/yosys/mac_v2_stat.rpt`, and
   **Compare** them. Without a key, reports are saved as evidence and compared, but the project state isn't updated.

## Live Nemotron features (Nebius Token Factory)

1. Get an API key from [Nebius Token Factory](https://tokenfactory.nebius.com/).
2. Create your settings file and put the key in it:

   ```bash
   copy .env.example .env        # Windows
   cp .env.example .env          # macOS/Linux
   ```

   Edit `.env` and set `NEBIUS_API_KEY=...`. The model defaults to `nvidia/nemotron-3-super-120b-a12b`.
3. Check the key (this lists the models your key can use):

   ```bash
   python -m statetrace models
   ```

4. Restart `python -m statetrace serve`. The top bar shows **Nemotron ready**.

With a key you can add updates (**N**), ask questions in plain English (**/**), reconstruct the catch-up with Nemotron
(**C**), get a project review (**R**), apply or discard proposed changes from imported Yosys reports, and have
synthesis comparisons explained.

Optional: build five sample projects (including a MAC unit with real Yosys reports) through the live model. This makes
about 50 Nemotron calls and takes a few minutes:

```bash
python -m statetrace --db demo.db seed
python -m statetrace --db demo.db serve
```

## Using TaskMaster

- **Add update** (**N**): paste a note, log or report and choose its source. An artifact source (sim log, test
  output, synthesis report…) can verify a claim; a note or chat can't.
- **Keep projects separate** by workspace: `python -m statetrace --db my-work.db serve`.
- **Import Git commits** from the project's *Inbox*. Commits are staged, and nothing changes until you accept them.
- Press **?** in the app for all keyboard shortcuts.
- Full guide: [docs/GUIDE.md](docs/GUIDE.md). Windows desktop companion (hotkey popup, optional notifications):
  [docs/COMPANION.md](docs/COMPANION.md).
- Run the tests: `python -m unittest discover -s tests`

## Limitations

- Nemotron calls take about 4–30 seconds. Without network access, updates are saved and applied when Nebius is reachable.
- The model can still misjudge what an update means. Its proposals are validated, cited and visible in history, but not
  always right.
- Review before commit covers Yosys imports in the web app; other updates are applied right after validation.
- The keyless sample is a single project. The desktop companion is Windows-only. Tested on Windows only.

## Security

- Your API key stays in `.env` (git-ignored) and is read only by the local server. It is never sent to the browser.
- The server listens on `127.0.0.1` only and refuses requests from other websites.
- Workspace databases (`*.db`) are git-ignored and stay on your machine.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
