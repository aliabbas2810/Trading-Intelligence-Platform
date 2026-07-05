interface ImportMetaEnv {
  readonly VITE_TIP_API_BASE_URL?: string;
  readonly VITE_TIP_POLL_INTERVAL_MS?: string;
}

interface TipImportMeta extends ImportMeta {
  readonly env?: ImportMetaEnv;
}

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_POLL_INTERVAL_MS = 0;

function readEnv(): ImportMetaEnv {
  return ((import.meta as TipImportMeta).env ?? {}) as ImportMetaEnv;
}

function normalizeBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return DEFAULT_API_BASE_URL;
  }
  return trimmed.replace(/\/+$/, "");
}

function parsePollInterval(value: string | undefined): number {
  if (value === undefined || value.trim() === "") {
    return DEFAULT_POLL_INTERVAL_MS;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return DEFAULT_POLL_INTERVAL_MS;
  }
  return Math.floor(parsed);
}

const env = readEnv();

export const API_BASE_URL = normalizeBaseUrl(env.VITE_TIP_API_BASE_URL);
export const POLL_INTERVAL_MS = parsePollInterval(env.VITE_TIP_POLL_INTERVAL_MS);

