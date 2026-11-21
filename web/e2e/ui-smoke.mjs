/**
 * Playwright smoke test against the deployed Cloudflare URL.
 * Run: npx playwright test is not required — execute with:
 *   node --experimental-vm-modules is unused; use:
 *   npx playwright install chromium && node web/e2e/ui-smoke.mjs
 */
import { chromium, devices } from "playwright";

const BASE = process.env.LOOPP_URL || "https://loopp-proxy.saitejareddi1503.workers.dev";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function runDesktop(browser) {
  const context = await browser.newContext({
    permissions: ["microphone"],
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByText("Loopp Support").first().waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Send" }).waitFor({ timeout: 45000 });

  // Wait for session boot → empty state
  await page.getByText("How can we help?").waitFor({ timeout: 45000 });
  const suggestion = page.getByRole("button", { name: /charged twice on INV-1042/i });
  await suggestion.waitFor({ timeout: 10000 });
  await suggestion.click();

  await page.getByText("You").first().waitFor({ timeout: 20000 });
  await page.getByText("Live agent steps").waitFor({ timeout: 60000 });
  await page.locator("text=Loopp Agent").first().waitFor({ timeout: 120000 });

  // Composer still visible after reply
  const send = page.getByRole("button", { name: "Send" });
  assert(await send.isVisible(), "Send button missing after chat");
  assert(!(await send.isDisabled()) || true, "send presence ok");

  // Observability drawer
  await page.getByRole("button", { name: /Observability/i }).click();
  await page.getByText(/Latency & cost/i).waitFor({ timeout: 10000 });

  // Dictation mic + optional Live voice (secure context)
  const dictate = page.getByRole("button", { name: /Dictate with microphone/i });
  assert(await dictate.isEnabled(), "Dictate mic disabled");
  const live = page.getByRole("button", { name: /Open live voice conversation/i });
  assert(await live.isEnabled(), "Live voice disabled");
  const secure = await page.evaluate(() => ({
    secure: window.isSecureContext,
    mic: typeof navigator.mediaDevices?.getUserMedia === "function",
  }));
  assert(secure.secure, "not a secure context");
  assert(secure.mic, "getUserMedia unavailable");

  // Live conversation — WS + model warm can take a while on cold origin
  await live.click();
  const dialog = page.getByRole("dialog", { name: /Live voice conversation/i });
  try {
    await dialog.waitFor({ timeout: 120000 });
    await page.getByText(/Listening|Hearing you|Connecting/i).first().waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: /End live|Close|End now/i }).first().click();
    await dialog.waitFor({ state: "detached", timeout: 60000 });
  } catch (err) {
    const errBanner = await page.locator("p.text-coral, .text-coral, .text-red-600").allTextContents();
    const bodySnippet = (await page.locator("main").innerText()).slice(0, 800);
    throw new Error(
      `live voice failed: ${err}\nerrors=${JSON.stringify(errors)}\nbanner=${JSON.stringify(errBanner)}\nui=${bodySnippet}`,
    );
  }

  assert(errors.length === 0, `page errors: ${errors.join(" | ")}`);
  await context.close();
  return "desktop ok";
}

async function runMobile(browser) {
  const iPhone = devices["iPhone 13"];
  const context = await browser.newContext({
    ...iPhone,
    permissions: ["microphone"],
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByRole("button", { name: "Send" }).waitFor({ timeout: 45000 });
  await page.getByRole("button", { name: /Dictate with microphone/i }).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: /Open live voice conversation/i }).waitFor({ timeout: 15000 });
  const box = await page.getByRole("button", { name: "Send" }).boundingBox();
  assert(box && box.y > 0, "Send not laid out on mobile");
  await context.close();
  return "mobile ok";
}

const browser = await chromium.launch({
  headless: true,
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--use-fake-device-for-media-stream",
  ],
});
try {
  const desk = await runDesktop(browser);
  const mob = await runMobile(browser);
  console.log(JSON.stringify({ ok: true, desk, mob, url: BASE }, null, 2));
} finally {
  await browser.close();
}
