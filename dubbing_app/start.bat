@echo off
chcp 65001 >nul 2>&1
echo ╔══════════════════════════════════════════════╗
echo ║        DubIndia — Hindustani Dubbing Tool    ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python install nahi hai! python.org se install karo.
    pause
    exit /b 1
)

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ffmpeg install nahi hai!
    echo   Yahan se download karo: https://ffmpeg.org/download.html
    echo   Phir PATH mein add karo.
    pause
    exit /b 1
)

echo [1/4] Dependencies install kar rahe hain...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARN] Kuch packages install nahi hua, phir bhi try karte hain...
)

:: Install faster-whisper if not present (much faster than openai-whisper on CPU)
echo [2/4] faster-whisper check kar rahe hain...
python -c "import faster_whisper" >nul 2>&1
if errorlevel 1 (
    echo   faster-whisper install nahi hai — install kar rahe hain...
    pip install faster-whisper --quiet
) else (
    echo   faster-whisper already installed.
)

:: Pre-download the Whisper model so app doesn't hang on first run
echo [3/4] Whisper 'small' model pre-download kar rahe hain...
echo   (Yeh ek baar hi hoga — ~244MB download. Please wait...)
python -c "
import sys
print('  Checking faster-whisper model cache...')
try:
    from faster_whisper import WhisperModel
    print('  Loading/downloading faster-whisper small model...')
    m = WhisperModel('small', device='cpu', compute_type='int8')
    print('  [OK] faster-whisper small model ready!')
    sys.exit(0)
except Exception as e:
    print(f'  faster-whisper failed: {e}')
    print('  Trying openai-whisper...')
    try:
        import whisper
        m = whisper.load_model('small')
        print('  [OK] openai-whisper small model ready!')
        sys.exit(0)
    except Exception as e2:
        print(f'  openai-whisper also failed: {e2}')
        print('  [WARN] Model download fail — app chalega but pehli run slow hogi.')
        sys.exit(0)
"

echo.
echo [4/4] Sab theek hai!
echo.
echo ══════════════════════════════════════════════
echo   Browser mein yeh link kholo:
echo   http://localhost:5050
echo ══════════════════════════════════════════════
echo.
echo   TIP: Pehli baar 'tiny' ya 'base' model select karo (fast)
echo   Baad mein 'small' ya 'medium' use karo accuracy ke liye
echo.

echo Server shuru kar rahe hain...
python app.py

pause
