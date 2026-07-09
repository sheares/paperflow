#!/usr/bin/env bash
# Overlay ElevenLabs voice-over files onto docs/paperflow-demo.mp4.
#
# Input:
#   docs/_vo/vo_01_premise.mp3   at  0.0s
#   docs/_vo/vo_02_upload.mp3    at  7.0s
#   docs/_vo/vo_03_record.mp3    at 26.0s
#   docs/_vo/vo_04_ask.mp3       at 35.0s
#   docs/_vo/vo_05_glow.mp3      at 47.0s
#   docs/_vo/vo_06_airgapped.mp3 at 58.0s
#   docs/_vo/vo_07_close.mp3     at 72.0s
#
# Output:
#   docs/paperflow-demo-vo.mp4
#
# Approach:
#   ffmpeg loads the video's silent audio track + each voice-over
#   file with an `adelay` filter that shifts the mp3 to its target
#   start. amix combines them all into one track. Video is copied
#   through without re-encoding.
#
# If a file is missing, the script skips it with a warning rather than
# aborting — useful if you want to iterate one line at a time before
# generating the whole set.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS="$REPO_ROOT/docs"
VO_DIR="$DOCS/_vo"
IN_MP4="$DOCS/paperflow-demo.mp4"
OUT_MP4="$DOCS/paperflow-demo-vo.mp4"

if [ ! -f "$IN_MP4" ]; then
  echo "Missing input video: $IN_MP4" >&2
  exit 1
fi
if [ ! -d "$VO_DIR" ]; then
  echo "Missing voice-over directory: $VO_DIR" >&2
  echo "See docs/DEMO_VOICEOVER.md for the script + workflow." >&2
  exit 1
fi

# name -> start-time-in-ms
declare -a LINES=(
  "vo_01_premise.mp3:0"
  "vo_02_upload.mp3:7000"
  "vo_03_record.mp3:26000"
  "vo_04_ask.mp3:35000"
  "vo_05_glow.mp3:47000"
  "vo_06_airgapped.mp3:58000"
  "vo_07_close.mp3:72000"
)

INPUTS=(-i "$IN_MP4")
FILTER=""
MIX_INPUTS="[0:a]"
IDX=1
COUNT=0

for entry in "${LINES[@]}"; do
  file="${entry%%:*}"
  delay_ms="${entry##*:}"
  path="$VO_DIR/$file"
  if [ ! -f "$path" ]; then
    echo "  skip (missing): $file"
    continue
  fi
  INPUTS+=(-i "$path")
  # Delay each channel; adelay expects one value per channel or a
  # single value that applies to all. Stereo VO stays stereo.
  FILTER+="[$IDX:a]adelay=${delay_ms}|${delay_ms}[vo${IDX}];"
  MIX_INPUTS+="[vo${IDX}]"
  IDX=$((IDX + 1))
  COUNT=$((COUNT + 1))
done

if [ "$COUNT" -eq 0 ]; then
  echo "No voice-over files found in $VO_DIR. Nothing to apply." >&2
  exit 1
fi

FILTER+="${MIX_INPUTS}amix=inputs=$((COUNT + 1)):dropout_transition=0:normalize=0[aout]"

echo "Applying $COUNT voice-over lines to $IN_MP4…"
ffmpeg -y "${INPUTS[@]}" \
  -filter_complex "$FILTER" \
  -map 0:v -map "[aout]" \
  -c:v copy \
  -c:a aac -b:a 192k \
  -shortest \
  "$OUT_MP4" 2>&1 | tail -6

echo ""
echo "✓ Voice-over applied: $OUT_MP4"
echo "  Review it; when you're happy, rename to paperflow-demo.mp4 (or"
echo "  keep both around so you can revert)."
ffprobe -v error -show_entries format=duration,bit_rate:stream=codec_name -of default=noprint_wrappers=1 "$OUT_MP4"
