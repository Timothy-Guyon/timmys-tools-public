---
name: thread-backlog
description: The routine that keeps the client's open threads from piling up. Each week every thread gets one state, shows that state truly, and is asked whether it is still worth doing, the client gets a ranked "needs you" list of at most seven items, each with a recommendation, and three numbers show whether the backlog is shrinking; each day, what threads wait for is checked. Use when coordinating a project's threads (the weekly sweep, the daily check), whenever a thread asks the client something, waits for an event or leaves them an action, and when they say how the routine works for them.
---

# Thread backlog

**The client** here is the person the threads work for: the one who decides, approves and does what only a person can. Every "the client" below means them, whoever has installed the tools.

New threads open faster than old ones close, so a project's threads pile up unless something closes them on purpose. Better ranking doesn't fix that. Only three things do: open fewer, close more (dropping some deliberately), and cap how many wait on the client at once. This routine does all three. Claude does the upkeep, and the client gets only the decisions.

The session that sees all of a project's threads runs it: the project's coordinator, or whichever session coordinates the project's work. Every thread also uses it, when it asks the client something, waits for something, or finishes. Every change goes through `scripts/backlog.py`, never by hand, and every command takes `--project` with the project's fixed id (rule 35 of the shared rules), or `$THREAD_BACKLOG_PROJECT`.

## The record

A **thread** here means one conversation with an agent about one piece of work, in the everyday sense of an email or chat thread, whatever the harness calls it on screen: a thread, a session, a chat. Anything with a fixed id that work happens in counts.

Three kinds of things, each kept on its own and linked to the others.

- **A thread** is one conversation. It holds its title, the day it opened, whether it is active, snoozed until a date, or resolved with a one-line summary, and its next step when Claude holds one.
- **A task** is something only the client can do. Its kind is *decide*, *approve* or *act*. It holds a title, a due date and a "pointless after" date if there are any, and the thread that raised it. A decide or approve task also holds Claude's recommendation, the kind of ask it is (such as "resolve an idle thread"), and, once they answer, whether they took the recommendation.
- **A watch** is something a thread waits for: a date, a change to a web page, an email (a mail search), or anything else said in words. It holds its thread, the check, and the day the thread stops waiting.

What a thread is waiting on is never written down. It is worked out each time from the thread's tasks and watches: an open task means it waits on the client, a live watch means it waits on an event, an act on the client's to-do list means only the to-do list is left, a next step means it is Claude's to move, and none of these means the sweep catches it.

The record is one file per project, `backlog/<project id>.jsonl` in the mailbox repo (`Timothy-Guyon/claude-shared`), found beside or above the current folder, or at `$THREAD_BACKLOG_DIR`. Lines are only ever added, each one dated change to one thread, task or watch. Everything else, from a thread's snooze count to the weekly numbers, is worked out from those lines whenever the script runs, so no total can go stale. Pull the mailbox before a run, and push `backlog/` straight to its `main` after.

## What the routine holds

1. **Every thread is in one state.** It is resolved, snoozed until a date, waiting on the client, waiting on an event, Claude's to move with a next step, or standing. A thread with none of these turns up in the sweep until it has one.

   **A standing thread is kept open for good, and the routine leaves it alone.** It is a thread with no end, such as a mailbox its doorbell wakes, a log of a hobby or a running topic, or any thread the client has pinned. Mark it once with `thread <id> --standing "why it stays open"`. A thread the app shows as pinned is marked standing by the sweep itself, and unpinning it takes the mark off again. The routine never snoozes or resolves a standing thread, never puts it up to drop, and never asks whether it is still worth doing; the script refuses to. It reaches the client's list only when it holds an ask for them, like any other thread. Only the client takes the mark off (`--not-standing`). Standing threads aren't backlog, so the weekly numbers leave them out. When the client says a thread stays open, or reopens one the routine closed because it is ongoing, mark it standing in the same turn. On the first sweep, any list the project already keeps of threads never to close marks those threads standing.
2. **The client's list holds at most seven items.** They are the open decide and approve tasks, ranked by what each blocks and what a week's delay would cost, each with a recommendation. The rest wait in the queue, ranked the same way.
3. **A task off the list for three weeks is put to the client once:** drop it, or snooze it a month. They are asked once, not every week.
4. **A snooze always ends in a decision.** When it ends, the thread goes to the client's list, back to Claude to move, or is resolved. After two snoozes the script refuses a third: the thread is resolved with a one-line summary instead, and it can be reopened any time.
5. **A decision stays in its thread.** Claude asks it there, on a decision card where the harness has one, and it goes on the client's list. A decision no open thread holds, such as one owed from a thread already resolved, gets a thread: reopen the one it came from, or start one for it (where only a coordinator starts threads, ask it to). Every ask then has a place for its card, its context and the work after they answer, and it counts as open work. **An action only the client can take outside Claude goes on their to-do list** wherever the project can reach one, by mail to the project that keeps it if need be. The task records the link, and when it was the thread's only step left, the thread resolves with a summary that links it. Where no to-do list can be reached, the thread stays open until they say it's done (rule 23 of the shared rules).
6. **Claude goes ahead on steps that can be undone** and doesn't make tasks of them (rules 20 and 21 of the shared rules). A task is only for what only the client can do.
7. **Kinds of asks the client almost always approves stop being asked.** When they have taken Claude's recommendation on at least 95% of the asks of one kind, over at least ten answers, the sweep says so. Claude puts "stop asking?" to them, and on their yes runs `stop-asking`. From then on the script refuses that kind of ask, and Claude goes ahead and lists what it did in the weekly report.
8. **A task past its "pointless after" date is dropped,** not shown as overdue.
9. **Every week every open thread is looked at, not only the stuck ones.** The worksheet shows only threads that need something, so a thread that looks fine, with a next step and some activity, can live on though nobody would start it today. Each one like that goes to the client as a drop, with a recommendation, on its own thread. Once they take nearly all of these, they stop being asked (point 7): Claude drops them and lists them in the weekly report.
10. **What a thread shows is what it waits on.** The state the app shows for a thread (such as "waiting on you", "working" or "done") and the line that sums it up say the one thing it waits on now, the same as the record. A thread shows that it waits on the client only while it truly does, and shows it every time it does: an ask written in plain words, with no card and no task, is buried, and the sweep digs it out. The routine checks this, so the client doesn't have to nudge threads to fix their state: each thread that shows the wrong state is told, and fixes it itself.

## As a thread works

One example. A thread emails a clinic, and needs the client to pick between two appointment times once they reply.

    backlog.py watch add --thread <id> --check "mail:from:clinic newer_than:1d" --expires 2026-12-07

The daily run finds the reply and wakes the thread. The thread asks the client in the thread, on a card, and records the ask:

    backlog.py task add --thread <id> --kind decide --title "Pick the clinic appointment" \
        --recommend "Tuesday 9am, it's before work" --ask-kind "pick a time" --due 2026-12-03

When they answer, `task answer <task> --took yes` (or `no`, with `--choice` saying what they picked). If they then have to call to confirm, that's an act: `task add --kind act`, put it on their to-do list, `task todo <task> <link>`, and resolve the thread with `thread <id> --resolve "..."`.

The thread runs these itself where it can reach the mailbox. Where it can't, it tells the coordinator, who records it.

Whenever what a thread waits on changes, it updates what it shows in the same turn (point 10). Asking the client something, it asks on a card where the harness has one, so the app shows it waits on them. Once they answer, or the question no longer matters, nothing it shows still says it waits on them. Its status line, such as the current step of its checklist, names the one thing it waits on now, in words the client would use. When the routine tells a thread it shows the wrong state, the thread checks what it really waits on and fixes what it shows, or records the ask the record is missing.

## Every day

Run `backlog.py daily` from whatever the project already runs each day, such as its scheduled check or mail doorbell. It:

- checks every watch. A date or a web page is checked by the script itself. A mail search or anything else is listed for the Claude running the check to look up by hand in the same run, then `watch match <id>` for any that came true.
- lists the threads to wake: send each one a message, or, where that can't reach it, a push to the client's phone through the notifier.
- marks watches that ran out. Each one's thread is told once, and decides whether to chase, wait again or drop it.
- ends snoozes that are due, and lists them for a decision.
- lists tasks due within three days, to raise with the client today (a deadline also goes to their phone, rule 33 of the shared rules), and tasks past their "pointless after" date, to drop.
- given the project's thread list as in the sweep (`backlog.py daily <file>`), lists the threads showing the wrong state, so each is told the same day rather than at the next sweep.

## Every week: the sweep

Once a week, on Monday unless the client says otherwise:

1. Pull the mailbox.
2. Get the project's full list of threads from the harness, with each thread's id, title, the day it opened, its last activity, whether it is resolved, and the state the app shows it in. Save it as JSON (a list of `{"id", "title", "opened", "last_activity", "resolved", "shows"}`, where `shows` is the app's word for its state, plus `"pinned"` where the app has pins; a listing that uses `thread_id`, `created_at`, `last_activity_at` and `state` or `status_category` works as it is) and run `backlog.py sweep <file>`. The sweep adds new threads, notes threads resolved or reopened in the app, ends due snoozes, and prints a worksheet. A thread resolved in the record that the app still shows open stays resolved unless something happened in it since; the worksheet lists it to resolve in the app.
3. Work through the worksheet. Give each new or stuck thread a next step, a task or a watch, mark it standing if it is kept open for good (point 1), or resolve it. Decide each ended snooze. Put each three-week task to the client once (`task offered-drop`). Drop what is past its date. Resolve threads whose only step is on the to-do list. Check each open task against its thread, and record any answer the client gave there that the thread didn't record. For each thread the worksheet lists as not read since its last activity, however old, read its last messages: a thread can ask the client something in plain words, without a card, and then show "done" or sit idle while it waits on them. Record each such buried ask as a task, and tell the thread to put it in front of them on a card. Then mark the thread read (`thread <id> --read`): it comes back to the sweep only when something new happens in it, so the first sweep reads every thread and later ones read only what moved. Tell each thread the worksheet lists as showing the wrong state, by a message to it where the harness allows, else through the coordinator, and it fixes what it shows itself.
4. Run `backlog.py review`: it lists every open thread, oldest first, with its age, last activity, what it waits on and what the app shows. Read each one's last messages and status line too. Record any buried ask the same way as in step 3, however old the thread, and tell the thread if its status line doesn't say what it waits on. Ask of each: would the client start this today? Standing threads are listed apart and never asked about. Resolve a thread whose work is done. For one not worth doing, ask them on its thread, recording it with `--ask-kind "drop a thread nobody would start today"` and the drop as the recommendation, and on their yes resolve it. One they chose to keep isn't asked about again unless something changed; the review marks it. Leave the rest as they are.
5. Rank the open decide and approve tasks: `backlog.py rank <task> <task> ...`, most important first. The first seven are the client's list.
6. Run `backlog.py report` and post it to the client in one message, where they read the project's news. Each item names its thread, where the card waits. A list of one or two is fine; an empty list says so.
7. Push `backlog/` to the mailbox's `main`.

## The weekly numbers

The report ends with three numbers next to last week's: threads opened and closed, how many wait on the client, and the median and oldest age of open threads. If more open than close two weeks running, the backlog grows however well it is sorted, and the report says so: the fix is to open fewer threads or drop more. The numbers for a past week come from what the record knew then, so the first weeks of a new record start low. Threads resolved in the past week that the record never saw open, such as on a first run or opened and closed between two sweeps, still count as closed.

## How the routine learns

Whenever the client corrects how the routine works for them, or says they like something it did, log it the same day, in their own words:

    backlog.py --project <id> note --kind correct|like --words "their words" --what "what the routine did"

Then run `backlog.py open`. When three open notes say the same thing, put the rule to the client at once, on a decision card where the harness has one: accept, edit or strike, quoting the three notes. A point they state outright in their own words needs no three. An accepted rule goes under "Rules learned" below, in a pull request on `Timothy-Guyon/timmys-tools` that only its owner merges, and `backlog.py used <notes> --rule <number>` marks the notes as counted (`--rule struck` for a struck one). If they overrule a rule twice, or it stops fitting, log a `correct` note naming it and put the change to them the same way. The tools' own weekly review reads this log with the others.

The log is `backlog/LOG.md` in the mailbox repo, beside the records.

## Without the mailbox

An account that can't read the mailbox repo, such as a work account using the public copy, keeps its records and log in `~/.thread-backlog/`, for that place only, and the script says so. Where a session's files don't last, keep the notes in the session. Lessons go back as an issue on `Timothy-Guyon/timmys-tools-public` with its "Rule candidate" template, one rule per issue, in general terms only, since that repository is public.

## Rules learned

None yet.
