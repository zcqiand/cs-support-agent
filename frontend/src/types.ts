/** 与后端 api/routes.py、agent/support.py 的事件与行形状一一对应。 */

export type SseEvent =
  | { type: "session"; session_id: string; status: string }
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "ticket"; ticket: Ticket }
  | { type: "handoff"; reason: string }
  | {
      type: "done";
      status: "live" | "ended";
      citations: Citation[];
      ticket: Ticket | null;
      handoff: { reason: string } | null;
      no_result: boolean;
    }
  | { type: "error"; message: string };

export interface Citation {
  id: string;
  category: string;
  title: string;
  snippet: string;
  score: number;
}

export interface Ticket {
  id: string;
  session_id: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
}

export interface KbArticle {
  id: string;
  category: string;
  title: string;
  content: string;
  updated_at: string;
}

export interface SessionInfo {
  id: string;
  channel: string;
  user_name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  role: string;
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface SessionDetail {
  session: SessionInfo;
  messages: ChatMessage[];
}
