# paperflow demo · voice-over script

Seven short lines matched to `docs/paperflow-demo.mp4`. Each line is
its own ElevenLabs generation so ffmpeg can drop it at the exact
video timestamp without drift.

**Voice suggestion.** Reuse the Clarice voice from the pitch anim
(`ElevenLabs_2026-07-09T04_27_35_Clarice…`) — calm, human, unrushed.
No SSML breaks needed inside a single line; the breaks live between
files.

**Delivery notes.**
- Keep pace measured. Judges are reading the on-screen chips and
  glows at the same time as listening.
- Read the punctuation. Commas = quarter beats. Full stops = full
  beats.
- No emphasis on "extraction", "MI300X" or "Fireworks" — those are
  proper nouns, let them ride the sentence.
- Emphasis on **verbs**: "drop", "runs", "reach", "click", "flip".

**Total spoken time:** ~38 seconds spread across 81 seconds of
video. The gaps let interactions land and breathe.

## The seven lines

Copy each line into ElevenLabs, generate at your usual quality
setting, and save as the filename shown. Put the output in
`docs/_vo/`.

### `vo_01_premise.mp3` — 0:00-0:07

> You have a stack of confidential documents. You need cross-document
> reasoning. Legal won't let them leave the building.

### `vo_02_upload.mp3` — 0:07-0:14

> Drop them in. Extraction runs on the AMD MI300X in your own
> container. Nothing crosses the network.

### `vo_03_record.mp3` — 0:26-0:33

> Every field lands with its source. Cross-document conflicts are
> flagged automatically.

### `vo_04_ask.mp3` — 0:35-0:44

> Ask a question, and only redacted tokens reach Fireworks. Real
> identities never do.

### `vo_05_glow.mp3` — 0:47-0:56

> Click a token. Follow the entity across every pane. The trust story
> is something you can see, not documentation you have to trust.

### `vo_06_airgapped.mp3` — 0:58-1:07

> Flip air-gapped mode. Same question. Zero cloud calls. True by
> construction, not by convention.

### `vo_07_close.mp3` — 1:12-1:19

> Extraction on the AMD MI300X. Reasoning on redacted tokens.
> Zero-egress mode when you need it.

## After you generate the seven files

Put them in `docs/_vo/` (that dir is gitignored via the
`docs/_demo_capture/` pattern — actually let me add it explicitly).

Then run:

```
bash scripts/apply_voiceover.sh
```

That script overlays each mp3 at its start timestamp onto
`docs/paperflow-demo.mp4` and writes `docs/paperflow-demo-vo.mp4`.
When you're happy with the take, rename to `paperflow-demo.mp4`.

## If ElevenLabs balks at a line

Common fixes without asking me:
- Break long sentences at the comma; ElevenLabs sometimes over-
  emphasises the first clause of a compound sentence.
- If a line rushes, add a period-plus-space where you want a breath:
  `You need cross-document reasoning.` -> `You need cross-document
  reasoning. `. Trailing whitespace becomes a beat.
- If a name reads oddly ("MI three hundred X" instead of
  "MI three hundred X"), spell it as `M I three hundred X` in the
  input.
