#!/usr/bin/env python3
"""The log behind voice.md: what Timmy picked, changed or said about drafts
written as him.

Every session that drafts as Timmy logs a note here each time he picks between
two drafts, edits one, or says something about how a draft sounds. Three alike
become a rule he approves (see "How the voice grows" in SKILL.md).

Only the lesson is logged, never the writing itself: what the draft did, what
Timmy did instead, and at most a short fragment of each with names taken out.
His writing stays where it was written.

Plain Markdown, one entry per note. The log is found at $TIMMY_VOICE_LOG if
set, else at voice/LOG.md of the mailbox repo (Timothy-Guyon/claude-shared)
beside or above the current folder or this script, else at
~/.timmy-voice/LOG.md, a log for this place only (an account without the
mailbox). Push the mailbox's log straight to its main.

  voice.py status                      how many drafts to show, and what is due
  voice.py note --kind pick|edit|said --for "kind of writing" --draft "what the draft did"
                --timmy "what he chose, changed or said" [--before "..." --after "..."] [--date YYYY-MM-DD]
  voice.py open                        notes not yet counted toward a rule
  voice.py examples                    his own writing he approved as examples (private, in the mailbox)
  voice.py used 3,7,9 --rule 8         mark notes as counted toward rule 8 (or --rule struck)
  voice.py check --with N --without N [--ties N] --found N [--note "..."]
                [--with-examples N --rules-only N --examples-ties N]
                                       record a check against his real writing (check.md)
"""
import argparse
import datetime
import os
import pathlib
import re
import sys

TWO_DRAFTS_UNTIL = 30  # picks and edits logged before one draft becomes the default
CHECK_DUE_AFTER = 3    # rules added to voice.md since the last check
CHECK_EVERY_DAYS = 7   # a fresh look at his writing every week at first (Timmy, 2026-11-24),
CHECK_EVERY_MAX = 28   # the gap doubling after each check that found nothing new, up to four weeks
FRAGMENT_MAX = 200


def find_log():
    """Return (path, shared): shared is False for a log kept in this place only."""
    env = os.environ.get("TIMMY_VOICE_LOG")
    if env:
        return pathlib.Path(env).expanduser(), True
    for start in (pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            for name in ("claude-shared", "."):
                if (d / name / "inbox").is_dir():
                    return d / name / "voice" / "LOG.md", True
    return pathlib.Path.home() / ".timmy-voice" / "LOG.md", False


LOG, SHARED = find_log()
HEADER = """# Timmy's voice: the log

Every pick, edit or remark Timmy makes on a draft written as him, one note each: what the draft did and what he did instead.
Only the lesson is kept, never the writing itself, and no names.
Written only by `voice.py` in the `write-like-timmy` skill of Timmy's Tools; see "How the voice grows" in its `SKILL.md`.
A note with `Rule: open` still counts toward a new rule; one with a rule number or `struck` is done.
"""
ENTRY = re.compile(r"^## (\d+)\. ", re.M)


def read():
    if not LOG.exists():
        return HEADER
    return LOG.read_text()


def write(text):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(text)


def entries(text):
    """Yield (number, block) for each note."""
    parts = ENTRY.split(text)
    for i in range(1, len(parts), 2):
        yield int(parts[i]), "## %s. %s" % (parts[i], parts[i + 1])


def need(value, name, limit=None):
    if not value or not value.strip():
        sys.exit("refused: --%s is empty" % name)
    if "\n" in value:
        sys.exit("refused: --%s must be one line" % name)
    value = value.strip()
    if limit and len(value) > limit:
        sys.exit("refused: --%s is over %d characters; log the lesson, not the writing" % (name, limit))
    return value


def day(value):
    value = value or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        sys.exit("refused: --date must be YYYY-MM-DD")
    return value


def append(text, heading, lines):
    n = max([num for num, _ in entries(text)], default=0) + 1
    block = "\n## %d. %s\n%s\n" % (n, heading, "\n".join(lines))
    write(text.rstrip("\n") + "\n" + block)
    return n


def where():
    return "" if SHARED else " (kept in this place only: %s)" % LOG


def rules_now():
    """How many rules voice.md holds: the numbered lines that open with bold."""
    voice = pathlib.Path(__file__).resolve().parent.parent / "voice.md"
    if not voice.exists():
        return 0
    return len(re.findall(r"^\d+\. \*\*", voice.read_text(), re.M))


def examples_file():
    """His private examples sit beside the shared log; a log for this place only has none."""
    return LOG.parent / "examples.md" if SHARED else None


def examples_count():
    f = examples_file()
    if not f or not f.exists():
        return None
    return len(ENTRY.findall(f.read_text()))


def examples(a):
    f = examples_file()
    if not f or not f.exists():
        print("No private examples can be reached here. Use the public ones under \"Examples\" in voice.md, if any.")
        return
    print(f.read_text().rstrip("\n"))


def note(a):
    if bool(a.before) != bool(a.after):
        sys.exit("refused: --before and --after go together: every bad fragment is logged with what he did instead")
    timmy = need(a.timmy, "timmy")
    lines = [
        "The draft: %s" % need(a.draft, "draft"),
        "Timmy: %s" % ('"%s"' % timmy.strip('"') if a.kind == "said" else timmy),
    ]
    if a.before:
        lines.append('Before: "%s"' % need(a.before, "before", FRAGMENT_MAX))
        lines.append('After: "%s"' % need(a.after, "after", FRAGMENT_MAX))
    lines.append("Rule: open")
    n = append(read(), "%s, %s, %s" % (day(a.date), a.kind, need(a.to, "for")), lines)
    print("logged note %d%s. Now run: voice.py open" % (n, where()))


def open_(a):
    found = [block.strip() for _, block in entries(read()) if "\nRule: open" in block]
    if not found:
        print("No open notes.")
        return
    print("%d open note(s). Three sharing one way of writing make a rule to put to Timmy now.\n" % len(found))
    print("\n\n".join(found))


def used(a):
    rule = a.rule.strip()
    if rule != "struck" and not rule.isdigit():
        sys.exit("refused: --rule is a rule number in voice.md or 'struck'")
    try:
        wanted = {int(x) for x in a.notes.split(",") if x.strip()}
    except ValueError:
        sys.exit("refused: notes are numbers, comma-separated")
    text = read()
    have = dict(entries(text))
    missing = wanted - set(have)
    if missing:
        sys.exit("refused: no note %s" % ", ".join(map(str, sorted(missing))))
    for num in sorted(wanted):
        block = have[num]
        if "\nRule: open" not in block:
            sys.exit("refused: note %d is already counted" % num)
        text = text.replace(block, block.replace("\nRule: open", "\nRule: " + rule, 1), 1)
    write(text)
    print("marked note(s) %s: Rule %s" % (", ".join(map(str, sorted(wanted))), rule))


def check(a):
    second = (a.with_examples, a.rules_only, a.examples_ties)
    asked = any(x is not None for x in second)
    second = tuple(x or 0 for x in second)
    for count in (a.with_, a.without, a.ties, a.found) + second:
        if count < 0:
            sys.exit("refused: counts can't be negative")
    if asked and sum(second) == 0:
        sys.exit("refused: the comparison with his examples needs at least one piece")
    lines = [
        "Closer to his real writing: with the voice %d, without it %d, ties %d" % (a.with_, a.without, a.ties),
        "Rules in voice.md: %d" % rules_now(),
    ]
    if asked:
        lines.append("Reading his examples, against the rules alone: with examples %d, rules only %d, ties %d" % second)
    lines.append("Found: %d new rules or examples put to Timmy" % a.found)
    if a.note:
        lines.append("Note: %s" % need(a.note, "note"))
    lines.append("Rule: check")
    n = append(read(), "%s, check" % day(a.date), lines)
    print("logged check as note %d%s." % (n, where()))
    if a.without > a.with_:
        print("Drafts without the voice were closer more often. Tell Timmy: a rule may be pulling drafts away from him.")
    if second[0] > second[1]:
        print("Drafts that read his examples were closer more often. A rule is missing: find it in the judge's notes and put it to Timmy (check.md, step 6).")


def check_every(checks):
    """Weekly while checks keep finding new things; each check in a row that
    found nothing doubles the gap, up to CHECK_EVERY_MAX."""
    every = CHECK_EVERY_DAYS
    for block in reversed(checks):
        m = re.search(r"\nFound: (\d+)", block)
        if not m or int(m.group(1)) > 0:
            break
        every = min(every * 2, CHECK_EVERY_MAX)
    return every


def status(a):
    all_ = list(entries(read()))
    taught = sum(1 for _, b in all_ if re.match(r"## \d+\. [\d-]+, (pick|edit),", b))
    if taught < TWO_DRAFTS_UNTIL:
        print("Drafts to show: two, differing in one way (%d of %d picks and edits logged)." % (taught, TWO_DRAFTS_UNTIL))
    else:
        print("Drafts to show: one (%d picks and edits logged); two when he asks." % taught)
    open_count = sum(1 for _, b in all_ if "\nRule: open" in b)
    print("Open notes: %d%s" % (open_count, ". Three alike make a rule: voice.py open" if open_count >= 3 else "."))
    shown = examples_count()
    if shown is None:
        print("Examples: none of his private ones can be reached here.")
    else:
        print("Examples: %d of his own pieces. Read them before drafting: voice.py examples" % shown)
    checks = [b for _, b in all_ if "\nRule: check" in b]
    now = rules_now()
    if not checks:
        print("Last check: none yet. Rules in voice.md: %d. Run one where his real writing can be read (check.md)." % now)
    else:
        last = checks[-1].strip().splitlines()
        then = re.search(r"\nRules in voice.md: (\d+)", checks[-1])
        added = now - int(then.group(1)) if then else 0
        when = last[0].split(". ", 1)[1].split(",")[0]
        days = (datetime.date.today() - datetime.date.fromisoformat(when)).days
        every = check_every(checks)
        due = ""
        if added >= CHECK_DUE_AFTER or days >= every:
            due = "; a check is due on his writing since then, where it can be read (check.md)"
        print("Last check: %s (%d days ago). %s. Rules added since: %d%s." % (when, days, last[1], added, due))
        found = [m.group(1) for m in (re.search(r"\nFound: (\d+)", b) for b in checks) if m]
        if found:
            print("  New things found per check, oldest first: %s. Checks come every %d days." % (", ".join(found[-6:]), every))
        plus = [l for l in last if l.startswith("Reading his examples")]
        if plus:
            print("  %s." % plus[0])
    print("Log: %s%s" % (LOG, "" if SHARED else " (this place only; lessons travel as SKILL.md says under \"Without the mailbox\")"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="how many drafts to show, and what is due")
    s.set_defaults(fn=status)
    n = sub.add_parser("note", help="log one pick, edit or remark of Timmy's")
    n.add_argument("--kind", choices=["pick", "edit", "said"], required=True)
    n.add_argument("--for", dest="to", required=True, help="the kind of writing, with no names: 'text to a friend', 'document for work'")
    n.add_argument("--draft", required=True, help="what the draft did")
    n.add_argument("--timmy", required=True, help="what he chose or changed; for said, his own words")
    n.add_argument("--before", help="a short fragment of the draft, names taken out")
    n.add_argument("--after", help="the same fragment as he left it")
    n.add_argument("--date")
    n.set_defaults(fn=note)
    o = sub.add_parser("open", help="list notes not yet counted toward a rule")
    o.set_defaults(fn=open_)
    e = sub.add_parser("examples", help="print his own writing he approved as examples")
    e.set_defaults(fn=examples)
    u = sub.add_parser("used", help="mark notes as counted toward a rule")
    u.add_argument("notes", help="note numbers, comma-separated")
    u.add_argument("--rule", required=True)
    u.set_defaults(fn=used)
    c = sub.add_parser("check", help="record a check against his real writing")
    c.add_argument("--with", dest="with_", type=int, required=True, help="pairs where the draft written with voice.md was closer")
    c.add_argument("--without", type=int, required=True, help="pairs where the draft written without it was closer")
    c.add_argument("--ties", type=int, default=0, help="pairs where the judge flipped when the order was swapped")
    c.add_argument("--found", type=int, required=True, help="new rules or examples this check put to Timmy (check.md, steps 6 and 7)")
    c.add_argument("--with-examples", type=int, help="pairs where the draft that also read his examples was closer")
    c.add_argument("--rules-only", type=int, help="pairs where the draft with voice.md alone was closer")
    c.add_argument("--examples-ties", type=int, help="ties in that second comparison")
    c.add_argument("--note")
    c.add_argument("--date")
    c.set_defaults(fn=check)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
