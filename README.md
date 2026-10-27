# TaskMaster

**Pick up any engineering project exactly where you left it.**

Long projects leave their history everywhere: notes, simulation logs, synthesis reports, commits and chat messages.
After a few days away, it's hard to remember what was done, what is blocking you, and what comes next.

TaskMaster keeps all of that evidence in one place for each project and turns it into a clear, up-to-date summary:

- **where you left off** and **what to do next**;
- what is **verified** (backed by a log, test or report) and what is only **reported** by someone;
- what **conflicts**, so you can settle it instead of guessing.

Every statement links back to the evidence it came from, so you can always check why TaskMaster believes something.

## How it works

1. **You add evidence** as you work: paste a note, a log or a report, import a Yosys synthesis report, or pull in Git
   commits.
2. **NVIDIA Nemotron reads it** (through Nebius Token Factory) and suggests how the project's status should change.
3. **TaskMaster checks the suggestion** against clear rules before saving it. For example, only a real log or report can
   mark something as verified, and a chat message can't overrule a test result.
4. **You see the result**: an updated project summary, what changed, and the evidence behind each point.

Nothing is ever deleted, so you can look back at how a project got to where it is.

## What you can do

- See **"Where you left off & what to do next"** at the top of every project.
- Open any piece of evidence or ask **"Why?"** about any statement.
- Ask questions in plain English, such as *"What have I already tried?"*
- Get a **project review** from Nemotron: on track, at risk or blocked, with suggestions.
- Import **Yosys synthesis reports**, compare runs, and approve each proposed change before it's applied.
- Review **Git commits** before they count as evidence.
- Set **milestones** and get reminders. Today's page shows which project needs you first, and why.
- On Windows, open a compact TaskMaster window from any app with **Ctrl+Alt+T**.

## Works with your tools

**Today:** TaskMaster has built-in support for **Yosys** synthesis reports and **Git** commits. Text output from any
other tool, such as a simulator log, a timing or implementation report, or test results, can be pasted in as evidence
with **Add update**. TaskMaster then treats it like any other log or report.

**In the works:** direct integrations with more engineering software, including **CAD**, **ECAD** (PCB and chip
design) and **proprietary EDA tools**. The goal is to read their reports automatically, the way Yosys reports are
read today.

## Get started

You need **Python 3.10 or newer** and a web browser. There's nothing else to install.

```bash
git clone https://github.com/Aneeka-Yasmeen/taskmaster.git
cd taskmaster
python -m statetrace serve
```

Then open **http://127.0.0.1:8765** in your browser.

> On Windows, use `py` instead of `python` if the command isn't found. On macOS or Linux, you may need `python3`.

### Try the sample project (no API key needed)

1. On the start page, click **Load sample project**.
2. The *FFT Accelerator* project opens. It's an example project, marked **Sample data**.
3. At the top, the **Where you left off** card shows the next action and the project's status. Each point is labelled
   **Verified**, **Reported** or **Contested**. Click an evidence chip such as **E16** to read the source.
4. Press **D** to see the full history. Click any event to see exactly what it changed.
5. Open **Synthesis (Yosys)** in the sidebar, import `demo/yosys/mac_v1_stat.rpt` and then `mac_v2_stat.rpt`, and
   click **Compare**.

To stop TaskMaster, press **Ctrl+Q** in the app or **Ctrl+C** in the terminal. Your work is saved automatically in
`statetrace.db` in the same folder.

## Turn on Nemotron

The AI features use NVIDIA Nemotron through Nebius Token Factory.

1. Create an API key at [Nebius Token Factory](https://tokenfactory.nebius.com/).
2. Copy the settings template and add your key:

   ```bash
   copy .env.example .env        # Windows
   cp .env.example .env          # macOS / Linux
   ```

   Open `.env` and set `NEBIUS_API_KEY=` to your key.
3. Check that the key works. You should see a list of available models:

   ```bash
   python -m statetrace models
   ```

4. Restart TaskMaster. The top bar now shows **Nemotron ready**.

You can now add your own updates (**N**), ask questions (**/**), have Nemotron reconstruct where you left off (**C**),
request a project review (**R**), and get explanations of Yosys comparisons.

**More examples:** with a key, this builds five example projects, including a MAC unit with real Yosys reports. It takes
a few minutes:

```bash
python -m statetrace --db demo.db seed
python -m statetrace --db demo.db serve
```

## Everyday use

- **Add an update:** press **N**, paste your note, log or report, and choose where it came from. Logs, test output and
  reports can verify a result; notes and chats are recorded as reported.
- **Keep work separate:** each workspace is its own file, e.g. `python -m statetrace --db my-chip.db serve`.
- **Shortcuts:** press **?** in the app to see them all.
- **Learn more:** the [user guide](docs/GUIDE.md) covers every screen. The [desktop companion guide](docs/COMPANION.md)
  covers the Windows shortcut window and notifications.

## Good to know

- **You stay in control.** Nemotron suggests and TaskMaster checks, but you can always see what changed and why. For
  Yosys reports, you approve each change before it's applied.
- **Nemotron takes a moment.** Each request usually takes a few seconds and can take up to about 30. A timer shows
  progress, and you can keep working meanwhile.
- **Works offline.** Updates are saved immediately and processed once Nebius is reachable again.
- **Platforms:** developed and tested on Windows. The main app uses only standard Python, so it should also run on
  macOS and Linux, though these haven't been tested yet. The desktop companion is Windows-only.

## Privacy

- Your API key stays in `.env` on your computer and is never sent to the browser.
- TaskMaster runs locally (`127.0.0.1`), and your projects stay in local database files.
- It only reads what you give it, or Git repositories you choose to connect.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
