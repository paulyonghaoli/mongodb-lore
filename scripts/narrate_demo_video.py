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
# One narration line per block of scenes; the line starts with the block's first scene.
BLOCKS = [
    (["title"], "Lore: memory you can govern, on MongoDB Atlas."),
    (["q1", "leak"], "Question one: no leaks between teams. Three roles ask one question. The store memory reaches "
                     "Finance and the store manager, never the analyst. Role rules are Atlas Vector Search filters."),
    (["q2", "wrong"], "Question two: fixing a wrong memory. Shared memory says East's margin is thirty-six percent."),
    (["correct"], "Fatima corrects it. The agent files a new version, as a proposal."),
    (["approve"], "A reviewer approves it. The old version is kept, and every step is audited."),
    (["fixed"], "Now every agent says one point seven percent."),
    (["q3", "replay"], "Question three: proof. The same question, replayed with and without memory, gives a "
                       "different query, and a different result."),
    (["atlas"], "Vector Search, Voyage A I, aggregation and change streams: one MongoDB Atlas cluster."),
]
ff = imageio_ffmpeg.get_ffmpeg_exe()

def dur(path):
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

async def tts():
    for i, (_, text) in enumerate(BLOCKS):
        for attempt in range(8):
            try:
                await edge_tts.Communicate(text, VOICE, rate="+0%").save(str(F / f"vo_{i}.mp3")); break
            except Exception:
                if attempt == 7: raise
                await asyncio.sleep(3)
asyncio.run(tts())

inputs, filters, labels, t = ["-i", SRC], [], [], 0.0
for i, (scenes, _) in enumerate(BLOCKS):
    slot = sum(d for name in scenes for _, d in json.loads((F / f"{name}.json").read_text()))
    clip = F / f"vo_{i}.mp3"; d = dur(clip)
    tempo = min(1.3, max(1.0, d / (slot - 0.35)))
    print(f"{'+'.join(scenes):12} start {t:5.1f}s  slot {slot:4.1f}s  speech {d:4.1f}s  tempo x{tempo:.2f}")
    inputs += ["-i", str(clip)]
    ms = int((t + 0.15) * 1000)
    filters.append(f"[{i + 1}:a]atempo={tempo:.3f},adelay={ms}|{ms}[a{i}]"); labels.append(f"[a{i}]")
    t += slot
filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{t:.2f}", "-movflags", "+faststart", DST], check=True)
print("built", DST, f"{dur(DST):.1f}s")
