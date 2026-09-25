// Thin client for the FastAPI engine. Every number shown in the UI comes from here.
export type Market = "IN" | "US";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<T>;
}

export const get = <T>(path: string) => call<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface Status {
  version: string; edition: string; market: Market; as_of: string;
  ai: { model: string; reachable: boolean; spend_this_month: number; budget: number };
  data: { source: string; age: string };
}
export interface Explanation { text: string; sources: string[]; model: string; where: string; blocked: boolean }
