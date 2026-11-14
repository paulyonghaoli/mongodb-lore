"""Record the 1-minute demo video scene by scene against the running app (real answers, real database).

Needs the app on localhost:8000, Microsoft Edge, and: pip install playwright imageio-ffmpeg
The "approve" scene approves a real correction: afterwards, re-add the wrong Net margin as a new
version (propose + approve as Fatima) so the live demo starts uncorrected again.

python record.py <out_dir> scene1 [scene2 ...]     # record scenes (frames + manifest per scene)
python record.py <out_dir> --build out.mp4         # assemble all recorded scenes, in ORDER
"""
import json
import pathlib
import subprocess
import sys
import time

BASE = "http://localhost:8000"
W, H, SCALE = 1280, 720, 1.5
ORDER = ["title", "problem", "roles", "wrong", "correct", "approve", "fixed", "skills", "proof"]

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

CSS = """
/* Captions: one amber bar on every page, above a soft scrim so it always stands out */
#__cap { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 2147483647;
  max-width: 1120px; width: max-content; padding: 13px 30px; border-radius: 14px; text-align: center;
  background: #ffd54a; color: #14110a; font: 700 25px/1.3 system-ui, "Segoe UI", sans-serif;
  box-shadow: 0 8px 34px rgba(0,0,0,.7), 0 0 0 3px rgba(20,17,10,.85); margin: 0; }
#__cap b { color: #a3140a; }
#__scrim { position: fixed; left: 0; right: 0; bottom: 0; height: 190px; z-index: 2147483646; pointer-events: none;
  background: linear-gradient(to top, rgba(0,0,0,.82), rgba(0,0,0,0)); }
.controls, .progress { display: none !important; }
::-webkit-scrollbar { display: none; }
/* Highlights are blue so they never compete with the amber captions */
.__ring { outline: 3px solid #4fd1ff !important; outline-offset: 4px; border-radius: 6px;
  box-shadow: 0 0 0 7px rgba(79,209,255,.22) !important; }
tr.__ring { outline: none !important; box-shadow: none !important; }
tr.__ring td { background: rgba(79,209,255,.20) !important; box-shadow: inset 0 2px 0 #4fd1ff, inset 0 -2px 0 #4fd1ff; }
/* What the user types or clicks */
.__input { outline: 3px solid #4fd1ff !important; outline-offset: 2px;
  box-shadow: 0 0 0 8px rgba(79,209,255,.28), 0 0 26px rgba(79,209,255,.55) !important; }
"""


class Scene:
    def __init__(self, page, name):
        self.page, self.name, self.frames = page, name, []
        for old in OUT.glob(f"{name}_*.png"):
            old.unlink()

    def snap(self, dur):
        path = OUT / f"{self.name}_{len(self.frames):03d}.png"
        self.page.screenshot(path=str(path))
        self.frames.append([path.name, dur])

    def setup(self):
        self.page.add_style_tag(content=CSS)

    def goto(self, url):
        self.page.goto(BASE + url)
        self.page.wait_for_load_state("networkidle")
        self.setup()

    def caption(self, html):
        # An open <dialog> sits in the top layer and dims everything else, so the caption moves into it
        self.page.evaluate("""(h) => { let c = document.getElementById('__cap');
            if (!c) { c = document.createElement('div'); c.id = '__cap'; }
            if (!document.getElementById('__scrim')) {
              const g = document.createElement('div'); g.id = '__scrim'; document.body.append(g); }
            const host = document.querySelector('dialog[open]') || document.body;
            if (c.parentElement !== host) host.append(c);
            c.innerHTML = h; c.style.display = h ? '' : 'none'; }""", html)

    def mark(self, selector, on=True):
        """Highlight something the user types into or clicks."""
        self.page.evaluate("""([sel, on]) => { document.querySelectorAll('.__input').forEach(e => e.classList.remove('__input'));
            if (on) document.querySelector(sel)?.classList.add('__input'); }""", [selector, on])

    def click(self, selector, hold=0.45):
        self.mark(selector)
        self.snap(hold)
        self.page.locator(selector).click()
        self.mark(selector, False)

    def type_question(self, text):
        box = self.page.locator("#question")
        box.click()
        box.fill("")
        self.page.evaluate("() => { window.scrollTo(0, 0); document.querySelectorAll('.__ring').forEach(e => e.classList.remove('__ring')); }")
        self.mark("#question")
        for i in range(0, len(text), 3):
            box.press_sequentially(text[i:i + 3])
            self.snap(0.07)
        self.snap(0.4)

    def wait_answers(self, timeout=150):
        self.snap(0.9)  # the "Planning, running and explaining…" state
        self.page.wait_for_function(
            "() => document.querySelector('#results .card') && !document.querySelector('#results .waiting')",
            timeout=timeout * 1000)
        time.sleep(0.4)

    def ring(self, js_find):
        """js_find: JS expression returning elements to highlight (also scrolls the first into view)."""
        self.page.evaluate(f"""() => {{ const els = [...{js_find}].filter(Boolean);
            document.querySelectorAll('.__ring').forEach(e => e.classList.remove('__ring'));
            els.forEach(e => e.classList.add('__ring'));
            if (els[0]) els[0].scrollIntoView({{block: 'center'}}); return els.length; }}""")

    def scroll_to(self, y, steps=6):
        y0 = self.page.evaluate("() => window.scrollY")
        for i in range(1, steps + 1):
            self.page.evaluate("(y) => window.scrollTo(0, y)", y0 + (y - y0) * i / steps)
            self.snap(0.06)

    def save(self):
        (OUT / f"{self.name}.json").write_text(json.dumps(self.frames))
        print(f"scene {self.name}: {len(self.frames)} frames, {sum(d for _, d in self.frames):.1f}s")


EAST_ROWS = "[...document.querySelectorAll('#results tr')].filter(r => [...r.cells].some(c => c.textContent.trim() === 'East'))"
Q_MARGIN = "What was net margin by region in Q3?"


def scene_title(s):
    s.goto("/demo?full#1")
    s.caption("Shared memory for analyst agents, <b>governed by people</b>")
    s.snap(4.0)


def scene_problem(s):
    s.goto("/demo?full#2")
    s.caption("Agents forget definitions, lose corrections, and overshare")
    s.snap(4.5)


def scene_roles(s):
    s.goto("/?user=fatima#analyst")
    s.caption("One question, asked by <b>three roles</b>")
    s.type_question("Return rate by region in Q3")
    s.click("#roles-btn")
    s.wait_answers()
    s.page.evaluate("() => document.querySelector('#results').scrollIntoView({block: 'start'})")
    s.caption("Finance sees every region. <b>Sam, the East manager, sees only East.</b>")
    s.snap(4.0)
    s.ring("document.querySelectorAll('#results .box.box-warn')")
    s.caption("A <b>query guard</b> adds each user's row filter and removes hidden fields")
    s.snap(4.0)


def scene_wrong(s):
    s.goto("/?user=fatima#analyst")
    s.caption("Shared memory holds a <b>wrong definition</b> of net margin")
    s.type_question(Q_MARGIN)
    s.click("#ask-btn")
    s.wait_answers()
    s.ring(EAST_ROWS)
    s.caption("So every agent says East's margin is a healthy <b>36%</b>")
    s.snap(5.0)


def scene_correct(s):
    # continues on the page left by scene_wrong (same session)
    s.caption("Fatima, the finance lead, corrects it")
    s.type_question("Net margin must subtract returns. Show Q3 by region again")
    s.click("#ask-btn")
    s.wait_answers()
    s.ring("document.querySelectorAll('#results .callout.pending')")
    s.caption("The agent files a <b>proposal</b>. Shared memory does not change yet.")
    s.snap(5.0)


PENDING = "#mem-list .item:has(.status-pending):has(.item-title:text-is('Net margin'))"


def scene_approve(s):
    link = s.page.locator("#results [data-goto='reviewer']")
    if link.count():
        link.first.click()
    else:  # recorded on its own: open Memory review directly
        s.goto("/?user=fatima#reviewer")
    item = s.page.locator(PENDING).first
    item.wait_for()
    time.sleep(0.8)

    def ring_item():  # the list re-renders when it refreshes, so re-apply right before each frame
        item.evaluate("""e => { document.querySelectorAll('.__ring').forEach(x => x.classList.remove('__ring'));
            e.classList.add('__ring'); e.scrollIntoView({block: 'center'}); }""")

    print("approving", item.locator(".chip").first.text_content())
    s.caption("A <b>reviewer</b> sees the proposal in Memory review")
    ring_item()
    s.snap(3.0)
    ring_item()
    item.locator("button[data-act='approve']").evaluate("e => e.classList.add('__input')")
    s.snap(0.5)
    item.locator("button[data-act='approve']").click()
    s.page.wait_for_selector("dialog[open]")
    s.caption("She approves it <b>for every role</b>")
    s.snap(1.8)
    s.click("#dialog-confirm", hold=0.5)
    s.page.wait_for_function("() => !document.querySelector('dialog[open]')", timeout=60000)
    time.sleep(0.5)
    s.caption("The old version is superseded. Every step is <b>audited</b>.")
    s.snap(3.0)


def scene_fixed(s):
    s.goto("/?user=fatima#analyst")
    s.caption("Now any agent asks the same question…")
    s.type_question(Q_MARGIN)
    s.click("#ask-btn")
    s.wait_answers()
    s.ring(EAST_ROWS)
    s.caption("…and gets the truth: East's margin is <b>1.7%</b>")
    s.snap(5.0)


def scene_skills(s):
    s.goto("/?user=fatima#skills")
    time.sleep(1.5)
    s.caption("Repeated questions become <b>tested, reviewed skills</b>")
    s.snap(4.0)


def scene_proof(s):
    s.goto("/demo?full#10")
    s.caption("Accuracy with memory: <b>4/10 → 10/10</b> after one approved correction")
    s.snap(4.0)
    s.goto("/demo?full#1")
    s.caption("<b>Lore</b> · built on MongoDB Atlas and Vector Search")
    s.snap(3.0)


def record(names):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=SCALE,
                                  color_scheme="dark")
        ctx.add_init_script("try { localStorage.setItem('lore.templates', 'closed'); } catch (e) {}")
        page = ctx.new_page()
        for name in names:
            s = Scene(page, name)
            globals()[f"scene_{name}"](s)
            s.save()
        browser.close()


def build(target):
    import imageio_ffmpeg
    lines, total = [], 0.0
    for name in ORDER:
        frames = json.loads((OUT / f"{name}.json").read_text())
        for f, d in frames:
            lines += [f"file '{f}'", f"duration {d}"]
            total += d
    lines.append(lines[-2])  # concat demuxer needs the last file repeated
    (OUT / "list.txt").write_text("\n".join(lines))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", "list.txt", "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
                    "-t", f"{total:.2f}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart",
                    str(pathlib.Path(target).resolve())], cwd=OUT, check=True)
    print(f"built {target}: {total:.1f}s")


if __name__ == "__main__":
    if sys.argv[2] == "--build":
        build(sys.argv[3])
    else:
        record(sys.argv[2:])
