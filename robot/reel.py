"""Stitches a batch of finished videos into one small 'review reel', each clip numbered (#1, #2 ...)
with a short title card before it, so a whole batch can be checked in one sitting."""
import os
import subprocess
import tempfile

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "TitanOne-Regular.ttf")
W, H, FPS = 540, 960, 30
ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-video_track_timescale", "15360", "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "2"]


def _has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _text(tmp, name, s):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)
    return p.replace("\\", "/").replace(":", "\\:")


def make_reel(items, out):
    """items: [(video_path, number, label)] -> out (mp4). Returns out."""
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for n, (path, num, label) in enumerate(items):
            big = _text(tmp, f"big{n}.txt", f"#{num}")
            small = _text(tmp, f"lab{n}.txt", label)
            card = os.path.join(tmp, f"card{n}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y",
                            "-f", "lavfi", "-i", f"color=c=0x221c33:s={W}x{H}:d=1.2:r={FPS}",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1.2",
                            "-vf", (f"drawtext=fontfile={FONT}:textfile={big}:fontsize=180:fontcolor=0xff8dcc:"
                                    f"x=(w-text_w)/2:y=(h-text_h)/2-60,"
                                    f"drawtext=fontfile={FONT}:textfile={small}:fontsize=30:fontcolor=white:"
                                    f"x=(w-text_w)/2:y=(h/2)+90"),
                            *ENC, "-shortest", card], check=True, capture_output=True, text=True, timeout=120)
            seg = os.path.join(tmp, f"seg{n}.mp4")
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                  f"setsar=1,fps={FPS},"
                  f"drawtext=fontfile={FONT}:textfile={big}:fontsize=54:fontcolor=white:box=1:boxcolor=0xff2d8a@0.85:"
                  f"boxborderw=12:x=18:y=h-text_h-30")
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", path]
            if _has_audio(path):
                cmd += ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0"]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-vf", vf,
                        "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
            subprocess.run(cmd + ENC + [seg], check=True, capture_output=True, text=True, timeout=600)
            parts += [card, seg]
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        # one clean re-encode of the whole reel: every player (Drive's too) plays it start to finish
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0",
                        "-i", lst, "-af", "aresample=async=1:first_pts=0", *ENC, "-movflags", "+faststart", out],
                       check=True, capture_output=True, text=True, timeout=3600)
    return out
