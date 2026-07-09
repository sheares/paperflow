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
PADDED_MP4="$DOCS/_padded.mp4"
PAD_END_S=7

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
# Offsets re-anchored from actual visual beat starts, verified frame-
# by-frame against the last take:
#   - Beat 3 (record) doesn't render until overlay dismisses at ~43s
#   - Beat 4 (ask) — user types + Enter around 49-52s
#   - Beat 5 (glow) — click fires around 58s; VO starts a beat earlier
#   - Beat 6 (air-gapped) — flip at ~65s; VO starts at 66s so it
#     doesn't clash with the tail of vo_05
#   - Beat 7 (close) — air-gapped reply visible from ~74s onward
declare -a LINES=(
  "vo_01_premise.mp3:0"           #  0.0-7.1  empty-pile boundary
  "vo_02_upload_new.mp3:8000"     #  8.0-...  upload overlay + file rows
  "vo_02b_redact.mp3:22000"       # 22.0-...  Presidio entity map
  "vo_02c_reconcile.mp3:31000"    # 31.0-...  cloud reasons on tokens
  "vo_03_record.mp3:43000"        # 43.0-48.5 record just rendered
  "vo_04_ask.mp3:49000"           # 49.0-54.9 question typed + sent
  "vo_05_glow.mp3:56000"          # 56.0-65.1 click-glow money shot
  "vo_06_airgapped.mp3:66000"     # 66.0-74.0 air-gapped mode flip
  "vo_07_close_new.mp3:74500"     # 74.5-...  close over the local reply
)

# Extend the video by PAD_END_S seconds of frozen last frame so the
# closing VO line has room to finish. tpad replicates the final
# rendered frame; no re-encode noise. The padded intermediate is
# then the input to the audio-mix step below.
echo "Padding tail of $IN_MP4 by ${PAD_END_S}s of frozen final frame..."
ffmpeg -y -i "$IN_MP4" \
  -vf "tpad=stop_mode=clone:stop_duration=${PAD_END_S}" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -an \
  "$PADDED_MP4" 2>&1 | tail -4

INPUTS=(-i "$PADDED_MP4")
FILTER=""
# Padded video has no audio track (-an during pad step). Mix the
# delayed VO channels together as the sole audio; no silent base
# needed. IDX starts at 1 because [0] is the video.
MIX_INPUTS=""
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

FILTER+="${MIX_INPUTS}amix=inputs=${COUNT}:dropout_transition=0:normalize=0:duration=longest[aout]"

echo "Applying $COUNT voice-over lines to ${IN_MP4}..."
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
