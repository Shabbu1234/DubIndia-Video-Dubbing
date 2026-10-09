# 🎙️ DubIndia — Hindustani Video Dubbing & Segment Sync Tool

> Automatically detect speech clips, identify speaker genders, translate dialogue into natural Hindustani (Hindi + Urdu + English mix), and sync dubbed audio with precise video cuts while preserving original Background Music (BGM).

---

## 🌟 Key Features

- **⏱️ Segment-by-Segment Cut & Sync:** Detects exact timestamps where voice occurs, splits clips, dubs them, and re-fits them into the timeline with zero audio drift.
- **👥 Multi-Speaker & Gender Matching:** Pitch detection + voice embeddings to automatically match Male (`hi-IN-MadhurNeural`) and Female (`hi-IN-SwaraNeural`) Neural voices.
- **🎵 Background Music (BGM) Preservation:** Uses **Demucs AI** stem separation to keep background score & sound effects untouched while swapping speech.
- **⚡ Time-Fitting (`atempo`):** Automatically speeds up or adjusts TTS playback to fit exact clip slot durations.
- **🌐 Interactive Web Dashboard (`dubbing_app`):** Web UI with live progress tracking, timeline dialogue cut list, video player preview, and SRT subtitle generator.

---

## 🛠️ Tech Stack

- **Speech-to-Text:** OpenAI Whisper
- **Vocal Separation:** Demucs (`htdemucs`)
- **Speech Synthesis (TTS):** Edge-TTS
- **Audio/Video Processing:** FFmpeg, PyDub, Librosa, Resemblyzer
- **Web Frontend & Server:** HTML5, CSS3 Glassmorphism, JavaScript, Python / Flask

---

## 🚀 Quick Start

### 1. Command Line Interface (CLI)

```bash
# Dub any video into Hindustani with multi-speaker support & BGM preserve
python dub_tool.py "input_video.mp4" -o "output_dubbed.mp4"
```

### 2. Web Application

```bash
cd dubbing_app
python app.py
```
Then open `http://localhost:5000` in your browser.

---

## 📂 Project Structure

```
├── dub_tool.py           # Core CLI dubbing pipeline
├── dubbing_app/          # Full Web Application
│   ├── app.py            # Flask backend server & job runner
│   ├── templates/        # HTML index & UI layout
│   └── static/           # Styling & JavaScript logic
├── demo_segments.json    # Sample timeline cuts & segments
└── README.md             # Documentation
```

---

## 📜 License

MIT License. Free to use for personal & commercial comic-to-video / montage dubbing projects.
