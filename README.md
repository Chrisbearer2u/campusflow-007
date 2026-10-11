# CampusFlow

A text-based helpdesk for **Learn2Earn** campus staff to record and track technical
support requests.

## Problem statement

Support requests on campus — Wi-Fi outages, faulty laptops, broken development
environments, platforms nobody can log into — are currently reported informally:
a message here, a comment in a corridor there. Requests get lost, duplicated, or
quietly forgotten, and nobody can answer the two questions that matter most:
*what is outstanding?* and *what should be worked on next?*

CampusFlow gives those reports a home. Staff log a ticket in under a minute, the
app works out how urgent it is, and a prioritised work queue plus simple reports
make the state of campus support visible at a glance. It is deliberately
dependency-free — Python's standard library only — so it runs on any campus
machine with a Python interpreter.

## Requirements and setup

* **Python 3.9 or newer** (developed and tested on 3.13). No third-party packages.
* Nothing to install. Clone or copy the project directory and you are ready:

```bash
git clone <repository-url> campusflow
cd campusflow
```

Optionally, work inside a virtual environment:

```bash
python3 -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

## Running the CLI

From the project root:

```bash
python3 main.py
```

To keep a separate store — useful for demos, experiments or a second campus:

```bash
python3 main.py path/to/other-tickets.json
```

### Menu options

| Option | What it does |
| ------ | ------------ |
| 1 | **Create a ticket** — prompts for title, category, urgency and affected users. |
| 2 | **List all tickets** — summary table of every ticket, ordered by ticket id. |
| 3 | **View one ticket in full** — every field for one ticket id. |
| 4 | **Assign a ticket** to a staff member by name. |
| 5 | **Update a ticket's status** — start work, resolve, or reopen. |
| 6 | **Show the work queue** — unresolved tickets, most urgent first. |
| 7 | **Show reports** — totals by status and by priority. |
| 8 | **Save now** — writes the store to disk on demand. |
| 9 | **Exit** — saves and leaves. |

The menu loops until you choose Exit. Every successful change is written to disk
immediately, so option 8 is a convenience rather than a necessity. `Ctrl+C` at a
prompt saves and exits; an invalid entry prints an error and returns you to the
menu without changing anything.

## Ticket fields

```json
{
  "id": "T001",
  "title": "Campus Wi-Fi is down",
  "category": "Network",
  "urgency": "high",
  "affected_users": 15,
  "priority": "critical",
  "status": "open",
  "assigned_to": null
}
```

| Field | Rules |
| ----- | ----- |
| `id` | Generated automatically: `T001`, `T002`, … Unique and sequential, and it stays unique after a reload. Lookups accept loose input (`t7` finds `T007`). |
| `title` | Free text, must not be blank once whitespace is stripped. |
| `category` | One of `Network`, `Hardware`, `Software`, `Other`. Input is case-insensitive and normalised to the canonical spelling. |
| `urgency` | One of `low`, `medium`, `high`. Case-insensitive, stored lowercase. |
| `affected_users` | A positive whole number. Zero, negatives, decimals (`2.5`), text and booleans (`true`/`false`) are all rejected. |
| `priority` | Calculated, never entered by hand (see below). |
| `status` | `open` → `in_progress` → `resolved`. New tickets start `open`. |
| `assigned_to` | A staff name, or `null` while unassigned. |

Invalid input produces a specific error message (for example *"Affected users must
be greater than zero, got 0."*) and leaves the stored data exactly as it was — no
partial ticket, and no ticket id consumed.

## How priority works

The rules are applied **in order** and the first match wins:

| Order | Condition | Priority |
| ----- | --------- | -------- |
| 1 | high urgency **and** ≥ 10 affected users | `critical` |
| 2 | high urgency **or** ≥ 10 affected users | `high` |
| 3 | medium urgency **or** ≥ 3 affected users | `medium` |
| 4 | anything else | `low` |

Worked examples:

| Urgency | Users | Priority | Why |
| ------- | ----- | -------- | --- |
| high | 12 | critical | Rule 1 |
| high | 2 | high | Rule 2 (urgency) |
| low | 10 | high | Rule 2 (user count) |
| low | 4 | medium | Rule 3 (user count) |
| medium | 2 | medium | Rule 3 (urgency) |
| low | 1 | low | Rule 4 |

## How status and assignment work

```
open --(start work)--> in_progress --(resolve)--> resolved
 ^                                                    |
 +---------------------(reopen)------------------------+
```

* A ticket **cannot start work while unassigned** — assign it to a staff member first.
* A ticket **cannot jump from open straight to resolved**; it must be in progress.
* A **resolved ticket is frozen**: it cannot be started, resolved again or
  reassigned until it is reopened. Reopening sets the status back to `open` and
  keeps the existing assignee.
* Every other transition is rejected with a message naming the allowed ones.

## Reports and the work queue

* **Reports** show the total number of tickets, counts by status and counts by
  priority. An empty store reports zeros rather than crashing.
* The **work queue** shows only unresolved tickets (`open` and `in_progress`),
  ordered by priority (`critical` → `high` → `medium` → `low`) and, where
  priorities tie, by the earlier numeric ticket id (`T002` before `T010`).

## Where tickets are saved

Tickets are stored as JSON at **`data/tickets.json`**, relative to the project
root regardless of the directory you launch from. The file is created on the
first save.

**To start fresh, delete or rename that file** — a missing file simply means an
empty store:

```bash
rm data/tickets.json                     # macOS / Linux
Remove-Item data\tickets.json            # Windows PowerShell
mv data/tickets.json data/tickets.bak    # or keep the old one aside
```

Saving is atomic: tickets are written to a temporary file in the same directory,
flushed to disk, and then moved over the target. A crash mid-save leaves either
the old file or the new one, never a half-written mixture. If `data/tickets.json`
exists but cannot be parsed, CampusFlow reports the problem and **refuses to
start**, so the unreadable file is never overwritten.

## Running the tests

From the project root:

```bash
python3 -m unittest discover -s tests -v
```

`main.py` is deliberately not covered — the suite targets the package modules,
where all the behaviour lives. The tests use `tempfile` for their own throwaway
data directories and never read or write your real `data/tickets.json`.

What is covered:

* **`tests/test_tickets.py`** — the four priority rules and their boundaries
  (exactly 10 users, exactly 3 users), every rejection case for affected users
  (zero, negative, decimal, text, boolean), blank titles, category and urgency
  normalisation, malformed ticket ids, sequential id generation, and that a
  rejected input leaves the store untouched with no id consumed.
* **`tests/test_workflow.py`** — assignment and reassignment, blank staff names,
  unknown ticket ids, the unassigned ticket that refuses to start, the full
  `open → in_progress → resolved` path, the frozen resolved state, reopening,
  every invalid transition, and the work queue's priority and numeric tie-break
  ordering.
* **`tests/test_storage.py`** — save/reload round trips, a missing file starting
  an empty store, corrupt and structurally invalid JSON raising a clear error
  while leaving the file byte-for-byte intact, no temporary files left behind,
  unicode preservation, and that creating a ticket after a reload neither
  duplicates nor reuses ids.

## Project layout

```
campusflow/
├── README.md
├── .gitignore
├── main.py                  # the menu loop; no validation logic of its own
├── campusflow/
│   ├── __init__.py
│   ├── tickets.py           # model, validation, priority calculation
│   ├── workflow.py          # assignment, status transitions, work queue
│   ├── storage.py           # atomic JSON load/save, error handling
│   └── reports.py           # summary statistics
└── tests/
    ├── test_tickets.py
    ├── test_workflow.py
    └── test_storage.py
```

## Known limitations

* **Single user, single machine.** There is no locking and no server; two
  people editing the same file at once can lose one another's changes.
* **No authentication.** Assignee names are free text, not accounts, so nothing
  stops a typo like `Adaa Lovelace`. Renaming someone means editing the tickets.
* **No history or audit trail.** Only the current state of a ticket is kept —
  who changed what, and when, is not recorded.
* **No dates.** Tickets have no created/updated/resolved timestamps, so there is
  no ageing or "oldest unresolved" view.
* **No deletion or editing.** Tickets can be assigned and moved through the
  lifecycle, but a mistyped title or a ticket raised by mistake cannot be
  corrected from the menu; that needs a hand edit of the JSON, with the app
  closed.
* **No search or filtering.** Listing shows everything; there is no filter by
  category, assignee or status.
* **Monolithic JSON file.** Fine for hundreds of tickets, but the whole store is
  read and rewritten on every change.

## Possible future improvements

* Timestamps (`created_at`, `updated_at`, `resolved_at`) and an ageing report.
* Edit and delete a ticket, with a confirmation prompt.
* Filter and search the list by category, assignee, status or free text.
* A ticket history log so changes can be reviewed.
* Per-staff workload and "time to resolve" statistics.
* Named staff accounts to complement free-text assignment.
* CSV export for reporting, and an optional `--file` flag on `main.py`.
* File locking, or a move to SQLite, if CampusFlow ever needs several users at once.
