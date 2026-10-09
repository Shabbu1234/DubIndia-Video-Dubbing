# Horror narration with word timestamps — used to place SFX exactly on the spoken word
import asyncio
import json

import edge_tts

TEXT = (
    "रात के ठीक बारह बजे थे... घर में सब सो चुके थे। "
    "फिर भी... किसी ने दरवाज़ा खटखटाया। "
    "धीरे से... बहुत धीरे।"
)


async def main():
    tts = edge_tts.Communicate(
        TEXT, "hi-IN-MadhurNeural", rate="-12%", pitch="-20Hz", boundary="WordBoundary"
    )
    bounds = []
    with open("voice_horror.mp3", "wb") as f:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                bounds.append(
                    {"t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7, "w": chunk["text"]}
                )
    with open("horror_bounds.json", "w", encoding="utf-8") as f:
        json.dump(bounds, f, ensure_ascii=False, indent=1)
    for b in bounds:
        print(f'{b["t"]:6.2f}  {b["w"]}')
    print("last_end", round(bounds[-1]["t"] + bounds[-1]["d"], 2))


asyncio.run(main())
