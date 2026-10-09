"""
DubIndia Diagnostic Script
Run: python check.py
Sab kuch check karta hai aur batata hai kya theek hai, kya nahi.
"""
import sys
import os
import subprocess
import time

OK = "  [OK]"
FAIL = "  [FAIL]"
WARN = "  [WARN]"

print("=" * 55)
print("  DubIndia — Full System Diagnostic")
print("=" * 55)
print()

errors = []
warnings = []

# 1. Python version
print(f"Python: {sys.version}")
if sys.version_info < (3, 9):
    print(f"{FAIL} Python 3.9+ chahiye! Abhi: {sys.version_info.major}.{sys.version_info.minor}")
    errors.append("Python 3.9+ install karo")
else:
    print(f"{OK} Python version theek hai")

# 2. ffmpeg
print()
print("Checking ffmpeg...")
r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
if r.returncode != 0:
    print(f"{FAIL} ffmpeg nahi mila!")
    errors.append("ffmpeg install karo aur PATH mein add karo")
else:
    line = r.stdout.split("\n")[0]
    print(f"{OK} {line}")

# 3. Core packages
print()
print("Checking Python packages...")
packages = {
    "flask": "Flask",
    "numpy": "numpy",
    "torch": "PyTorch",
    "whisper": "openai-whisper",
    "faster_whisper": "faster-whisper",
    "edge_tts": "edge-tts",
    "demucs": "demucs",
    "resemblyzer": "resemblyzer",
    "librosa": "librosa",
    "deep_translator": "deep-translator",
    "requests": "requests",
}
for mod, pkg in packages.items():
    try:
        m = __import__(mod)
        ver = getattr(m, "__version__", "?")
        print(f"  {OK} {pkg} ({ver})")
    except ImportError:
        print(f"  {FAIL} {pkg} — NOT INSTALLED")
        errors.append(f"pip install {pkg}")

# 4. Test faster-whisper model cache
print()
print("Checking Whisper model cache...")
hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
whisper_cache = os.path.join(os.path.expanduser("~"), ".cache", "whisper")

cached_fw = []
if os.path.isdir(hf_cache):
    for d in os.listdir(hf_cache):
        if "whisper" in d.lower():
            cached_fw.append(d)

cached_ow = []
if os.path.isdir(whisper_cache):
    cached_ow = os.listdir(whisper_cache)

if cached_fw:
    print(f"  {OK} faster-whisper cached models: {cached_fw}")
elif cached_ow:
    print(f"  {OK} openai-whisper cached models: {cached_ow}")
else:
    print(f"  {WARN} Koi Whisper model cached nahi! Pehli run pe download hoga.")
    warnings.append("start.bat se run karo — model pre-download hoga (1-2 min, one-time only)")

# 5. Quick faster-whisper test (tiny model only if cached)
print()
print("Testing faster-whisper (tiny model)...")
try:
    from faster_whisper import WhisperModel
    import numpy as np

    tiny_cached = any("tiny" in d for d in cached_fw)
    if tiny_cached:
        print("  Testing with cached tiny model...")
        t0 = time.time()
        m = WhisperModel("tiny", device="cpu", compute_type="int8")
        audio = np.zeros(16000 * 2, dtype=np.float32)  # 2s silence
        segs, info = m.transcribe(audio, vad_filter=True)
        _ = list(segs)
        print(f"  {OK} faster-whisper working! ({time.time()-t0:.1f}s for 2s audio)")
    else:
        print(f"  {WARN} Tiny model not cached — skipping live test (would need download)")
        warnings.append("start.bat chalao — pehle model download ho jayega")
except Exception as e:
    print(f"  {FAIL} faster-whisper test failed: {e}")
    errors.append(f"faster-whisper error: {e}")

# 6. Test edge-tts
print()
print("Testing edge-tts...")
try:
    import asyncio
    import edge_tts

    async def _test():
        c = edge_tts.Communicate("Hello", "hi-IN-MadhurNeural")
        data = b""
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                data += chunk["data"]
        return len(data)

    sz = asyncio.run(_test())
    print(f"  {OK} edge-tts working! ({sz} bytes generated)")
except Exception as e:
    print(f"  {FAIL} edge-tts test failed: {e}")
    errors.append("edge-tts kaam nahi kar raha — internet check karo")

# 7. Summary
print()
print("=" * 55)
if not errors:
    print("SUCCESS: SAB THEEK HAI! DubIndia chalane ke liye ready hai.")
else:
    print(f"ERROR: {len(errors)} ERROR(S) mili:")
    for e in errors:
        print(f"   -> {e}")

if warnings:
    print(f"\nWARNING: {len(warnings)} WARNING(S):")
    for w in warnings:
        print(f"   -> {w}")

print()
print("Dobara check karne ke liye: python check.py")
print("App start karne ke liye:   start.bat (ya python app.py)")
print("=" * 55)
