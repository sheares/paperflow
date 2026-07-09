#!/usr/bin/env bash
# Stitch the demo video: intro anim + live UI capture + outro title.
#
# Inputs (all expected to exist):
#   docs/paperflow-demo-live.webm  — Playwright recording of the UI
#   ../AMD Hackathon 2026/paperflow-final.mp4  — the pitch anim + audio
#   ../AMD Hackathon 2026/chime out.mp3        — transition chime
#
# Output:
#   docs/paperflow-demo.mp4  — the final deliverable
#
# Approach:
#   1. Transcode the .webm capture to a matching 1920x1080 h264/aac mp4
#      (silent audio track so the concat has a consistent stream layout).
#   2. Render a 5-second outro title card as an mp4.
#   3. Use ffmpeg concat filter to stitch anim → capture → outro with
#      no re-encode of the anim's audio track beyond the join.
#
# Run from repo root:
#   bash scripts/stitch_demo.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCS="$REPO_ROOT/docs"
HACK="$REPO_ROOT/../AMD Hackathon 2026"

LIVE_WEBM="$DOCS/paperflow-demo-live.webm"
INTRO_MP4="$HACK/paperflow-final.mp4"
OUTRO_MP4="$DOCS/_outro.mp4"
LIVE_MP4="$DOCS/_live.mp4"
FINAL_MP4="$DOCS/paperflow-demo.mp4"
LIST_TXT="$DOCS/_concat.txt"

if [ ! -f "$LIVE_WEBM" ]; then
  echo "Missing live capture: $LIVE_WEBM" >&2
  echo "Run: node scripts/record_demo.mjs" >&2
  exit 1
fi
if [ ! -f "$INTRO_MP4" ]; then
  echo "Missing intro: $INTRO_MP4" >&2
  exit 1
fi

echo "1/3  Transcoding live capture .webm -> .mp4 (1920x1080, h264/aac)…"
# Silent audio track so it concatenates cleanly with the intro (which
# already has an audio stream).
ffmpeg -y -i "$LIVE_WEBM" \
  -f lavfi -t 999 -i anullsrc=channel_layout=stereo:sample_rate=48000 \
  -map 0:v -map 1:a -shortest \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,\
pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,\
setsar=1,fps=25" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  "$LIVE_MP4" 2>&1 | tail -8

echo "2/3  Rendering 5s outro from paperflow-cover_V10.png…"
# Homebrew ffmpeg on this system doesn't include libfreetype, so
# drawtext is unavailable. Loop the branded cover PNG (from the pitch
# assets) as a 5s title card instead — better on-brand anyway.
COVER_PNG="$HACK/paperflow-cover_V10.png"
if [ ! -f "$COVER_PNG" ]; then
  echo "Missing cover image: $COVER_PNG" >&2
  exit 1
fi
ffmpeg -y -loop 1 -t 5 -i "$COVER_PNG" \
  -f lavfi -t 5 -i anullsrc=channel_layout=stereo:sample_rate=48000 \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,\
pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,\
setsar=1,fps=25" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  "$OUTRO_MP4" 2>&1 | tail -8

echo "3/3  Concatenating intro → live → outro…"
# Use the concat DEMUXER (safe when streams already share codec params).
# All three files are h264 + aac at 1920x1080/25fps after the transcode
# steps above.
cat > "$LIST_TXT" <<EOF
file '$INTRO_MP4'
file '$LIVE_MP4'
file '$OUTRO_MP4'
EOF

ffmpeg -y -f concat -safe 0 -i "$LIST_TXT" \
  -c copy \
  "$FINAL_MP4" 2>&1 | tail -6 || {
    echo "Concat -c copy failed (codec params likely differ). Re-encoding…"
    ffmpeg -y -f concat -safe 0 -i "$LIST_TXT" \
      -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
      -c:a aac -b:a 128k \
      "$FINAL_MP4" 2>&1 | tail -6
  }

echo ""
echo "✓ Final: $FINAL_MP4"
ffprobe -v error -show_entries format=duration,bit_rate:stream=codec_name,width,height -of default=noprint_wrappers=1 "$FINAL_MP4"
