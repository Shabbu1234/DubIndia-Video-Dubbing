# dub_tool.py — ek hi tool: video -> Hindi dub (multi-speaker, gender-matched, BGM untouched)
# Usage: python dub_tool.py video.mp4 [-o out.mp4] [--speakers N] [--model small]
# Pipeline: demucs (voice/music alag) -> whisper (timestamps+lang) -> speaker count (resemblyzer
#           + pitch) -> gender (edge-tts anchor voices se match) -> translate -> edge-tts Hindi
#           -> time-fit -> mix -> mux
import argparse, asyncio, subprocess, sys, wave
from pathlib import Path

import numpy as np
import torch

SR = 44100
ANCHOR_SIM_MARGIN = 0.03
VOICES = {"F": "hi-IN-SwaraNeural", "M": "hi-IN-MadhurNeural"}
ANCHOR_TEXTS = {
    "M": "Namaste, yeh ek awaaz ka sample hai. Main is kahani ko padh sakta hoon.",
    "F": "Namaste, yeh ek awaaz ka sample hai. Main is kahani ko padh sakti hoon.",
}


def ok(r, what):
    if r.returncode != 0:
        sys.exit(f"FAILED: {what}\n{r.stderr[-2000:]}")


def dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], shell=False, capture_output=True, text=True)
    ok(r, f"ffprobe {path}")
    return float(r.stdout.strip())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        return data.reshape(-1, w.getnchannels())


def write_wav(path, data, sr=SR):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype(np.int16).tobytes())


_ENC = None
def get_enc():
    global _ENC
    if _ENC is None:
        from resemblyzer import VoiceEncoder
        _ENC = VoiceEncoder()
    return _ENC


def embed_file(path):
    from resemblyzer import preprocess_wav
    return torch.from_numpy(get_enc().embed_utterance(preprocess_wav(str(path))))


def group_utts(segs, gap=0.5):
    """word-timestamp gaps se utterance banao (whisper ke segment end times loose hote hain,
    word times tight). Ek utterance = ek speaker ki ek line."""
    utts, cur_end = [], None
    for i, s in enumerate(segs):
        w0 = s["words"][0]["start"] if s.get("words") else s["start"]
        if utts and (w0 - cur_end) < gap:
            utts[-1].append(i)
        else:
            utts.append([i])
        cur_end = s["words"][-1]["end"] if s.get("words") else s["end"]
    return utts


def utt_f0s(utts, segs, mono16k):
    """per utterance median F0 (librosa pyin) — gender tiebreak aur report ke liye."""
    import librosa, warnings
    out = {}
    for u, ii in enumerate(utts):
        a = int(segs[ii[0]]["words"][0]["start"] * 16000) if segs[ii[0]].get("words") else int(segs[ii[0]]["start"] * 16000)
        b = int(segs[ii[-1]]["words"][-1]["end"] * 16000) if segs[ii[-1]].get("words") else int(segs[ii[-1]]["end"] * 16000)
        if b - a < 16000 * 0.3:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f0, _, _ = librosa.pyin(np.ascontiguousarray(mono16k[a:b]), fmin=60, fmax=400,
                                    sr=16000, frame_length=1024)
        f0 = f0[~np.isnan(f0)]
        if len(f0):
            out[u] = float(np.median(f0))
    return out


def assign_speakers(segs, mono16k, utts, want_n=None):
    """Utterance-level greedy centroid clustering (resemblyzer) + orphan post-merge.
    Returns (spk list, centroids dict)."""
    from resemblyzer import preprocess_wav
    enc = get_enc()
    idx, embs = [], []
    for u, ii in enumerate(utts):
        a = int(max(0.0, segs[ii[0]]["words"][0]["start"] - 0.10) * 16000) if segs[ii[0]].get("words") else int(segs[ii[0]]["start"] * 16000)
        b = int(segs[ii[-1]]["words"][-1]["end"] * 16000 + 1600) if segs[ii[-1]].get("words") else int(segs[ii[-1]]["end"] * 16000)
        b = min(b, len(mono16k))
        if b - a < 16000 * 1.2:
            continue  # chhoti line: embed risky, nearest-in-time utterance se inherit hogi
        w = preprocess_wav(mono16k[a:b], source_sr=16000)
        if len(w) < 16000 * 0.4:
            continue
        idx.append(u)
        embs.append(torch.from_numpy(enc.embed_utterance(w)))

    def cluster(th):
        cents, lab = [], {}
        for j, e in zip(idx, embs):
            sims = [float(e @ c) for c in cents]
            if sims and max(sims) >= th:
                k = int(np.argmax(sims)); lab[j] = k
                cents[k] = torch.nn.functional.normalize(cents[k] + e, dim=0)
            else:
                lab[j] = len(cents); cents.append(e.clone())
        return lab, cents

    if want_n:
        best = min(np.arange(0.30, 0.95, 0.02), key=lambda th: abs(len(set(cluster(float(th))[0].values())) - want_n))
        lab, cents = cluster(float(best))
    else:
        lab, cents = cluster(0.70)  # ponytail: heuristic threshold, galat count ho to --speakers N do

    # post-merge: same speaker ke orphan utterances (0.70 pe match na hue) wapas jodo.
    # same-speaker orphan sims ~0.6+, cross-gender centroids ~0.55 -> 0.62 beech ka point hai.
    while len(cents) > 1:
        best = max(((float(cents[x] @ cents[y]), x, y)
                    for x in range(len(cents)) for y in range(x + 1, len(cents))))
        if best[0] < 0.62:
            break
        _, a, b = best
        na = sum(1 for v in lab.values() if v == a); nb = sum(1 for v in lab.values() if v == b)
        cents[a] = torch.nn.functional.normalize(cents[a] * na + cents[b] * nb, dim=0)
        cents.pop(b)
        lab = {j: (k if k < b else (k - 1 if k > b else a)) for j, k in lab.items()}

    spk = [None] * len(segs)
    for u, ii in enumerate(utts):
        k = lab.get(u)
        if k is None:
            k = lab[min(idx, key=lambda x: abs(segs[utts[x][0]]["start"] - segs[ii[0]]["start"]))]
        for i in ii:
            spk[i] = k
    return spk, {k: cents[k] for k in set(lab.values())}


def pick_genders(cents_d, uf0s, utts, spk, work):
    """Gender: edge-tts anchor voices (Madhur/Swara) se centroid similarity; close ho to pitch tiebreak."""
    async def mk():
        import edge_tts
        outs = {}
        for g, txt in ANCHOR_TEXTS.items():
            p = work / f"anchor_{g}.mp3"
            await edge_tts.Communicate(txt, VOICES[g]).save(str(p))
            outs[g] = p
        return outs
    anchors = asyncio.run(mk())
    e_f = embed_file(anchors["F"]); e_m = embed_file(anchors["M"])
    genders, med = {}, {}
    for k, c in cents_d.items():
        sf, sm = float(c @ e_f), float(c @ e_m)
        vals = [f0 for u, f0 in uf0s.items() if spk[utts[u][0]] == k]
        med[k] = float(np.median(vals)) if vals else 120.0
        if abs(sf - sm) > ANCHOR_SIM_MARGIN:
            genders[k] = "F" if sf > sm else "M"
        else:
            genders[k] = "F" if med[k] > 175 else "M"  # ponytail: pitch tiebreak, TTS voices 160-180 pe blur
    return genders, med


def translate_all(segs, src_lang):
    """Google batched (newline-joined chunks) -> MyMemory per-line -> warna English rehne do."""
    import time
    if src_lang == "hi":
        for s in segs:
            s["hi"] = s["text"].strip()
        return
    texts = [s["text"].strip() for s in segs]
    hindi = [None] * len(texts)
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source=src_lang if src_lang in ("en", "auto") else "en", target="hi")
        i = 0
        while i < len(texts):
            j, chunk = i, []
            while j < len(texts) and sum(len(t) for t in chunk) + len(texts[j]) < 3000:
                chunk.append(texts[j]); j += 1
            out = None
            for att in range(4):
                try:
                    out = tr.translate("\n".join(chunk)); break
                except Exception:
                    time.sleep(15 * (att + 1))  # ponytail: google temp-block minutes tak reh sakta hai
            lines = [l for l in (out or "").split("\n") if l.strip()]
            if len(lines) == len(chunk):
                for kk, l in enumerate(lines):
                    hindi[i + kk] = l.strip()
            i = j
    except Exception:
        pass
    missing = [k for k in range(len(texts)) if not hindi[k]]
    if missing:
        print(f"    google se {len(missing)} lines nahi bani, MyMemory try kar rahe hain...")
        import requests
        for k in missing:
            try:
                rr = requests.get("https://api.mymemory.translated.net/get",
                                  params={"q": texts[k][:480], "langpair": f"{src_lang if src_lang != 'auto' else 'en'}|hi-IN"},
                                  timeout=15)
                hindi[k] = rr.json()["responseData"]["translatedText"] or None
            except Exception:
                hindi[k] = None
            time.sleep(0.3)
    for k in range(len(texts)):
        segs[k]["hi"] = (hindi[k] or texts[k]).strip()
        if not hindi[k]:
            print(f"  ! translate fail (English reh gaya): {texts[k][:40]}")


async def tts_all(segs, genders, spk, work):
    import edge_tts
    jobs = []
    for i, s in enumerate(segs):
        s["mp3"] = str(work / f"tts_{i:03d}.mp3")
        jobs.append(edge_tts.Communicate(s["hi"], VOICES[genders[spk[i]]]).save(s["mp3"]))
    await asyncio.gather(*jobs)


def fit_and_mix(segs, bg, work):
    """TTS clip ko original speech slot me fit (chhota to natural, lamba to max 2x tez), bg pe mix."""
    voice = np.zeros_like(bg)
    warns = []
    for i, s in enumerate(segs):
        d = dur(s["mp3"])
        slot = s["end"] - s["start"]
        tempo = max(1.0, min(2.0, d / max(slot, 0.2)))
        dst = work / f"clip_{i:03d}.wav"
        filt = f"atempo={tempo:.4f}" if tempo > 1.001 else "anull"
        r = subprocess.run(["ffmpeg", "-y", "-i", s["mp3"], "-af", filt, "-ar", str(SR),
                            "-ac", "2", "-c:a", "pcm_s16le", str(dst)],
                           shell=False, capture_output=True, text=True)
        ok(r, f"clip convert {i}")
        clip = read_wav(dst)
        i0 = int(round(s["start"] * SR))
        nxt = segs[i + 1]["start"] if i + 1 < len(segs) else len(bg) / SR
        if len(clip) / SR > (nxt - s["start"]):
            warns.append(f"segment {i}: Hindi clip slot se lamba ({d:.1f}s vs {slot:.1f}s) — agli line pe halka overlap")
        i1 = min(len(bg), i0 + len(clip))
        if i1 > i0:
            voice[i0:i1] += clip[: i1 - i0]
    return bg + voice, warns


def main():
    ap = argparse.ArgumentParser(description="Video ko Hindi me dub karo (multi-speaker, gender-matched, BGM same)")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--speakers", type=int, help="speaker count pata hai to force karo")
    ap.add_argument("--model", default="small", help="whisper model (default small)")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.exists():  # ponytail: extension chhoot jaye to guess karo (kanta -> kanta.mp4)
        hits = [src.with_name(src.name + e) for e in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4a", ".mp3", ".wav")]
        hits = [p for p in hits if p.exists()] or \
               sorted(p for p in src.parent.iterdir() if p.is_file() and src.name.lower() in p.name.lower())
        assert hits, f"file nahi mili: {src}"
        src = hits[0]
        print(f"    (guess) ye file li: {src.name}")
    assert src.exists(), f"file nahi mili: {src}"
    out = Path(args.output).resolve() if args.output else src.with_name(src.stem + ".hindi.mp4")
    work = src.with_name(src.stem + "_dub_work"); work.mkdir(exist_ok=True)
    print(f"[1/7] {src.name}")

    print("[2/7] audio nikal rahe hain...")
    run = None  # noqa: placeholder to keep diff small
    r = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", str(SR),
                        "-c:a", "pcm_s16le", str(work / "src44.wav")],
                       shell=False, capture_output=True, text=True)
    ok(r, "audio extract stereo")

    print("[3/7] voice vs background music alag kar rahe hain (demucs, CPU pe thoda time lagega)...")
    r = subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals",
                        "-o", str(work / "sep"), str(work / "src44.wav")],
                       shell=False, capture_output=True, text=True)
    ok(r, "demucs separation")
    sep = work / "sep" / "htdemucs" / "src44"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(sep / "no_vocals.wav"), "-c:a", "pcm_s16le",
                        str(work / "bg.wav")], shell=False, capture_output=True, text=True)
    ok(r, "bg convert")
    bg = read_wav(work / "bg.wav")
    r = subprocess.run(["ffmpeg", "-y", "-i", str(sep / "vocals.wav"), "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(work / "mono16.wav")], shell=False, capture_output=True, text=True)
    ok(r, "vocals convert mono16")


    print("[4/7] speech samajh rahe hain (whisper)...")
    import whisper
    res = whisper.load_model(args.model).transcribe(str(work / "mono16.wav"), fp16=False,
                                                    verbose=False, word_timestamps=True)
    lang = res.get("language", "en")
    segs = [s for s in res["segments"]
            if s["text"].strip() and not set(s["text"].strip()) <= set("♪♫.!? -—")]
    segs.sort(key=lambda s: s["start"])
    assert segs, "koi speech nahi mili video me"
    print(f"    language={lang}, {len(segs)} segments")

    print("[5/7] speakers + gender detect kar rahe hain...")
    mono = np.asarray(whisper.audio.load_audio(str(work / "mono16.wav")), dtype=np.float32)
    utts = group_utts(segs)
    uf0s = utt_f0s(utts, segs, mono)
    spk, cents_d = assign_speakers(segs, mono, utts, args.speakers)
    genders, f0s_med = pick_genders(cents_d, uf0s, utts, spk, work)
    for k in sorted(set(spk)):
        print(f"    Speaker {k+1}: {'FEMALE' if genders[k]=='F' else 'MALE'} (pitch {f0s_med[k]:.0f} Hz, "
              f"{spk.count(k)} lines) -> {VOICES[genders[k]]}")

    print("[6/7] Hindi translate + TTS...")
    translate_all(segs, lang)
    asyncio.run(tts_all(segs, genders, spk, work))

    print("[7/7] timing fit + mix + video ke saath jod rahe hain...")
    mix, warns = fit_and_mix(segs, bg, work)
    write_wav(work / "mix.wav", mix)
    r = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-i", str(work / "mix.wav"),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "192k", str(out)],
                       shell=False, capture_output=True, text=True)
    ok(r, "mux")

    lines = [f"Input: {src.name}", f"Output: {out.name}", f"Language detected: {lang}",
             f"Speakers: {len(set(spk))}"]
    for k in sorted(set(spk)):
        lines.append(f"  Speaker {k+1}: {'FEMALE' if genders[k]=='F' else 'MALE'} "
                     f"(pitch {f0s_med[k]:.0f} Hz) -> {VOICES[genders[k]]}, {spk.count(k)} lines")
    lines += [f"Segments: {len(segs)}"] + [f"WARN: {w}" for w in warns] + \
             [f"BGM demucs se alag kiya gaya (music preserve, original voice hataya).",
              f"Note: same-gender ke multiple speakers ko same voice milti hai."]
    (work / "dub_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nDONE -> {out}")


if __name__ == "__main__":
    main()
