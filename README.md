# Lore

Governed shared memory for analyst agents, built for the **Memory You Can Govern** track.

Analysts ask business questions in plain language. Lore answers from the retail data in MongoDB Atlas.
Corrections become versioned, role-scoped memories that a reviewer approves, expires or forgets, with
every change audited. Repeated analyses become tested skills. Each user only ever sees the rows and
fields their role allows.

Demo company: **Northwind Outfitters**, 20 stores in 4 regions, synthetic data.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in MONGODB_URI, ANTHROPIC_API_KEY, VOYAGE_API_KEY
python -m scripts.generate_sales --drop     # ~243k sales docs (add --products-per-category 3 for a small set)
python -m scripts.setup_indexes             # regular + memory_vec / episode_vec Vector Search indexes
python -m scripts.seed_memories --reset     # starting memories, incl. the deliberately wrong net margin
uvicorn app.main:app --reload               # http://localhost:8000
python -m app.workers.learning              # optional: turns sessions into episodes (change stream)
pytest -q                                   # runs offline: mongomock + hash embeddings
```

Offline dev without Atlas or Voyage: set `EMBEDDING_PROVIDER=hash` and `VECTOR_BACKEND=local`, and point
`MONGODB_URI` at a local `mongod`.

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
web/                 index.html, app.js, style.css: analyst, reviewer and audit views
scripts/             generate_sales, setup_indexes, seed_memories, expected_answers, run_eval
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
| GET | `/api/skills` · `/api/skills/clusters` | Skill library and episode clusters |
| POST | `/api/skills/generate` · `/api/skills/{name}/publish` · `/retire` | Draft (manual trigger), publish, retire |
| GET | `/api/audit` | Recent audit events (reviewers see all; others see their own) |

## Workstreams

Framework only: each piece runs end to end at a starter level. Owners take it from here.

| Workstream | Owner | Files | Next steps |
| --- | --- | --- | --- |
| Data and access | | `scripts/generate_sales.py`, `scripts/expected_answers.py`, `app/guard.py`, `app/audit.py`, `app/users.json` | Tune the generator so the planted patterns are clear; fill expected answers for all 8 demo questions; create the read-only Atlas user; confirm Sandbox vector index limit |
| Analyst agent | | `app/agent.py`, `app/llm.py`, `app/routes/ask.py`, `scripts/run_eval.py` | Run demo questions 1–8 end to end; tune prompts until accuracy holds; make the replay show a different query and answer |
| Memory governance | | `app/memory.py`, `app/routes/memories.py`, `scripts/seed_memories.py` | Verify Vector Search filters on the Sandbox; confirm the visibility rule for proposals; leak tests through memory |
| Skills and interface | | `app/skills.py`, `app/workers/learning.py`, `app/routes/skills.py`, `web/` | Generate 3 episodes from 2 users, draft and publish one skill; polish the analyst and reviewer views for the demo |

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
- **`/api/replay`** is an addition for the interface; the contract replay (calling `/api/ask` twice) still works.
- **Vector Search filter on `expires_at: null`** needs checking on the Sandbox; retrieval re-checks
  expiry in code either way.
