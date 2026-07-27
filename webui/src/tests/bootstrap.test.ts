import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BootstrapAuthRequiredError,
  consumeUrlBootstrapSecret,
  deriveWsUrl,
  fetchBootstrap,
} from "@/lib/bootstrap";

describe("bootstrap helpers", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("prefers the server-provided websocket URL over the current dev host", () => {
    expect(deriveWsUrl("/", "tok en", "ws://127.0.0.1:8765/")).toBe(
      "ws://127.0.0.1:8765/?token=tok%20en",
    );
  });

  it("overrides the server-provided websocket URL when on dev server port 5173", () => {
    vi.stubGlobal("window", {
      location: {
        port: "5173",
        hostname: "192.168.1.100",
        protocol: "http:",
      },
    });
    expect(deriveWsUrl("/", "tok", "ws://127.0.0.1:8765/")).toBe(
      "ws://192.168.1.100:8765/?token=tok",
    );
  });

  it("keeps the gateway websocket port when Vite proxies a custom target", () => {
    vi.stubGlobal("window", {
      location: {
        port: "5173",
        hostname: "127.0.0.1",
        protocol: "http:",
      },
    });
    expect(deriveWsUrl("/ws", "tok", "ws://127.0.0.1:8899/ws")).toBe(
      "ws://127.0.0.1:8899/ws?token=tok",
    );
  });

  it("preserves the host socket bridge URL", () => {
    expect(deriveWsUrl("/", "tok en", "nanobot-host://engine/")).toBe(
      "nanobot-host://engine/?token=tok%20en",
    );
  });

  it("does not double-prefix a server-provided mounted websocket URL", () => {
    expect(
      deriveWsUrl(
        "/nanobot-a/ws",
        "tok",
        "wss://example.test/nanobot-a/ws",
      ),
    ).toBe("wss://example.test/nanobot-a/ws?token=tok");
  });

  it("mounts the bootstrap request beneath an explicit WebUI base", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      token: "ws-token",
      api_token: "api-token",
      ws_path: "/nanobot-a/ws",
      expires_in: 300,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchBootstrap("/nanobot-a");

    expect(fetchMock).toHaveBeenCalledWith(
      "/nanobot-a/webui/bootstrap",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("falls back to the current window host for legacy bootstrap payloads", () => {
    expect(deriveWsUrl("/", "tok")).toBe(
      "ws://localhost:3000/?token=tok",
    );
  });

  it("times out when the bootstrap endpoint never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    const pending = expect(fetchBootstrap("", "", 25)).rejects.toThrow(
      "Request timed out after 25ms",
    );
    await vi.advanceTimersByTimeAsync(25);

    await pending;
  });

  it("treats bootstrap responses without an API token as auth-required", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ token: "ws-token", ws_path: "/", expires_in: 300 }),
      })),
    );

    const promise = fetchBootstrap();
    await expect(promise).rejects.toMatchObject({
      name: "BootstrapAuthRequiredError",
      message: "bootstrap authentication required: missing api_token",
    });
    await expect(promise).rejects.toBeInstanceOf(BootstrapAuthRequiredError);
  });

  it("consumes bootstrap secrets from the URL fragment", () => {
    window.history.replaceState(
      null,
      "",
      "/#/settings?bootstrapSecret=s3cret&section=models",
    );

    expect(consumeUrlBootstrapSecret()).toBe("s3cret");
    expect(window.location.hash).toBe("#/settings?section=models");
  });
});
