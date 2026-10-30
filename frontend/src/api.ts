export const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type Card =
  | { kind: "fields"; title?: string; rows: [string, string][] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "skipped"; rows: string[][] }
  | { kind: "report"; rows: { n: number; name: string; id: string; result: string; issues: string[]; warnings: string[] }[] }
  | { kind: "download" };
export interface Msg { role: "user" | "assistant"; text: string; card?: Card | null; files?: string[] }
export interface Progress { phase: "idle" | "collecting" | "review"; total: number; index: number; name: string; done: number }
interface Reply { messages: Msg[]; progress: Progress; chips: string[] }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try { r = await fetch(`${API}${url}`, init); }
  catch { throw new Error(`Cannot reach the server at ${API}. Is the backend running?`); }
  if (!r.ok) {
    let m = r.statusText;
    try { m = (await r.json()).detail ?? m; } catch { /* keep */ }
    throw new Error(String(m));
  }
  return r.json() as Promise<T>;
}

export const history = (sid: string) => call<Reply>(`/api/chat/${sid}`);
export const send = (sid: string, text: string, files: File[]) => {
  const fd = new FormData();
  fd.append("session_id", sid);
  fd.append("text", text);
  files.forEach((f) => fd.append("files", f));
  return call<Reply>("/api/chat", { method: "POST", body: fd });
};
export const downloadUrl = (fmt: "xlsx" | "xls") => `${API}/api/master/download?format=${fmt}`;
