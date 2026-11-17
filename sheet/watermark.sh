#!/usr/bin/env bash
# Leonida Reels | GTA 6 — one master clip in, one watermarked copy per account out.
# Usage:  ./watermark.sh master.mp4
# Needs:  ffmpeg  (Mac: brew install ffmpeg)
# Edit the 6 handles below once. Leave a line as "" to skip that account.
set -euo pipefail

HANDLES=(
  "@GTA6VCStreamers"   # Account 1
  "@StreamersInVC"     # Account 2
  ""                   # Account 3
  ""                   # Account 4
  ""                   # Account 5
  ""                   # Account 6
)

IN="${1:?Usage: ./watermark.sh master.mp4}"
BASE="$(basename "${IN%.*}")"
BASE="${BASE%_MASTER}"
OUTDIR="$(dirname "$IN")/exports"
mkdir -p "$OUTDIR"

# Font: uses a system bold font if found, otherwise ffmpeg's default.
FONT=""
for f in "/System/Library/Fonts/Supplemental/Arial Bold.ttf" \
         "/Library/Fonts/Arial Bold.ttf" \
         "C:/Windows/Fonts/arialbd.ttf" \
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; do
  [ -f "$f" ] && FONT="fontfile='$f':" && break
done

for i in "${!HANDLES[@]}"; do
  H="${HANDLES[$i]}"
  [ -z "$H" ] && continue
  N=$((i+1))
  OUT="$OUTDIR/${BASE}_A${N}.mp4"
  # Handle sits top-left, inside TikTok/Shorts safe zone (clear of the top bar and the right-side buttons),
  # white text, 55% opacity, thin shadow so it reads on any background.
  ffmpeg -hide_banner -loglevel error -y -i "$IN" \
    -vf "drawtext=${FONT}text='${H}':fontsize=h*0.026:fontcolor=white@0.55:shadowcolor=black@0.5:shadowx=2:shadowy=2:x=w*0.06:y=h*0.13" \
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a copy -movflags +faststart "$OUT"
  echo "Account $N ($H) -> $OUT"
done
echo "Done. Upload the exports/ files to Drive: 03_Exports/<date>/Account N/"
