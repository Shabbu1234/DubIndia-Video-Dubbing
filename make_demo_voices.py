# Generate per-character Hindi voice segments for the 30s Solo Leveling demo.
# Pass 1 streams word boundaries for timing; pass 2 saves the mp3 (edge-tts handles file IO).
# Timing JSON goes to stdout so the caller redirects it where needed.
import asyncio
import json
import sys

import edge_tts

# (file, voice, rate, pitch, text) — natural spoken Hindi, movie-trailer style
SEGMENTS = [
    ("seg_a_title.mp3", "hi-IN-MadhurNeural", "-8%", "+0Hz",
     "सोलो लेवलिंग। अध्याय एक सौ आठ।"),
    ("seg_b_narr.mp3", "hi-IN-MadhurNeural", "-5%", "+0Hz",
     "जेजू द्वीप का रेड जब ख़त्म हुआ... दुनिया सिर्फ़ एक ही बात कर रही थी।"),
    ("seg_c_male.mp3", "hi-IN-MadhurNeural", "+5%", "+30Hz",
     "इतने सारे जानवर बुलाना... बिल्कुल नामुमकिन था।"),
    ("seg_d_female.mp3", "hi-IN-SwaraNeural", "-10%", "+0Hz",
     "वाह... मैं तो शब्द ही भूल गई।"),
    ("seg_e_soft.mp3", "hi-IN-SwaraNeural", "-18%", "-15Hz",
     "सुंग जिनवू के जानवरों को चींटियों से लड़ते देख कर... मेरा दस साल पुराना कैंसर ठीक हो गया।"),
]

TAIL = 0.55   # mp3 tail after last word
PAD = 0.6     # breathing room after each voice inside its beat


async def gen(name, voice, rate, pitch, text):
    tts = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    last_end = 0.0
    async for chunk in tts.stream():
        if chunk["type"] == "WordBoundary":
            last_end = (chunk["offset"] + chunk["duration"]) / 1e7
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(name)
    return last_end + TAIL


async def main():
    meta = []
    for name, voice, rate, pitch, text in SEGMENTS:
        d = await gen(name, voice, rate, pitch, text)
        meta.append({"file": name, "dur": round(d, 3)})
        print(f"{name}: {d:.2f}s", file=sys.stderr)
    t = 0.0
    for m in meta:
        m["beat_start"] = round(t, 3)
        m["beat_dur"] = round(m["dur"] + PAD, 3)
        t += m["beat_dur"]
    meta.append({"total": round(t, 3)})
    sys.stdout.write(json.dumps(meta, indent=1))


asyncio.run(main())
