#!/usr/bin/env node
/*
 * paperflow demo recorder.
 *
 * Drives the live UI through the storyboard beats in
 * docs/DEMO_VIDEO_HANDOVER.md and captures a browser recording as
 * .webm. All timings are chosen to match the 2:30 script; each beat
 * has room to breathe so the click-glow interactions read cleanly.
 *
 * Prerequisites (do these first, from the paperflow container host):
 *  1. docker compose up   (container reachable on http://localhost:8080)
 *  2. MI300X droplet up + SSH tunnel open (host.docker.internal:8000
 *     is reaching a live Gemma-4-31B-IT).
 *  3. curl -s http://localhost:8080/api/status | jq .local_reachable
 *     -> true (this recorder aborts if the badge is red)
 *
 * Usage:
 *   node scripts/record_demo.mjs
 *
 * Output:
 *   docs/paperflow-demo.webm   (~2:30, 1920x1080, browser recording)
 *
 * The video is captured by Playwright's browserContext.recordVideo,
 * which streams every rendered frame to disk. No macOS Screen
 * Recording, no external capture tool — the recording IS the browser.
 */

import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { mkdirSync, existsSync, renameSync, readdirSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(HERE);
const DOCS = join(REPO, 'docs');
// Direct-to-deliverable path: the recorder is now the whole video
// (Ben's call — the pitch anim from the other Claude session runs
// separately). We save the raw .webm here and then transcode to
// docs/paperflow-demo.mp4 in one step at the end of main().
const OUT_VIDEO = join(DOCS, 'paperflow-demo-live.webm');
const OUT_MP4 = join(DOCS, 'paperflow-demo.mp4');
const VIDEO_DIR = join(DOCS, '_demo_capture');
const BASE_URL = process.env.PAPERFLOW_URL || 'http://localhost:8080';

const VIEWPORT = { width: 1920, height: 1080 };

// ----- helpers -----

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function assertBadgeGreen(page) {
  // Read /api/status through the browser context so we know the JS the
  // recorder is about to observe sees the same reachability the badge
  // rendering code sees.
  const status = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/status`);
    return r.json();
  }, BASE_URL);
  console.log('  /api/status =', JSON.stringify(status));
  if (!status.local_reachable) {
    throw new Error(
      'MI300X badge is red (/api/status.local_reachable = false). ' +
      'Cannot record: hybrid asks would fall back to local artefacts ' +
      'and the trust story would look broken on video. Fix the SSH ' +
      'tunnel + Gemma container on the droplet, re-verify, and retry.'
    );
  }
  if (!status.remote_configured) {
    throw new Error(
      'FIREWORKS_API_KEY is not set in the container env. ' +
      'Hybrid asks would 500. Set it in .env and docker compose up -d.'
    );
  }
}

async function slowMove(page, x, y, steps = 12) {
  await page.mouse.move(x, y, { steps });
}

async function typeSlow(locator, text, perChar = 45) {
  await locator.click();
  await locator.pressSequentially(text, { delay: perChar });
}

async function safeClick(locator, opts = {}) {
  await locator.scrollIntoViewIfNeeded();
  await sleep(200);
  await locator.click(opts);
}

async function pause(label, ms) {
  process.stdout.write(`   … ${label} (${ms}ms)\n`);
  await sleep(ms);
}

// ----- fake cursor for headless recording -----
// Playwright headless doesn't render the OS cursor. When we need the
// viewer to see WHERE we clicked (small header toggles, token chips),
// we inject a soft glowing dot that we control from JS: fade in, slide
// to the target, pulse on click, fade out.

async function injectFakeCursor(page) {
  await page.evaluate(() => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.style.cssText = [
      'position: fixed', 'left: 0', 'top: 0',
      'width: 28px', 'height: 28px',
      'background: radial-gradient(circle at 30% 30%,'
        + ' rgba(255,255,255,0.98),'
        + ' rgba(255,255,255,0.4) 45%,'
        + ' rgba(255,255,255,0) 70%)',
      'border-radius: 50%',
      'box-shadow: 0 0 0 2px rgba(120,140,255,0.55),'
        + ' 0 0 22px 6px rgba(120,140,255,0.35)',
      'pointer-events: none',
      'z-index: 999999',
      'transform: translate(-14px, -14px)',
      'opacity: 0',
      'transition: opacity 0.35s ease,'
        + ' left 0.55s cubic-bezier(0.4, 0, 0.2, 1),'
        + ' top 0.55s cubic-bezier(0.4, 0, 0.2, 1),'
        + ' transform 0.2s ease,'
        + ' box-shadow 0.2s ease',
    ].join('; ');
    document.body.appendChild(c);
  });
}

async function fadeCursorIn(page) {
  await page.evaluate(() => {
    const c = document.getElementById('__demo_cursor');
    if (c) c.style.opacity = '1';
  });
  await sleep(400);
}

async function fadeCursorOut(page) {
  await page.evaluate(() => {
    const c = document.getElementById('__demo_cursor');
    if (c) c.style.opacity = '0';
  });
  await sleep(400);
}

async function moveCursorTo(page, x, y) {
  await page.evaluate(({x, y}) => {
    const c = document.getElementById('__demo_cursor');
    if (!c) return;
    c.style.left = x + 'px';
    c.style.top = y + 'px';
  }, {x, y});
  await sleep(650); // let the CSS transition finish
}

async function pulseCursor(page) {
  await page.evaluate(() => {
    const c = document.getElementById('__demo_cursor');
    if (!c) return;
    c.style.transform = 'translate(-14px, -14px) scale(0.7)';
    c.style.boxShadow = '0 0 0 6px rgba(120,140,255,0.5),'
                      + ' 0 0 32px 10px rgba(120,140,255,0.55)';
  });
  await sleep(180);
  await page.evaluate(() => {
    const c = document.getElementById('__demo_cursor');
    if (!c) return;
    c.style.transform = 'translate(-14px, -14px) scale(1)';
    c.style.boxShadow = '0 0 0 2px rgba(120,140,255,0.55),'
                      + ' 0 0 22px 6px rgba(120,140,255,0.35)';
  });
  await sleep(200);
}

async function cursorClick(page, locator, {fadeInFirst = true, fadeOutAfter = true} = {}) {
  // Slide the fake cursor to the element's centre, pulse it, actually
  // fire the click, then optionally fade out. Used for small controls
  // (mode toggle, header buttons) and tiny targets (token chips) where
  // headless recording would otherwise leave the viewer guessing.
  const box = await locator.boundingBox();
  if (!box) {
    await locator.click();
    return;
  }
  const cx = Math.round(box.x + box.width / 2);
  const cy = Math.round(box.y + box.height / 2);
  if (fadeInFirst) await fadeCursorIn(page);
  await moveCursorTo(page, cx, cy);
  await pulseCursor(page);
  await locator.click();
  if (fadeOutAfter) await fadeCursorOut(page);
}

// ----- storyboard beats -----

async function beatEmpty(page) {
  console.log('BEAT 1 — Empty pile → load sample (0:00-0:10)');
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    document.documentElement.style.height = '100%';
    document.body.style.height = '100%';
    document.body.style.margin = '0';
    try { window.REAL_SESSION = null; } catch (_) {}
    try { window.loadPile && window.loadPile('real'); } catch (_) {}
    window.scrollTo(0, 0);
  });
  await injectFakeCursor(page);   // headless has no OS cursor
  await pause('empty state settles + user reads the sample cards', 3200);
  await pause('boundary explanation on screen', 1200);
}

async function beatPipelineRuns(page) {
  console.log('BEAT 2 — Upload real synthetic PDFs → live MI300X extraction');
  // Ben's ask: don't skip through a cached-sample load — do a REAL
  // upload with real PDFs and wait for Gemma extraction to finish. The
  // pipeline overlay's per-file "Extracting…" pill is only honest if
  // there's actual GPU work behind it.
  const pdfDir = join(REPO, 'synthetic', 'kyc_onboarding');
  const files = [
    join(pdfDir, 'kyc_form_hassan.pdf'),
    join(pdfDir, 'nric_scan_goh.pdf'),
    join(pdfDir, 'utility_bill_hassan.pdf'),
    join(pdfDir, 'kyc_declaration_goh.txt'),
  ];
  const fileInput = page.locator('#real-file-input');
  await fileInput.waitFor({ state: 'attached', timeout: 15000 });
  await fileInput.setInputFiles(files);
  await pause('upload overlay appears — files panel + stages', 3000);

  // Real work: MI300X reads each PDF page in parallel via asyncio.gather.
  // Wall time varies with page count but 3 small PDFs land in ~15-30 s.
  // Poll every second to keep the recording lively while we wait.
  console.log('   waiting for /api/real/run to complete on the MI300X…');
  const t0 = Date.now();
  await page.waitForFunction(
    () => !document.getElementById('run-overlay')
        || document.getElementById('run-overlay').style.display === 'none',
    null, { timeout: 180000, polling: 500 }
  ).catch(() => console.log('   (overlay did not close in 180s — continuing)'));
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`   extraction wall time: ${secs}s`);
  await pause('reconciled record renders', 2500);
}

async function beatReconciledRecord(page) {
  console.log('BEAT 3 — Reconciled record → resolve + flag (0:25-0:35)');
  await page.evaluate(() => {
    const body = document.getElementById('record-body');
    if (body) body.scrollTo({ top: 0, behavior: 'smooth' });
  });
  await pause('record pane in view', 2000);

  const conflictOpt = page.locator('.field-conflict .conflict-row .opt').first();
  if (await conflictOpt.count()) {
    await safeClick(conflictOpt);
    await pause('conflict resolves', 1800);
  }

  const flagBtn = page.getByRole('button', { name: /Flag for compliance/i }).first();
  if (await flagBtn.count()) {
    await safeClick(flagBtn);
    await pause('flagged for compliance', 2400);
  }
}

async function beatMoneyShot(page) {
  console.log('BEAT 4 — Money shot: hybrid ask + click-glow (0:35-1:00)');
  const input = page.locator('#chat-input');
  await input.scrollIntoViewIfNeeded();
  await typeSlow(input, 'summarise this pile');
  await pause('question typed', 600);
  await input.press('Enter');
  await pause('pending pill counts up', 3500);
  await page.waitForSelector('.bubble.ai:not(.pending-ai)', { timeout: 25000 })
    .catch(() => console.log('   (AI bubble did not land in 25s — recording continues)'));
  await pause('reader sees formatted paragraphs', 3500);

  // Click a receipt token chip → sidebar + record scroll, everything
  // glows. Receipt tokens use .token (not .chip); tagTokensForLinking
  // stamps data-token on them after render.
  let tokenChip = page.locator('.receipt .token[data-token^="[PERSON_"], .receipt .token[data-token^="[ADDR_"], .receipt .token[data-token^="[ID_"]').first();
  if (!(await tokenChip.count())) {
    tokenChip = page.locator('.receipt .token[data-token], .receipt [data-token]').first();
  }
  if (await tokenChip.count()) {
    await safeClick(tokenChip);
    await pause('cross-panel glow', 3800);
  } else {
    console.log('   (no receipt token chip found — skipping click-glow beat)');
  }

  // Hover a rehydrated entity chip in the reply → tooltip shows [PERSON_1].
  const replyChip = page.locator('.bubble.ai .hl[data-token]').first();
  if (await replyChip.count()) {
    await replyChip.hover();
    await pause('token tooltip visible', 2800);
  }
}

async function beatAirGapped(page) {
  console.log('BEAT 5 — Air-gapped mode → 0 cloud calls (1:00-1:15)');
  // The mode toggle is a small chip in the header. Without a visible
  // cursor the viewer sees the sysnote appear from nowhere. Slide the
  // fake cursor over, pulse it on click, then fade out so the sysnote
  // reads as a consequence of the press.
  const toggle = page.locator('#mode-toggle');
  await toggle.scrollIntoViewIfNeeded();
  await cursorClick(page, toggle);
  await pause('sysnote + pipeline strip flips', 2500);

  const input = page.locator('#chat-input');
  await typeSlow(input, 'summarise this pile');
  await input.press('Enter');
  await pause('local routing + 0 cloud calls receipt', 4500);
  await page.waitForSelector('.bubble.ai:not(.pending-ai)', { timeout: 20000 })
    .catch(() => {});
  await pause('reader sees local-only receipt', 3200);
}

async function beatClose(page) {
  console.log('BEAT 6 — Close (1:15-1:20)');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await pause('final frame with badge', 4000);
}

// ----- driver -----

async function main() {
  console.log('paperflow demo recorder');
  console.log('  BASE_URL:', BASE_URL);
  console.log('  OUT_VIDEO:', OUT_VIDEO);

  if (!existsSync(DOCS)) mkdirSync(DOCS, { recursive: true });
  if (!existsSync(VIDEO_DIR)) mkdirSync(VIDEO_DIR, { recursive: true });

  // Headless mode: cleaner 1920x1080 viewport with no browser chrome
  // bleed. Chromium new-headless renders animations + WebGL as well
  // as headed does, and gets us a pixel-exact viewport recording.
  const browser = await chromium.launch({
    headless: true,
    args: ['--force-device-scale-factor=1',
           '--disable-blink-features=AutomationControlled'],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    recordVideo: { dir: VIDEO_DIR, size: VIEWPORT },
    reducedMotion: 'no-preference',
  });
  const page = await context.newPage();

  try {
    console.log('\nPre-flight: verifying MI300X badge + Fireworks…');
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await assertBadgeGreen(page);
    console.log('  ✓ pre-flight OK\n');

    await beatEmpty(page);
    await beatPipelineRuns(page);
    await beatReconciledRecord(page);
    await beatMoneyShot(page);
    await beatAirGapped(page);
    await beatClose(page);
  } finally {
    await page.close();
    await context.close();
    await browser.close();
  }

  // Playwright writes the video with a randomised name into VIDEO_DIR
  // after the context closes. Rename the newest .webm to the final
  // deliverable path so the README link is stable.
  const videos = readdirSync(VIDEO_DIR)
    .filter((f) => f.endsWith('.webm'))
    .map((f) => ({ f, mtime: statSync(join(VIDEO_DIR, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  if (!videos.length) {
    throw new Error(`No .webm produced in ${VIDEO_DIR}`);
  }
  renameSync(join(VIDEO_DIR, videos[0].f), OUT_VIDEO);
  console.log(`\n✓ demo recorded (.webm): ${OUT_VIDEO}`);

  // Transcode .webm -> .mp4 in one step so the shipped deliverable is
  // a broadly playable file. lavfi silent audio keeps the stream
  // layout consistent with anything a compositor might chain later.
  console.log('  transcoding to h264/aac mp4…');
  const ff = spawnSync('ffmpeg', [
    '-y', '-i', OUT_VIDEO,
    '-f', 'lavfi', '-t', '999', '-i',
    'anullsrc=channel_layout=stereo:sample_rate=48000',
    '-map', '0:v', '-map', '1:a', '-shortest',
    '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,'
         + 'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,'
         + 'setsar=1,fps=25',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k',
    OUT_MP4,
  ], { stdio: ['ignore', 'inherit', 'inherit'] });
  if (ff.status !== 0) {
    throw new Error(`ffmpeg transcode exited with status ${ff.status}`);
  }
  console.log(`✓ deliverable: ${OUT_MP4}`);
}

main().catch((err) => {
  console.error('\n✗ demo recording failed:', err.message);
  process.exit(1);
});
