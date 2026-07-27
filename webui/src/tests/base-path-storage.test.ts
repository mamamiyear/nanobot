import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

import {
  mountWebuiPath,
  normalizeWebuiBasePath,
  toViteBasePath,
} from "@/lib/base-path";
import {
  readScopedStorage,
  scopedBrowserStorageKey,
  writeScopedStorage,
} from "@/lib/browser-storage";

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("WebUI base paths", () => {
  it("uses canonical runtime and Vite forms", () => {
    expect(normalizeWebuiBasePath(undefined)).toBe("/");
    expect(normalizeWebuiBasePath("/nanobot-a/")).toBe("/nanobot-a");
    expect(toViteBasePath("/nanobot-a")).toBe("/nanobot-a/");
    expect(mountWebuiPath("/nanobot-a", "/api/settings")).toBe(
      "/nanobot-a/api/settings",
    );
    expect(mountWebuiPath("/", "/api/settings")).toBe("/api/settings");
  });
});

describe("per-base browser storage", () => {
  it("keeps two Nanobot instances on the same origin isolated", () => {
    const storage = createMemoryStorage();
    writeScopedStorage(storage, "bootstrap-secret", "secret-a", "/nanobot-a");
    writeScopedStorage(storage, "bootstrap-secret", "secret-b", "/nanobot-b");

    expect(readScopedStorage(storage, "bootstrap-secret", { base: "/nanobot-a" }))
      .toBe("secret-a");
    expect(readScopedStorage(storage, "bootstrap-secret", { base: "/nanobot-b" }))
      .toBe("secret-b");
    expect(scopedBrowserStorageKey("theme", "/nanobot-a")).not.toBe(
      scopedBrowserStorageKey("theme", "/nanobot-b"),
    );
  });

  it("uses the same base namespace in the pre-bundle HTML bootstrap", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const script = html.match(
      /<script>\s*(\(function \(\) \{\s*var rawBase = "%BASE_URL%" \|\| "\/";[\s\S]*?\}\)\(\);)\s*<\/script>/,
    )?.[1];
    if (!script) throw new Error("Could not find WebUI preboot storage script");

    const reads: string[] = [];
    runInNewContext(script.replaceAll("%BASE_URL%", "/nanobot-a/"), {
      localStorage: {
        getItem: (key: string) => {
          reads.push(key);
          return null;
        },
        removeItem: () => undefined,
        setItem: () => undefined,
      },
      window: {
        matchMedia: () => ({ matches: false }),
      },
      document: {
        documentElement: {
          classList: { add: () => undefined },
        },
      },
      encodeURIComponent,
    });

    expect(reads).toContain(scopedBrowserStorageKey("theme", "/nanobot-a"));
  });

  it("never reads an unscoped legacy key for a non-root instance", () => {
    const storage = createMemoryStorage();
    storage.setItem("nanobot-webui.bootstrap-secret", "legacy-root-secret");

    expect(readScopedStorage(storage, "bootstrap-secret", {
      base: "/nanobot-a",
      legacyKey: "nanobot-webui.bootstrap-secret",
    })).toBeNull();
  });

  it("migrates legacy storage only for the root-mounted instance", () => {
    const storage = createMemoryStorage();
    storage.setItem("nanobot-webui.theme", "dark");

    expect(readScopedStorage(storage, "theme", {
      base: "/",
      legacyKey: "nanobot-webui.theme",
    })).toBe("dark");
    expect(storage.getItem("nanobot-webui.theme")).toBeNull();
    expect(storage.getItem(scopedBrowserStorageKey("theme", "/"))).toBe("dark");
  });
});
