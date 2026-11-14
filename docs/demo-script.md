# Demo scripts

The deck is part of the app. Start the app, then open:

| Version | URL | Slides | Timer |
| --- | --- | --- | --- |
| 1 minute | `http://localhost:8000/demo?1min` | 4 | 1:00 |
| 3 minutes | `http://localhost:8000/demo` | 8 | 3:00 |
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

1. **Wrong Net margin active** for all roles (the correction must still be possible). After any
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

## 3-minute version (`/demo`)

**0:00 · [1 · Title]**
"We built Lore: governed shared memory for analyst agents, for the Memory You Can Govern track. Our
demo company is Northwind Outfitters, a retailer with 20 stores in 4 regions."

**0:10 · [2 · The problem]**
"Analyst agents have three problems. Every answer reinvents the definitions: ask 'is sales up?'
twice and you might get gross revenue once and net revenue the next. Corrections disappear: a
finance lead fixes a metric in one chat, and no one else's agent ever learns it. And everyone sees
everything, unless something stops them."

**0:30 · [3 · Three roles: Run across all roles, or L if pre-run]**
"Here's one question, return rate by region in Q3, asked by three people. Fatima is the finance
lead and sees everything. Alex is an analyst and can't see supplier cost. Sam manages East stores
and only sees East.
*The model only plans. Our code checks every pipeline, adds the user's row filter and removes
hidden fields before MongoDB runs it.*
Same question, three correct answers. Sam's covers East only."

**1:10 · [4 · Wrong definition]**
"Shared memory is powerful, so a wrong definition is dangerous. Ours says net margin ignores
returns, so every agent tells us East's Q3 margin is a healthy 36%."

**1:25 · [5 · The correction: Make the correction]**
"Fatima says net margin must subtract returns. The agent answers with her definition right away,
but it doesn't change shared memory on its own. It files a proposal.
*(Open Memory review, approve for every role)* The reviewer approves it for every role. The old
version is superseded, not deleted, and both steps go into the audit log."

**2:00 · [6 · After approval: Ask again]**
"Now any agent asking the same question gets 1.7%. East's 35% return rate was eating its margin.
One approval fixed every agent's answer."

**2:35 · [7 · The eval]**
"This isn't a one-off. On our eval, with the wrong definition in memory, accuracy with memory was 4
out of 10. After the approved correction: 10 out of 10. Memory also fixed questions like sales
growth, which the agent gets wrong on its own."

**2:50 · [8 · Thank you]**
"Lore runs on MongoDB Atlas: Vector Search with role and expiry filters for memory, guarded
aggregation for every query, and the audit log beside it. Built by Jimmy, Paul, Chloe and Yue.
Thank you."

---

## Full version with the live skill demo (about 4½ minutes)

Slides 1–6 as in the 3-minute version (0:00–2:20), then:

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

**4:15 · [7 · The eval]** and **4:30 · [8 · Thank you]** as in the 3-minute version.

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
