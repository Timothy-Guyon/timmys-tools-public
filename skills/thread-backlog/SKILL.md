---
name: thread-backlog
description: The routine that keeps Timmy's open threads from piling up. Each week every thread gets one state, Timmy gets a ranked "needs you" list of at most seven items, each with a recommendation, and three numbers show whether the backlog is shrinking; each day, what threads wait for is checked. Use when coordinating a project's threads (the weekly sweep, the daily check), whenever a thread asks Timmy something, waits for an event or leaves him an action, and when he says how the routine works for him.
---

# Thread backlog

New threads open faster than old ones close, so a project's threads pile up unless something closes them on purpose. Better ranking doesn't fix that. Only three things do: open fewer, close more (dropping some deliberately), and cap how many wait on Timmy at once. This routine does all three. Claude does the upkeep, and Timmy gets only the decisions.

The session that sees all of a project's threads runs it: the project's coordinator, or whichever session coordinates the project's work. Every thread also uses it, when it asks Timmy something, waits for something, or finishes. Every change goes through `scripts/backlog.py`, never by hand, and every command takes `--project` with the project's fixed id (rule 35 of the shared rules), or `$TIMMY_BACKLOG_PROJECT`.

## The record

A **thread** here means one conversation with an agent about one piece of work, in the everyday sense of an email or chat thread, whatever the harness calls it on screen: a thread, a session, a chat. Anything with a fixed id that work happens in counts.

Three kinds of things, each kept on its own and linked to the others.

- **A thread** is one conversation. It holds its title, the day it opened, whether it is active, snoozed until a date, or resolved with a one-line summary, and its next step when Claude holds one.
- **A task** is something only Timmy can do. Its kind is *decide*, *approve* or *act*. It holds a title, a due date and a "pointless after" date if there are any, and the thread that raised it. A decide or approve task also holds Claude's recommendation, the kind of ask it is (such as "resolve an idle thread"), and, once he answers, whether he took the recommendation.
- **A watch** is something a thread waits for: a date, a change to a web page, an email (a mail search), or anything else said in words. It holds its thread, the check, and the day the thread stops waiting.

What a thread is waiting on is never written down. It is worked out each time from the thread's tasks and watches: an open task means it waits on Timmy, a live watch means it waits on an event, an act on Timmy's to-do list means only the to-do list is left, a next step means it is Claude's to move, and none of these means the sweep catches it.

The record is one file per project, `backlog/<project id>.jsonl` in the mailbox repo (`Timothy-Guyon/claude-shared`), found beside or above the current folder, or at `$TIMMY_BACKLOG_DIR`. Lines are only ever added, each one dated change to one thread, task or watch. Everything else, from a thread's snooze count to the weekly numbers, is worked out from those lines whenever the script runs, so no total can go stale. Pull the mailbox before a run, and push `backlog/` straight to its `main` after.

## What the routine holds

1. **Every thread is in one state.** It is resolved, snoozed until a date, waiting on Timmy, waiting on an event, or Claude's to move with a next step. A thread with none of these turns up in the sweep until it has one.
2. **Timmy's list holds at most seven items.** They are the open decide and approve tasks, ranked by what each blocks and what a week's delay would cost, each with a recommendation. The rest wait in the queue, ranked the same way.
3. **A task off the list for three weeks is put to Timmy once:** drop it, or snooze it a month. He is asked once, not every week.
4. **A snooze always ends in a decision.** When it ends, the thread goes to Timmy's list, back to Claude to move, or is resolved. After two snoozes the script refuses a third: the thread is resolved with a one-line summary instead, and it can be reopened any time.
5. **A decision stays in its thread.** Claude asks it there, on a decision card where the harness has one, and it goes on Timmy's list. **An action only Timmy can take outside Claude goes on his to-do list** wherever the project can reach one, by mail to the project that keeps it if need be. The task records the link, and when it was the thread's only step left, the thread resolves with a summary that links it. Where no to-do list can be reached, the thread stays open until he says it's done (rule 23 of the shared rules).
6. **Claude goes ahead on steps that can be undone** and doesn't make tasks of them (rules 20 and 21 of the shared rules). A task is only for what only Timmy can do.
7. **Kinds of asks Timmy almost always approves stop being asked.** When he has taken Claude's recommendation on at least 95% of the asks of one kind, over at least ten answers, the sweep says so. Claude puts "stop asking?" to him, and on his yes runs `stop-asking`. From then on the script refuses that kind of ask, and Claude goes ahead and lists what it did in the weekly report.
8. **A task past its "pointless after" date is dropped,** not shown as overdue.

## As a thread works

One example. A thread emails a clinic, and needs Timmy to pick between two appointment times once they reply.

    backlog.py watch add --thread <id> --check "mail:from:clinic newer_than:1d" --expires 2026-12-07

The daily run finds the reply and wakes the thread. The thread asks Timmy in the thread, on a card, and records the ask:

    backlog.py task add --thread <id> --kind decide --title "Pick the clinic appointment" \
        --recommend "Tuesday 9am, it's before work" --ask-kind "pick a time" --due 2026-12-03

When he answers, `task answer <task> --took yes` (or `no`, with `--choice` saying what he picked). If he then has to call to confirm, that's an act: `task add --kind act`, put it on his to-do list, `task todo <task> <link>`, and resolve the thread with `thread <id> --resolve "..."`.

The thread runs these itself where it can reach the mailbox. Where it can't, it tells the coordinator, who records it.

## Every day

Run `backlog.py daily` from whatever the project already runs each day, such as its scheduled check or mail doorbell. It:

- checks every watch. A date or a web page is checked by the script itself. A mail search or anything else is listed for the Claude running the check to look up by hand in the same run, then `watch match <id>` for any that came true.
- lists the threads to wake: send each one a message, or, where that can't reach it, a push to Timmy's phone through the notifier.
- marks watches that ran out. Each one's thread is told once, and decides whether to chase, wait again or drop it.
- ends snoozes that are due, and lists them for a decision.
- lists tasks due within three days, to raise with Timmy today (a deadline also goes to his phone, rule 33 of the shared rules), and tasks past their "pointless after" date, to drop.

## Every week: the sweep

Once a week, on Monday unless Timmy says otherwise:

1. Pull the mailbox.
2. Get the project's full list of threads from the harness, with each thread's id, title, the day it opened, its last activity and whether it is resolved. Save it as JSON (a list of `{"id", "title", "opened", "last_activity", "resolved"}`; a listing that uses `thread_id`, `created_at` and `last_activity_at` works as it is) and run `backlog.py sweep <file>`. The sweep adds new threads, notes threads resolved or reopened in the app, ends due snoozes, and prints a worksheet.
3. Work through the worksheet. Give each new or stuck thread a next step, a task or a watch, or resolve it. Decide each ended snooze. Put each three-week task to Timmy once (`task offered-drop`). Drop what is past its date. Resolve threads whose only step is on the to-do list.
4. Rank the open decide and approve tasks: `backlog.py rank <task> <task> ...`, most important first. The first seven are Timmy's list.
5. Run `backlog.py report` and post it to Timmy in one message, where he reads the project's news. Each item names its thread, where the card waits. A list of one or two is fine; an empty list says so.
6. Push `backlog/` to the mailbox's `main`.

## The weekly numbers

The report ends with three numbers next to last week's: threads opened and closed, how many wait on Timmy, and the median and oldest age of open threads. If more open than close two weeks running, the backlog grows however well it is sorted, and the report says so: the fix is to open fewer threads or drop more. The numbers for a past week come from what the record knew then, so the first weeks of a new record start low.

## How the routine learns

Whenever Timmy corrects how the routine works for him, or says he likes something it did, log it the same day, in his own words:

    backlog.py --project <id> note --kind correct|like --words "his words" --what "what the routine did"

Then run `backlog.py open`. When three open notes say the same thing, put the rule to Timmy at once, on a decision card where the harness has one: accept, edit or strike, quoting the three notes. A point he states outright in his own words needs no three. An accepted rule goes under "Rules learned" below, in a pull request on `Timothy-Guyon/timmys-tools` that only Timmy merges, and `backlog.py used <notes> --rule <number>` marks the notes as counted (`--rule struck` for a struck one). If he overrules a rule twice, or it stops fitting, log a `correct` note naming it and put the change to him the same way. The weekly review of Timmy's Tools reads this log with the others.

The log is `backlog/LOG.md` in the mailbox repo, beside the records.

## Without the mailbox

An account that can't read the mailbox repo, such as a work account using the public copy, keeps its records and log in `~/.timmy-backlog/`, for that place only, and the script says so. Where a session's files don't last, keep the notes in the session. Lessons go back as an issue on `Timothy-Guyon/timmys-tools-public` with its "Rule candidate" template, one rule per issue, in general terms only, since that repository is public.

## Rules learned

None yet.
