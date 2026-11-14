"""Caption and narrate the 1-minute video so the voice says exactly what each caption shows.

Usage: python scripts/narrate_demo_video.py <frames_dir> <out_dir> <silent.mp4> <voiced.mp4> [voice]

<frames_dir> is what scripts/record_demo_video.py wrote. For every caption moment (a "cue") this
script speaks the cue's line with text-to-speech, redraws the caption on the frames, and sets how
long the cue stays on screen to the length of its spoken line. Typing and waiting are shortened.
The result goes to <out_dir> (frames and timings), then both videos are built.

Needs: pip install edge-tts imageio-ffmpeg pillow truststore. Sends only the narration text to
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
ORDER = ["title", "q1", "leak", "q2", "wrong", "correct", "approve", "fixed", "q3", "replay", "atlas"]

# scene -> cues: (frame slice, kind, caption with *key words*, spoken text or None to read the caption)
# kind "head" = typing and waiting (shortened, then stretched to the line); "hold" = a still result.
CUES = {
    "title": [((None, None), "hold", "Lore: memory you can govern, on *MongoDB Atlas*", None)],
    "q1": [((None, None), "hold", "Question one: *no leaks*", None)],
    "leak": [((None, -3), "head", "Three roles, one question", None),
             ((-3, -1), "hold", "Finance and the store manager *get the store memory*", None),
             ((-1, None), "hold", "The analyst *never does*. Atlas Vector Search filters by role.", None)],
    "q2": [((None, None), "hold", "Question two: *fix* a wrong memory", None)],
    "wrong": [((None, -1), "head", "Memory has a *wrong definition*", None),
              ((-1, None), "hold", "Every agent says East's margin is *36%*",
               "Every agent says East's margin is thirty-six percent.")],
    "correct": [((None, -1), "head", "Fatima corrects it", None),
                ((-1, None), "hold", "The agent files a *proposal*", None)],
    "approve": [((0, 2), "hold", "A *reviewer* sees it", None),
                ((2, 4), "hold", "and approves it for every role", None),
                ((4, None), "hold", "The old version is kept and *audited*", None)],
    "fixed": [((None, -1), "head", "Now any agent asks again", None),
              ((-1, None), "hold", "East's margin is *1.7%*", "East's margin is one point seven percent.")],
    "q3": [((None, None), "hold", "Question three: *prove it*", None)],
    "replay": [((None, -2), "head", "Same question, with and without memory", None),
               ((-2, -1), "hold", "The *query* and the *result* both change", None),
               ((-1, None), "hold", "Gross revenue becomes *net revenue*", None)],
    "atlas": [((0, 1), "hold", "Vector Search, Voyage AI, aggregation, change streams: *one Atlas cluster*",
               "Vector Search, Voyage A I, aggregation, and change streams: one Atlas cluster."),
              ((1, None), "hold", "*Lore*: memory you can govern", None)],
}
HEAD_SPEED = {0.07: 0.045, 0.4: 0.25, 0.45: 0.3, 0.9: 0.5}   # typing, pause, click, waiting
GAP = 0.22

ff = imageio_ffmpeg.get_ffmpeg_exe()
OUT.mkdir(parents=True, exist_ok=True)


def seconds(path) -> float:
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def spoken(caption: str, speech: str | None) -> str:
    return speech or caption.replace("*", "")


async def speak(rate: str) -> None:
    for scene in ORDER:
        for i, (_, _, caption, speech) in enumerate(CUES[scene]):
            for attempt in range(8):
                try:
                    await edge_tts.Communicate(spoken(caption, speech), VOICE, rate=rate).save(str(OUT / f"vo_{scene}_{i}.mp3"))
                    break
                except Exception:
                    if attempt == 7:
                        raise
                    await asyncio.sleep(3)


# ---------- captions ----------
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


# ---------- timing ----------
def plan() -> tuple[float, list[tuple[float, pathlib.Path]]]:
    """Set every cue's time on screen from its spoken line. Returns (total seconds, [(start, clip)])."""
    t, clips = 0.0, []
    for scene in ORDER:
        frames = json.loads((SRC / f"{scene}.json").read_text())
        out = []
        for i, ((a, b), kind, caption, _) in enumerate(CUES[scene]):
            clip = OUT / f"vo_{scene}_{i}.mp3"
            need = seconds(clip) + GAP
            cue = [[f, d] for f, d in frames[a:b]]
            if kind == "head":
                for fr in cue:
                    fr[1] = HEAD_SPEED.get(round(fr[1], 2), fr[1])
                cue[-1][1] += max(0.0, need - sum(d for _, d in cue))
            else:
                fixed = sum(d for _, d in cue[1:]) if len(cue) == 2 and cue[1][1] <= 0.5 else None
                if fixed is not None:          # a result followed by a short click highlight
                    cue[0][1] = max(0.6, need - fixed)
                else:
                    for fr in cue:
                        fr[1] = max(1.0, need) / len(cue)
            clips.append((t, clip))
            for f, d in cue:
                draw_caption(SRC / f, OUT / f, caption)
                out.append([f, round(d, 3)])
            t += sum(d for _, d in cue)
        assert len(out) == len(frames), (scene, len(out), len(frames))
        (OUT / f"{scene}.json").write_text(json.dumps(out))
    return t, clips


for rate in ("+4%", "+8%", "+12%"):
    asyncio.run(speak(rate))
    total, clips = plan()
    print(f"voice rate {rate}: {total:.1f}s")
    if total <= LIMIT:
        break
else:
    sys.exit("still over the limit: shorten the lines in CUES")

# ---------- build ----------
lines = []
for scene in ORDER:
    for f, d in json.loads((OUT / f"{scene}.json").read_text()):
        lines += [f"file '{f}'", f"duration {d}"]
lines.append(lines[-2])
(OUT / "list.txt").write_text("\n".join(lines))
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
                "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p", "-t", f"{total:.2f}",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart",
                str(pathlib.Path(SILENT).resolve())], cwd=OUT, check=True)

inputs, filters, labels = ["-i", SILENT], [], []
for i, (start, clip) in enumerate(clips):
    inputs += ["-i", str(clip)]
    ms = int((start + 0.08) * 1000)
    filters.append(f"[{i + 1}:a]adelay={ms}|{ms}[a{i}]")
    labels.append(f"[a{i}]")
filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{total:.2f}", "-movflags", "+faststart", VOICED], check=True)

t = 0.0
for scene in ORDER:
    frames = json.loads((OUT / f"{scene}.json").read_text())
    for i, ((a, b), _, caption, _) in enumerate(CUES[scene]):
        d = sum(x for _, x in frames[a:b])
        print(f"{t:5.1f}s  {d:4.1f}s  {caption.replace('*', '')}")
        t += d
print(f"built {VOICED}: {seconds(VOICED):.1f}s")
