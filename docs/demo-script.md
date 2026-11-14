# Demo scripts

The demo answers the three track questions of **Memory You Can Govern**, each with a live proof and
the MongoDB Atlas feature behind it.

| Track question | How Lore answers it | Live proof | Atlas feature |
| --- | --- | --- | --- |
| How do you keep one team's memory from leaking into another's? | Every memory has role rules, applied as Vector Search filters before retrieval | "Why did East's return rate rise in Q3?" asked by all three roles: the East store memory reaches Finance and the store manager, never the analyst | Atlas Vector Search with filters on status, role and expiry; Voyage AI `voyage-4` embeddings |
| How does the agent fix or drop a memory that is wrong or expired? | Corrections create a new version a reviewer approves; expired memories stop being retrieved; forgotten ones keep an audit record | Net margin: 36% with the wrong memory, a correction becomes a proposal, the reviewer approves it, then 1.7% | One document per version; status and expiry as Vector Search filters; an audit collection |
| How do you prove a memory changed behavior? | The same question is replayed with and without the memory, showing a different query and result | "Sales growth by region, August to September": gross revenue without memory, the agreed net revenue definition with it | The agent writes aggregation pipelines; every query is saved; eval 4/10 → 10/10 |

The deck is part of the app. Start the app, then open:

| Version | URL | Slides | Timer |
| --- | --- | --- | --- |
| In-person, 3 minutes | `http://localhost:8000/demo` | 6: title, the three questions, why Atlas, thank you | 3:00 |
| 1 minute | `http://localhost:8000/demo?1min` | 4: title and the three questions | 1:00 |
| Full | `http://localhost:8000/demo?full` | 16, with background slides | 8:00 |

**Keys:** → / Space next · ← back · **L** open the slide's first live demo · **Esc** back to the slides ·
**F** full screen · **R** reset the timer (it starts when you leave the first slide).

**Live buttons** open the real app over the slides, signed in as the right person, with the question
running. Every live run stays open: clicking the same button again shows its earlier result at once,
so slow runs can be done before the talk. **Shift+click** (or Shift+L) runs it again.

Every number comes from real runs against the shared Atlas cluster on Nov 14: East Q3 net margin
36.1% with the wrong definition and 1.7% after the correction, and the eval at 4/10 → 10/10.

---

## Before you present

1. **Wrong Net margin active** for all roles, and no pending Net margin proposals. After any
   run-through that approves a correction, put the wrong definition back as a new version
   (propose + approve as Fatima); approving an older version is blocked.
2. **Pre-run the two slow comparisons** from the deck, wait for the answers, press Esc each time:
   - question 1 slide: **Ask as all three roles**
   - question 3 slide: **Replay with and without memory**
   On the question 2 slide you can also pre-run **1 · Ask (wrong memory)**.
3. Go back to slide 1. During the talk, pressing the same buttons shows the finished results.
4. Answers take 10–30 s each. Only question 2's correction and "ask again" run live.

---

## In-person demo: 3-minute slot, about 1.5 minutes of speaking (`/demo`)

About 175 words, in short sentences.

**0:00 · [1 · Title]**
"Hi, we are team Lore. Lore is shared memory for analyst agents. People govern it. It runs on
MongoDB Atlas."

**0:10 · [2 · Question 1: press L, the results are already there]**
"Question one: how do we stop memory leaking between teams? Three roles ask the same question. A
store memory reaches Finance and the store manager. The analyst never gets it. Every memory has role
rules. They run as Atlas Vector Search filters, on Voyage embeddings."

**0:40 · [3 · Question 2]**
"Question two: how do we fix a wrong memory?"
*(click 1 · Ask)* "Our memory says East's margin is 36%. That is wrong."
*(click 2 · Correct it, wait)* "Fatima corrects it. The agent files a new version, as a proposal."
*(in the answer, click Review it now, then Approve, then Approve)* "A reviewer approves it. The old
version is kept and audited. Expired and forgotten memories are never retrieved."
*(Esc, click 4 · Ask again, wait)* "Now every agent says 1.7%."

**2:05 · [4 · Question 3: press L, the results are already there]**
"Question three: how do we prove memory changed behavior? We replay the same question, with and
without memory. The query is different. The result is different. In our eval, accuracy went from 4
out of 10 to 10 out of 10."

**2:35 · [5 · Why MongoDB Atlas]**
"MongoDB Atlas made this simple: Vector Search, Voyage embeddings, aggregation and change streams, in
one cluster."

**2:50 · [6 · Thank you]**
"Thank you."

**If you are short on time:** skip "4 · Ask again" and say "after approval, every agent says 1.7%".

---

## 1-minute version (`/demo?1min`, about 110 words)

**[1 · Title]** "Lore is shared memory for analyst agents, governed by people, on MongoDB Atlas."

**[2 · Question 1: press L]** "No leaks between teams. Three roles ask one question. The store
memory reaches Finance and the store manager, never the analyst. Role rules are Atlas Vector Search
filters."

**[3 · Question 2]** "Fixing a wrong memory. Memory said East's margin was 36%. Fatima corrected it,
a reviewer approved the new version, and every agent now says 1.7%. Everything is audited."

**[4 · Question 3: press L]** "Proof. The same question, with and without memory, gives a different
query and a different result. Accuracy went from 4 out of 10 to 10 out of 10. Thank you."

Pre-run everything for this version; there is no time for a live answer.

---

## 1-minute video

`demo/lore-demo-1min.mp4` (1080p, 60 seconds, amber captions and voice narration);
`demo/lore-demo-1min-captions-only.mp4` is the same video without sound.

It follows the three track questions. Every scene is a real run against the shared cluster, and only
the waiting time is cut. Typed questions, clicks and key results are highlighted in blue.

| Time | Scene |
| --- | --- |
| 0:00 | Title |
| 0:04 | Question 1, then three roles ask about East's return rate: Finance and the store manager get the East store memory, the analyst does not |
| 0:15 | Question 2, then net margin with the wrong memory (36%), the correction and its proposal, the reviewer's approval, and the new answer (1.7%) |
| 0:41 | Question 3, then the replay with and without memory: a different query and result |
| 0:53 | Why MongoDB Atlas, and the closing card |

To re-record (needs the app running, Microsoft Edge, and
`pip install playwright imageio-ffmpeg edge-tts truststore`):

```bash
python scripts/record_demo_video.py frames title q1 leak q2 wrong correct approve fixed q3 replay atlas
python scripts/record_demo_video.py frames --build demo/lore-demo-1min-captions-only.mp4
python scripts/narrate_demo_video.py frames demo/lore-demo-1min-captions-only.mp4 demo/lore-demo-1min.mp4
```

The `approve` scene approves a real correction. Afterwards, re-add the wrong Net margin as a new
version (propose + approve as Fatima) so the live demo starts uncorrected again. The narration uses
Microsoft's Edge text-to-speech service (voice "Andrew"); only the narration text is sent to it.

---

## Optional: live skill demo (adds about 2 minutes)

Not part of the 3-minute slot. Prep: the learning worker running
(`python -m app.workers.learning`, add `--auto-draft` to have it draft by itself), and two questions
asked beforehand: Alex "Units sold by category in August", Sam "Units sold by category in September".
The Skills tab should show that cluster at 2 episodes, not ready.

1. As Fatima, ask "Units sold by category in October". The worker, watching a MongoDB change stream,
   adds the third episode and the cluster becomes ready.
2. In Skills, click **Draft skill** (or wait for the automatic draft). It is tested by replay and by
   role before it can be published.
3. Click **Publish**.
4. As Sam, ask "Units sold by category in July": the agent reuses the skill, with Sam's permissions,
   so he gets East only.

This flow has not been rehearsed end to end.

---

## Fallback lines

- **An answer is slow:** keep talking, or say "each answer is a real query on Atlas".
- **The network is slow at the venue:** skip the live steps of question 2 and say the numbers:
  36% before, 1.7% after the approved correction.
- **The replay shows the same result on both sides:** Shift+click to run it again; the agent
  sometimes picks net revenue without memory.
