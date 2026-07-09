# paperflow demo video · handover to recording session

This document briefs a fresh Claude Code session on how to record the
demo video for paperflow's AMD Developer Hackathon ACT II submission.
It is self-contained: you (the recording session) don't need any
context from prior conversations to execute it.

## Deliverable

A 2:30 screen-capture demo video that shows a judge exactly what
they'd see on a fresh clone. Save to
`/Users/benjaminxue/Documents/Claude OS Folder/paperflow-hackathon/docs/paperflow-demo.mp4`.
Target 1920 × 1080 minimum, 60 fps preferred.

If you can add captions (no voice-over needed unless Ben requests it),
use the narration lines below as burnt-in subtitles or an SRT file at
`docs/paperflow-demo.srt`.

## Pre-flight (do this first; do NOT skip)

The demo uses a live MI300X for PDF extraction and a live Fireworks
call for cross-doc reasoning. Both need to be up before you start
recording.

### 1. MI300X (Gemma-4-31B-IT via vLLM on the AMD Developer Cloud droplet)

**Handled by the other Claude Code session (paperflow-hackathon
project session), not you.** Before you start recording, ask Ben to
confirm the droplet is up + tunnel is open. Then verify from the
Mac:

```
curl -s http://localhost:8080/api/status | python3 -m json.tool
```

You want to see:

```
"local_reachable": true,
"local_model": "google/gemma-4-31b-it",
```

If it says `false`, stop and ping the other session. Do NOT try to
fix the droplet yourself — that session is the source of truth for
the MI300X lifecycle.

### 2. Fireworks

`.env` already has `FIREWORKS_API_KEY` set and `FIREWORKS_MODEL=minimax`
in `docker-compose.yml`. Should just work. Verify:

```
curl -s http://localhost:8080/api/status | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('remote_configured'), d.get('remote_model_label'))"
```

Expect: `True Minimax M3`.

### 3. Container

```
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep paperflow
```

Expect `paperflow-hackathon-paperflow-1` with `Up`. If it's down:

```
cd "/Users/benjaminxue/Documents/Claude OS Folder/paperflow-hackathon" && docker compose up -d
```

### 4. Browser state

Open Chrome (recommended for screen capture consistency) at
`http://localhost:8080`. Hard-refresh (`Cmd+Shift+R`). You want the
**empty pile pane** as the starting frame — the "Load a sample" cards
+ drop zone. If a previous session left a pile loaded, click the
paperflow logo / refresh + confirm the empty state renders.

Recommended browser zoom: `100%`. Recommended window size:
`1920 × 1080`. Turn off any extension toolbars that add visual
noise (DevTools, ad blocker overlays, etc.).

### 5. Recording tool

macOS Screen Recording (Cmd+Shift+5) at 60 fps if possible. Or
QuickTime → File → New Screen Recording. Record just the browser
window (not the whole screen).

## The script

Each beat below is `[timing] narration line — screen action`. Aim
for the timing as a rough guide; ±3s per beat is fine as long as the
total lands under 2:35.

---

### Beat 1 — the premise (0:00–0:15)

> "You have a stack of confidential documents. You need cross-doc
> reasoning. Legal won't let them leave the building."

**Screen:** Cold open on the empty pile pane. Show the three sample
cards ("KYC onboarding", "Patient intake", "Partner collation") and
the drop zone. Slow cursor drift toward the KYC card.

---

### Beat 2 — the pipeline runs (0:15–0:50)

> "Extraction on the AMD MI300X. Redaction on the same server. Only
> redacted tokens ever leave the building."

**Screen action:**

1. Click "Load KYC onboarding sample".
2. The run overlay appears with:
   - Title: "Loading KYC sample"
   - Files panel: rows for each sample PDF with the `PDF` type chip,
     initial status "Queued"
   - Pipeline stages: Upload → Extract (vision, concurrent) →
     Redact → Reconcile → Emit
3. Watch the file rows transition: **Queued → Uploading →
   Extracting… (purple) → ✓ Extracted (green)**. Stages advance
   in real time.
4. Pause 1s on the trust-boundary line at the bottom: "redaction
   runs on this paperflow server, not on the LLM side. Only redacted
   tokens — never raw names, IDs, addresses or phones — reach
   Minimax M3."

---

### Beat 3 — the reconciled record (0:50–1:20)

> "Two entities. Six fields each. Two conflicts flagged. Every value
> traces to a source document."

**Screen action:**

1. Overlay closes; the reconciled record pane populates on the left.
2. Scroll slowly through the record to show:
   - Client cards with state pills ("✓ Reconciled" or "⚠ 1 conflict")
   - A conflict row showing two `.opt` options with source doc
     citations
3. Click one of the conflict options to resolve it. The state pill
   should update live to reflect the resolution.
4. On another conflict row, click **"Flag for compliance"**. The
   button turns to "⚑ flagged", the note updates to "⚑ Flagged for
   compliance review".
5. Click **Export JSON**. A file downloads. Open it (or preview in
   Finder) to show the `compliance_review.escalations[]` block with
   the flagged field + client + timestamp.

---

### Beat 4 — the money shot: tokenisation you can *see* (1:20–1:55)

> "This is where the trust story stops being documentation and starts
> being something you can follow with your finger."

**Screen action:**

1. In the chat input at the bottom-right, type:
   `summarise this pile`
2. Hit Enter. The pending state appears — a shimmering pill labelled
   "Minimax M3 is reasoning over the redacted tokens…" with a live
   elapsed-time chip counting up.
3. When the reply lands (~2 s), it renders as multiple paragraphs
   with **bolded verdicts** and `code`-styled field names.
4. **The signature interaction:** click the `[PERSON_1]` chip in the
   privacy receipt above the reply. Watch:
   - Sidebar entity list scrolls smoothly to the matching entity
   - Record pane scrolls to the matching field
   - Every occurrence of that token — including the rehydrated
     "Yvonne Goh" chips inside the reply text — pulses a purple glow
     twice
5. Hover a "Yvonne Goh" chip in the reply text. The tooltip shows
   `[PERSON_1]`. Narrate:

   > "This is what Fireworks actually saw."

6. Click a different family (e.g. `[ADDR_5]`) to show the glow
   colour swap to orange, and the scroll retarget to the address
   field.

**This beat is the whole video's payoff. Give it room. Don't rush
the click-glow interactions.**

---

### Beat 5 — air-gapped mode (1:55–2:20)

> "The zero-egress switch. Nothing crosses. True by construction."

**Screen action:**

1. Click the mode toggle at the top-right of the chat pane to flip
   into **Air-gapped mode**.
2. A system note appears in the chat: "Air-gapped mode on · Fireworks
   disabled · reconciliation runs entirely on the MI300X + paperflow
   container".
3. Ask the same question again: `summarise this pile`.
4. The reply comes back with:
   - Receipt says `Local only · 0 cloud calls` (green chip)
   - Routing chip: `Routed local`
   - Reason: "answering from stored artefacts on the MI300X"
5. Slow pan to the "Honest limits" line if it's on screen, or the
   receipt's "0 detected identifiers among them" text.

---

### Beat 6 — close (2:20–2:30)

Static frame or title card with three lines:

- Extraction on the AMD MI300X.
- Reasoning on redacted tokens.
- Zero-egress mode by construction.

Fade out.

## Common pitfalls / what to redo

- **Badge red during recording:** stop, fix MI300X reachability, re-
  record. Don't ship a demo where the header badge says "MI300X
  offline". It undercuts the pipeline story.
- **Pending pill counter reads 30+ seconds:** Fireworks response is
  laggy; re-record. Under 10 s reads well.
- **Reply comes back as a wall of text:** something regressed on the
  formatting prompt. Check `paperflow/router.py:CHAT_PROMPT` still
  has the paragraph/bullet rules. Re-run.
- **Click-glow doesn't reach the record:** check that
  `tagRecordChipsForLinking` ran (should happen automatically on
  every record render). If not, hard-refresh and try again.
- **Long PDF filenames overflow the file panel:** they shouldn't —
  the panel truncates with ellipsis. If they do, screenshot and file
  it as a bug, don't work around it.

## Key files (for reference, no edits needed)

- UI: `ui/index.html` — one-file HTML/JS/CSS app
- Router: `paperflow/router.py` — `_answer_remote`, `_answer_local`,
  the `CHAT_PROMPT`
- API: `paperflow/api.py` — `/api/ask`, `/api/status`, `/api/real/*`
- Docker compose: `docker-compose.yml` — `FIREWORKS_MODEL=minimax`
- Env template: `.env.example`
- Droplet lifecycle helper: `scripts/droplet.sh`
- Pitch deck source: `docs/paperflow-pitch.html` (already exported to
  `docs/paperflow-pitch.pdf`)

## After recording

1. Save the video to `docs/paperflow-demo.mp4`.
2. Commit + push:

   ```
   cd "/Users/benjaminxue/Documents/Claude OS Folder/paperflow-hackathon"
   git add docs/paperflow-demo.mp4 docs/paperflow-demo.srt  # if SRT exists
   git commit -m "Add demo video"
   git push
   ```

3. Update `README.md` line 13 to swap the placeholder:

   ```
   📽️ **Demo video**: [link pending Thursday recording]
   ```

   to a link to the file (relative path
   `[docs/paperflow-demo.mp4](docs/paperflow-demo.mp4)`) or a
   YouTube unlisted URL if the file is too big for the repo.

4. Once shipped, tell Ben the video is ready for review before the
   Saturday submission window.

## Sanity check before you start recording

- [ ] MI300X badge shows green in the header
- [ ] Fireworks configured (Minimax M3 label in the header)
- [ ] Empty pile pane visible (sample cards + drop zone)
- [ ] Chrome window at 1920×1080, zoom 100%
- [ ] Screen recorder set to 60 fps, browser-window-only capture
- [ ] Microphone muted (this is a silent capture)
- [ ] Do Not Disturb on (no notifications during recording)
