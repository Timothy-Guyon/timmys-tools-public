#!/usr/bin/env python3
"""Ring a scheduled task when someone opens an issue or a pull request.

Run by the GitHub Action ring.yml (copied into the public mirror's
.github/workflows/), whoever opened the issue, the repository's owner included:
    python3 ring.py [--dry-run]
It reads the event GitHub saved at $GITHUB_EVENT_PATH and POSTs one line to
the task's API trigger: what was opened, its number, who opened it and its
link. Nothing the submitter wrote goes in the ring; the task reads the
submission itself, as data (see TASK.md).

Two Actions secrets on the repository name the task:
    SUBMISSIONS_URL    the task's fire URL, or just its trig_... id
    SUBMISSIONS_TOKEN  the task's API key (shown once when the key is made)
No secrets, no ring: a copy or fork of the repository rings nobody.
Knows no harness beyond one HTTP POST; swap ring() to ring something else.
"""
import json, os, re, sys, urllib.error, urllib.request

FIRE = "https://api.anthropic.com/v1/claude_code/routines/%s/fire"


def message(event, repo):
    """The ring's one line, or None when the event is not a new submission."""
    item = event.get("pull_request") or event.get("issue")
    if not item or event.get("action") != "opened":
        return None
    kind = "pull request" if "pull_request" in event else "issue"
    login = (item.get("user") or {}).get("login", "")
    login = login if re.fullmatch(r"[A-Za-z0-9-]+(\[bot\])?", login) else "?"
    return "New %s #%d on %s by %s: https://github.com/%s/%s/%d. Read it there." % (
        kind, int(item["number"]), repo, login, repo, "pull" if kind == "pull request" else "issues", int(item["number"]))


def ring(url, token, text):
    """Fire the task with the line. On a 403, print why the API refused, then
    fire once more without the text: the task then finds the new submission
    itself (TASK.md). If that also fails, the key or URL is wrong."""
    try:
        fire(url, token, {"text": text})
    except urllib.error.HTTPError as e:
        if e.code != 403:
            raise
        print("ring: 403 with text: %s; ringing without it" % why(e))
        fire(url, token, {})


def why(e):
    """The API's own reason for an HTTP error, cut short; it holds no secret."""
    try:
        return e.read(400).decode("utf-8", "replace").strip() or str(e)
    except Exception:
        return str(e)


def fire(url, token, body):
    if url.startswith("trig_"):
        url = FIRE % url
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": "Bearer " + token,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "experimental-cc-routine-2026-04-01",
        "Content-Type": "application/json",
    })
    urllib.request.urlopen(req, timeout=10).read()


def main():
    dry = "--dry-run" in sys.argv[1:]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    text = message(event, os.environ.get("GITHUB_REPOSITORY", "?"))
    if text is None:
        print("ring: not a new issue or pull request; nothing to ring")
        return 0
    if dry:
        print(text)
        return 0
    url, token = os.environ.get("SUBMISSIONS_URL", "").strip(), os.environ.get("SUBMISSIONS_TOKEN", "").strip()
    if not (url and token):
        print("ring: SUBMISSIONS_URL or SUBMISSIONS_TOKEN not set; nobody rung")
        return 0
    try:
        ring(url, token, text)
    except Exception as e:  # never retried: a task can't tell a repeat ring apart
        detail = why(e) if isinstance(e, urllib.error.HTTPError) else e
        print("ring: %s: %s" % (e, detail), file=sys.stderr)
        return 1
    print("ring: " + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
