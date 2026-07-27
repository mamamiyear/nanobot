const SAFE_BASE_SEGMENT = /^[A-Za-z0-9._~-]+$/;

/**
 * Normalize the public WebUI mount path shared by Vite and the gateway.
 *
 * The canonical runtime form is "/" for the root mount and a leading-slash,
 * no-trailing-slash path for every non-root mount.
 */
export function normalizeWebuiBasePath(value: string | null | undefined): string {
  const raw = (value ?? "").trim() || "/";
  if (!raw.startsWith("/")) {
    throw new Error(`WebUI base path must start with "/": ${raw}`);
  }
  if (raw.includes("?") || raw.includes("#") || raw.includes("\\")) {
    throw new Error(`WebUI base path must contain only URL path segments: ${raw}`);
  }

  const canonical = raw === "/" ? "/" : raw.replace(/\/+$/, "");
  const segments = canonical.slice(1).split("/");
  if (
    canonical !== "/"
    && (
      segments.some((segment) => !segment || segment === "." || segment === "..")
      || segments.some((segment) => !SAFE_BASE_SEGMENT.test(segment))
    )
  ) {
    throw new Error(`WebUI base path contains an unsafe segment: ${raw}`);
  }
  return canonical;
}

/** Return the trailing-slash form required by Vite's `base` option. */
export function toViteBasePath(value: string | null | undefined): string {
  const base = normalizeWebuiBasePath(value);
  return base === "/" ? "/" : `${base}/`;
}

/** Mount an absolute application path beneath a normalized WebUI base. */
export function mountWebuiPath(
  baseValue: string | null | undefined,
  pathValue: string,
): string {
  const base = normalizeWebuiBasePath(baseValue);
  const path = pathValue.startsWith("/") ? pathValue : `/${pathValue}`;
  if (path === "/") return base;
  return base === "/" ? path : `${base}${path}`;
}
