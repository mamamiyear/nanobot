import {
  mountWebuiPath,
  normalizeWebuiBasePath,
  toViteBasePath,
} from "../../base-path";

/** Canonical public mount path embedded by Vite at build time. */
export const WEBUI_BASE_PATH = normalizeWebuiBasePath(import.meta.env.BASE_URL);

/** Prefix suitable for direct string concatenation with an absolute route. */
export const WEBUI_BASE_PREFIX = WEBUI_BASE_PATH === "/" ? "" : WEBUI_BASE_PATH;

/** Vite-style mount path, always ending in `/`. */
export const WEBUI_BASE_URL = toViteBasePath(WEBUI_BASE_PATH);

/** Prefix an application endpoint or public asset with the compiled WebUI base. */
export function withWebuiBase(path: string): string {
  return mountWebuiPath(WEBUI_BASE_PATH, path);
}

/** Resolve an asset beneath Vite's public base without depending on document URL. */
export function webuiAssetUrl(path: string): string {
  return withWebuiBase(path);
}

export {
  mountWebuiPath,
  normalizeWebuiBasePath,
  toViteBasePath,
};
