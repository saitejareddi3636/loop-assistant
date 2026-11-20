/**
 * Public HTTPS front door for Loopp on Oracle.
 * clients → https://*.workers.dev (trusted) → http://ORIGIN (existing VM)
 */

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "cf-connecting-ip",
  "cf-ipcountry",
  "cf-ray",
  "cf-visitor",
  "cdn-loop",
]);

function buildOriginUrl(request, originBase) {
  const incoming = new URL(request.url);
  const origin = new URL(originBase);
  return new URL(incoming.pathname + incoming.search, origin);
}

function filterRequestHeaders(request, originHost) {
  const headers = new Headers();
  for (const [key, value] of request.headers) {
    if (HOP_BY_HOP.has(key.toLowerCase())) continue;
    headers.set(key, value);
  }
  headers.set("Host", originHost);
  headers.set("X-Forwarded-Proto", "https");
  headers.set("X-Forwarded-Host", new URL(request.url).host);
  return headers;
}

function filterResponseHeaders(response) {
  const headers = new Headers();
  for (const [key, value] of response.headers) {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower)) continue;
    if (lower === "content-encoding") continue;
    headers.set(key, value);
  }
  const ct = headers.get("content-type") || "";
  if (ct.includes("text/event-stream")) {
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("X-Accel-Buffering", "no");
  }
  return headers;
}

function safeClose(socket, code, reason) {
  try {
    if (
      typeof code === "number" &&
      code >= 1000 &&
      code < 5000 &&
      ![1004, 1005, 1006, 1015].includes(code)
    ) {
      socket.close(code, reason);
    } else {
      socket.close();
    }
  } catch {
    /* already closed */
  }
}

async function proxyWebSocket(request, targetUrl) {
  const originResponse = await fetch(targetUrl.toString(), {
    headers: {
      Upgrade: "websocket",
      Connection: "Upgrade",
      ...(request.headers.get("Sec-WebSocket-Protocol")
        ? { "Sec-WebSocket-Protocol": request.headers.get("Sec-WebSocket-Protocol") }
        : {}),
    },
  });

  const originWs = originResponse.webSocket;
  if (!originWs) {
    return new Response("Origin did not accept WebSocket upgrade", { status: 502 });
  }

  const pair = new WebSocketPair();
  const client = pair[0];
  const server = pair[1];

  originWs.accept({ allowHalfOpen: true });
  server.accept({ allowHalfOpen: true });

  server.addEventListener("message", (event) => {
    try {
      originWs.send(event.data);
    } catch {
      /* ignore */
    }
  });
  originWs.addEventListener("message", (event) => {
    try {
      server.send(event.data);
    } catch {
      /* ignore */
    }
  });

  server.addEventListener("close", (event) => {
    safeClose(originWs, event.code, event.reason);
  });
  originWs.addEventListener("close", (event) => {
    safeClose(server, event.code, event.reason);
  });
  server.addEventListener("error", () => safeClose(originWs));
  originWs.addEventListener("error", () => safeClose(server));

  return new Response(null, { status: 101, webSocket: client });
}

export default {
  async fetch(request, env) {
    // Workers cannot fetch bare IPs (error 1003). Use a hostname that resolves to the VM.
    const originBase = (env.ORIGIN_BASE || "https://129.80.125.203.sslip.io").replace(/\/$/, "");
    const target = buildOriginUrl(request, originBase);
    const originHost = new URL(originBase).host;

    if ((request.headers.get("Upgrade") || "").toLowerCase() === "websocket") {
      return proxyWebSocket(request, target);
    }

    const init = {
      method: request.method,
      headers: filterRequestHeaders(request, originHost),
      redirect: "manual",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
      init.duplex = "half";
    }

    const response = await fetch(target.toString(), init);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: filterResponseHeaders(response),
    });
  },
};
