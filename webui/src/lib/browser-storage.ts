import { WEBUI_BASE_PATH, normalizeWebuiBasePath } from "./base-path";

const STORAGE_PREFIX = "nanobot-webui.v2";

export type BrowserStorageKind = "local" | "session";

/** Return the canonical per-WebUI-instance browser storage key. */
export function scopedBrowserStorageKey(
  key: string,
  base: string = WEBUI_BASE_PATH,
): string {
  const normalizedBase = normalizeWebuiBasePath(base);
  return `${STORAGE_PREFIX}:${encodeURIComponent(normalizedBase)}:${key}`;
}

export function readScopedStorage(
  storage: Storage,
  key: string,
  options?: { base?: string; legacyKey?: string },
): string | null {
  const base = normalizeWebuiBasePath(options?.base ?? WEBUI_BASE_PATH);
  const scopedKey = scopedBrowserStorageKey(key, base);
  const value = storage.getItem(scopedKey);
  if (value !== null) return value;
  const legacyKey = options?.legacyKey;
  if (base !== "/" || !legacyKey) return null;
  const legacyValue = storage.getItem(legacyKey);
  if (legacyValue === null) return null;
  storage.setItem(scopedKey, legacyValue);
  storage.removeItem(legacyKey);
  return legacyValue;
}

export function writeScopedStorage(
  storage: Storage,
  key: string,
  value: string,
  base: string = WEBUI_BASE_PATH,
): void {
  storage.setItem(scopedBrowserStorageKey(key, base), value);
}

function resolveStorage(kind: BrowserStorageKind): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Read instance-scoped storage.
 *
 * Root-mounted installations may migrate legacy global keys. Non-root mounts
 * never inspect global keys because multiple Nanobot instances share one
 * origin in the supported reverse-proxy deployment.
 */
export function readBrowserStorage(
  kind: BrowserStorageKind,
  key: string,
  options?: { legacyKey?: string },
): string | null {
  const storage = resolveStorage(kind);
  if (!storage) return null;
  try {
    return readScopedStorage(storage, key, options);
  } catch {
    return null;
  }
}

export function writeBrowserStorage(
  kind: BrowserStorageKind,
  key: string,
  value: string,
): void {
  const storage = resolveStorage(kind);
  if (!storage) return;
  try {
    writeScopedStorage(storage, key, value);
  } catch {
    // Browser persistence must never block the application.
  }
}

export function removeBrowserStorage(
  kind: BrowserStorageKind,
  key: string,
  options?: { legacyKey?: string },
): void {
  const storage = resolveStorage(kind);
  if (!storage) return;
  try {
    storage.removeItem(scopedBrowserStorageKey(key));
    if (WEBUI_BASE_PATH === "/" && options?.legacyKey) {
      storage.removeItem(options.legacyKey);
    }
  } catch {
    // Browser persistence must never block the application.
  }
}

export const scopedLocalStorage = {
  getItem(key: string, legacyKey?: string): string | null {
    return readBrowserStorage("local", key, { legacyKey });
  },
  setItem(key: string, value: string): void {
    writeBrowserStorage("local", key, value);
  },
  removeItem(key: string, legacyKey?: string): void {
    removeBrowserStorage("local", key, { legacyKey });
  },
};

export const scopedSessionStorage = {
  getItem(key: string, legacyKey?: string): string | null {
    return readBrowserStorage("session", key, { legacyKey });
  },
  setItem(key: string, value: string): void {
    writeBrowserStorage("session", key, value);
  },
  removeItem(key: string, legacyKey?: string): void {
    removeBrowserStorage("session", key, { legacyKey });
  },
};
