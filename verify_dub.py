# verify_dub.py — dub output ka end-to-end check (temp verification script)
import warnings, wave
warnings.filterwarnings("ignore")

import numpy as np
import torch
import whisper

import dub_tool as dt

WORK = "test_input_dub_work"
OUT = "test_input.hindi.mp4"

def wav_read_mono16k(path, sr=16000):
    # kisi bhi audio/video file ko mono 16k float me: whisper loader hi use karo
    return np.asarray(whisper.audio.load_audio(path), dtype=np.float32)

def rms_at_band(x, sr, f0, half=4):
    # FFT se f0 ke aas-paas ka band energy (tonal BGM check)
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    m = (freqs > f0 - half) & (freqs < f0 + half)
    return float(X[m].mean())

print("== 1. Duration match ==")
a = wav_read_mono16k("test_input.mp4"); b = wav_read_mono16k(OUT)
print("input %.2fs, output %.2fs (diff %.3fs)" % (len(a)/16000, len(b)/16000, abs(len(a)-len(b))/16000))

print("== 2. Hindi round-trip (whisper output pe) ==")
res = whisper.load_model("small").transcribe(OUT, fp16=False, verbose=False)
text = " ".join(s["text"].strip() for s in res["segments"])
devanagari = sum(1 for ch in text if "\u0900" <= ch <= "\u097F")
print("lang=%s, devanagari chars=%d" % (res["language"], devanagari))
print("sample:", text[:150])

print("== 3. BGM preserved (280Hz tonal energy, input vs output) ==")
e_in = rms_at_band(a[: 16000 * 38], 16000, 280)
e_out = rms_at_band(b[: 16000 * 38], 16000, 280)
print("input=%.1f output=%.1f ratio=%.2f (1.0 ke paas = music same)" % (e_in, e_out, e_out / e_in))

print("== 4. Voice genders output clips me (anchor sim) ==")
e_f = dt.embed_file(f"{WORK}/anchor_F.mp3"); e_m = dt.embed_file(f"{WORK}/anchor_M.mp3")
from resemblyzer import preprocess_wav
enc = dt.get_enc()
ok_m = ok_f = 0
for i in range(12):
    try:
        emb = torch.from_numpy(enc.embed_utterance(preprocess_wav(f"{WORK}/tts_{i:03d}.mp3")))
        sf, sm = float(emb @ e_f), float(emb @ e_m)
        g = "F" if sf > sm else "M"
        (ok_f if g == "F" else ok_m).__class__  # noqa
        if g == "F": ok_f += 1
        else: ok_m += 1
        print("clip %02d: %s (Swara=%.2f Madhur=%.2f)" % (i, g, sf, sm))
    except Exception as ex:
        print("clip %02d: skip (%s)" % (i, str(ex)[:40]))
print("male clips=%d, female clips=%d (expected alternate, 6-6)" % (ok_m, ok_f))
