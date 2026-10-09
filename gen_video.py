# Reads full_timeline.json on stdin, prints a bash script (stdout) that renders
# the full 16:9 movie: one Ken Burns beat per spoken page, concat, audio mux.
import json
import sys

TL = json.load(sys.stdin)
TOTAL = TL["total"]
SEGS = TL["segments"]

# page -> first segment start (playback order preserved)
page_start = {}
page_order = []
for s in SEGS:
    if s["page"] not in page_start:
        page_start[s["page"]] = s["start"]
        page_order.append(s["page"])

lines = [
    "set -e",
    'cd "C:/Users/PC/Desktop/10th/montege/comics to videos"',
    "mkdir -p vt",
    "rm -f vt/*.mp4 vt/list.txt",
]

FPS = 30
for i, page in enumerate(page_order):
    start = page_start[page]
    if i == 0:
        start = 0.0  # opening: hold title card through the music intro
    if i + 1 < len(page_order):
        end = page_start[page_order[i + 1]]
    else:
        end = TOTAL
    win = round(end - start, 3)
    n = max(2, round(win * FPS))
    png = f"pages_hi/page_{page:03d}.png"
    m = i % 3
    if m == 0:      # slow push in
        z = f"1+0.07*on/{n}"
        x = "(iw-iw/zoom)/2"
    elif m == 1:    # slow pull out
        z = f"1.07-0.07*on/{n}"
        x = "(iw-iw/zoom)/2"
    else:           # push in with gentle right drift
        z = f"1+0.06*on/{n}"
        x = f"(iw-iw/zoom)/2+30*on/{n}"
    fade_out = round(win - 0.25, 3)
    lines.append(
        f'ffmpeg -nostdin -y -v error -loop 1 -t {win + 0.1} -i "{png}" -filter_complex '
        f'"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=28,'
        f'eq=brightness=-0.18:saturation=0.85[bg];[0:v]scale=-2:1080[fg];'
        f'[bg][fg]overlay=(W-w)/2:(H-h)/2,'
        f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={n}:s=1920x1080:fps={FPS},"
        f'fade=t=in:st=0:d=0.22,fade=t=out:st={fade_out}:d=0.25,format=yuv420p" '
        f'-frames:v {n} -c:v libx264 -preset veryfast -crf 20 "vt/s{i:03d}.mp4"'
    )
    lines.append(f"echo 'file s{i:03d}.mp4' >> vt/list.txt")

lines.append('ffmpeg -nostdin -y -v error -f concat -safe 0 -i vt/list.txt -c copy vt/full_silent.mp4')
lines.append(
    'ffmpeg -nostdin -y -v error -i vt/full_silent.mp4 -i full_audio_master.wav '
    '-c:v copy -c:a aac -b:a 192k -movflags +faststart -shortest Solo_Leveling_Ch108_Hindi_16x9.mp4'
)
lines.append("echo VIDEO_DONE")

sys.stdout.write("\n".join(lines) + "\n")
