#!/usr/bin/env bash
# Leonida Reels | GTA 6 - assembly line, station 4.
# One clean master (vertical, trimmed, NO text) + a hooks file -> 6 account versions,
# each with its own watermark spot, zoom, start offset and hook color (matches the "Account Styles" tab).
#
# Usage:  ./make_variants.sh 1118-kaicenat-001_MASTER.mp4 1118-kaicenat-001_hooks.txt
#   hooks.txt = 6 lines, line 1 = Account 1's hook ... line 6 = Account 6's hook (copy from the Clip Bank tab).
#   Leave a line empty to skip that account. No emoji in hook text (they won't render); put emoji in the caption.
# Needs:  ffmpeg  (Mac: brew install ffmpeg)
set -euo pipefail

# ---- Account styles: edit once (keep in sync with the "Account Styles" tab) ----
HANDLE=( "@GTA6VCStreamers" "@StreamersInVC" "@HANDLE3" "@HANDLE4" "@HANDLE5" "@HANDLE6" )
ZOOM=(   1.00   1.04   1.06   1.02   1.08   1.04 )          # 1.04 = 4% zoom-in
OFFSET=( 0.0    0.3    0.6    0.2    0.5    0.4 )           # seconds trimmed from the start
WM_X=(   "w*0.06" "w*0.94-tw" "w*0.06" "w*0.06" "w*0.94-tw" "w*0.06" )
WM_Y=(   "h*0.13" "h*0.13"    "h*0.66" "h*0.13" "h*0.13"    "h*0.45" )
HOOKCOL=( "yellow" "white" "cyan" "hotpink" "lime" "orange" )
# -------------------------------------------------------------------------------

IN="${1:?Usage: ./make_variants.sh MASTER.mp4 hooks.txt}"
HOOKS="${2:?Usage: ./make_variants.sh MASTER.mp4 hooks.txt}"
BASE="$(basename "${IN%.*}")"; BASE="${BASE%_MASTER}"
OUTDIR="$(dirname "$IN")/exports_${BASE}"
mkdir -p "$OUTDIR"
mapfile -t HOOK < <(sed 's/\r$//' "$HOOKS"; echo)

FONT=""
for f in "/System/Library/Fonts/Supplemental/Arial Bold.ttf" "/Library/Fonts/Arial Bold.ttf" \
         "C:/Windows/Fonts/arialbd.ttf" "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; do
  [ -f "$f" ] && FONT="fontfile='$f':" && break
done

for i in 0 1 2 3 4 5; do
  N=$((i+1)); H="${HOOK[$i]:-}"
  [ -z "$H" ] && { echo "Account $N: no hook, skipped"; continue; }
  TXT="$OUTDIR/.hook_A$N.txt"
  # wrap the hook to lines of max 18 characters so it never runs off screen
  printf '%s' "$H" | awk '{n=split($0,w," ");l="";for(i=1;i<=n;i++){if(length(l)+length(w[i])+1>18&&l!=""){print l;l=w[i]}else{l=(l==""?w[i]:l" "w[i])}} printf "%s",l}' > "$TXT"
  Z="${ZOOM[$i]}"
  VF="scale=iw*$Z:ih*$Z,crop=1080:1920,setsar=1,"
  VF+="drawtext=${FONT}textfile='$TXT':fontsize=h*0.042:line_spacing=12:text_align=center:fontcolor=${HOOKCOL[$i]}:borderw=6:bordercolor=black:x=(w-tw)/2:y=h*0.19,"
  VF+="drawtext=${FONT}text='${HANDLE[$i]}':fontsize=h*0.026:fontcolor=white@0.55:shadowcolor=black@0.5:shadowx=2:shadowy=2:x=${WM_X[$i]}:y=${WM_Y[$i]}"
  OUT="$OUTDIR/${BASE}_A${N}.mp4"
  ffmpeg -hide_banner -loglevel error -y -ss "${OFFSET[$i]}" -i "$IN" -vf "$VF" \
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart "$OUT"
  rm -f "$TXT"
  echo "Account $N (${HANDLE[$i]}) -> $OUT"
done
echo "Done. Next: captions in CapCut with each account's preset, then music in-app at upload."
