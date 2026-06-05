/* Capture a series of demo screenshots of the BlackBar app.
 *
 * Designed to run inside the official Playwright Docker image, joined to the
 * app's docker network so it can reach the frontend by service name:
 *
 *   docker run --rm --network blackbar_blackbar-network \
 *     -v "$PWD/scripts:/scripts" -v "$PWD/deploy/demo/screenshots:/out" \
 *     -e BASE_URL=http://frontend:3000 -e CASE_ID=... -e DOC_ID=... \
 *     -e ADMIN_EMAIL=... -e ADMIN_PASSWORD=... -e NODE_PATH=/usr/lib/node_modules \
 *     mcr.microsoft.com/playwright:v1.49.0-jammy node /scripts/demo_screenshots.cjs
 *
 * Each shot is best-effort: a failure is logged and the run continues.
 */
let chromium;
for (const m of ['playwright', 'playwright-core']) {
  try { ({ chromium } = require(m)); break; } catch {}
}
if (!chromium) { console.error('playwright/playwright-core not resolvable'); process.exit(1); }

const BASE = process.env.BASE_URL || 'http://frontend:3000';
const CASE_ID = process.env.CASE_ID;
const DOC_ID = process.env.DOC_ID;
const EMAIL = process.env.ADMIN_EMAIL;
const PASSWORD = process.env.ADMIN_PASSWORD;
const OUT = '/out';

const VIEWPORT = { width: 1440, height: 900 };
// Optional: ONLY=11,12 captures just those shots (login always runs so the
// authenticated ones work). Empty = capture everything.
const ONLY = (process.env.ONLY || '').split(',').map((s) => s.trim()).filter(Boolean);
const wanted = (name) => ONLY.length === 0 || name === 'login' || ONLY.some((o) => name.startsWith(o));
const results = [];

async function shot(page, name, label) {
  const file = `${OUT}/${name}.png`;
  await page.screenshot({ path: file });
  console.log(`  ✓ ${name}  (${label})`);
  results.push({ name, ok: true });
}

async function settle(page, ms = 1200) {
  try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
  await page.waitForTimeout(ms);
}

async function step(name, label, fn) {
  if (!wanted(name)) return;
  try { await fn(); }
  catch (e) {
    console.log(`  ✗ ${name}  (${label}) — ${e.message.split('\n')[0]}`);
    results.push({ name, ok: false, err: e.message.split('\n')[0] });
  }
}

(async () => {
  const browser = await chromium.launch();

  // ---- Public / requester context (unauthenticated) --------------------
  const pub = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });
  const pp = await pub.newPage();

  await step('01-public-login', 'public login page', async () => {
    await pp.goto(`${BASE}/public/login`, { waitUntil: 'domcontentloaded' });
    await settle(pp);
    await shot(pp, '01-public-login', 'public login page');
  });

  await step('02-requester-portal', 'requester dashboard via demo login', async () => {
    const demo = pp.locator('button', { hasText: /demo/i }).first();
    await demo.click({ timeout: 8000 });
    await pp.waitForURL(/\/public\/dashboard/, { timeout: 12000 });
    await settle(pp);
    await shot(pp, '02-requester-portal', 'requester dashboard');
  });
  await pub.close();

  // ---- Staff context (authenticated) -----------------------------------
  const staff = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });
  const p = await staff.newPage();

  await step('03-staff-login', 'staff login form', async () => {
    await p.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
    await settle(p);
    await shot(p, '03-staff-login', 'staff login form');
  });

  // Authenticate (used by all later shots).
  await step('login', 'authenticate as admin', async () => {
    if (!/\/login/.test(p.url())) {
      await p.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
      await settle(p, 800);
    }
    const email = p.locator('input[type="email"], input[name="email"], input[placeholder*="mail" i]').first();
    const pass = p.locator('input[type="password"]').first();
    await email.fill(EMAIL);
    await pass.fill(PASSWORD);
    await p.locator('button[type="submit"], button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Login")').first().click();
    await p.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 15000 });
    await settle(p);
  });

  await step('04-case-queue', 'case queue', async () => {
    await p.goto(`${BASE}/cases`, { waitUntil: 'domcontentloaded' });
    await settle(p, 1200);
    // Show the full queue, not just "My Cases".
    try { await p.locator('button:has-text("All Cases")').first().click({ timeout: 4000 }); } catch {}
    await settle(p, 1200);
    await shot(p, '04-case-queue', 'case queue');
  });

  await step('05-case-detail', 'case detail', async () => {
    await p.goto(`${BASE}/cases/${CASE_ID}`, { waitUntil: 'domcontentloaded' });
    await settle(p, 1600);
    await shot(p, '05-case-detail', 'case detail');
  });

  await step('10-release-package', 'release package', async () => {
    // On the case detail page; open the Generate Release Package dialog
    // (enabled now that documents are approved).
    const gen = p.locator('button:has-text("Generate Package")').first();
    await gen.scrollIntoViewIfNeeded({ timeout: 5000 });
    await p.waitForTimeout(400);
    await gen.click({ timeout: 5000 });
    // Wait for the generate dialog (document selection) to appear.
    try { await p.getByRole('dialog').waitFor({ timeout: 6000 }); } catch {}
    await p.waitForTimeout(800);
    await shot(p, '10-release-package', 'release package');
  });

  await step('06-document-viewer', 'document viewer', async () => {
    await p.goto(`${BASE}/documents/${DOC_ID}`, { waitUntil: 'domcontentloaded' });
    try { await p.locator('canvas').first().waitFor({ timeout: 15000 }); } catch {}
    await settle(p, 2500);
    await shot(p, '06-document-viewer', 'document viewer (rendered PDF + redaction)');
  });

  await step('08-ai-suggestions', 'AI suggestions drawer', async () => {
    // The onClick lives on the IconButton (AutoAwesome icon), not the label.
    await p.locator('button:has(svg[data-testid="AutoAwesomeIcon"])').first().click({ timeout: 8000 });
    await p.locator('text=Auto Suggestions').first().waitFor({ timeout: 8000 });
    // Switch to the AI tab (rich seeded suggestions live there).
    try { await p.getByRole('tab', { name: /AI Recommended/i }).click({ timeout: 5000 }); } catch {}
    try { await p.locator('text=/Personal email address|Matt Crossley/').first().waitFor({ timeout: 8000 }); } catch {}
    await p.waitForTimeout(1000);
    await shot(p, '08-ai-suggestions', 'AI suggestions drawer');
  });

  await step('09-review-reasoning', 'suggestion reasoning expanded', async () => {
    await p.locator('button:has-text("Why")').first().click({ timeout: 6000 });
    await p.waitForTimeout(800);
    await shot(p, '09-review-reasoning', 'suggestion reasoning expanded');
  });

  await step('07-manual-redaction', 'manual redaction tooling', async () => {
    // Close the suggestions drawer (its Cancel button), then activate the
    // draw/redaction tool in the left rail.
    try { await p.locator('button:has-text("Cancel")').first().click({ timeout: 4000 }); } catch {}
    await p.waitForTimeout(600);
    const tool = p.locator('button:has-text("Redact"), [aria-label*="redact" i], button:has-text("Draw"), [title*="redact" i]').first();
    try { await tool.click({ timeout: 4000 }); } catch {}
    await p.waitForTimeout(800);
    await shot(p, '07-manual-redaction', 'manual redaction tooling');
  });

  await step('11-email-thread', 'documents list / email thread', async () => {
    await p.goto(`${BASE}/cases/${CASE_ID}/documents`, { waitUntil: 'domcontentloaded' });
    await settle(p, 2000);
    await shot(p, '11-email-thread', 'documents list (email thread consolidation)');
  });

  await step('12-redacted-view', 'redacted view (black bars)', async () => {
    await p.goto(`${BASE}/documents/${DOC_ID}`, { waitUntil: 'domcontentloaded' });
    try { await p.locator('canvas').first().waitFor({ timeout: 15000 }); } catch {}
    await settle(p, 2500);
    // Toggle the redaction-preview eyeball. Default is preview=ON (colored,
    // editable boxes, Visibility icon); clicking it turns preview OFF, which
    // renders the redactions as solid black bars (final appearance).
    try { await p.locator('button:has(svg[data-testid="VisibilityIcon"])').first().click({ timeout: 6000 }); } catch {}
    await p.waitForTimeout(1800);
    await shot(p, '12-redacted-view', 'redacted view (black bars)');
  });

  await staff.close();
  await browser.close();

  const ok = results.filter(r => r.ok).length;
  console.log(`\nDone: ${ok}/${results.length} steps captured a screenshot.`);
  for (const r of results.filter(r => !r.ok)) console.log(`  MISSED ${r.name}: ${r.err}`);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
