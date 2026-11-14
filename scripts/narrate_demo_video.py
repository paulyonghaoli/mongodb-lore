"""Narrate the 1-minute video: one neural TTS clip per scene, fitted to the scene and mixed in.

Usage: python scripts/narrate_demo_video.py <frames_dir> <silent.mp4> <out.mp4> [voice]
<frames_dir> is the one scripts/record_demo_video.py wrote (it holds the scene timings).
Needs: pip install edge-tts imageio-ffmpeg truststore. Sends only the narration text to
Microsoft's Edge text-to-speech service.
"""
import asyncio, json, pathlib, re, subprocess, sys
import truststore; truststore.inject_into_ssl()
import edge_tts, imageio_ffmpeg

F = pathlib.Path(sys.argv[1]); SRC, DST = sys.argv[2], sys.argv[3]
VOICE = sys.argv[4] if len(sys.argv) > 4 else "en-US-AndrewNeural"
ORDER = ["title", "problem", "roles", "wrong", "correct", "approve", "fixed", "skills", "proof"]
LINES = {
    "title": "Lore is shared memory for analyst agents, governed by people.",
    "problem": "Agents forget definitions, lose corrections, and overshare data.",
    "roles": "One question, three roles. Finance sees every region. Sam, the East manager, sees only East. "
             "A query guard enforces each user's permissions.",
    "wrong": "Shared memory holds a wrong definition. Every agent says East's margin is a healthy thirty-six percent.",
    "correct": "Fatima, the finance lead, corrects it. The agent files a proposal. Memory does not change yet.",
    "approve": "A reviewer approves it for every role. The old version is kept, and every step is audited.",
    "fixed": "Now any agent asks again, and gets the truth: one point seven percent.",
    "skills": "Repeated questions become tested, reviewed skills.",
    "proof": "Accuracy with memory went from four out of ten, to ten out of ten. Lore. Built on MongoDB Atlas.",
}
ff = imageio_ffmpeg.get_ffmpeg_exe()

def dur(path):
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

async def tts():
    for name, text in LINES.items():
        for attempt in range(5):
            try:
                await edge_tts.Communicate(text, VOICE, rate="+4%").save(str(F / f"vo_{name}.mp3")); break
            except Exception as e:
                if attempt == 4: raise
                await asyncio.sleep(1.5)
asyncio.run(tts())

inputs, filters, labels, t = ["-i", SRC], [], [], 0.0
for i, name in enumerate(ORDER, 1):
    slot = sum(d for _, d in json.loads((F / f"{name}.json").read_text()))
    clip = F / f"vo_{name}.mp3"; d = dur(clip)
    tempo = min(1.3, max(1.0, d / (slot - 0.35)))
    print(f"{name:8} start {t:5.1f}s  slot {slot:4.1f}s  speech {d:4.1f}s  tempo x{tempo:.2f}")
    inputs += ["-i", str(clip)]
    ms = int((t + 0.15) * 1000)
    filters.append(f"[{i}:a]atempo={tempo:.3f},adelay={ms}|{ms}[a{i}]"); labels.append(f"[a{i}]")
    t += slot
filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{t:.2f}", "-movflags", "+faststart", DST], check=True)
print("built", DST, f"{dur(DST):.1f}s")
