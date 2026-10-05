/** API 封装：全部同源相对路径（vite proxy → 8803），无绝对 baseURL。 */
import type { KbArticle, SessionDetail, SessionInfo, SseEvent, Ticket } from "./types";

async function readError(res: Response): Promise<string> {
  const detail = await res
    .json()
    .then((d) => d?.detail)
    .catch(() => null);
  return typeof detail === "string" ? detail : `请求失败 (${res.status})`;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

// ---- 会话 ----

export function createSession(userName: string): Promise<SessionInfo> {
  return postJSON("/api/sessions", { channel: "web", user_name: userName });
}

export function fetchSession(sid: string): Promise<SessionDetail> {
  return getJSON(`/api/sessions/${sid}`);
}

/** SSE：发消息，逐事件回调（session/delta/reasoning/citations/ticket/handoff/done/error）。 */
export async function sendMessage(
  sid: string,
  text: string,
  onEvent: (ev: SseEvent) => void
): Promise<void> {
  const res = await fetch(`/api/sessions/${sid}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok || !res.body) throw new Error(await readError(res));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = block.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as SseEvent);
      } catch {
        // 半个 JSON 块，忽略
      }
    }
  }
}

// ---- 知识库 / 工单 ----

export function fetchKb(): Promise<KbArticle[]> {
  return getJSON("/api/kb");
}

export function fetchTickets(): Promise<Ticket[]> {
  return getJSON("/api/tickets");
}
