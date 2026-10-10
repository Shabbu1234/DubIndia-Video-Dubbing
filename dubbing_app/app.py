"""
Dubbing Web App — Flask Backend
Natural Hindustani dub: Hindi + Urdu + English mix (jaise Indians actually bolte hain)
No AI model needed. Uses: whisper (speech recognition) + edge-tts (TTS) + demucs (source separation)
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB max upload

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        res = Response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return res

WORK_DIR = Path("dub_jobs")
WORK_DIR.mkdir(exist_ok=True)

SR = 44100
ANCHOR_SIM_MARGIN = 0.03

# Best Edge-TTS voices for natural Hindustani dubbing
# Madhu = warm male, Swara = clear female (both Neural, Hindi-IN)
VOICES = {
    "M": "hi-IN-MadhurNeural",   # warm, natural male voice
    "F": "hi-IN-SwaraNeural",    # clear, expressive female voice
}

# Alternative voices (speaker 3+ will cycle through these)
VOICES_ALT = {
    "M": ["hi-IN-MadhurNeural"],
    "F": ["hi-IN-SwaraNeural"],
}

ANCHOR_TEXTS = {
    "M": "Namaste bhai, kya scene hai yaar! Kal raat party mein to maza aa gaya.",
    "F": "Are yaar, movie dekhi? Ekdum awesome thi! Seriously bohot mast thi.",
}

# --- job store ---
jobs: dict[str, dict] = {}


def emit(job_id: str, msg: str, level: str = "info"):
    """Push SSE log message to job store."""
    if job_id not in jobs:
        return
    jobs[job_id]["logs"].append({"t": time.time(), "msg": msg, "level": level})


def set_progress(job_id: str, pct: int, stage: str = ""):
    if job_id not in jobs:
        return
    jobs[job_id]["progress"] = pct
    if stage:
        jobs[job_id]["stage"] = stage


# ── utilities ───────────────────────────────────────────────────────────────

def ok(r, what, job_id=None):
    if r.returncode != 0:
        msg = f"FAILED: {what}\n{r.stderr[-2000:]}"
        if job_id:
            emit(job_id, msg, "error")
        raise RuntimeError(msg)


def dur(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, shell=False
    )
    return float(r.stdout.strip() or "0")


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        return data.reshape(-1, w.getnchannels())


def write_wav(path, data, sr=SR):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype(np.int16).tobytes())


# ── speaker detection ────────────────────────────────────────────────────────

_ENC = None


def get_enc():
    global _ENC
    if _ENC is None:
        from resemblyzer import VoiceEncoder
        _ENC = VoiceEncoder()
    return _ENC


def group_utts(segs, gap=0.5):
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
    import librosa
    import warnings
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
    from resemblyzer import preprocess_wav
    enc = get_enc()
    idx, embs = [], []
    for u, ii in enumerate(utts):
        a_raw = segs[ii[0]]["words"][0]["start"] if segs[ii[0]].get("words") else segs[ii[0]]["start"]
        b_raw = segs[ii[-1]]["words"][-1]["end"] if segs[ii[-1]].get("words") else segs[ii[-1]]["end"]
        a = int(max(0.0, a_raw - 0.10) * 16000)
        b = min(int(b_raw * 16000 + 1600), len(mono16k))
        if b - a < 16000 * 1.2:
            continue
        w = preprocess_wav(mono16k[a:b], source_sr=16000)
        if len(w) < 16000 * 0.4:
            continue
        import torch
        idx.append(u)
        embs.append(torch.from_numpy(enc.embed_utterance(w)))

    import torch

    def cluster(th):
        cents, lab = [], {}
        for j, e in zip(idx, embs):
            sims = [float(e @ c) for c in cents]
            if sims and max(sims) >= th:
                k = int(np.argmax(sims))
                lab[j] = k
                cents[k] = torch.nn.functional.normalize(cents[k] + e, dim=0)
            else:
                lab[j] = len(cents)
                cents.append(e.clone())
        return lab, cents

    if want_n:
        best = min(np.arange(0.30, 0.95, 0.02),
                   key=lambda th: abs(len(set(cluster(float(th))[0].values())) - want_n))
        lab, cents = cluster(float(best))
    else:
        lab, cents = cluster(0.70)

    while len(cents) > 1:
        best = max(
            ((float(cents[x] @ cents[y]), x, y)
             for x in range(len(cents)) for y in range(x + 1, len(cents)))
        )
        if best[0] < 0.62:
            break
        _, a, b = best
        na = sum(1 for v in lab.values() if v == a)
        nb = sum(1 for v in lab.values() if v == b)
        cents[a] = torch.nn.functional.normalize(cents[a] * na + cents[b] * nb, dim=0)
        cents.pop(b)
        lab = {j: (k if k < b else (k - 1 if k > b else a)) for j, k in lab.items()}

    spk = [None] * len(segs)
    for u, ii in enumerate(utts):
        k = lab.get(u)
        if k is None and idx:
            k = lab[min(idx, key=lambda x: abs(segs[utts[x][0]]["start"] - segs[ii[0]]["start"]))]
        if k is None:
            k = 0
        for i in ii:
            spk[i] = k
    return spk, {k: cents[k] for k in set(lab.values())}


def pick_genders(cents_d, uf0s, utts, spk, work):
    """
    Pitch-first gender detection (much more reliable than resemblyzer alone).
    F0 median > 165 Hz  →  Female
    F0 median < 140 Hz  →  Male
    140-165 Hz          →  resemblyzer tiebreak with wide margin
    """
    genders, med = {}, {}

    # Pre-build resemblyzer anchors lazily (only if needed)
    _anchors_built = {}

    def _get_anchor_embs():
        if _anchors_built:
            return _anchors_built
        try:
            import torch
            from resemblyzer import preprocess_wav as pw

            async def _mk():
                import edge_tts
                outs = {}
                for g, txt in ANCHOR_TEXTS.items():
                    p = work / f"anchor_{g}.mp3"
                    await edge_tts.Communicate(txt, VOICES[g]).save(str(p))
                    outs[g] = p
                return outs

            anchors = asyncio.run(_mk())
            enc = get_enc()
            _anchors_built["F"] = torch.from_numpy(enc.embed_utterance(pw(str(anchors["F"]))))
            _anchors_built["M"] = torch.from_numpy(enc.embed_utterance(pw(str(anchors["M"]))))
        except Exception:
            pass
        return _anchors_built

    for k, c in cents_d.items():
        vals = [f0 for u, f0 in uf0s.items()
                if u < len(utts) and spk[utts[u][0]] == k]
        med_f0 = float(np.median(vals)) if vals else 130.0
        med[k] = med_f0

        if med_f0 > 165.0:
            genders[k] = "F"
        elif med_f0 < 140.0:
            genders[k] = "M"
        else:
            # Ambiguous zone: try resemblyzer with wider margin
            embs = _get_anchor_embs()
            if "F" in embs and "M" in embs:
                sf, sm = float(c @ embs["F"]), float(c @ embs["M"])
                if abs(sf - sm) > 0.05:
                    genders[k] = "F" if sf > sm else "M"
                else:
                    genders[k] = "F" if med_f0 >= 152 else "M"
            else:
                genders[k] = "F" if med_f0 >= 152 else "M"

    return genders, med


# ── translation ──────────────────────────────────────────────────────────────

HINGLISH_FIXES = {
    # common shuddh→natural swaps
    "आप": "आप", "तुम": "tum", "क्योंकि": "kyunki",
    "लेकिन": "lekin", "मैं": "main", "है": "hai",
    "नहीं": "nahi", "हाँ": "haan", "ठीक": "theek",
    "अच्छा": "accha", "बहुत": "bohot", "क्या": "kya",
    "यह": "ye", "वह": "wo", "और": "aur",
}


def natural_hindustani(text: str, src_word_count: int = 0) -> str:
    """
    Post-process Google translate output:
    1. Replace formal Hindi words with colloquial Hindustani
    2. If translation is >40% longer than source (word count), trim filler words
    """
    import re
    subs = {
        "किन्तु": "lekin", "परन्तु": "lekin", "तथापि": "phir bhi",
        "अथवा": "ya", "इसलिए": "isliye", "इसलिये": "isliye",
        "अभी": "abhi", "पुनः": "phir se", "वास्तव में": "actually",
        "ठीक है": "theek hai", "हां": "haan", "नहीं": "nahi",
        "मैं": "main", "यह": "ye", "वह": "wo", "वे": "wo log",
        "बहुत अच्छा": "ekdum mast", "धन्यवाद": "shukriya",
        "क्षमा करें": "maafi", "क्षमा करो": "maafi karo",
        "कार्य": "kaam", "अपना": "apna", "अपनी": "apni",
        "स्वयं": "khud", "अवश्य": "zaroor", "शायद": "shayad",
        "निश्चित": "pakka", "वास्तव": "actually", "सत्य": "sach",
        "मित्र": "yaar", "दोस्त": "dost", "प्रिय": "pyaare",
        "सुनिए": "suno", "देखिए": "dekho", "जाइए": "jao",
        "आइए": "aao", "बताइए": "batao", "करिए": "karo",
        "रहिए": "raho", "सोचिए": "socho", "लीजिए": "lo",
        # Extra fillers that bloat length
        "वास्तव में यह": "ye", "इस बारे में": "iske baare mein",
        "के बारे में": "ke baare mein", "के लिए": "ke liye",
        "के साथ": "ke saath", "के बाद": "ke baad",
    }
    for old, new in subs.items():
        text = re.sub(re.escape(old), new, text)

    # If Hindi is noticeably longer than source, strip leading filler phrases
    if src_word_count > 0:
        hi_words = len(text.split())
        if hi_words > src_word_count * 1.5:
            # Remove common sentence-starting fillers that add length but no meaning
            fillers = [
                r"^(तो\s+)?", r"^(और\s+)?", r"^(अब\s+)?",
                r"^(देखो[,\s]+)", r"^(सुनो[,\s]+)", r"^(जानते हो[,\s]+)",
            ]
            for f in fillers:
                text = re.sub(f, "", text).strip()

    return text.strip()


def translate_all(segs, src_lang, job_id):
    import time as tm
    if src_lang == "hi":
        emit(job_id, "   Hindi video hai — translation skip kar rahe hain", "info")
        for s in segs:
            s["hi"] = s["text"].strip()
        return

    texts = [s["text"].strip() for s in segs]
    hindi = [None] * len(texts)

    emit(job_id, f"   {len(texts)} lines translate kar rahe hain ({src_lang}→Hindustani)...", "info")

    try:
        from deep_translator import GoogleTranslator
        src = src_lang if src_lang in ("en", "auto") else "en"
        tr = GoogleTranslator(source=src, target="hi")
        i = 0
        while i < len(texts):
            j, chunk = i, []
            while j < len(texts) and sum(len(t) for t in chunk) + len(texts[j]) < 3000:
                chunk.append(texts[j])
                j += 1
            out = None
            for att in range(4):
                try:
                    out = tr.translate("\n".join(chunk))
                    break
                except Exception as e:
                    emit(job_id, f"   translate retry {att+1}/4: {e}", "warn")
                    tm.sleep(15 * (att + 1))
            lines = [l for l in (out or "").split("\n") if l.strip()]
            if len(lines) == len(chunk):
                for kk, l in enumerate(lines):
                    src_wc = len(chunk[kk].split())
                    hindi[i + kk] = natural_hindustani(l.strip(), src_wc)
            i = j
    except Exception as e:
        emit(job_id, f"   Google translate error: {e}", "warn")

    missing = [k for k in range(len(texts)) if not hindi[k]]
    if missing:
        emit(job_id, f"   {len(missing)} lines MyMemory se try kar rahe hain...", "warn")
        import requests as rq
        for k in missing:
            try:
                rr = rq.get(
                    "https://api.mymemory.translated.net/get",
                    params={"q": texts[k][:480],
                            "langpair": f"{src_lang if src_lang != 'auto' else 'en'}|hi-IN"},
                    timeout=15,
                )
                val = rr.json()["responseData"]["translatedText"]
                hindi[k] = natural_hindustani(val) if val else None
            except Exception:
                hindi[k] = None
            tm.sleep(0.3)

    for k in range(len(texts)):
        segs[k]["hi"] = (hindi[k] or texts[k]).strip()
        if not hindi[k]:
            emit(job_id, f"   ! translate fail (original text rakha): {texts[k][:40]}", "warn")


# ── TTS ──────────────────────────────────────────────────────────────────────

# ── Voice Reference Extraction ───────────────────────────────────────────────

def extract_speaker_refs(segs, spk, audio_np, work, job_id):
    """
    Extract the best (longest clean) audio clip per speaker as voice reference.
    Returns dict: {speaker_id: path_to_wav}
    """
    SR16 = 16000
    refs = {}
    spk_segs = {}
    for i, s in enumerate(segs):
        k = spk[i]
        dur_s = s["end"] - s["start"]
        if dur_s < 2.0:   # too short for good reference
            continue
        if k not in spk_segs or dur_s > spk_segs[k][0]:
            spk_segs[k] = (dur_s, s)

    for k, (dur_s, s) in spk_segs.items():
        a = int(s["start"] * SR16)
        b = min(int(s["end"]  * SR16), len(audio_np))
        clip = audio_np[a:b]
        if len(clip) < SR16 * 2:
            continue
        # Use up to 8 seconds
        clip = clip[:SR16 * 8]
        ref_path = work / f"ref_spk{k}.wav"
        with wave.open(str(ref_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR16)
            wf.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())
        refs[k] = ref_path
        emit(job_id, f"   🎤 Speaker {k+1} reference: {dur_s:.1f}s clip extracted", "info")

    return refs


# ── TTS with Voice Cloning ────────────────────────────────────────────────────

def tts_one_clone(text, ref_wav, ref_text, out_wav, job_id):
    """
    Generate speech using f5-tts voice cloning.
    ref_wav  = original speaker's WAV (3-8 seconds)
    ref_text = transcribed text from that WAV segment (helps model)
    out_wav  = output WAV path
    Returns True on success.
    """
    try:
        from f5_tts.api import F5TTS
        tts_engine = F5TTS()
        wav, sr, _ = tts_engine.infer(
            ref_file=str(ref_wav),
            ref_text=ref_text[:200],   # reference transcript
            gen_text=text,
            file_wave=str(out_wav),
        )
        return True
    except Exception as e:
        emit(job_id, f"   f5-tts clone fail: {e}", "warn")
        return False


def tts_all_with_cloning(segs, genders, spk, speaker_refs, spk_ref_texts,
                         work, job_id, audio_np, f0s_med):
    """
    Generate all TTS clips:
    1. Try f5-tts voice cloning (sounds like original speaker)
    2. Fallback: edge-tts + pitch shift to match original speaker's F0
    """
    import edge_tts as _edge_tts

    # Check if f5-tts works at all (try one quick test)
    f5_available = False
    try:
        from f5_tts.api import F5TTS
        f5_available = True
        emit(job_id, "   🔊 F5-TTS voice cloning available!", "success")
    except Exception as e:
        emit(job_id, f"   ⚠️ F5-TTS not available ({e}) — pitch-matched Edge-TTS use hoga", "warn")

    async def _edge_tts_fallback(text, voice, out_mp3, slot_s):
        """Edge-TTS with SSML rate control."""
        natural_est = max(1.0, len(text) / 3.5)
        ratio = natural_est / max(slot_s, 0.5)
        if ratio > 1.20:
            rate = "-20%"
        elif ratio > 1.08:
            rate = "-10%"
        elif ratio < 0.75:
            rate = "+10%"
        else:
            rate = "0%"
        safe = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="hi-IN">'
                f'<voice name="{voice}"><prosody rate="{rate}">{safe}</prosody></voice></speak>')
        try:
            comm = _edge_tts.Communicate(ssml, voice)
            await comm.save(out_mp3)
            return True
        except Exception:
            try:
                await _edge_tts.Communicate(text, voice).save(out_mp3)
                return True
            except Exception:
                return False

    def _pitch_shift_to_target(src_wav, dst_wav, src_f0, target_f0):
        """
        Use ffmpeg to pitch-shift edge-tts output so it sounds closer
        to the original speaker's pitch.
        semitones = 12 * log2(target / source)
        Edge-TTS male is ~110 Hz, female ~220 Hz
        """
        if target_f0 <= 0 or src_f0 <= 0:
            return
        import math
        semitones = 12 * math.log2(target_f0 / src_f0)
        semitones = max(-12, min(12, semitones))  # clamp to ±1 octave
        if abs(semitones) < 0.5:
            return  # not worth shifting
        cents = int(semitones * 100)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_wav),
             "-af", f"asetrate={SR}*2^({cents}/1200),atempo=1/2^({cents}/1200)",
             "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst_wav)],
            capture_output=True, shell=False
        )

    EDGE_TTS_F0 = {"M": 110.0, "F": 220.0}

    total = len(segs)
    clone_ok = 0
    clone_fail = 0

    for i, s in enumerate(segs):
        text = s.get("hi", "").strip()
        if not text:
            continue

        k = spk[i]
        g = genders.get(k, "M")
        slot = s["end"] - s["start"]
        target_f0 = f0s_med.get(k, EDGE_TTS_F0[g])

        out_wav = work / f"tts_{i:03d}.wav"
        out_mp3 = work / f"tts_{i:03d}.mp3"
        s["mp3"] = str(out_mp3)

        cloned = False

        # ── Try f5-tts voice cloning ──
        if f5_available and k in speaker_refs:
            ref_wav = speaker_refs[k]
            ref_text = spk_ref_texts.get(k, "")
            if tts_one_clone(text, ref_wav, ref_text, out_wav, job_id):
                # Convert WAV → MP3 for consistency
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(out_wav),
                     "-ar", str(SR), "-ac", "2", "-q:a", "2", str(out_mp3)],
                    capture_output=True, shell=False
                )
                if r.returncode == 0 and out_mp3.exists():
                    cloned = True
                    clone_ok += 1

        # ── Fallback: edge-tts + pitch shift ──
        if not cloned:
            voice = VOICES[g]
            asyncio.run(_edge_tts_fallback(text, voice, out_mp3, slot))
            clone_fail += 1

            # Pitch shift to match original speaker's F0
            if abs(target_f0 - EDGE_TTS_F0[g]) > 15:
                shifted = work / f"tts_{i:03d}_shifted.wav"
                tmp_wav = work / f"tts_{i:03d}_tmp.wav"
                # Convert mp3 → wav first
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(out_mp3),
                     "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(tmp_wav)],
                    capture_output=True, shell=False
                )
                _pitch_shift_to_target(tmp_wav, shifted, EDGE_TTS_F0[g], target_f0)
                if shifted.exists():
                    # Re-encode to mp3
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", str(shifted), "-q:a", "2", str(out_mp3)],
                        capture_output=True, shell=False
                    )

        if (i + 1) % 10 == 0:
            emit(job_id, f"   🎙️ TTS: {i+1}/{total} clips done ({clone_ok} cloned, {clone_fail} edge-tts)", "info")

    emit(job_id,
         f"   ✅ TTS complete: {clone_ok} voice-cloned, {clone_fail} edge-tts fallback",
         "success" if clone_ok > 0 else "warn")


# ── timeline cuts & mixing ────────────────────────────────────────────────────

def format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    s = max(0.0, float(seconds))
    millis = int(round((s - int(s)) * 1000))
    total_sec = int(s)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt_file(segs, out_path: Path):
    """Write standardized SRT subtitle file matching timeline cuts."""
    with open(out_path, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            t0 = format_srt_time(s["start"])
            t1 = format_srt_time(s["end"])
            txt = s.get("hi", s.get("text", "")).strip()
            f.write(f"{i}\n{t0} --> {t1}\n{txt}\n\n")


def timeline_cut_and_mix(segs, bg, work, job_id, voice_vol=1.0, bg_vol=0.35, is_raw_bg=False):
    """
    Timeline Dialogue Cuts & Sample-Accurate Mixing Engine:
    1. Timeline Speech Cuts: Every dialogue occurs in a cut window [s['start'], s['end']].
    2. Background Dynamic Ducking:
       - During dialogue cuts:
         * If raw audio (skip_bgm / Demucs fallback): BG is ducked to ~0.02 (silenced) so the
           original language voice does NOT bleed or clash with dubbed Hindi!
         * If Demucs no_vocals: BG is smoothly ducked to 30% for broadcast-quality dialogue clarity.
       - Outside cuts: Background music / ambiance plays at full 100% volume.
       - Smooth 40ms ramps at cut boundaries ensure zero digital clicks or pops.
    3. Sample-Accurate Voice Placement:
       - Dubbed clips start exactly at sample round(s['start'] * SR).
       - Length is fitted to the cut window + available silence gap (atempo clamped 1.0 - 1.25x).
       - Micro fade-in (15ms) and fade-out (25ms) on each cut.
    """
    N = len(bg)
    bg_envelope = np.ones((N, 1), dtype=np.float32)
    voice = np.zeros_like(bg)
    warns = []
    ramp_samples = int(0.04 * SR)  # 40ms crossfade

    # Target volume multiplier during dialogue cuts
    # If raw audio is used as BG, duck almost completely so old voice doesn't bleed through
    cut_target = 0.02 if is_raw_bg else 0.35

    # 1. Build timeline ducking envelope for background
    for s in segs:
        t0 = max(0.0, s["start"] - 0.02)
        t1 = min(N / SR, s["end"] + 0.02)
        i0 = int(round(t0 * SR))
        i1 = int(round(t1 * SR))

        if i1 <= i0:
            continue

        # Ramp down
        r_start = max(0, i0 - ramp_samples)
        if i0 > r_start:
            ramp_down = np.linspace(1.0, cut_target, i0 - r_start).reshape(-1, 1)
            bg_envelope[r_start:i0] = np.minimum(bg_envelope[r_start:i0], ramp_down)

        # Mute/duck during dialogue cut
        bg_envelope[i0:i1] = np.minimum(bg_envelope[i0:i1], cut_target)

        # Ramp up
        r_end = min(N, i1 + ramp_samples)
        if r_end > i1:
            ramp_up = np.linspace(cut_target, 1.0, r_end - i1).reshape(-1, 1)
            bg_envelope[i1:r_end] = np.minimum(bg_envelope[i1:r_end], ramp_up)

    # Apply timeline ducking to background
    ducked_bg = bg * bg_envelope * bg_vol

    # 2. Process each timeline dialogue cut
    for i, s in enumerate(segs):
        mp3 = s.get("mp3")
        if not mp3 or not Path(mp3).exists():
            continue

        d = dur(mp3)
        slot_dur = s["end"] - s["start"]

        if i + 1 < len(segs):
            gap_end = segs[i + 1]["start"]
        else:
            gap_end = N / SR

        available_gap = gap_end - s["start"]

        # Calculate best fitting tempo for the cut
        if d <= slot_dur + 0.05:
            tempo = 1.0
        elif d <= available_gap - 0.05:
            # Can comfortably breathe into gap with subtle speedup
            tempo = max(1.0, min(1.15, d / max(available_gap, 0.2)))
        else:
            # Tighter gap — fit before next dialogue cut begins
            tempo = max(1.0, min(1.25, d / max(available_gap - 0.05, 0.2)))

        dst = work / f"clip_{i:03d}.wav"
        filt = f"atempo={tempo:.4f}" if tempo > 1.001 else "anull"
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", mp3, "-af", filt, "-ar", str(SR),
             "-ac", "2", "-c:a", "pcm_s16le", str(dst)],
            capture_output=True, text=True, shell=False
        )
        if r.returncode != 0:
            emit(job_id, f"   clip convert fail {i}: {r.stderr[-200:]}", "warn")
            continue

        clip = read_wav(dst)
        i0 = int(round(s["start"] * SR))

        # Clamp to prevent collision with next cut
        max_samples = int(round(gap_end * SR)) - i0
        if max_samples <= 0:
            continue

        clip = clip[:max_samples]

        # Apply smooth 15ms fade-in and 25ms fade-out for clean cut edges
        fade_in_len = min(int(0.015 * SR), len(clip) // 4)
        if fade_in_len > 0:
            fade_in = np.linspace(0.0, 1.0, fade_in_len)[:, None]
            clip[:fade_in_len] *= fade_in

        fade_out_len = min(int(0.025 * SR), len(clip) // 4)
        if fade_out_len > 0:
            fade_out = np.linspace(1.0, 0.0, fade_out_len)[:, None]
            clip[-fade_out_len:] *= fade_out

        clip_dur = len(clip) / SR
        if clip_dur > slot_dur + 0.15:
            warns.append(f"Cut #{i+1}: speech extended into gap ({clip_dur:.1f}s vs slot {slot_dur:.1f}s, speed {tempo:.2f}x)")

        i1 = min(N, i0 + len(clip))
        if i1 > i0:
            voice[i0:i1] += clip[:i1 - i0] * voice_vol

    # Final combined mix
    mixed = ducked_bg + voice
    return mixed, warns


# ── main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(job_id: str, src: Path, speakers: int | None, model: str,
                 voice_vol: float, bg_vol: float, skip_bgm: bool = False):
    jobs[job_id]["skip_bgm"] = skip_bgm
    try:
        jobs[job_id]["status"] = "running"
        work = WORK_DIR / job_id
        work.mkdir(exist_ok=True)
        out = work / (src.stem + ".hindustani.mp4")

        # ── Step 1: audio extract ──
        set_progress(job_id, 5, "Audio nikal rahe hain...")
        emit(job_id, "▶ [1/7] Audio extract kar rahe hain...")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", str(SR),
             "-c:a", "pcm_s16le", str(work / "src44.wav")],
            capture_output=True, text=True, shell=False
        )
        ok(r, "audio extract", job_id)

        # mono 16k for whisper
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(work / "src44.wav"), "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(work / "mono16.wav")],
            capture_output=True, text=True, shell=False
        )
        ok(r, "mono16 convert", job_id)

        # ── Step 2: source separation ──
        skip_bgm = jobs[job_id].get("skip_bgm", False)
        sep_out = work / "sep" / "htdemucs" / "src44" / "no_vocals.wav"

        if skip_bgm:
            set_progress(job_id, 20, "BGM separation skip kiya (fast mode)...")
            emit(job_id, "▶ [2/7] BGM separation skip — original audio use hoga background ke liye", "warn")
            bg_src = work / "src44.wav"
        elif sep_out.exists():
            # Already separated from a previous run or concurrent process
            set_progress(job_id, 20, "Demucs already done — reusing...")
            emit(job_id, "▶ [2/7] Demucs output already exist karta hai — reuse kar rahe hain", "success")
            bg_src = sep_out
        else:
            set_progress(job_id, 12, "Voice aur music alag kar rahe hain (demucs)...")
            emit(job_id, "▶ [2/7] Demucs se voice/music alag kar rahe hain... (CPU pe 2-10 min lag sakte hain, please wait)")
            emit(job_id, "   ⚠️  Yeh step slow hai — progress bar 12% pe ruk sakti hai, rukna mat!", "warn")

            # KEY FIX: Don't use capture_output=True for large files — it fills the pipe buffer
            # and blocks the subprocess. Write stderr to a file instead.
            demucs_log = work / "demucs.log"
            with open(demucs_log, "w") as logf:
                proc = subprocess.run(
                    [sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals",
                     "-o", str(work / "sep"), str(work / "src44.wav")],
                    stdout=logf, stderr=logf, shell=False
                )

            if proc.returncode != 0 or not sep_out.exists():
                # Read last 500 chars from log for error msg
                try:
                    log_tail = demucs_log.read_text(encoding="utf-8", errors="replace")[-500:]
                except Exception:
                    log_tail = "(log unreadable)"
                emit(job_id, f"   Demucs fail — original audio use kar rahe hain. Error: {log_tail}", "warn")
                bg_src = work / "src44.wav"
            else:
                emit(job_id, "   ✅ Demucs complete — voice aur music alag ho gaye!", "success")
                bg_src = sep_out

        set_progress(job_id, 22, "Background audio prepare kar rahe hain...")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(bg_src), "-ar", str(SR), "-ac", "2",
             "-c:a", "pcm_s16le", str(work / "bg.wav")],
            capture_output=True, text=True, shell=False
        )
        ok(r, "bg convert", job_id)
        bg = read_wav(work / "bg.wav")

        # ── Step 3: transcription ──
        set_progress(job_id, 30, "Speech samajh rahe hain (Whisper)...")
        emit(job_id, f"▶ [3/7] Whisper ({model}) se speech samajh rahe hain...")

        # Load mono 16k WAV to numpy array
        with wave.open(str(work / "mono16.wav"), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        MODEL_MB = {"tiny": 39, "base": 74, "small": 244, "medium": 769, "large": 1550}
        emit(job_id,
             f"   ⏳ Whisper '{model}' model load ho raha hai (~{MODEL_MB.get(model, 500)}MB)...\n"
             f"   ⚠️  Pehli baar chalane pe yeh download hota hai — please WAIT karo!", "warn")

        segs = []
        lang = "en"

        def _run_heartbeat(stop_event, prefix="   🎙️ Kaam chal raha hai"):
            """Emit a periodic 'alive' log so the frontend doesn't look frozen."""
            elapsed = 0
            while not stop_event.is_set():
                stop_event.wait(timeout=6)
                elapsed += 6
                if not stop_event.is_set():
                    emit(job_id, f"{prefix}... ({elapsed}s)", "info")

        # ── Try faster-whisper first (CTranslate2 INT8 — fast on CPU) ──────────
        fw_ok = False
        try:
            from faster_whisper import WhisperModel

            # Check if model is already cached (avoid silent HF download hang)
            import os as _os
            hf_cache = _os.path.join(_os.path.expanduser("~"), ".cache", "huggingface", "hub")
            model_cached = any(
                f"whisper-{model}" in d or f"faster-whisper-{model}" in d
                for d in (_os.listdir(hf_cache) if _os.path.isdir(hf_cache) else [])
            )
            if not model_cached:
                emit(job_id,
                     f"   📥 Model cache mein nahi hai — HuggingFace se download hoga (~{MODEL_MB.get(model,500)}MB).\n"
                     f"   Yeh ek baar hi hoga. Internet slow ho to 5-10 min lag sakte hain!", "warn")

            hb_stop = threading.Event()
            hb = threading.Thread(target=_run_heartbeat,
                                  args=(hb_stop, f"   📥 Model load/download chal raha hai ({model})"),
                                  daemon=True)
            hb.start()
            try:
                fw_model = WhisperModel(model, device="cpu", compute_type="int8")
            finally:
                hb_stop.set()

            emit(job_id, "   ✅ faster-whisper model ready! Transcription shuru...", "success")

            hb2_stop = threading.Event()
            hb2 = threading.Thread(target=_run_heartbeat,
                                   args=(hb2_stop, "   🎙️ Transcribing"),
                                   daemon=True)
            hb2.start()
            try:
                segs_gen, info = fw_model.transcribe(
                    audio_np,
                    word_timestamps=True,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400),
                )
                lang = info.language
                emit(job_id, f"   🌐 Language: {lang.upper()}", "info")
                for seg in segs_gen:
                    t = seg.text.strip()
                    if t and not set(t) <= set("♪♫.!? -—"):
                        segs.append({"start": float(seg.start), "end": float(seg.end), "text": t})
                        if len(segs) % 5 == 0:
                            emit(job_id, f"   📝 {len(segs)} segments ({seg.start:.0f}s–{seg.end:.0f}s)...", "info")
            finally:
                hb2_stop.set()

            fw_ok = True
            emit(job_id, f"   ✅ faster-whisper complete! {len(segs)} segments mili.", "success")

        except Exception as fw_err:
            emit(job_id, f"   ⚠️ faster-whisper error: {fw_err}", "warn")

        # ── Fallback: openai-whisper (always installed, reliable) ───────────────
        if not fw_ok:
            emit(job_id, "   🔄 openai-whisper se try kar rahe hain (yeh slow hai)...", "warn")
            try:
                import whisper as _whisper

                hb3_stop = threading.Event()
                hb3 = threading.Thread(target=_run_heartbeat,
                                       args=(hb3_stop, f"   ⏳ openai-whisper '{model}' load/transcribe"),
                                       daemon=True)
                hb3.start()
                try:
                    wm = _whisper.load_model(model)
                    emit(job_id, "   ✅ Model load hua — transcribing...", "info")
                    result = wm.transcribe(
                        str(work / "mono16.wav"),
                        fp16=False,
                        verbose=False,
                        word_timestamps=True,
                    )
                finally:
                    hb3_stop.set()

                lang = result.get("language", "en")
                segs = [
                    {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
                    for s in result["segments"]
                    if s["text"].strip() and not set(s["text"].strip()) <= set("♪♫.!? -—")
                ]
                emit(job_id, f"   ✅ openai-whisper complete! {len(segs)} segments mili.", "success")

            except Exception as wb_err:
                raise RuntimeError(
                    f"❌ Whisper bilkul kaam nahi kar raha!\n"
                    f"faster-whisper error: {fw_err if not fw_ok else 'N/A'}\n"
                    f"openai-whisper error: {wb_err}\n\n"
                    f"Fix: Terminal mein run karo:\n"
                    f"  pip install -U openai-whisper faster-whisper\n"
                    f"  whisper --model {model} --language auto dub_jobs/test.wav"
                )

        segs.sort(key=lambda s: s["start"])

        if not segs:
            raise RuntimeError(
                "Video mein koi speech nahi mili! Check karo:\n"
                "1. Video mein actually dialogue hai?\n"
                "2. 'tiny' ya 'base' model try karo (fast mode on karo)\n"
                "3. Video silent ya music-only to nahi?"
            )

        emit(job_id, f"   ✅ {lang.upper()} language, {len(segs)} segments mili", "success")

        # ── Step 4: speaker detection ──
        set_progress(job_id, 45, "Speakers detect kar rahe hain...")
        emit(job_id, "▶ [4/7] Speaker diarization + gender detect kar rahe hain...")

        mono = audio_np
        utts = group_utts(segs)
        uf0s = utt_f0s(utts, segs, mono)

        try:
            spk, cents_d = assign_speakers(segs, mono, utts, speakers)
            genders, f0s_med = pick_genders(cents_d, uf0s, utts, spk, work)
        except Exception as e:
            emit(job_id, f"   Speaker detection mein error: {e} — single speaker assume kar rahe hain", "warn")
            spk = [0] * len(segs)
            cents_d = {}
            genders = {0: "M"}
            f0s_med = {0: 120.0}

        n_spk = len(set(spk))
        emit(job_id, f"   {n_spk} speaker(s) mili:", "success")
        for k in sorted(set(spk)):
            g = genders.get(k, "M")
            f = f0s_med.get(k, 0)
            cnt = spk.count(k)
            emit(job_id, f"   Speaker {k+1}: {'FEMALE' if g=='F' else 'MALE'} (pitch {f:.0f}Hz, {cnt} lines) → {VOICES[g]}")

        # Extract speaker reference audio for voice cloning
        emit(job_id, "   🎤 Voice cloning ke liye speaker references extract kar rahe hain...", "info")
        speaker_refs = extract_speaker_refs(segs, spk, audio_np, work, job_id)
        # Build ref_text dict: text of the reference segment per speaker
        spk_ref_texts = {}
        for i, s in enumerate(segs):
            k = spk[i]
            ref_path = work / f"ref_spk{k}.wav"
            if ref_path.exists() and k not in spk_ref_texts:
                spk_ref_texts[k] = s.get("text", "")

        # ── Step 5: translation ──
        set_progress(job_id, 58, "Natural Hindustani mein translate kar rahe hain...")
        emit(job_id, "▶ [5/7] Natural Hindustani translation (Hindi+Urdu+English mix)...")
        translate_all(segs, lang, job_id)

        # ── Step 6: TTS with Voice Cloning ──
        set_progress(job_id, 70, "Voice cloning se Hindi awaaz bana rahe hain...")
        emit(job_id, "▶ [6/7] Voice Cloning (F5-TTS) se Hindustani awaaz bana rahe hain...")
        emit(job_id, "   ⚠️  Pehli baar F5-TTS model download hoga (~1.5GB) — please wait!", "warn")
        tts_all_with_cloning(segs, genders, spk, speaker_refs, spk_ref_texts,
                             work, job_id, audio_np, f0s_med)
        emit(job_id, f"   {len(segs)} clips generate kiye", "success")

        # ── Step 7: timeline cuts mix & mux ──
        set_progress(job_id, 85, "Timeline cuts ke hisab se audio mix kar rahe hain...")
        emit(job_id, "▶ [7/7] Timeline Dialogue Cuts mix + dynamic background ducking...")
        is_raw_bg = (bg_src == work / "src44.wav")
        mix, warns = timeline_cut_and_mix(segs, bg, work, job_id, voice_vol, bg_vol, is_raw_bg=is_raw_bg)
        write_wav(work / "mix.wav", mix)

        # Write SRT timeline cuts file
        srt_path = work / (src.stem + ".timeline.srt")
        write_srt_file(segs, srt_path)
        emit(job_id, f"   📜 Timeline Subtitles (.srt) generate ho gaye: {srt_path.name}", "info")

        for w in warns:
            emit(job_id, f"   WARN: {w}", "warn")

        # Mux with soft subtitles
        mux_cmd = [
            "ffmpeg", "-y", "-i", str(src), "-i", str(work / "mix.wav"),
            "-i", str(srt_path),
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-c:s", "mov_text",
            "-metadata:s:s:0", "language=hin",
            str(out)
        ]
        r = subprocess.run(mux_cmd, capture_output=True, text=True, shell=False)
        if r.returncode != 0:
            # Fallback to standard mux if mov_text has container issue
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-i", str(work / "mix.wav"),
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", str(out)],
                capture_output=True, text=True, shell=False
            )
        ok(r, "mux", job_id)

        # Build timeline cuts data for frontend visualizer
        cuts_data = []
        for idx, s in enumerate(segs):
            cuts_data.append({
                "id": idx + 1,
                "start": round(float(s["start"]), 2),
                "end": round(float(s["end"]), 2),
                "duration": round(float(s["end"] - s["start"]), 2),
                "speaker": int(spk[idx] + 1),
                "gender": genders.get(spk[idx], "M"),
                "orig": s.get("text", "").strip(),
                "hi": s.get("hi", "").strip()
            })

        set_progress(job_id, 100, "Done!")
        jobs[job_id]["status"] = "done"
        jobs[job_id]["output"] = str(out)
        jobs[job_id]["srt_path"] = str(srt_path)
        jobs[job_id]["filename"] = out.name
        jobs[job_id]["cuts"] = cuts_data

        summary = {
            "language": lang.upper(),
            "speakers": n_spk,
            "segments": len(segs),
            "cuts": len(cuts_data),
            "warnings": len(warns),
        }
        jobs[job_id]["summary"] = summary
        emit(job_id, f"✅ Done! Output: {out.name} ({len(cuts_data)} timeline cuts synced)", "success")

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        emit(job_id, f"❌ Error: {e}", "error")


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "Koi video nahi mili"}), 400

    file = request.files["video"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    speakers = request.form.get("speakers", None)
    model = request.form.get("model", "small")
    voice_vol = float(request.form.get("voice_vol", "1.0"))
    bg_vol = float(request.form.get("bg_vol", "0.35"))
    skip_bgm = request.form.get("skip_bgm", "false").lower() == "true"

    if speakers:
        try:
            speakers = int(speakers)
        except Exception:
            speakers = None

    job_id = str(uuid.uuid4())
    job_work = WORK_DIR / job_id
    job_work.mkdir(exist_ok=True)

    # save upload
    ext = Path(file.filename).suffix or ".mp4"
    src = job_work / f"input{ext}"
    file.save(str(src))

    jobs[job_id] = {
        "id": job_id,
        "filename": file.filename,
        "status": "queued",
        "progress": 0,
        "stage": "Waiting...",
        "logs": [],
        "output": None,
        "srt_path": None,
        "cuts": [],
        "error": None,
        "summary": None,
        "skip_bgm": skip_bgm,
    }

    t = threading.Thread(
        target=run_pipeline,
        args=(job_id, src, speakers, model, voice_vol, bg_vol, skip_bgm),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job nahi mili"}), 404
    return jsonify({
        "status": job["status"],
        "progress": job["progress"],
        "stage": job.get("stage", ""),
        "error": job.get("error"),
        "summary": job.get("summary"),
        "filename": job.get("filename"),
        "cuts": job.get("cuts", []),
    })


@app.route("/api/logs/<job_id>")
def logs_sse(job_id):
    """Server-Sent Events for live log streaming."""
    def generate():
        sent = 0
        while True:
            job = jobs.get(job_id)
            if not job:
                yield "data: {\"msg\": \"Job nahi mili\", \"level\": \"error\"}\n\n"
                break
            logs = job["logs"]
            while sent < len(logs):
                entry = logs[sent]
                yield f"data: {json.dumps(entry)}\n\n"
                sent += 1
            if job["status"] in ("done", "error"):
                yield "data: {\"_done\": true}\n\n"
                break
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File taiyar nahi hai"}), 404
    out_path = job["output"]
    if not out_path or not Path(out_path).exists():
        return jsonify({"error": "Output file nahi mili"}), 404
    return send_file(out_path, as_attachment=True, download_name=job["filename"])


@app.route("/api/video/<job_id>")
def video_preview(job_id):
    """Stream dubbed video with byte-range support for in-browser playback."""
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Video taiyar nahi hai"}), 404
    out_path = job["output"]
    if not out_path or not Path(out_path).exists():
        return jsonify({"error": "Output video file nahi mili"}), 404
    return send_file(out_path, mimetype="video/mp4", conditional=True)


@app.route("/api/subtitles/<job_id>")
def download_subtitles(job_id):
    """Download SRT subtitle file containing exact timeline cuts."""
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Subtitles taiyar nahi hain"}), 404
    srt_path = job.get("srt_path")
    if not srt_path or not Path(srt_path).exists():
        return jsonify({"error": "SRT file nahi mili"}), 404
    srt_name = Path(job.get("filename", "subtitles.mp4")).stem + ".timeline.srt"
    return send_file(srt_path, as_attachment=True, download_name=srt_name, mimetype="text/plain; charset=utf-8")


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5050, threaded=True)
