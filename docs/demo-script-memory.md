# Demo scripts: memory-focused version

This is the default demo. It spends almost all its time on **shared
memory**: the life of one memory, then proof that it changed the agent's behavior. Role scoping,
skills and the Atlas features get one line each.

| Share | Part | What is shown |
| --- | --- | --- |
| 10% | Opening | Lore is an analyst agent for a retail company; agents forget what the team agreed, so it has shared memory that a person governs |
| 5% | Architecture (optional) | One diagram: Claude plans, the guard checks, MongoDB runs it; memories, skills, episodes, sessions and the audit log in one Atlas cluster |
| 10% | How Lore works | The agent writes and runs MongoDB queries; every session is saved; repeated questions become episodes, then skills; what the team agrees becomes shared memory |
| 50% | The life of a memory, live | Wrong memory (36%) → correction → proposal → reviewer approves → every agent says 1.7% |
| 20% | Proof | Replay with and without memory: a different query and result; eval 4/10 → 10/10 |
| 10% | The rest, one line each | Scoped by role (Vector Search filter), Voyage embeddings, guarded pipelines, skills, one cluster |

The three track questions are still answered: fixing or dropping a memory (the life of a memory),
proving a memory changed behavior (the replay), and no leaks between teams (one line on the last
content slide).

**Deck:** start the app and open `http://localhost:8000/demo` (7 slides, 3:00 timer). The earlier deck,
built around the three track questions, is at `/demo/questions`, with its script in `docs/demo-script.md`.

**Keys:** → / Space next · ← back · **L** open the slide's first live demo · **Esc** back to the slides ·
**F** full screen · **R** reset the timer. Every live run stays open; clicking the same button again
shows its earlier result. **Shift+click** runs it again.

Every number comes from real runs against the shared Atlas cluster on Nov 14.

---

## Before you present

1. **Wrong Net margin active** for all roles, and no pending Net margin proposals. After any
   run-through that approves a correction, put the wrong definition back as a new version
   (propose + approve as Fatima).
2. **Pre-run** on slide 4: **1 · Ask (wrong memory)**, and on slide 5:
   **Replay with and without memory**. Wait for the answers, press Esc each time, go back to slide 1.
3. Only the correction, the approval and "ask again" run live (10–30 s each).

---

## In-person demo: 3-minute slot, 2 minutes of speaking

About 210 words in short sentences: 2 minutes at a slow, clear pace. The other minute is the live
answers on slide 4 (10–30 s each). The time before each slide is when you should reach it.

**0:00 · [1 · Title] · 15 s**
"Hi, we are team Lore. Lore is an analyst agent for a retail company. Staff ask business questions,
and it answers from the sales data in MongoDB Atlas."

**0:15 · [2 · How Lore works] · 20 s**
"Here is how it works. You ask a question. The agent writes a MongoDB query and runs it. Every
session is saved in MongoDB. Repeated questions become episodes, and then skills. And what the team
agrees becomes shared memory."

**0:35 · [3 · Architecture] · 15 s**
"This is the architecture. Claude plans the query, using memories and skills. A guard checks it.
MongoDB runs it. Memories are found with Atlas Vector Search, filtered by role."

**0:50 · [4 · The life of a memory] · 80 s, with three live steps**
*(click 1 · Ask, already run)* "But memory can be wrong. Ours says East's margin is 36%."
*(click 2 · Correct it, wait)* "Fatima corrects it. The agent does not change memory itself. It files
a proposal."
*(in the answer, click Review it now, then Approve, then Approve)* "A reviewer approves the new
version. The old one is kept and audited."
*(Esc, click 4 · Ask again, wait)* "Now every agent says 1.7%. One approval fixed all of them."

**2:10 · [5 · Proof: press L, the result is already there] · 25 s**
"How do we prove memory changed behavior? We replay one question, with and without memory. The query
is different. The result is different. In our eval, accuracy went from 4 out of 10 to 10 out of 10."

**2:35 · [6 · The rest] · 15 s**
"Each memory is scoped by role. Repeated questions become tested skills. All of it runs in one
MongoDB Atlas cluster."

**2:50 · [7 · Thank you]**
"Thank you."

**If you are running long:** skip slide 3 (use it in Q&A), or skip "4 · Ask again" and point at
36% → 1.7% on the slide.

---

## 1-minute video

`demo/lore-demo-1min-memory.mp4` (1080p, captions and voice narration);
`demo/lore-demo-1min-memory-captions-only.mp4` is the same video without sound.

The voice reads exactly what each caption shows, and each caption stays on screen for as long as its
line takes. Every scene is a real run against the shared cluster; typing and waiting are shortened.

| Order | Caption and spoken line | On screen |
| --- | --- | --- |
| 1 | Lore is an analyst agent for a retail company | Title slide |
| 2 | It writes and runs MongoDB queries to answer business questions | "How Lore works" slide, step 1 |
| 3 | Every session is saved in MongoDB | step 2 |
| 4 | Repeated questions become episodes, then skills | step 3 |
| 5 | What the team agrees becomes shared memory | step 4 |
| 6 | But this memory has a wrong definition | Fatima asks for net margin |
| 7 | Every agent says East's margin is 36% | The answer |
| 8 | Fatima, the finance lead, corrects it | She types the correction |
| 9 | The agent files a proposal. Memory does not change yet. | The proposal |
| 10 | A reviewer checks the proposal | Memory review |
| 11 | and approves it for every role | The approval dialog |
| 12 | The old version is kept and audited | Memory review after approval |
| 13 | Now any agent asks again | She asks again |
| 14 | East's margin is 1.7% | The new answer |
| 15 | Proof: the same question, with and without memory | The replay runs |
| 16 | Memory changed the query and the result | The app's comparison |
| 17 | Each memory is scoped by role, an Atlas Vector Search filter | Three roles' memory boxes |
| 18 | Vector Search, Voyage AI, change streams: one Atlas cluster | "The rest" slide |
| 19 | Lore: memory you can govern | Title slide |

The opening, the Atlas line and the closing show slides 1, 2 and 6 of this deck, captured from the
running app each time the video is built, so the video always matches the slides. The live scenes
come from what `scripts/record_demo_video.py` recorded, so no new recording is needed:

```bash
python scripts/narrate_demo_video_memory.py frames out demo/lore-demo-1min-memory-captions-only.mp4 demo/lore-demo-1min-memory.mp4
```

It needs the app running and Microsoft Edge. Change a caption or its order in `CUES` at the top of
that script and run it again; if you change a slide in `web/demo-memory.html`, just run it again. The narration
uses Microsoft's Edge text-to-speech service (voice "Andrew"); only the narration text is sent to it.

---

## Fallback lines

- **An answer is slow:** keep talking, or say "each answer is a real query on Atlas".
- **The network is slow at the venue:** skip the live steps and say the numbers: 36% before, 1.7%
  after the approved correction.
- **The replay shows the same result on both sides:** Shift+click to run it again; the agent
  sometimes picks net revenue without memory.
