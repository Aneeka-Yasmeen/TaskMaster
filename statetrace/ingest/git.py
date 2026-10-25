"""Local Git source: reads commit metadata only.

What is read: hash, author date, author name, branch, subject, message body, and a line/file
count (`--shortstat`). What is NOT read: diffs, file contents, untracked files, remotes.
Nothing leaves the machine except the commit message that becomes evidence (which, like any
evidence, is sent to the model when the user accepts it).

WSL2: repositories inside WSL are best read with WSL's own git (`wsl: true` in the config),
which runs `wsl git -C /home/...`. Windows git on \\\\wsl.localhost paths works but is slow and
may need `git config --global --add safe.directory`.
"""

import subprocess

FIELD = "\x1f"
RECORD = "\x1e"
END = "\x1d"
FORMAT = f"{RECORD}%H{FIELD}%h{FIELD}%aI{FIELD}%an{FIELD}%s{FIELD}%b{END}"
MAX_BODY = 1500


class GitError(RuntimeError):
    pass


def _cmd(config):
    base = ["wsl", "git"] if config.get("wsl") else ["git"]
    return base + ["-C", config["path"]]


def _run(config, *args, timeout=30):
    try:
        out = subprocess.run(_cmd(config) + list(args), capture_output=True, timeout=timeout,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise GitError("git was not found" + (" inside WSL" if config.get("wsl") else " on PATH"))
    except subprocess.TimeoutExpired:
        raise GitError(f"git timed out after {timeout} s")
    if out.returncode != 0:
        msg = (out.stderr or out.stdout).strip().splitlines()
        hint = ""
        if any("dubious ownership" in m for m in msg):
            hint = " (git refuses this folder: run `git config --global --add safe.directory <path>` or use WSL git)"
        raise GitError((msg[-1] if msg else f"git exited with {out.returncode}") + hint)
    return out.stdout


def validate(config):
    """Check the folder is a git work tree and resolve the branch. Returns normalized config."""
    if not str(config.get("path") or "").strip():
        raise GitError("Give the repository folder.")
    config = {"path": str(config["path"]).strip(), "wsl": bool(config.get("wsl")),
              "branch": (config.get("branch") or "").strip() or None,
              "max_initial": int(config.get("max_initial") or 30)}
    if _run(config, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise GitError("That folder is not a git work tree.")
    if not config["branch"]:
        config["branch"] = _run(config, "rev-parse", "--abbrev-ref", "HEAD").strip()
    else:
        _run(config, "rev-parse", "--verify", "--quiet", config["branch"] + "^{commit}")
    return config


def parse_log(text, branch):
    items = []
    for rec in text.split(RECORD):
        if not rec.strip():
            continue
        head, _, stat = rec.partition(END)
        parts = head.split(FIELD)
        if len(parts) < 6:
            continue
        full, short, date, author, subject, body = parts[:6]
        body = body.strip()
        stat = " ".join(stat.split())
        text = f"commit {short} on {branch} by {author}: {subject.strip()}"
        if body:
            text += "\n" + (body if len(body) <= MAX_BODY else body[:MAX_BODY] + " …")
        if stat:
            text += f"\n({stat})"
        items.append({
            "external_id": full, "occurred_at": date, "title": subject.strip() or short,
            "text": text, "source": "git_commit", "ref": short,
            "meta": {"branch": branch, "author": author, "stat": stat},
        })
    return items


def scan(config, known):
    """Return new commits (oldest first), skipping ones already known to this source.
    The first scan of a source is limited to the most recent `max_initial` commits."""
    limit = config.get("max_initial", 30) if not known else 200
    text = _run(config, "log", config["branch"], f"--max-count={limit}", "--no-merges",
                f"--format={FORMAT}", "--shortstat")
    items = [i for i in parse_log(text, config["branch"]) if i["external_id"] not in known]
    return list(reversed(items))
