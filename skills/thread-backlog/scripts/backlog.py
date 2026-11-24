#!/usr/bin/env python3
"""The record behind the thread-backlog routine: a project's threads, the tasks
only the client can do, and the watches threads wait on.

One file per project, `<project id>.jsonl`. Lines are only ever added: each is
one dated change to one thread, task or watch. Nothing else is stored. A
thread's state, what it waits on, its snooze count, the weeks a task has sat
off the client's list, how often they take each kind of recommendation and the
weekly numbers are all worked out from the lines every time this runs.

The client is the person the threads work for: the one who decides, approves
and does what only a person can.

The record lives in backlog/ of the mailbox repo (Timothy-Guyon/claude-shared)
beside or above the current folder or this script, or at $THREAD_BACKLOG_DIR,
else in ~/.thread-backlog/, a record for this place only. Push the mailbox's
backlog/ straight to its main. The same folder holds LOG.md, the notes from
the client that teach the routine (see "How the routine learns" in SKILL.md).

Every command takes --project ID (or $THREAD_BACKLOG_PROJECT): the project's
fixed id, never its display name.

  sweep [FILE]                        weekly: compare the full thread list (JSON) with the record, print the worksheet
  daily [FILE]                        check watches, snoozes that end, tasks due soon or past their date;
                                      with the thread list, also threads that show the wrong state
  report                              the "needs you" list and the weekly numbers, ready to post
  show [ID]                           every open thread with what it waits on, or one object in full
  review                              weekly, after the sweep: every open thread, oldest first, to ask of each whether it is still worth doing

  thread add ID --title T [--opened DATE]
  thread ID [--next STEP] [--snooze DATE] [--resolve SUMMARY] [--reopen]
            [--standing WHAT_WAKES_IT | --not-standing]   a thread kept open on purpose, such as a mail thread

  task add --thread ID --kind decide|approve|act --title T
           [--recommend R --ask-kind K] [--due DATE] [--pointless-after DATE] [--todo LINK]
  task answer T --took yes|no [--choice C]   The client answered a decide or approve task
  task done T | task drop T --why W | task todo T LINK | task offered-drop T
  rank T T T ...                      order the open decide and approve tasks; the first 7 are the client's list
  stop-asking KIND                    The client said this kind of ask stops coming to them

  watch add --thread ID --check date:DATE|url:URL|mail:QUERY|other:TEXT --expires DATE
  watch match W [--what TEXT] | watch cancel W

  note --kind correct|like --words "the client's words" --what "what the routine did"
  open                                notes not yet counted toward a rule
  used 3,7,9 --rule N                 mark notes as counted toward rule N in SKILL.md (or --rule struck)
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
import urllib.request

LIST_CAP = 7               # items on the client's "needs you" list
OFF_LIST_DAYS = 21         # a task off the list this long is put to them once: drop it, or snooze a month
MAX_SNOOZES = 2            # a third snooze resolves the thread instead
IDLE_DAYS = 21             # a thread untouched this long is shown in the sweep
DUE_SOON_DAYS = 3          # tasks due this soon are raised by the daily run
STOP_ASKING_RATE = 0.95    # kinds of asks they take the recommendation on this often...
STOP_ASKING_MIN = 10       # ...over at least this many answers are put to them: stop asking?
KINDS = ("decide", "approve", "act")
REVIEW_ASK = "drop a thread nobody would start today"   # the ask kind of a drop from the weekly review
# What a thread shows in the app, from the state words harnesses use in a thread list.
SHOWN = {"you": ("need_input", "blocked", "waiting", "waiting_on_you", "needs_you", "you"),
         "working": ("working", "running", "in_progress"),
         "done": ("done", "completed", "review_ready", "idle", "finished"),
         "stopped": ("stopped", "failed", "error", "errored")}
CHECKS = ("date", "url", "mail", "other")


# ---------------------------------------------------------------- where it lives

def find_dir():
    """Return (folder, shared): shared is False for a record kept in this place only."""
    env = os.environ.get("THREAD_BACKLOG_DIR") or os.environ.get("TIMMY_BACKLOG_DIR")  # old name still read
    if env:
        return pathlib.Path(env).expanduser(), True
    for start in (pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            for name in ("claude-shared", "."):
                if (d / name / "inbox").is_dir():
                    return d / name / "backlog", True
    old = pathlib.Path.home() / ".timmy-backlog"  # the folder's old name, kept if a record is already there
    return (old if old.is_dir() else pathlib.Path.home() / ".thread-backlog"), False


DIR, SHARED = find_dir()
TODAY = datetime.date.today()


def refuse(msg):
    sys.exit("refused: " + msg)


def line(value, name):
    if value is None or not value.strip():
        refuse("--%s is empty" % name)
    if "\n" in value:
        refuse("--%s must be one line" % name)
    return value.strip()


def day(value, name="date"):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        refuse("--%s must be YYYY-MM-DD" % name)


def d(s):
    return datetime.date.fromisoformat(s[:10])


# ---------------------------------------------------------------- the record

class Record:
    def __init__(self, project):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", project or ""):
            refuse("--project is the project's fixed id (letters, digits, - _ .), not its name")
        self.path = DIR / ("%s.jsonl" % project)
        self.lines = []
        if self.path.exists():
            for n, raw in enumerate(self.path.read_text().splitlines(), 1):
                if raw.strip():
                    try:
                        self.lines.append(json.loads(raw))
                    except ValueError:
                        sys.exit("%s line %d is not JSON; fix it by hand, the record is only ever added to" % (self.path, n))

    def add(self, op, **fields):
        entry = {"on": TODAY.isoformat(), "op": op}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        self.lines.append(entry)
        return entry

    def state(self, until=None):
        return State([e for e in self.lines if until is None or d(e["on"]) <= until])


class State:
    """Everything worked out from the lines, as of the last line given."""

    def __init__(self, lines):
        self.threads, self.tasks, self.watches = {}, {}, {}
        self.ranks, self.stopped, self.resolves = [], {}, []
        for e in lines:
            getattr(self, "_" + e["op"].replace("-", "_"))(e)

    # threads
    def _thread_seen(self, e):
        t = self.threads.setdefault(e["id"], {"id": e["id"], "status": "active", "snoozes": 0,
                                              "next": None, "opened": e.get("opened", e["on"]),
                                              "first_seen": e["on"]})
        for k in ("title", "opened", "last_activity", "shows"):
            if k in e:
                t[k] = e[k]
        t["seen"] = e["on"]

    def _thread_next(self, e):
        self.threads[e["id"]]["next"] = e["next"]

    def _thread_standing(self, e):
        self.threads[e["id"]]["standing"] = e.get("standing") or None

    def _thread_snooze(self, e):
        t = self.threads[e["id"]]
        t.update(status="snoozed", until=e["until"], snoozes=t["snoozes"] + 1)

    def _thread_wake(self, e):
        t = self.threads[e["id"]]
        t["status"], t["until"] = "active", None

    def _thread_resolve(self, e):
        t = self.threads[e["id"]]
        t.update(status="resolved", summary=e["summary"], resolved_on=e["on"])
        self.resolves.append(e)

    def _thread_reopen(self, e):
        t = self.threads[e["id"]]
        t.update(status="active", until=None, snoozes=0)

    # tasks
    def _task_add(self, e):
        t = dict(e, status="open", created=e["on"])
        t.pop("op")
        t.setdefault("thread", None)  # an act can belong to no thread
        self.tasks[e["id"]] = t

    def _task_answer(self, e):
        self.tasks[e["id"]].update(status="answered", took=e["took"], choice=e.get("choice"), closed=e["on"])

    def _task_done(self, e):
        self.tasks[e["id"]].update(status="done", closed=e["on"])

    def _task_drop(self, e):
        self.tasks[e["id"]].update(status="dropped", why=e["why"], closed=e["on"])

    def _task_todo(self, e):
        self.tasks[e["id"]]["todo"] = e["todo"]

    def _task_offered_drop(self, e):
        self.tasks[e["id"]]["offered_drop"] = e["on"]

    def _rank(self, e):
        self.ranks.append(e)

    def _stop_asking(self, e):
        self.stopped[e["kind"]] = e["on"]

    # watches
    def _watch_add(self, e):
        w = dict(e, status="live", created=e["on"])
        w.pop("op")
        self.watches[e["id"]] = w

    def _watch_baseline(self, e):
        self.watches[e["id"]]["baseline"] = e["hash"]

    def _watch_match(self, e):
        self.watches[e["id"]].update(status="matched", what=e.get("what"), closed=e["on"])

    def _watch_expire(self, e):
        self.watches[e["id"]].update(status="expired", closed=e["on"])

    def _watch_cancel(self, e):
        self.watches[e["id"]].update(status="cancelled", closed=e["on"])

    # derived
    def open_tasks(self, thread=None):
        return [t for t in self.tasks.values() if t["status"] == "open" and (thread is None or t["thread"] == thread)]

    def live_watches(self, thread=None):
        return [w for w in self.watches.values() if w["status"] == "live" and (thread is None or w["thread"] == thread)]

    def ranked(self):
        """Open decide and approve tasks in order: the last rank first, then any added since, oldest first."""
        asks = [t for t in self.open_tasks() if t["kind"] != "act"
                and self.threads.get(t["thread"], {}).get("status") != "resolved"]
        order = self.ranks[-1]["order"] if self.ranks else []
        pos = {tid: i for i, tid in enumerate(order)}
        return sorted(asks, key=lambda t: (pos.get(t["id"], len(order)), t["created"], t["id"]))

    def on_list(self):
        return {t["id"] for t in self.ranked()[:LIST_CAP]}

    def last_on_list(self, tid):
        for r in reversed(self.ranks):
            if tid in r["order"][:LIST_CAP]:
                return r["on"]
        return None

    def waits_on(self, tid):
        """What a thread waits on, worked out from its tasks and watches: (kind, words)."""
        t = self.threads[tid]
        if t["status"] == "resolved":
            return "resolved", t.get("summary", "")
        if t["status"] == "snoozed":
            return "snoozed", "until %s" % t["until"]
        mine = self.open_tasks(tid)
        here = [x for x in mine if not x.get("todo")]
        if here:
            return "client", "; ".join("%s: %s" % (x["kind"], x["title"]) for x in here)
        watches = self.live_watches(tid)
        if watches:
            return "event", "; ".join(w["check"] for w in watches)
        if mine:
            return "todo", "; ".join(x["title"] for x in mine)
        if t.get("next"):
            return "claude", t["next"]
        if t.get("standing"):
            return "standing", t["standing"]
        return "nothing", ""

    def asks_by_kind(self):
        out = {}
        for t in self.tasks.values():
            if t["status"] == "answered" and t.get("ask_kind"):
                took, total = out.get(t["ask_kind"], (0, 0))
                out[t["ask_kind"]] = (took + (t["took"] == "yes"), total + 1)
        return out

    def numbers(self, on):
        week = on - datetime.timedelta(days=7)
        opened = [t for t in self.threads.values() if week < d(t["opened"]) <= on]
        closed = [e for e in self.resolves if week < d(e["on"]) <= on]
        live = [t for t in self.threads.values() if t["status"] != "resolved"
                and self.waits_on(t["id"])[0] != "standing"]  # kept open on purpose: not backlog
        waiting = [t for t in live if self.waits_on(t["id"])[0] == "client"]
        ages = sorted((on - d(t["opened"])).days for t in live)
        oldest = max(live, key=lambda t: (on - d(t["opened"])).days, default=None)
        return {"opened": len(opened), "closed": len(closed), "open": len(live), "waiting": len(waiting),
                "median": statistics.median(ages) if ages else 0, "oldest": oldest,
                "oldest_days": (on - d(oldest["opened"])).days if oldest else 0}


def next_id(state, prefix, pool):
    nums = [int(k[1:]) for k in pool if k[1:].isdigit()]
    return "%s%d" % (prefix, max(nums, default=0) + 1)


def need_thread(s, tid):
    if tid not in s.threads:
        refuse("no thread %s in the record; run a sweep or 'thread add' first" % tid)
    return s.threads[tid]


def need_task(s, tid, status="open"):
    if tid not in s.tasks:
        refuse("no task %s" % tid)
    t = s.tasks[tid]
    if status and t["status"] != status:
        refuse("task %s is %s, not %s" % (tid, t["status"], status))
    return t


def title(s, tid):
    if not tid:
        return "no thread"
    t = s.threads.get(tid)
    return "%s (%s)" % (t.get("title", "untitled"), tid) if t else tid


# ---------------------------------------------------------------- threads

def cmd_thread(a, r):
    s = r.state()
    if a.id == "add":
        if not a.rest:
            refuse("thread add needs the thread's id")
        tid = a.rest[0]
        if tid in s.threads:
            refuse("thread %s is already in the record" % tid)
        r.add("thread-seen", id=tid, title=line(a.title, "title"),
              opened=day(a.opened, "opened") if a.opened else TODAY.isoformat())
        print("added thread %s" % tid)
        return
    t = need_thread(s, a.id)
    done = False
    if a.reopen:
        if t["status"] != "resolved":
            refuse("thread %s isn't resolved" % a.id)
        r.add("thread-reopen", id=a.id)
        print("reopened %s" % title(s, a.id))
        done = True
    if a.next:
        r.add("thread-next", id=a.id, next=line(a.next, "next"))
        print("next step for %s: %s" % (title(s, a.id), a.next.strip()))
        done = True
    if a.snooze:
        until = day(a.snooze, "snooze")
        if d(until) <= TODAY:
            refuse("--snooze is a date after today")
        if t["status"] == "resolved":
            refuse("thread %s is resolved; reopen it first" % a.id)
        if t["snoozes"] >= MAX_SNOOZES:
            refuse("%s has been snoozed %d times; a third snooze resolves it. Resolve it with a one-line summary "
                   "(it can be reopened any time)" % (title(s, a.id), t["snoozes"]))
        r.add("thread-snooze", id=a.id, until=until)
        print("snoozed %s until %s (snooze %d of %d). When it ends it needs a decision: the client's list, "
              "Claude's to move, or resolved." % (title(s, a.id), until, t["snoozes"] + 1, MAX_SNOOZES))
        done = True
    if a.resolve:
        if t["status"] == "resolved":
            refuse("thread %s is already resolved" % a.id)
        open_here = [x for x in s.open_tasks(a.id) if not x.get("todo")]
        if open_here:
            refuse("thread %s still has open tasks for the client (%s): answer, finish, drop or hand them to the "
                   "to-do list first" % (a.id, ", ".join(x["id"] for x in open_here)))
        for w in s.live_watches(a.id):
            r.add("watch-cancel", id=w["id"])
        r.add("thread-resolve", id=a.id, summary=line(a.resolve, "resolve"))
        print("resolved %s: %s" % (title(s, a.id), a.resolve.strip()))
        done = True
    if a.standing or a.not_standing:
        if a.standing and a.not_standing:
            refuse("--standing or --not-standing, not both")
        r.add("thread-standing", id=a.id, standing=line(a.standing, "standing") if a.standing else "")
        print(("%s is a standing thread, kept open on purpose: %s" % (title(s, a.id), a.standing.strip()))
              if a.standing else "%s is no longer a standing thread" % title(s, a.id))
        done = True
    if not done:
        refuse("say what changed: --next, --snooze, --resolve, --reopen or --standing")


# ---------------------------------------------------------------- tasks

def cmd_task(a, r):
    s = r.state()
    if a.action == "add":
        thread = a.thread
        if thread:
            if thread not in s.threads:
                refuse("no thread %s in the record: add it first ('thread add %s --title ...')" % (thread, thread))
            if s.threads[thread]["status"] == "resolved":
                refuse("thread %s is resolved. An ask the client still owes needs an open thread: reopen this one "
                       "('thread %s --reopen'), or start a thread for the ask" % (thread, thread))
        fields = {"thread": thread, "kind": a.kind, "title": line(a.title, "title")}
        if a.kind in ("decide", "approve"):
            if not thread:
                refuse("decide and approve tasks are asked in their thread, so this needs --thread. If no open "
                       "thread holds it, reopen the thread it came from or start one for it")
            fields["recommend"] = line(a.recommend, "recommend")
            fields["ask_kind"] = line(a.ask_kind, "ask-kind").lower()
            if fields["ask_kind"] in s.stopped:
                refuse("The client said on %s to stop asking about '%s': go ahead, and report it in the next report"
                       % (s.stopped[fields["ask_kind"]], fields["ask_kind"]))
        elif a.recommend or a.ask_kind:
            refuse("--recommend and --ask-kind belong to decide and approve tasks")
        if a.todo and a.kind != "act":
            refuse("only an act task goes on the to-do list; a decision is asked in its thread")
        for name in ("due", "pointless_after"):
            v = getattr(a, name)
            if v:
                fields[name] = day(v, name.replace("_", "-"))
        if a.todo:
            fields["todo"] = line(a.todo, "todo")
        tid = next_id(s, "t", s.tasks)
        r.add("task-add", id=tid, **fields)
        print("added task %s (%s): %s" % (tid, a.kind, fields["title"]))
        if a.kind == "act" and not a.todo:
            print("An act is done outside Claude: put it on the client's to-do list if this project can reach one "
                  "(by mail if need be), then 'task todo %s LINK'." % tid)
        return
    tid = a.task
    if a.action == "answer":
        t = need_task(s, tid)
        if t["kind"] == "act":
            refuse("task %s is an act; use 'task done'" % tid)
        r.add("task-answer", id=tid, took=a.took, choice=line(a.choice, "choice") if a.choice else None)
        print("recorded the client's answer to %s (took the recommendation: %s)" % (tid, a.took))
    elif a.action == "done":
        need_task(s, tid)
        r.add("task-done", id=tid)
        print("task %s done" % tid)
    elif a.action == "drop":
        need_task(s, tid)
        r.add("task-drop", id=tid, why=line(a.why, "why"))
        print("dropped task %s" % tid)
    elif a.action == "todo":
        t = need_task(s, tid)
        if t["kind"] != "act":
            refuse("only an act task goes on the to-do list; a decision is asked in its thread")
        r.add("task-todo", id=tid, todo=line(a.link, "link"))
        print("task %s is on the to-do list: %s" % (tid, a.link))
        if t.get("thread"):
            print("If it was the thread's only step, resolve the thread with a summary that links the to-do.")
    elif a.action == "offered-drop":
        t = need_task(s, tid)
        if t.get("offered_drop"):
            refuse("The client was already asked about %s on %s; they are asked once" % (tid, t["offered_drop"]))
        r.add("task-offered-drop", id=tid)
        print("recorded: the client was asked to drop %s or snooze it a month" % tid)


def cmd_rank(a, r):
    s = r.state()
    asks = {t["id"] for t in s.open_tasks() if t["kind"] != "act"}
    unknown = [x for x in a.order if x not in asks]
    if unknown:
        refuse("not open decide or approve tasks: %s" % ", ".join(unknown))
    if len(set(a.order)) != len(a.order):
        refuse("a task appears twice")
    r.add("rank", order=a.order)
    rest = sorted(asks - set(a.order))
    print("ranked. The client's list: %s" % ", ".join(a.order[:LIST_CAP]))
    queue = a.order[LIST_CAP:] + rest
    if queue:
        print("queue: %s" % ", ".join(queue))


def cmd_stop_asking(a, r):
    kind = line(a.kind, "kind").lower()
    s = r.state()
    if kind in s.stopped:
        refuse("already stopped on %s" % s.stopped[kind])
    r.add("stop-asking", kind=kind)
    print("'%s' asks stop coming to the client. Go ahead on them and report them in the weekly report." % kind)


# ---------------------------------------------------------------- watches

def cmd_watch(a, r):
    s = r.state()
    if a.action == "add":
        need_thread(s, a.thread)
        kind, _, value = (a.check or "").partition(":")
        if kind not in CHECKS or not value.strip():
            refuse("--check is date:YYYY-MM-DD, url:URL, mail:QUERY or other:TEXT")
        if kind == "date":
            value = day(value, "check date")
        expires = day(a.expires, "expires")
        if d(expires) <= TODAY:
            refuse("--expires is a date after today")
        wid = next_id(s, "w", s.watches)
        r.add("watch-add", id=wid, thread=a.thread, check="%s:%s" % (kind, line(value, "check")), expires=expires)
        print("watch %s for %s, until %s" % (wid, title(s, a.thread), expires))
        return
    if a.id not in s.watches or s.watches[a.id]["status"] != "live":
        refuse("no live watch %s" % a.id)
    if a.action == "match":
        r.add("watch-match", id=a.id, what=line(a.what, "what") if a.what else None)
        print("watch %s came true. Wake its thread: %s" % (a.id, title(s, s.watches[a.id]["thread"])))
    elif a.action == "cancel":
        r.add("watch-cancel", id=a.id)
        print("cancelled watch %s" % a.id)


def page_hash(url):
    req = urllib.request.Request(url, headers={"User-Agent": "thread-backlog-watch/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return hashlib.sha256(resp.read()).hexdigest()


# ---------------------------------------------------------------- the runs

def cmd_daily(a, r):
    out = []
    if a.file:
        new, still_open = see(r, read_threads(a.file))
        s = r.state()
        if new:
            out.append("New since the last run: give each a next step, a task for the client, or a watch:")
            out += ["- " + title(s, tid) for tid in new]
        if still_open:
            out.append("Resolved in the record but still open in the app: resolve each there, or reopen it here:")
            out += ["- " + title(s, tid) for tid in still_open]
        wrong = wrong_shown(s)
        if wrong:
            out.append("Showing the wrong state: tell each thread, and it fixes what it shows itself:")
            out += ["- " + row for row in wrong]
    s = r.state()
    wake, by_hand, expired, trouble = [], [], [], []
    for w in sorted(s.live_watches(), key=lambda w: w["id"]):
        kind, _, value = w["check"].partition(":")
        if TODAY > d(w["expires"]):
            r.add("watch-expire", id=w["id"])
            expired.append(w)
            continue
        if kind == "date":
            if TODAY >= d(value):
                r.add("watch-match", id=w["id"], what="the date came")
                wake.append((w, "the date %s came" % value))
        elif kind == "url":
            try:
                h = page_hash(value)
            except Exception as err:  # a page that can't be read is reported, never fatal
                trouble.append((w, str(err)[:120]))
                continue
            if "baseline" not in w:
                r.add("watch-baseline", id=w["id"], hash=h)
            elif h != w["baseline"]:
                r.add("watch-match", id=w["id"], what="the page changed")
                wake.append((w, "the page changed: %s" % value))
        else:
            by_hand.append(w)
    s = r.state()
    snoozes = [t for t in s.threads.values() if t["status"] == "snoozed" and d(t["until"]) <= TODAY]
    for t in snoozes:
        r.add("thread-wake", id=t["id"])
    due = [t for t in s.open_tasks() if t.get("due") and d(t["due"]) <= TODAY + datetime.timedelta(days=DUE_SOON_DAYS)
           and not t.get("todo")]
    pointless = [t for t in s.open_tasks() if t.get("pointless_after") and d(t["pointless_after"]) < TODAY]

    if wake:
        out.append("Wake these threads now (a watch came true):")
        out += ["- %s: %s (watch %s)" % (title(s, w["thread"]), why, w["id"]) for w, why in wake]
    if by_hand:
        out.append("Check these by hand in this run, then 'watch match ID' for any that came true:")
        out += ["- %s %s, for %s" % (w["id"], w["check"], title(s, w["thread"])) for w in by_hand]
    if expired:
        out.append("Gave up waiting (tell each thread once; it decides: chase, wait again or drop):")
        out += ["- %s %s, for %s" % (w["id"], w["check"], title(s, w["thread"])) for w in expired]
    if trouble:
        out.append("Couldn't check (try again tomorrow; tell the thread if it keeps failing):")
        out += ["- %s %s: %s" % (w["id"], w["check"], err) for w, err in trouble]
    if snoozes:
        out.append("Snoozes that ended, each needs a decision now (the client's list, Claude's to move, or resolved):")
        out += ["- %s, snoozed %d time(s)" % (title(s, t["id"]), t["snoozes"]) for t in snoozes]
    if due:
        out.append("Due within %d days, raise with the client today:" % DUE_SOON_DAYS)
        out += ["- %s %s, due %s, %s" % (t["id"], t["title"], t["due"], title(s, t.get("thread"))) for t in due]
    if pointless:
        out.append("Past their 'pointless after' date, drop them ('task drop ID --why'):")
        out += ["- %s %s (pointless after %s)" % (t["id"], t["title"], t["pointless_after"]) for t in pointless]
    print("\n".join(out) if out else "Nothing to do today.")


def read_threads(path):
    raw = sys.stdin.read() if path in (None, "-") else pathlib.Path(path).read_text()
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("threads") or data.get("sessions") or []
    out = []
    for item in data:
        tid = item.get("id") or item.get("thread_id")
        if not tid:
            refuse("every thread in the list needs an id (id or thread_id)")
        out.append({
            "id": tid,
            "title": (item.get("title") or "").strip() or None,
            "opened": (item.get("opened") or item.get("created_at") or "")[:10] or None,
            "last_activity": (item.get("last_activity") or item.get("last_activity_at") or "")[:10] or None,
            "resolved": bool(item.get("resolved")) or item.get("state") in ("resolved",),
            "shows": shown_state(item),
            "resolved_on": (item.get("resolved_on") or item.get("resolved_at") or "")[:10] or None,
        })
    return out


def shown_state(item):
    """What the app shows the thread as: you (waiting on the client), working, done or stopped; None if it doesn't say."""
    for key in ("shows", "status_category", "state"):
        word = str(item.get(key) or "").strip().lower().replace(" ", "_").replace("-", "_")
        for shown, words in SHOWN.items():
            if word in words:
                return shown
    return None


def see(r, listed):
    """Bring the record up to date with the thread list: new threads, titles, activity, what each shows,
    and threads resolved or reopened in the app. Returns the new threads, and those resolved in the
    record that the app still shows open with nothing new since."""
    s = r.state()
    new, still_open = [], []
    for item in listed:
        known = s.threads.get(item["id"])
        if known is None and item["resolved"]:
            # Resolved before the record knew it: not part of the backlog. One resolved in the past week still
            # counts in this week's numbers, so a first run (or a thread opened and closed between sweeps) adds up.
            if item["resolved_on"] and (TODAY - d(item["resolved_on"])).days < 7:
                r.add("thread-seen", id=item["id"], **{k: item[k] for k in ("title", "opened", "last_activity")
                                                        if item[k]})
                r.add("thread-resolve", id=item["id"], summary="resolved in the app")
                s = r.state()
            continue
        changes = {k: item[k] for k in ("title", "opened", "last_activity", "shows") if item[k]
                   and (known is None or known.get(k) != item[k])}
        if known is None:
            new.append(item["id"])
        if changes or known is None:
            r.add("thread-seen", id=item["id"], **changes)
        s = r.state()
        t = s.threads[item["id"]]
        if item["resolved"] and t["status"] != "resolved":
            for w in s.live_watches(item["id"]):
                r.add("watch-cancel", id=w["id"])
            r.add("thread-resolve", id=item["id"], summary="resolved in the app")
        elif not item["resolved"] and t["status"] == "resolved":
            if item["last_activity"] and item["last_activity"] > t["resolved_on"]:
                r.add("thread-reopen", id=item["id"])  # something happened there since: it's back
            else:
                still_open.append(item["id"])
        s = r.state()
    return new, still_open


def wrong_shown(s):
    """Open threads whose state in the app doesn't match what the record says they wait on."""
    rows = []
    for t in s.threads.values():
        shows = t.get("shows")
        if t["status"] == "resolved" or not shows:
            continue
        kind, words = s.waits_on(t["id"])
        if shows == "you" and kind != "client":
            rows.append("%s shows it waits on the client, but it waits on %s%s: it says what it really waits on, or "
                        "records the ask it has for them" % (title(s, t["id"]), kind, (": " + words) if words else ""))
        elif shows == "done" and kind == "client":
            rows.append("%s waits on the client (%s) but shows done: it puts the ask back in front of them, on a card "
                        "where it can, or records their answer" % (title(s, t["id"]), words))
        elif shows == "stopped":
            rows.append("%s stopped or failed in the app: restart it, or resolve it" % title(s, t["id"]))
    return rows


def cmd_sweep(a, r):
    listed = read_threads(a.file)
    new, still_open = see(r, listed)
    ids = {item["id"] for item in listed}
    s = r.state()
    ended = [t for t in s.threads.values() if t["status"] == "snoozed" and d(t["until"]) <= TODAY]
    for t in ended:
        r.add("thread-wake", id=t["id"])
    s = r.state()
    gone = [t for t in s.threads.values() if t["status"] != "resolved" and t["id"] not in ids]

    out = ["Sweep of %d threads in the list (%d in the record)." % (len(listed), len(s.threads))]

    def section(head, rows):
        if rows:
            out.append("")
            out.append(head)
            out.extend("- " + row for row in rows)

    section("New since the last sweep: give each a next step, a task for the client, or a watch:",
            [title(s, tid) for tid in new if s.waits_on(tid)[0] == "nothing"])
    section("Waiting on nothing and no next step: decide what each waits on, or resolve it:",
            [title(s, t["id"]) for t in s.threads.values() if t["id"] not in new
             and s.waits_on(t["id"])[0] == "nothing"])
    section("Only step left is on the client's to-do list: resolve the thread with a summary that links it:",
            [title(s, t["id"]) for t in s.threads.values() if s.waits_on(t["id"])[0] == "todo"])
    section("Snoozes that ended: each needs a decision now (the client's list, Claude's to move, or resolved):",
            ["%s, snoozed %d time(s)" % (title(s, t["id"]), s.threads[t["id"]]["snoozes"]) for t in ended])
    idle = []
    for t in s.threads.values():
        kind, words = s.waits_on(t["id"])
        last = t.get("last_activity") or t["opened"]
        if kind == "claude" and (TODAY - d(last)).days >= IDLE_DAYS:
            idle.append("%s, last active %s, next step: %s" % (title(s, t["id"]), last, words))
    section("Idle %d+ days though Claude holds the next step: move it, snooze it, or resolve it:" % IDLE_DAYS, idle)
    on = s.on_list()
    off = []
    for t in s.ranked():
        if t["id"] in on or t.get("offered_drop"):
            continue
        since = s.last_on_list(t["id"]) or t["created"]
        if (TODAY - d(since)).days >= OFF_LIST_DAYS:
            off.append("%s %s, %s, off the list since %s" % (t["id"], t["title"], title(s, t["thread"]), since))
    section("Off the client's list %d+ days: ask them once, drop it or snooze it a month, then 'task offered-drop ID':"
            % OFF_LIST_DAYS, off)
    section("Open tasks on resolved threads: finish, drop or hand each to the to-do list:",
            ["%s %s, %s" % (t["id"], t["title"], title(s, t["thread"])) for t in s.open_tasks()
             if t.get("thread") and not t.get("todo") and s.threads[t["thread"]]["status"] == "resolved"])
    section("Past their 'pointless after' date: drop them:",
            ["%s %s" % (t["id"], t["title"]) for t in s.open_tasks()
             if t.get("pointless_after") and d(t["pointless_after"]) < TODAY])
    section("Resolved in the record but still open in the app: resolve each there (the thread itself, or whoever "
            "can), or reopen it here if it isn't done:", [title(s, tid) for tid in still_open])
    section("Showing the wrong state: tell each thread, and it fixes what it shows itself:", wrong_shown(s))
    section("In the record but not in the list: pass the full list, or resolve these if they are gone:",
            [title(s, t["id"]) for t in gone])
    section("Kinds of asks the client nearly always approves: put 'stop asking?' to them, and on their yes run 'stop-asking KIND':",
            ["%s: took the recommendation %d of %d times" % (k, took, total)
             for k, (took, total) in sorted(s.asks_by_kind().items())
             if k not in s.stopped and total >= STOP_ASKING_MIN and took / total >= STOP_ASKING_RATE])
    asks = s.ranked()
    out.append("")
    out.append("Then run 'review' and ask of every open thread whether it is still worth doing.")
    out.append("Then rank the %d open decide and approve tasks by what each blocks and what a week's delay costs "
               "('rank ID ID ...'; the first %d are the client's list), and run 'report'." % (len(asks), LIST_CAP))
    print("\n".join(out))


def cmd_report(a, r):
    s = r.state()
    ranked = s.ranked()
    listed, queue = ranked[:LIST_CAP], ranked[LIST_CAP:]
    out = ["**Needs you (%d of %d)**" % (len(listed), LIST_CAP)]
    if not listed:
        out.append("Nothing needs you this week.")
    for i, t in enumerate(listed, 1):
        due = ", due %s" % t["due"] if t.get("due") else ""
        out.append("%d. %s (%s%s). Recommendation: %s. In %s." % (i, t["title"], t["kind"], due, t["recommend"],
                                                                  title(s, t["thread"])))
    if queue:
        oldest = min(queue, key=lambda t: t["created"])
        out.append("Queue: %d more, oldest raised %s." % (len(queue), oldest["created"]))
    snoozed = [t for t in s.threads.values() if t["status"] == "snoozed"]
    watching = s.live_watches()
    todo = [t for t in s.open_tasks() if t.get("todo")]
    out.append("Snoozed: %d threads. Watching for: %d events. On your to-do list: %d." % (
        len(snoozed), len(watching), len(todo)))
    week = TODAY - datetime.timedelta(days=7)
    done = [e for e in s.resolves if week < d(e["on"]) <= TODAY]
    if done:
        out.append("")
        out.append("**Closed this week**")
        out += ["- %s: %s" % (s.threads[e["id"]].get("title", e["id"]), e["summary"]) for e in done]
    stopped = [k for k, on in s.stopped.items()]
    if stopped:
        out.append("No longer asked, Claude goes ahead and reports: %s." % ", ".join(sorted(stopped)))
    now, then = s.numbers(TODAY), r.state(week).numbers(week)
    out.append("")
    out.append("**This week** (last week in brackets)")
    out.append("- Threads opened %d (%d), closed %d (%d)." % (now["opened"], then["opened"], now["closed"], then["closed"]))
    out.append("- Waiting on you: %d (%d)." % (now["waiting"], then["waiting"]))
    oldest = ", oldest %d days: %s" % (now["oldest_days"], now["oldest"].get("title", now["oldest"]["id"])) if now["oldest"] else ""
    out.append("- Open threads: %d (%d), median age %s days (%s)%s." % (
        now["open"], then["open"], fmt(now["median"]), fmt(then["median"]), oldest))
    if now["opened"] > now["closed"] and then["opened"] > then["closed"]:
        out.append("- More opened than closed two weeks running: the backlog grows until fewer open or more are dropped.")
    print("\n".join(out))


def fmt(x):
    return ("%.1f" % x).rstrip("0").rstrip(".")


def cmd_show(a, r):
    s = r.state()
    if a.id:
        obj = s.threads.get(a.id) or s.tasks.get(a.id) or s.watches.get(a.id)
        if not obj:
            refuse("nothing called %s" % a.id)
        print(json.dumps(obj, indent=2, sort_keys=True, default=str))
        if a.id in s.threads:
            kind, words = s.waits_on(a.id)
            print("waits on: %s%s" % (kind, (": " + words) if words else ""))
            for t in s.tasks.values():
                if t.get("thread") == a.id:
                    print("task %s [%s] %s: %s" % (t["id"], t["status"], t["kind"], t["title"]))
            for w in s.watches.values():
                if w["thread"] == a.id:
                    print("watch %s [%s] %s until %s" % (w["id"], w["status"], w["check"], w["expires"]))
        return
    on = s.on_list()
    rows = []
    for t in sorted(s.threads.values(), key=lambda t: t["opened"]):
        if t["status"] == "resolved":
            continue
        kind, words = s.waits_on(t["id"])
        mark = " [on the list]" if any(x["id"] in on for x in s.open_tasks(t["id"])) else ""
        rows.append("%s  %s%s%s" % (title(s, t["id"]), kind, (": " + words) if words else "", mark))
    print("\n".join(rows) if rows else "No open threads in the record.")
    print("Record: %s%s" % (r.path, "" if SHARED else " (this place only)"))


def cmd_review(a, r):
    s = r.state()
    live = sorted((t for t in s.threads.values() if t["status"] != "resolved"), key=lambda t: (t["opened"], t["id"]))
    if not live:
        print("No open threads in the record.")
        return
    on = s.on_list()
    out = ["Every open thread, oldest first (%d). Ask of each: would the client start this today?" % len(live), ""]
    for t in live:
        kind, words = s.waits_on(t["id"])
        last = t.get("last_activity") or t["opened"]
        kept = [x["closed"] for x in s.tasks.values() if x.get("thread") == t["id"]
                and x.get("ask_kind") == REVIEW_ASK and x["status"] == "answered" and x["took"] == "no"]
        extra = [", snoozed %d time(s)" % t["snoozes"] if t["snoozes"] else "",
                 " [on the list]" if any(x["id"] in on for x in s.open_tasks(t["id"])) else "",
                 " [the client kept it on %s: don't ask again unless something changed]" % max(kept) if kept else ""]
        shows = "; the app shows %s" % {"you": "it waits on the client"}.get(t.get("shows"), t.get("shows")) if t.get("shows") else ""
        out.append("- %s, %d days old, last active %s. Waits on %s%s%s%s" % (
            title(s, t["id"]), (TODAY - d(t["opened"])).days, last, kind, (": " + words) if words else "", shows,
            "".join(extra)))
    out.append("")
    out.append("Read each thread's own status line too. Where it, or the state the app shows, doesn't say what the "
               "thread waits on, tell the thread, and it fixes what it shows itself.")
    out.append("A thread whose work is done: resolve it with a one-line summary.")
    if REVIEW_ASK in s.stopped:
        out.append("A thread not worth doing: the client said to stop asking, so resolve it with a one-line summary "
                   "and list it in the report.")
    else:
        out.append("A thread not worth doing: put the drop to the client on its thread, "
                   "'task add --thread ID --kind decide --title \"Drop this thread?\" --recommend \"drop it: <why>\" "
                   "--ask-kind \"%s\"', and rank it with the rest. On their yes, resolve the thread." % REVIEW_ASK)
    out.append("Every other thread carries on as it is.")
    print("\n".join(out))


# ---------------------------------------------------------------- how it learns

LOG_HEADER = """# How the thread-backlog routine works for the client: the log

Every note the client gives about how the routine runs, a correction or something they liked, in their own words.
Written only by `backlog.py` in the `thread-backlog` skill of the shared tools; see "How the routine learns" in its `SKILL.md`.
A note with `Rule: open` still counts toward a new rule; one with a rule number or `struck` is done.
"""
ENTRY = re.compile(r"^## (\d+)\. ", re.M)


def log_path():
    return DIR / "LOG.md"


def log_read():
    p = log_path()
    return p.read_text() if p.exists() else LOG_HEADER


def log_entries(text):
    parts = ENTRY.split(text)
    for i in range(1, len(parts), 2):
        yield int(parts[i]), "## %s. %s" % (parts[i], parts[i + 1])


def cmd_note(a, project):
    text = log_read()
    n = max([num for num, _ in log_entries(text)], default=0) + 1
    block = "\n## %d. %s, %s, %s\nThe client: \"%s\"\nWhat the routine did: %s\nRule: open\n" % (
        n, TODAY.isoformat(), a.kind, project, line(a.words, "words").strip('"'), line(a.what, "what"))
    log_path().parent.mkdir(parents=True, exist_ok=True)
    log_path().write_text(text.rstrip("\n") + "\n" + block)
    print("logged note %d%s. Now run: backlog.py open" % (n, "" if SHARED else " (this place only: %s)" % log_path()))


def cmd_open(a, project):
    found = [b.strip() for _, b in log_entries(log_read()) if "\nRule: open" in b]
    if not found:
        print("No open notes.")
        return
    print("%d open note(s). Three alike make a rule to put to the client now.\n" % len(found))
    print("\n\n".join(found))


def cmd_used(a, project):
    rule = a.rule.strip()
    if rule != "struck" and not rule.isdigit():
        refuse("--rule is a rule number in the skill's SKILL.md or 'struck'")
    try:
        wanted = {int(x) for x in a.notes.split(",") if x.strip()}
    except ValueError:
        refuse("notes are numbers, comma-separated")
    text = log_read()
    have = dict(log_entries(text))
    missing = wanted - set(have)
    if missing:
        refuse("no note %s" % ", ".join(map(str, sorted(missing))))
    for num in sorted(wanted):
        if "\nRule: open" not in have[num]:
            refuse("note %d is already counted" % num)
        text = text.replace(have[num], have[num].replace("\nRule: open", "\nRule: " + rule, 1), 1)
    log_path().write_text(text)
    print("marked note(s) %s: Rule %s" % (", ".join(map(str, sorted(wanted))), rule))


# ---------------------------------------------------------------- the command line

def main():
    global TODAY
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default=os.environ.get("THREAD_BACKLOG_PROJECT") or os.environ.get("TIMMY_BACKLOG_PROJECT"),
                   help="the project's fixed id (or $THREAD_BACKLOG_PROJECT)")
    p.add_argument("--today", help=argparse.SUPPRESS)  # for trying the routine on a past or future date
    sub = p.add_subparsers(dest="cmd", required=True)

    x = sub.add_parser("sweep", help="weekly: compare the thread list with the record")
    x.add_argument("file", nargs="?", help="the thread list as JSON (default: stdin)")
    x = sub.add_parser("daily", help="check watches, snoozes and due tasks")
    x.add_argument("file", nargs="?", help="the thread list as JSON, to also catch threads showing the wrong state")
    sub.add_parser("report", help="The client's list and the weekly numbers")
    x = sub.add_parser("show", help="open threads, or one object")
    x.add_argument("id", nargs="?")
    sub.add_parser("review", help="weekly: every open thread, to ask whether it is still worth doing")

    x = sub.add_parser("thread", help="add or change a thread")
    x.add_argument("id", help="the thread's id, or 'add'")
    x.add_argument("rest", nargs="*")
    x.add_argument("--title")
    x.add_argument("--opened")
    x.add_argument("--next")
    x.add_argument("--snooze")
    x.add_argument("--resolve")
    x.add_argument("--reopen", action="store_true")
    x.add_argument("--standing", help="kept open on purpose; say what wakes it, such as its mail doorbell")
    x.add_argument("--not-standing", dest="not_standing", action="store_true")

    x = sub.add_parser("task", help="tasks only the client can do")
    ts = x.add_subparsers(dest="action", required=True)
    y = ts.add_parser("add")
    y.add_argument("--thread")
    y.add_argument("--kind", choices=KINDS, required=True)
    y.add_argument("--title", required=True)
    y.add_argument("--recommend")
    y.add_argument("--ask-kind", dest="ask_kind")
    y.add_argument("--due")
    y.add_argument("--pointless-after", dest="pointless_after")
    y.add_argument("--todo")
    y = ts.add_parser("answer")
    y.add_argument("task")
    y.add_argument("--took", choices=("yes", "no"), required=True)
    y.add_argument("--choice")
    for name in ("done", "offered-drop"):
        ts.add_parser(name).add_argument("task")
    y = ts.add_parser("drop")
    y.add_argument("task")
    y.add_argument("--why", required=True)
    y = ts.add_parser("todo")
    y.add_argument("task")
    y.add_argument("link")

    x = sub.add_parser("rank", help="order the open decide and approve tasks")
    x.add_argument("order", nargs="+")
    x = sub.add_parser("stop-asking", help="The client said this kind of ask stops coming to them")
    x.add_argument("kind")

    x = sub.add_parser("watch", help="what threads wait for")
    ws = x.add_subparsers(dest="action", required=True)
    y = ws.add_parser("add")
    y.add_argument("--thread", required=True)
    y.add_argument("--check", required=True)
    y.add_argument("--expires", required=True)
    y = ws.add_parser("match")
    y.add_argument("id")
    y.add_argument("--what")
    ws.add_parser("cancel").add_argument("id")

    x = sub.add_parser("note", help="log one note from the client about the routine")
    x.add_argument("--kind", choices=["correct", "like"], required=True)
    x.add_argument("--words", required=True)
    x.add_argument("--what", required=True)
    sub.add_parser("open", help="notes not yet counted toward a rule")
    x = sub.add_parser("used", help="mark notes as counted toward a rule")
    x.add_argument("notes")
    x.add_argument("--rule", required=True)

    a = p.parse_args()
    if a.today:
        TODAY = datetime.date.fromisoformat(a.today)
    if a.cmd in ("note", "open", "used"):
        if a.cmd == "note" and not a.project:
            refuse("--project is needed to log a note")
        {"note": cmd_note, "open": cmd_open, "used": cmd_used}[a.cmd](a, a.project)
        return
    if not a.project:
        refuse("--project (or $THREAD_BACKLOG_PROJECT) is the project's fixed id")
    r = Record(a.project)
    {"sweep": cmd_sweep, "daily": cmd_daily, "report": cmd_report, "show": cmd_show, "thread": cmd_thread,
     "task": cmd_task, "rank": cmd_rank, "stop-asking": cmd_stop_asking, "watch": cmd_watch,
     "review": cmd_review}[a.cmd](a, r)


if __name__ == "__main__":
    main()
