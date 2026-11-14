# Demo scripts

The deck is part of the app. Start the app, then open:

| Version | URL | Slides | Timer |
| --- | --- | --- | --- |
| 1 minute | `http://localhost:8000/demo?1min` | 4 | 1:00 |
| 3 minutes | `http://localhost:8000/demo` | 6 | 3:00 |
| Full | `http://localhost:8000/demo?full` | 13 | 8:00 |

**Keys:** → / Space next · ← back · **L** open the slide's live demo · **Esc** back to the slides ·
**F** full screen · **R** reset the timer. The timer starts when you leave the first slide.

**Live buttons** open the real app over the slides, signed in as the right person, with the
question filled in or already running. Reopening the same button shows the run already on screen,
so you can run a slow comparison before the talk and just press **L** during it.

Every number in these scripts comes from real runs against the shared Atlas cluster on Nov 14:
East Q3 net margin 36.1% with the wrong definition and 1.7% after the correction, East's Q3 return
rate 34.9%, and the eval at 4/10 → 10/10 with memory.

---

## Before you present

1. **Wrong Net margin active** for all roles (the correction must still be possible). In Memory
   review, approve the pending Net margin with the **highest version number**; older pending ones
   are stale test proposals. After any
   rehearsal that approves a correction, put the wrong definition back as a new version
   (propose + approve as Fatima); approving an older version is blocked.
2. **Learning worker running** (`python -m app.workers.learning`, add `--auto-draft` to have it
   draft the skill by itself) if you show the skill demo.
3. **Skill demo prep** (skill demo only): Alex asks "Units sold by category in August" and Sam asks
   "Units sold by category in September". The Skills tab should show that cluster at
   2 episodes, not ready.
4. **Pre-run the slow comparison:** on the three-roles slide, click **Run across all roles**, wait for
   all three answers, press Esc, go back to slide 1.
5. Answers take 10–30 s each. The lines in *italics* below are written to fill that wait.

---

## 1-minute version (`/demo?1min`, about 140 words)

**[1 · Lore]**
"Analyst agents have a memory problem. They reinvent metric definitions every time, corrections
vanish, and nothing stops them from showing data a user shouldn't see. Lore fixes that with
shared memory that a human governs."

**[2 · Three roles: press L, the results are already on screen]**
"Here's the same question from three roles. Finance sees everything. The analyst can't see
supplier cost. The East store manager only gets East. Every query goes through a guard before it
touches MongoDB."

**[3 · 36.1% → 1.7%]**
"Memory is shared, so a wrong definition spreads to every agent. Here, East looked healthy at 36%.
A finance lead corrected it, a reviewer approved it, and every agent now reports 1.7%. Every step
is versioned and audited."

**[4 · Eval]**
"And we measured it: with the corrected memory, accuracy went from 4 out of 10 to 10 out of 10.
Built on MongoDB Atlas and Vector Search. Thank you."

---

## In-person demo: 3-minute slot, 1.5 minutes of speaking (`/demo`, 6 slides)

About 160 words in short sentences. The rest of the 3 minutes is the live answers (10–30 s each):
stay quiet or use the *italic* lines while they load.

**0:00 · [1 · Title]**
"Hi, we are team Lore. Analyst agents forget definitions and show too much data. Lore gives them
shared memory that people govern."

**0:10 · [2 · Three roles: press L, the results are already on screen]**
"One question, three roles. Fatima is finance: she sees everything. Alex is an analyst: no supplier
cost. Sam manages East stores: he sees only East. A guard checks every query before MongoDB runs it."

**0:40 · [3 · The correction: click Make the correction]**
"Our shared memory has a wrong definition. It says East's margin is 36%. Fatima corrects it: net
margin must subtract returns."
*(answer appears)* "The agent does not change memory itself. It files a proposal."
*(click Review it now, then Approve on the pending Net margin with the highest version, then Approve)*
"The reviewer approves it for every role. The old version is kept. Every step is audited."

**1:50 · [4 · After approval: click Ask again]**
"Now we ask again." *(answer appears)* "Every agent says 1.7%. One approval fixed all agents."

**2:25 · [5 · The eval]**
"We measured it. With memory, accuracy went from 4 out of 10 to 10 out of 10. Repeated questions
also become tested skills."

**2:45 · [6 · Thank you]**
"Lore is built on MongoDB Atlas and Vector Search. Thank you."

**If you are short on time:** skip slide 4's live run and point at 36.1% → 1.7% on the slide.

---

## 1-minute video

`demo/lore-demo-1min.mp4` (1080p, 59 seconds, amber captions and voice narration);
`demo/lore-demo-1min-captions-only.mp4` is the same video without sound.

Every scene is a real run against the shared cluster: the three-role comparison, the wrong 36%
answer, Fatima's correction and the agent's proposal, the reviewer's approval, and the 1.7% answer
citing the new version. Only the waiting time is cut. Typed questions, clicks and key rows are
highlighted in blue.

To re-record (needs the app running, Microsoft Edge, and `pip install playwright imageio-ffmpeg edge-tts truststore`):

```bash
python scripts/record_demo_video.py frames title problem roles wrong correct approve fixed skills proof
python scripts/record_demo_video.py frames --build demo/lore-demo-1min-captions-only.mp4
python scripts/narrate_demo_video.py frames demo/lore-demo-1min-captions-only.mp4 demo/lore-demo-1min.mp4
```

The `approve` scene approves a real correction. Afterwards, re-add the wrong Net margin as a new
version (propose + approve as Fatima) so the live demo starts uncorrected again. The narration uses
Microsoft's Edge text-to-speech service (voice "Andrew"); only the narration text is sent to it.

---

## Full version with the live skill demo (about 4½ minutes)

Slides 1–4 as in the in-person demo (to about 2:20), then, in the app:

**2:20 · [Skills tab: the "units sold" cluster at 2 episodes]**
"Lore also learns from repetition. Alex and Sam have each asked for units sold by category, for
different months. Each answered question became an episode: the pattern, its parameters and the
query. Two isn't enough to trust yet."

**2:35 · [As Fatima, ask "Units sold by category in October"]**
"Fatima asks the same kind of question for October.
*When it's answered, a worker watching MongoDB's change stream turns it into a third episode.*
*(Skills tab)* Three episodes from three people: the cluster is ready."

**3:05 · [Draft skill]**
If the worker runs with `--auto-draft`, the draft appears on its own once the cluster is ready; then
say "The worker drafted it automatically; a reviewer still has to publish it." Otherwise:
"She drafts it. Claude turns the three queries into one template with the month as a parameter.
*Lore tests it before anyone can use it: it replays the original questions and checks the numbers
match, then runs it as every role to make sure nobody sees more than they should. A skill stores
logic, never results.*"

**3:40 · [Publish]**
"Tests pass, she publishes it, and that's audited too."

**3:50 · [As Sam, ask "Units sold by category in July"]**
"Sam asks for July. The agent doesn't write a new query: it reuses the skill Fatima just approved,
and because skills run with the asker's permissions, Sam gets East only."

**4:15 · [The eval]** and **4:30 · [Thank you]** as in the in-person demo.

The skill demo has not been rehearsed yet: run it once end to end before presenting.

---

## Fallback lines

- **An answer is slow:** keep talking over the italic lines.
- **The network is slow at the venue:** skip the live run on "After approval" and point at the
  36.1% → 1.7% on the slide.
- **The cluster isn't Ready after Fatima's question:** "The worker is still processing." Show the
  Audit log, then refresh Skills.
- **Sam's answer doesn't use the skill:** "The agent chose to plan it fresh this time; the skill is
  published and offered to him." Show it in the Skills tab.
