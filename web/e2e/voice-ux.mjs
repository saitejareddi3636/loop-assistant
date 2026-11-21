/**
 * Voice UX acceptance smoke + screenshots (local preview, no deploy).
 *
 *   cd web && npm run build && npm run preview -- --host 127.0.0.1 --port 4173
 *   LOOPP_URL=http://127.0.0.1:4173 node e2e/voice-ux.mjs
 *
 * Or against a live origin (dictation/live UI only; STT mocked for UI asserts):
 *   LOOPP_URL=https://… node e2e/voice-ux.mjs
 */
import { chromium, devices } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.LOOPP_URL || "http://127.0.0.1:4173";
const SHOT_DIR = join(dirname(fileURLToPath(import.meta.url)), "screenshots");
mkdirSync(SHOT_DIR, { recursive: true });

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function installApiMocks(page) {
  const conversationId = "11111111-1111-1111-1111-111111111111";
  const sessionToken = "test-session-token";
  let turns = 0;
  let transcribeCalls = 0;
  let chatMessages = [];

  // Live mode opens a WS; keep UI testable without a real voice backend.
  await page.addInitScript(() => {
    class FakeWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      binaryType = "arraybuffer";
      constructor() {
        queueMicrotask(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.onopen?.(new Event("open"));
          this.onmessage?.(
            new MessageEvent("message", {
              data: JSON.stringify({
                type: "voice.backend",
                backend: "moonshine+silero+pocket (mock)",
                tts_sample_rate: 24000,
              }),
            }),
          );
        });
      }
      send(data) {
        if (typeof data !== "string") return;
        try {
          const msg = JSON.parse(data);
          if (msg.type === "voice.commit") {
            queueMicrotask(() =>
              this.onmessage?.(
                new MessageEvent("message", {
                  data: JSON.stringify({ type: "voice.ignored" }),
                }),
              ),
            );
          }
          if (msg.type === "voice.interrupt") {
            queueMicrotask(() =>
              this.onmessage?.(
                new MessageEvent("message", {
                  data: JSON.stringify({ type: "voice.interrupted", stop_ms: 1 }),
                }),
              ),
            );
          }
        } catch {
          // ignore
        }
      }
      close() {
        this.readyState = FakeWebSocket.CLOSED;
        this.onclose?.(new CloseEvent("close"));
      }
      addEventListener() {}
      removeEventListener() {}
    }
    window.WebSocket = FakeWebSocket;
  });

  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        database: "ok",
        llm_configured: true,
        model: "mock-support",
      }),
    });
  });

  await page.route("**/api/conversations", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: conversationId,
          customer_id: "cust_pro_001",
          title: "Billing support",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          session_token: sessionToken,
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.route(`**/api/conversations/${conversationId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: conversationId,
        customer_id: "cust_pro_001",
        title: "Billing support",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        session_token: sessionToken,
        messages: chatMessages,
      }),
    });
  });

  /** @type {((chunk: string) => void) | null} */
  let pushSse = null;
  let sseSequence = 0;

  await page.route(`**/api/conversations/${conversationId}/events**`, async (route) => {
    const stream = new ReadableStream({
      start(controller) {
        const enc = new TextEncoder();
        pushSse = (chunk) => controller.enqueue(enc.encode(chunk));
        pushSse(": connected\n\n");
      },
      cancel() {
        pushSse = null;
      },
    });
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      body: stream,
    });
  });

  await page.route(`**/api/conversations/${conversationId}/transcribe`, async (route) => {
    transcribeCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        text: "I was charged twice on INV-1042",
        stt_ms: 42,
        stt_provider: "moonshine-onnx-tiny",
        sample_rate: 16000,
        duration_ms: 1200,
      }),
    });
  });

  await page.route(`**/api/conversations/${conversationId}/turns`, async (route) => {
    turns += 1;
    const body = route.request().postDataJSON();
    const runId = `22222222-2222-2222-2222-22222222222${turns}`;
    chatMessages = [
      ...chatMessages,
      {
        id: `u-${turns}`,
        role: "user",
        content: body.text,
        client_turn_id: body.client_turn_id,
        created_at: new Date().toISOString(),
        meta: {},
      },
      {
        id: `a-${turns}`,
        role: "assistant",
        content: "I can help with that invoice. One moment.",
        created_at: new Date().toISOString(),
        meta: {},
      },
    ];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        conversation_id: conversationId,
        run_id: runId,
        client_turn_id: body.client_turn_id,
        status: "running",
      }),
    });
    // Clear busy in the app the same way production does.
    sseSequence += 1;
    const payload = JSON.stringify({
      sequence: sseSequence,
      event_type: "run.completed",
      run_id: runId,
      payload: {},
    });
    pushSse?.(`event: run.completed\ndata: ${payload}\n\n`);
  });

  return {
    getTurns: () => turns,
    getTranscribeCalls: () => transcribeCalls,
    getMessages: () => chatMessages,
  };
}

async function runDesktop(browser) {
  const context = await browser.newContext({
    permissions: ["microphone"],
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  const api = await installApiMocks(page);

  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByText("Loopp Support").first().waitFor({ timeout: 20000 });
  await page.getByRole("button", { name: "Send" }).waitFor({ timeout: 45000 });
  await page.getByText("How can we help?").waitFor({ timeout: 45000 });

  // No giant standalone voice card in the dock
  assert(
    (await page.getByRole("button", { name: /Start voice/i }).count()) === 0,
    "legacy Start voice card should be gone",
  );
  await page.getByRole("button", { name: /Dictate with microphone/i }).waitFor();
  await page.getByRole("button", { name: /Open live voice conversation/i }).waitFor();

  await page.screenshot({ path: join(SHOT_DIR, "01-composer-default.png"), fullPage: true });

  // Esc cancels recording without send (while still idle / not busy)
  const beforeTx = api.getTranscribeCalls();
  const beforeTurns = api.getTurns();
  await page.getByRole("button", { name: /Dictate with microphone/i }).click();
  await page.getByRole("button", { name: /Stop recording and send/i }).waitFor({ timeout: 10000 });
  await page.screenshot({ path: join(SHOT_DIR, "02-dictation-recording.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  assert(api.getTranscribeCalls() === beforeTx, "Esc must not transcribe");
  assert(api.getTurns() === beforeTurns, "Esc must not submit");
  await page.getByRole("button", { name: /Dictate with microphone/i }).waitFor();

  // Live mode while chat is idle
  await page.getByRole("button", { name: /Open live voice conversation/i }).click();
  await page.getByRole("dialog", { name: /Live voice conversation/i }).waitFor({ timeout: 15000 });
  await page.getByText(/Listening|Connecting|Hearing/i).first().waitFor({ timeout: 10000 });
  await page.screenshot({ path: join(SHOT_DIR, "04-live-voice.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await page
    .getByRole("dialog", { name: /Live voice conversation/i })
    .waitFor({ state: "detached", timeout: 15000 });
  await page.getByText("Loopp Support").first().waitFor();
  await page.screenshot({ path: join(SHOT_DIR, "05-back-to-chat.png"), fullPage: true });

  // Mic toggle: tap to record (bright), tap again → transcribe + send
  await page.getByRole("button", { name: /Dictate with microphone/i }).click();
  await page.getByRole("button", { name: /Stop recording and send/i }).waitFor({ timeout: 10000 });
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: /Stop recording and send/i }).click();
  await page.waitForTimeout(800);
  assert(api.getTranscribeCalls() === 1, "expected one transcription call");
  assert(api.getTurns() === 1, "second mic tap must send the transcript");
  assert(api.getMessages().some((m) => m.role === "user" && m.content.includes("INV-1042")));
  await page.screenshot({ path: join(SHOT_DIR, "03-transcript-sent.png"), fullPage: true });

  await context.close();
  return { ok: true, turns: api.getTurns(), transcribe: api.getTranscribeCalls() };
}

async function runMobile(browser) {
  const iPhone = devices["iPhone 13"];
  const context = await browser.newContext({
    ...iPhone,
    permissions: ["microphone"],
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  await installApiMocks(page);
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByRole("button", { name: "Send" }).waitFor({ timeout: 45000 });
  await page.getByRole("button", { name: /Dictate with microphone/i }).waitFor();
  const box = await page.getByRole("button", { name: "Send" }).boundingBox();
  assert(box && box.y > 0, "Send not laid out on mobile");
  await page.screenshot({ path: join(SHOT_DIR, "06-mobile-composer.png"), fullPage: true });
  await context.close();
  return { ok: true };
}

const browser = await chromium.launch({
  headless: true,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});
try {
  const desk = await runDesktop(browser);
  const mob = await runMobile(browser);
  console.log(JSON.stringify({ ok: true, desk, mob, url: BASE, shots: SHOT_DIR }, null, 2));
} finally {
  await browser.close();
}
