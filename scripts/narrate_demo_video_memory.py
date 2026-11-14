"""Memory-focused cut of the 1-minute video: the life of one shared memory, then proof.

Usage: python scripts/narrate_demo_video_memory.py <frames_dir> <out_dir> <silent.mp4> <voiced.mp4> [voice]

<frames_dir> is what scripts/record_demo_video.py wrote (scenes wrong, correct, approve, fixed,
replay, leak). Scenes named "deck:N" are slide N of web/demo-memory.html, captured from the running
app (http://localhost:8000) with Microsoft Edge, so the video always shows the current slides.
"deck:N:K" is the same slide with its K-th step highlighted. For every caption moment (a "cue") this script speaks the cue's line
with text-to-speech, redraws the caption on the frames so the voice says exactly what is shown, and
keeps the cue on screen for as long as its line takes. Typing and waiting are shortened.

Needs: pip install edge-tts imageio-ffmpeg pillow truststore playwright. Sends only the narration text to
Microsoft's Edge text-to-speech service.
"""
import asyncio
import json
import pathlib
import re
import subprocess
import sys

import truststore

truststore.inject_into_ssl()
import edge_tts  # noqa: E402
import imageio_ffmpeg  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SRC, OUT = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
SILENT, VOICED = sys.argv[3], sys.argv[4]
VOICE = sys.argv[5] if len(sys.argv) > 5 else "en-US-AndrewNeural"
LIMIT = 59.8

# (scene, frame slice, kind, caption with *key words*, spoken text or None to read the caption)
# kind "head" = typing and waiting (shortened, then stretched to the line); "hold" = a still result.
CUES = [
    ("deck:1", (None, None), "hold", "Lore is an *analyst agent* for a retail company", None),
    # how it works
    ("deck:2:1", (None, None), "hold", "It writes and runs *MongoDB queries* to answer business questions", None),
    ("deck:2:2", (None, None), "hold", "Every *session* is saved in MongoDB", None),
    ("deck:2:3", (None, None), "hold", "Repeated questions become *episodes*, then skills", None),
    ("deck:2:4", (None, None), "hold", "What the team agrees becomes *shared memory*", None),
    # the life of one memory
    ("wrong", (None, -1), "head", "But this memory has a *wrong definition*", None),
    ("wrong", (-1, None), "hold", "Every agent says East's margin is *36%*",
     "Every agent says East's margin is thirty-six percent."),
    ("correct", (None, -1), "head", "Fatima, the finance lead, corrects it", None),
    ("correct", (-1, None), "hold", "The agent files a *proposal*. Memory does not change yet.", None),
    ("approve", (0, 2), "hold", "A *reviewer* checks the proposal", None),
    ("approve", (2, 4), "hold", "and approves it for every role", None),
    ("approve", (4, None), "hold", "The old version is kept and *audited*", None),
    ("fixed", (None, -1), "head", "Now any agent asks again", None),
    ("fixed", (-1, None), "hold", "East's margin is *1.7%*", "East's margin is one point seven percent."),
    # proof
    ("replay", (None, -2), "head", "Proof: the same question, with and without memory", None),
    ("replay", (-2, -1), "hold", "Memory *changed the query and the result*", None),
    # everything else, briefly
    ("leak", (-1, None), "hold", "Each memory is *scoped by role*, an Atlas Vector Search filter", None),
    ("deck:6", (None, None), "hold", "Vector Search, Voyage AI, change streams: *one Atlas cluster*",
     "Vector Search, Voyage A I, and change streams: one Atlas cluster."),
    ("deck:1", (None, None), "hold", "*Lore*: memory you can govern", None),
]
HEAD_SPEED = {0.07: 0.045, 0.4: 0.25, 0.45: 0.3, 0.9: 0.5}   # typing, pause, click, waiting
GAP = 0.3

ff = imageio_ffmpeg.get_ffmpeg_exe()
OUT.mkdir(parents=True, exist_ok=True)


def seconds(path) -> float:
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def speak(rate: str) -> None:
    for i, (_, _, _, caption, speech) in enumerate(CUES):
        for attempt in range(8):
            try:
                await edge_tts.Communicate(speech or caption.replace("*", ""), VOICE, rate=rate).save(str(OUT / f"vo_{i:02d}.mp3"))
                break
            except Exception:
                if attempt == 7:
                    raise
                await asyncio.sleep(3)


FONT = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 38)


def draw_caption(src: pathlib.Path, dst: pathlib.Path, caption: str) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - 150, w, h], fill=(10, 11, 10))                  # subtitle strip, covers the recorded caption
    parts = [(t, i % 2 == 1) for i, t in enumerate(caption.split("*")) if t]
    width = sum(d.textlength(t, font=FONT) for t, _ in parts)
    x0, y0 = (w - width) / 2, h - 108
    d.rounded_rectangle([x0 - 42, y0 - 16, x0 + width + 42, y0 + 66], radius=20, fill=(255, 213, 74))
    x = x0
    for text, key in parts:
        d.text((x, y0), text, font=FONT, fill=(163, 20, 10) if key else (20, 17, 10))
        x += d.textlength(text, font=FONT)
    im.save(dst)


def capture_slides() -> None:
    """Screenshot the deck slides the cues use, at the size the scenes were recorded in."""
    from playwright.sync_api import sync_playwright

    wanted = sorted({scene[5:] for scene, *_ in CUES if scene.startswith("deck:")})
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5,
                                   color_scheme="dark").new_page()
        for key in wanted:
            n, _, step = key.partition(":")
            page.goto(f"http://localhost:8000/demo?c={key.replace(':', '_')}#{n}")
            page.wait_for_load_state("networkidle")
            page.add_style_tag(content=".controls, .progress, .actions { visibility: hidden !important; }")
            if step:   # highlight one step of the slide's list
                page.evaluate("""(k) => document.querySelectorAll('.slide.active .life li').forEach(
                    (li, i) => { li.classList.toggle('now', i === k - 1); li.classList.toggle('off', i > k - 1); })""", int(step))
            page.wait_for_timeout(900)   # the slide's enter animation
            page.screenshot(path=str(OUT / f"deck_{key.replace(':', '_')}.png"))
        browser.close()


def scene_frames(scene: str) -> tuple[pathlib.Path, list]:
    if scene.startswith("deck:"):
        return OUT, [[f"deck_{scene[5:].replace(':', '_')}.png", 3.0]]
    return SRC, json.loads((SRC / f"{scene}.json").read_text())


def plan() -> tuple[float, list, list]:
    """Time every cue from its spoken line. Returns (total, [(file, seconds)], [(start, clip, caption, seconds)])."""
    t, timeline, clips = 0.0, [], []
    for i, (scene, (a, b), kind, caption, _) in enumerate(CUES):
        folder, frames = scene_frames(scene)
        clip = OUT / f"vo_{i:02d}.mp3"
        need = seconds(clip) + GAP
        cue = [[f, d] for f, d in frames[a:b]]
        if kind == "head":
            for fr in cue:
                fr[1] = HEAD_SPEED.get(round(fr[1], 2), fr[1])
            cue[-1][1] += max(0.0, need - sum(d for _, d in cue))
        elif len(cue) == 2 and cue[1][1] <= 0.5:        # a result followed by a short click highlight
            cue[0][1] = max(0.6, need - cue[1][1])
        else:
            for fr in cue:
                fr[1] = max(1.0, need) / len(cue)
        length = sum(d for _, d in cue)
        clips.append((t, clip, caption, length))
        for n, (f, d) in enumerate(cue):
            name = f"m{i:02d}_{n:03d}.png"
            draw_caption(folder / f, OUT / name, caption)
            timeline.append((name, round(d, 3)))
        t += length
    return t, timeline, clips


capture_slides()
for rate in ("+10%", "+16%", "+22%"):
    asyncio.run(speak(rate))
    total, timeline, clips = plan()
    print(f"voice rate {rate}: {total:.1f}s")
    if total <= LIMIT:
        break
else:
    sys.exit("still over the limit: shorten the lines in CUES")

lines = []
for f, d in timeline:
    lines += [f"file '{f}'", f"duration {d}"]
lines.append(lines[-2])
(OUT / "list.txt").write_text("\n".join(lines))
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
                "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p", "-t", f"{total:.2f}",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart",
                str(pathlib.Path(SILENT).resolve())], cwd=OUT, check=True)

inputs, filters, labels = ["-i", SILENT], [], []
for i, (start, clip, _, _) in enumerate(clips):
    inputs += ["-i", str(clip)]
    ms = int((start + 0.08) * 1000)
    filters.append(f"[{i + 1}:a]adelay={ms}|{ms}[a{i}]")
    labels.append(f"[a{i}]")
filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{total:.2f}", "-movflags", "+faststart", VOICED], check=True)

for start, clip, caption, length in clips:
    print(f"{start:5.1f}s  on screen {length:4.1f}s  speech {seconds(clip):4.1f}s  {caption.replace('*', '')}")
print(f"built {VOICED}: {seconds(VOICED):.1f}s")
