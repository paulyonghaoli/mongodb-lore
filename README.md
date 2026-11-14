# Lore

Governed shared memory for analyst agents, built for the **Memory You Can Govern** track.

Analysts ask business questions in plain language. Lore answers from the retail data in MongoDB Atlas.
Corrections become versioned, role-scoped memories that a reviewer approves, expires or forgets, with
every change audited. Repeated analyses become tested skills. Each user only ever sees the rows and
fields their role allows.

Demo company: **Northwind Outfitters**, 20 stores in 4 regions, synthetic data.

The net-margin memory-on/off demo uses `fatima` (finance lead), who can read `supplier_cost`.
`alex` and `sam` remain restricted from that field; shared memory visibility never grants data access.
Running `python -m scripts.seed_memories` without `--reset` also ensures the active baseline net-margin
memory is visible to every demo role and adds the shared access decision memory.

## Quick start

Python 3.12 or newer.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in MONGODB_URI, ANTHROPIC_API_KEY, VOYAGE_API_KEY
```

**The database is already loaded** (the team's shared Sandbox): start the app and open it.

```bash
uvicorn app.main:app --reload               # http://localhost:8000
```

**The database is empty** (your own cluster): load it once, then start the app as above.

```bash
python -m scripts.generate_sales --drop     # ~243k sales docs (add --products-per-category 3 for a small set)
python -m scripts.setup_indexes             # regular + memory_vec / episode_vec Vector Search indexes
python -m scripts.seed_memories --reset     # starting memories, incl. the deliberately wrong net margin
uvicorn app.main:app --reload               # http://localhost:8000
python -m app.workers.learning              # optional: turns newly answered questions into episodes (change stream)
python -m app.workers.learning --backlog    # the same, plus older questions never processed (one model call each)
python -m scripts.monthly_memory_review     # previous month; creates reviewer queues and pending memory proposals
pytest -q                                   # runs offline: mongomock + hash embeddings
```

`--drop` replaces the `sales` collection, and `--reset` clears memories, sessions, episodes, skills and the
audit log. Never run either against a database other people are using.

Offline dev without Atlas or Voyage: set `EMBEDDING_PROVIDER=hash` and `VECTOR_BACKEND=local`, and point
`MONGODB_URI` at a local `mongod`.

## Using the interface

Open http://localhost:8000. Choose who you are under **Signed in as** (top right). The tags beside it show
that user's role, row filter and hidden fields, and every request is sent as that user.

| Tab | What it is for |
| --- | --- |
| Analyst | Ask a question. The card shows the answer, the rows, the permissions applied and the memory in context. |
| Memory review | Every memory by status. The reviewer (Fatima) approves, rejects, expires and forgets. Other users see only the memories visible to their role. |
| Skills | Episode clusters and the skill library. The reviewer drafts a skill from a ready cluster, then publishes or retires it. |
| Audit log | Every query and every change to memory or skills. The reviewer sees all events, other users their own. |

The **Question templates** under the ask box hold the demo questions; a template with a name on it signs in
as that user first. Three to try:

1. *Return rate by region in Q3*, then **Across all roles**: the store manager's answer covers East only.
2. *Why did East's return rate rise in Q3?*, then **Across all roles**: the East return window memory reaches
   the finance lead and the store manager, and not the analyst.
3. *What were October sales by region, on the basis we use for Q4 targets?*, then **With and without memory**:
   with memory the agent applies the Q4 targets basis, and without it there is no agreed basis to use.

Steps 2 and 3 rely on memories that `scripts.synthesize_activity` creates. The interface marks those records
as sample data.

## How a question flows

1. `app/users.py` builds the **user context** from the `X-User` header (users fixed in `app/users.json`).
2. `app/memory.py` retrieves memories: Vector Search filtered by `status: active`, role in `visibility`,
   and not expired, plus direct title matching; every rule is re-checked in code.
3. `app/agent.py` asks Claude for a plan (structured JSON: interpretation, pipeline, metrics, skill,
   proposed memory). The model never runs anything.
4. `app/guard.py` validates the pipeline: `sales` only, allowlisted stages, banned operators, no hidden
   fields; prepends the row filter `$match` and `$unset` of hidden fields; caps rows.
5. Code runs the pipeline, Claude explains the permitted rows, and the session turn (no result rows)
   and an audit event are saved.

## Layout

```
app/
  main.py            FastAPI app, mounts routes and web/
  config.py db.py    settings (.env) and Mongo handles (business data can use a read-only user)
  models.py          shared document shapes (user context, agent output, request bodies)
  users.json users.py   the three demo users and the X-User dependency
  guard.py           query guard
  audit.py           audit log writer/reader
  memory.py          memory lifecycle + governed retrieval
  embeddings.py      Voyage embeddings (hash fallback for tests)
  llm.py             Anthropic SDK wrapper (one model ID from LORE_MODEL)
  agent.py           plan -> guard -> run -> explain -> save turn
  skills.py          episodes, clustering, skill drafting/testing/publishing
  workers/learning.py   change-stream worker: session turn -> episode
  routes/            ask.py, memories.py, skills.py, audit.py (one router per workstream)
web/                 index.html, app.js, style.css: analyst, memory review, skills and audit views
scripts/             generate_sales, setup_indexes, seed_memories, synthesize_activity, check_data,
                     expected_answers, run_eval
tests/               guard, memory governance and skills tests (offline)
```

## REST API

All calls send `X-User: fatima | alex | sam`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/ask` | `{question, session_id, use_memory}` → agent output + `answer`, `columns`, `rows`, `memories_used`, `skill_used`, `governance` |
| POST | `/api/replay` | Same question without and with memory, side by side |
| GET | `/api/memories?status=` | Memories the user can see |
| POST | `/api/memories/{id}/approve` · `reject` · `expire` · `forget` | Reviewer actions (`{reason}` for reject/forget) |
| POST | `/api/memory-review/run?month=YYYY-MM` | Scan one month (defaults to the previous complete month) |
| GET | `/api/memory-review/runs` · `/items?batch_id=&item_type=&status=` | Monthly query and memory review queues (reviewers only) |
| POST | `/api/memory-review/items/{item_id}/delete` · `/retain` | Reviewer confirms query deletion / memory forgetting, or keeps the item |
| GET | `/api/skills` · `/api/skills/clusters` | Skill library and episode clusters |
| GET | `/api/skills/clusters/{id}/episodes` · `/api/skills/learning` | The questions behind a cluster (reviewer only); what became of answered turns |
| POST | `/api/skills/generate` · `/api/skills/{name}/publish` · `/retire` | Draft (manual trigger), publish, retire |
| GET | `/api/audit` | Recent audit events (reviewers see all; others see their own) |

## Workstreams

Framework only: each piece runs end to end at a starter level. Owners take it from here.

| Workstream | Owner | Files | Next steps |
| --- | --- | --- | --- |
| Data and access | Jimmy | `scripts/generate_sales.py`, `scripts/expected_answers.py`, `app/guard.py`, `app/audit.py`, `app/users.json` | Tune the generator so the planted patterns are clear; fill expected answers for all 8 demo questions; create the read-only Atlas user; confirm Sandbox vector index limit |
| Analyst agent | Paul | `app/agent.py`, `app/llm.py`, `app/routes/ask.py`, `scripts/run_eval.py` | Run demo questions 1–8 end to end; tune prompts until accuracy holds; make the replay show a different query and answer |
| Memory governance | Chloe | `app/memory.py`, `app/routes/memories.py`, `scripts/seed_memories.py` | Verify Vector Search filters on the Sandbox; confirm the visibility rule for proposals; leak tests through memory |
| Skills and interface | Yue | `app/skills.py`, `app/workers/learning.py`, `app/routes/skills.py`, `web/` | Generate 3 episodes from 2 users, draft and publish one skill; polish the analyst and reviewer views for the demo |

Checkpoint: by **1:00 PM**, two roles get correctly different answers from the same question.

## Working rules

- Short-lived branches, merge to `main` on the hour. Change a shared shape in `app/models.py` only after
  telling the owners who read it.
- Fake nothing: every number and behavior change in the demo comes from a real run.
- No secrets in commits; `.env` is git-ignored.

## Open questions in the code

- **Proposal visibility.** The contracts say a user cannot propose wider visibility than their own role.
  Current rule: non-reviewers propose for their own role only, and the reviewer can widen it on approve
  (`memory.propose`). Confirm with the team.
- **`/api/replay`** is a convenience route. The interface runs the contract replay itself: two `/api/ask`
  calls in parallel, one with `use_memory: false`, each in a new session.
- **Vector Search filter on `expires_at: null`** needs checking on the Sandbox; retrieval re-checks
  expiry in code either way.

### Monthly memory review

Schedule `python -m scripts.monthly_memory_review` monthly (for example, on day 1). It scans all
session queries from the previous complete calendar month, places each query in a reviewer retention
queue, and asks the LLM to draft only explicit, reusable definitions or facts found in those turns.
Drafts enter `memories` as `pending`; they do not affect retrieval until approved. Active memories not
used during the scanned month are listed as review candidates, never deleted automatically. Reviewers
can keep or delete each query, and keep or forget each candidate memory. Deleting a query removes its
session and episode, scrubs its question and pipeline from the query audit event, and retires skills
that depended on its episode. A small audit event remains. Memory forgetting follows the existing
governance path and preserves its audit record.

Example cron entry (replace the paths with the project's checkout and Python environment):

```cron
0 2 1 * * cd /path/to/mongodb-lore && /path/to/venv/bin/python -m scripts.monthly_memory_review
```
