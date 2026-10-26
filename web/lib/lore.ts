// Server-only client for lore-backend. The browser never sees a Lore key.
const BASE = process.env.LORE_API_URL ?? "http://localhost:8000";

export type Source = [kind: string, label: string, url?: string];

export type WhyResult = {
  answer: string;
  sources: Source[];
  path?: string;
  hops?: number;
  guardrail?: { status: string; ok: boolean; reason: string; matched: string[]; unknown: string[] };
};

export class LoreError extends Error {
  constructor(readonly status: number, path: string) {
    super(`Lore API ${path} returned ${status}`);
  }
}

export type HistoryItem = WhyResult & { question: string; created_at: string };

export type BackfillJob = { id: number; type: string; status: string; progress: unknown; error: string | null };

export async function lore<T>(path: string, key: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    cache: "no-store",
    headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
  });
  if (!res.ok) throw new LoreError(res.status, path);
  return res.json() as Promise<T>;
}

/** Mint a Canon key for a GitHub account; the backend scopes it to gh:<login>. */
export async function mintKey(login: string): Promise<string> {
  const res = await fetch(BASE + "/v1/keys", {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json", "x-admin-secret": process.env.LORE_ADMIN_SECRET ?? "" },
    body: JSON.stringify({ tenant_name: login }),
  });
  if (!res.ok) throw new Error(`Could not mint a Lore key for ${login} (${res.status})`);
  return ((await res.json()) as { api_key: string }).api_key;
}
