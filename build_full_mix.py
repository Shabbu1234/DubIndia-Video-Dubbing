# Reads full_timeline.json on stdin, emits a bash script (stdout) that builds:
# 1) voice_track.wav (each segment placed at its exact start)
# 2) music_bed.wav   (11 mood windows from 10 royalty-free tracks, 2.5s crossfades)
# 3) sfx_track.wav   (key page-synced sounds: shutters, pings, heartbeat, boom, heels...)
# 4) full_audio master (voices + ducked bed + sfx -> loudnorm stereo)
import json
import sys

TL = json.load(sys.stdin)
TOTAL = TL["total"]
SEGS = TL["segments"]

page_start = {}
for s in SEGS:
    page_start.setdefault(s["page"], s["start"])


def t(page):
    return page_start.get(page, TOTAL)


# music windows: (page boundary, track file, track offset start)
WINDOWS = [
    (0,   "music/Impact_Prelude.mp3", 0),
    (3,   "music/Ossuary_5_-_Rest.mp3", 0),
    (13,  "music/Anguish.mp3", 0),
    (20,  "music/Heart_of_Nowhere.mp3", 0),
    (29,  "music/Meditation_Impromptu_02.mp3", 0),
    (43,  "music/Crypto.mp3", 0),
    (58,  "music/Crossing_the_Divide.mp3", 0),
    (82,  "music/Giant_Wyrm.mp3", 0),
    (87,  "music/Impact_Prelude.mp3", 30),
    (101, "music/Giant_Wyrm.mp3", 60),
    (108, "music/Rising_Tide.mp3", 0),
]
XFADE = 2.5

lines = ["set -e", "cd \"C:/Users/PC/Desktop/10th/montege/comics to videos\""]

# 1) voice track: pad each segment to its slot, concat
lines.append("mkdir -p vtmp")
lines.append("rm -f vtmp/*.wav vtmp/list.txt")
for i, s in enumerate(SEGS):
    nxt = SEGS[i + 1]["start"] if i + 1 < len(SEGS) else TOTAL
    slot = round(nxt - s["start"], 3)
    d = s["start"] * 1000
    lines.append(
        f'ffmpeg -y -v error -i "voices/{s["file"]}" '
        f'-af "aresample=48000,adelay={int(round(d))},apad" -t {slot} -ar 48000 -ac 2 '
        f'-c:a pcm_s16le "vtmp/v{i:03d}.wav"'
    )
    lines.append(f"echo 'file v{i:03d}.wav' >> vtmp/list.txt")
lines.append('ffmpeg -y -v error -f concat -safe 0 -i vtmp/list.txt -c:a pcm_s16le voice_track.wav')

# 2) music bed via acrossfade chain
inputs = []
chain = []
prev = None
for wi, (page, track, off) in enumerate(WINDOWS):
    b = t(page) if page != 0 else 0.0
    b_next = t(WINDOWS[wi + 1][0]) if wi + 1 < len(WINDOWS) else TOTAL
    if wi == 0:
        b = 0.0
    if wi == len(WINDOWS) - 1:
        wlen = TOTAL - b
    else:
        wlen = (b_next - b) + XFADE
    inputs.append(f'-i "{track}"')
    label = f"w{wi}"
    sl = f"[{wi}:a]atrim=start={off}:end={off + wlen + 3},asetpts=PTS-STARTPTS,loudnorm=I=-24:TP=-2.5:LRA=9,aformat=sample_rates=48000:channel_layouts=stereo[{label}]"
    chain.append(sl)
    if prev is None:
        prev = f"[{label}]"
    else:
        outl = f"x{wi}"
        chain.append(f"{prev}[{label}]acrossfade=d={XFADE}:c1=tri:c2=tri[{outl}]")
        prev = f"[{outl}]"
lines.append(
    "ffmpeg -y -v error " + " ".join(inputs) + ' -filter_complex "' + ";".join(chain) + '" -map "'
    + prev + '" -t ' + str(TOTAL) + " -c:a pcm_s16le music_bed.wav"
)

# 3) sfx track: real + synthesized page-synced sounds
def shutter_at(page, offs, gain=0.45):
    base = t(page)
    for j, o in enumerate(offs):
        lines.append(f'-f lavfi -i "sine=r=48000:d=0.01"')  # placeholder replaced below

# build sfx as its own ffmpeg command
sfx_inputs = [
    '-i "shutter.ogg"',                       # 0 real shutter (slice 0.40-1.15)
    '-i "thunder.flac"',                      # 1 real thunder (crack 46.5-49.5)
    '-i "wind_night.wav"',                    # 2 wind swell (slice)
    '-f lavfi -i "sine=f=880:r=48000:d=0.12"',  # 3 ping A
    '-f lavfi -i "sine=f=1320:r=48000:d=0.10"',  # 4 ping B
    '-f lavfi -i "anoisesrc=color=brown:r=48000:a=0.5:d=6"',  # 5 whisper bed
    '-f lavfi -i "sine=f=55:r=48000:d=0.5"',    # 6 heartbeat thump
    '-f lavfi -i "sine=f=70:r=48000:d=0.9"',    # 7 car clunk
    '-f lavfi -i "anoisesrc=color=brown:r=48000:a=0.6:d=4"',   # 8 flame roar
    '-f lavfi -i "anoisesrc=color=white:r=48000:a=0.5:d=0.6"',  # 9 paper slide
    '-f lavfi -i "sine=f=1200:r=48000:d=0.05"',  # 10 heel clack
    '-f lavfi -i "sine=f=40:r=48000:d=5"',       # 11 bass pulse
]
sfx_chain = []
sfx_labels = []

def add(label, filt, delay_ms):
    sfx_chain.append(f"{filt}[{label}]")
    sfx_chain.append(f"[{label}]adelay={delay_ms}[{label}d]")
    sfx_labels.append(f"[{label}d]")

# shutters at press pages 1-2
for j, o in enumerate([0.3, 0.95, 1.6, 2.4]):
    add(f"sh{j}", "[0:a]atrim=start=0.40:end=1.15,asetpts=PTS-STARTPTS,volume=0.45", int((t(1) + o) * 1000))
# netizen pings pages 5,7,8
for j, (pg, o, src) in enumerate([(5, 0.2, 3), (5, 1.9, 4), (7, 0.4, 4), (7, 2.1, 3), (8, 0.3, 3), (8, 1.8, 4)]):
    add(f"pg{j}", f"[{src}:a]volume=0.22,afade=t=out:st=0.03:d=0.08", int((t(pg) + o) * 1000))
# whisper swell pages 9-10
add("wh", "[5:a]bandpass=f=1000:width_type=h:w=800,tremolo=f=8:d=0.9,volume=0.28,afade=t=in:d=2,afade=t=out:st=4:d=2", int(t(9) * 1000))
# heartbeats pages 19 and 31
for j, (pg, o) in enumerate([(19, 0.5), (19, 1.4), (19, 2.3), (31, 0.4), (31, 1.3)]):
    add(f"hb{j}", "[6:a]volume=0.5,afade=t=in:d=0.01,afade=t=out:st=0.08:d=0.4", int((t(pg) + o) * 1000))
# wind swell page 46
add("wd", "[2:a]atrim=start=8:end=14,asetpts=PTS-STARTPTS,lowpass=f=1200,volume=0.4,afade=t=in:d=1,afade=t=out:st=4.5:d=1.4", int(t(46) * 1000))
# car clunk page 79 and 87
for j, pg in enumerate([79, 87]):
    add(f"cl{j}", "[7:a]volume=0.5,afade=t=in:d=0.005,afade=t=out:st=0.12:d=0.7", int(t(pg) * 1000))
# flame roar pages 83-84
add("fl", "[8:a]lowpass=f=600,tremolo=f=14:d=0.7,volume=0.35,afade=t=in:d=0.6,afade=t=out:st=2.6:d=1.3", int(t(83) * 1000))
# paper slide page 97
add("pp", "[9:a]highpass=f=1500,afade=t=in:d=0.05,afade=t=out:st=0.2:d=0.4,volume=0.4", int(t(97) * 1000))
# heels pages 105
for j, o in enumerate([0.6, 1.4, 2.2]):
    add(f"hl{j}", "[10:a]volume=0.5,afade=t=out:st=0.012:d=0.035", int((t(105) + o) * 1000))
# bass pulse page 108
add("bp", "[11:a]volume=0.55,afade=t=in:d=1.5,afade=t=out:st=3.2:d=1.7", int(t(108) * 1000))
# thunder boom under upgrader page 101
add("th", "[1:a]atrim=start=46.5:end=49.5,asetpts=PTS-STARTPTS,volume=0.3,afade=t=in:d=0.05,afade=t=out:st=2.2:d=0.8", int(t(101) * 1000))

sfx_chain.append("".join(sfx_labels) + f"amix=inputs={len(sfx_labels)}:normalize=0,apad[sfxc]")
lines.append(
    "ffmpeg -y -v error " + " ".join(sfx_inputs) + ' -filter_complex "'
    + ";".join(sfx_chain) + '" -map "[sfxc]" -t ' + str(TOTAL) + " -ar 48000 -ac 2 -c:a pcm_s16le sfx_track.wav"
)

# 4) master mix: voices + ducked bed + sfx
lines.append(
    'ffmpeg -y -v error -i voice_track.wav -i music_bed.wav -i sfx_track.wav -filter_complex '
    '"[1:a]volume=0.55[bed];[bed][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=150:release=1000[bedd];'
    '[0:a][bedd][2:a]amix=inputs=3:normalize=0,alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11[out]" '
    '-map "[out]" -ar 48000 -c:a pcm_s16le full_audio_master.wav'
)
lines.append('ffmpeg -y -v error -i full_audio_master.wav -c:a libmp3lame -b:a 320k full_audio_20min.mp3')
lines.append('ffmpeg -y -v error -i music_bed.wav -c:a libmp3lame -b:a 192k music_bed_20min.mp3')
lines.append(
    'ffmpeg -y -v error -i music_bed.wav -af "apad,atrim=0:1200,afade=t=out:st=1190:d=10" '
    '-c:a libmp3lame -b:a 192k music_bed_full20min.mp3'
)
lines.append('echo MIX_DONE')

sys.stdout.write("\n".join(lines) + "\n")
