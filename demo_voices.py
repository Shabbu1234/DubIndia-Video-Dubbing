# Demo: mood-matched Hindi narration samples via edge-tts (free)
import asyncio
import edge_tts

# (output name, voice, rate, pitch, text)
SAMPLES = [
    ("horror", "hi-IN-MadhurNeural", "-12%", "-20Hz",
     "रात के ठीक बारह बजे थे... घर में सब सो चुके थे। "
     "फिर भी... किसी ने दरवाज़ा खटखटाया। "
     "धीरे से... बहुत धीरे।"),
    ("emotional", "hi-IN-SwaraNeural", "-8%", "+0Hz",
     "पापा ने कहा था, बेटा... कभी हार मत मानना। "
     "आज जब मैं उनकी खाली कुर्सी देखती हूँ... "
     "वही बात याद आती है।"),
    ("narrator", "hi-IN-MadhurNeural", "+0%", "+0Hz",
     "ये कहानी है एक ऐसे शहर की, जहाँ हर रात एक राह निकलती है... "
     "और वापस कोई नहीं आता।"),
]


async def main():
    for name, voice, rate, pitch, text in SAMPLES:
        tts = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        out = f"voice_demo_{name}.mp3"
        await tts.save(out)
        print("saved", out)


asyncio.run(main())
