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

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(HERE);
const DOCS = join(REPO, 'docs');
// This is the RAW live-UI capture. scripts/stitch_demo.sh takes it,
// prepends the pitch anim and appends a title outro, and writes the
// final deliverable to docs/paperflow-demo.mp4.
const OUT_VIDEO = join(DOCS, 'paperflow-demo-live.webm');
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

// ----- storyboard beats -----

async function beatEmpty(page) {
  console.log('BEAT 1 — Empty pile → load sample (0:00-0:10)');
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    try { window.REAL_SESSION = null; } catch (_) {}
    try { window.loadPile && window.loadPile('real'); } catch (_) {}
  });
  await pause('empty state settles + user reads the sample cards', 3200);
  // Slow drift to the KYC sample card so the recording has motion.
  await slowMove(page, 500, 620, 24);
  await pause('cursor lands over KYC card', 1200);
}

async function beatPipelineRuns(page) {
  console.log('BEAT 2 — Pipeline runs on the sample (0:10-0:25)');
  // The sample buttons render inside the empty-state HTML; target by text.
  const kyc = page.getByText(/Load .*KYC|KYC onboarding sample|Load KYC/i).first();
  await safeClick(kyc);
  await pause('run overlay appears — files panel + stages', 3000);
  await pause('Extract / Redact stages advance', 5000);
  await pause('Reconcile + Emit + overlay dismisses', 5000);
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

  // Click a receipt token chip → sidebar + record scroll, everything glows.
  const tokenChip = page.locator('.receipt .chip[data-token]').first();
  if (await tokenChip.count()) {
    await safeClick(tokenChip);
    await pause('cross-panel glow', 3800);
  } else {
    const anyTok = page.locator('[data-token]').first();
    if (await anyTok.count()) {
      await safeClick(anyTok);
      await pause('cross-panel glow (fallback)', 3800);
    }
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
  const toggle = page.locator('#mode-toggle');
  await safeClick(toggle);
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

  const browser = await chromium.launch({
    headless: false,   // headed so Chrome renders animations correctly
    args: [`--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
           '--force-device-scale-factor=1'],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    recordVideo: { dir: VIDEO_DIR, size: VIEWPORT },
    // Small extra CSS to make the recording feel a touch smoother
    // (disable text-caret blink, kill hover delays).
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
  console.log(`\n✓ demo recorded: ${OUT_VIDEO}`);
}

main().catch((err) => {
  console.error('\n✗ demo recording failed:', err.message);
  process.exit(1);
});
