/** 对话页（M05.F01）：SSE 状态机 + 回答依据面板联动。 */
import { useRef, useState } from "react";
import { createSession, sendMessage } from "../api";
import type { Citation, Ticket } from "../types";

type MsgKind = "normal" | "no-result" | "handoff" | "error";

interface ViewMsg {
  role: "user" | "bot";
  content: string;
  citations: Citation[];
  kind: MsgKind;
  note?: string;
  ticket?: Ticket;
}

const REFERENCE_COPY = "本条回答均依据知识库原文，点击正文里的 [n] 可查看对应依据。";

export default function Chat() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<ViewMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [thinking, setThinking] = useState("");
  const [panelCitations, setPanelCitations] = useState<Citation[]>([]);
  const [litRef, setLitRef] = useState(0);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  function scrollBottom() {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  function focusRef(n: number) {
    setLitRef(n);
    const card = panelRef.current?.querySelector(`[data-ref="${n}"]`);
    if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy || ended) return;
    setDraft("");
    setMsgs((m) => [...m, { role: "user", content: text, citations: [], kind: "normal" }]);
    setBusy(true);
    setStreamText("");
    setThinking("");
    scrollBottom();

    let sid = sessionId;
    try {
      if (!sid) {
        const s = await createSession("网页访客");
        sid = s.id;
        setSessionId(s.id);
      }
      const acc = {
        content: "",
        citations: [] as Citation[],
        kind: "normal" as MsgKind,
        note: "",
        ticket: undefined as Ticket | undefined,
      };
      await sendMessage(sid, text, (ev) => {
        switch (ev.type) {
          case "delta":
            acc.content += ev.text;
            setStreamText(acc.content);
            scrollBottom();
            break;
          case "reasoning":
            setThinking((t) => (t + ev.text).slice(-400));
            break;
          case "citations":
            acc.citations = ev.citations;
            break;
          case "ticket":
            acc.ticket = ev.ticket;
            break;
          case "handoff":
            acc.kind = "handoff";
            acc.note = ev.reason;
            break;
          case "done":
            if (!acc.citations.length) acc.citations = ev.citations;
            if (ev.handoff) {
              acc.kind = "handoff";
              acc.note = ev.handoff.reason;
            } else if (ev.no_result && acc.kind === "normal") {
              acc.kind = "no-result";
            }
            break;
          case "error":
            acc.kind = "error";
            acc.note = ev.message;
            break;
          default:
            break;
        }
      });
      if (acc.kind === "error" && !acc.content) {
        setMsgs((m) => [
          ...m,
          { role: "bot", content: "", citations: [], kind: "error", note: acc.note },
        ]);
      } else {
        setMsgs((m) => [
          ...m,
          {
            role: "bot",
            content: acc.content,
            citations: acc.citations,
            kind: acc.kind,
            note: acc.note,
            ticket: acc.ticket,
          },
        ]);
      }
      if (acc.citations.length) setPanelCitations(acc.citations);
      if (acc.kind === "handoff") setEnded(true);
    } catch (e) {
      setMsgs((m) => [
        ...m,
        {
          role: "bot",
          content: "",
          citations: [],
          kind: "error",
          note: e instanceof Error ? e.message : "网络请求失败",
        },
      ]);
    } finally {
      setBusy(false);
      setStreamText("");
      setThinking("");
      scrollBottom();
    }
  }

  function newSession() {
    setSessionId(null);
    setMsgs([]);
    setPanelCitations([]);
    setLitRef(0);
    setEnded(false);
  }

  function renderContent(content: string) {
    const parts = content.split(/(\[\d+\])/g);
    return parts.map((p, i) => {
      const m = p.match(/^\[(\d+)\]$/);
      if (m) {
        const n = Number(m[1]);
        return (
          <button key={i} className="cite-ref" title="查看依据" onClick={() => focusRef(n)}>
            [{n}]
          </button>
        );
      }
      return <span key={i}>{p}</span>;
    });
  }

  return (
    <div className="chat-grid">
      <div className="chat-col">
        <div className="chat-scroll" ref={scrollRef}>
          {msgs.length === 0 && !busy && (
            <div className="page-empty">
              说说您遇到的问题——退货、发票、账号或报销都可以。
              <br />
              杉杉只依据知识库原文作答，查不到会如实告诉您。
            </div>
          )}
          {msgs.map((m, i) =>
            m.kind === "error" ? (
              <div key={i} className="msg-row bot">
                <div className="msg-note error">
                  <span className="note-title">出错了</span>
                  {m.note}
                </div>
              </div>
            ) : m.role === "user" ? (
              <div key={i} className="msg-row user">
                <div className="msg-bubble">{m.content}</div>
              </div>
            ) : (
              <div key={i} className="msg-row bot">
                <div className="msg-bubble">
                  <span className="msg-who">杉杉</span>
                  {m.kind === "no-result" && (
                    <div className="msg-note no-result" style={{ marginBottom: 8 }}>
                      <span className="note-title">知识库暂无相关资料</span>
                      杉杉不编造答案——换个说法试试，或回复「转人工」。
                    </div>
                  )}
                  {m.kind === "handoff" && (
                    <div className="msg-note handoff" style={{ marginBottom: 8 }}>
                      <span className="note-title">已转人工客服</span>
                      原因：{m.note || "用户要求"}。本会话已交给人工同事跟进。
                    </div>
                  )}
                  {m.content && <div>{renderContent(m.content)}</div>}
                  {m.ticket && (
                    <div className="ticket-chip">
                      已登记工单 <b>#{m.ticket.id}</b> · {m.ticket.title} · 状态 {m.ticket.status}
                    </div>
                  )}
                </div>
              </div>
            )
          )}
          {busy && (
            <div className="msg-row bot">
              <div className="msg-bubble">
                <span className="msg-who">杉杉</span>
                {thinking && <div className="thinking">思考中…{thinking.slice(-120)}</div>}
                {streamText ? (
                  <div>
                    {renderContent(streamText)}
                    <span className="cursor" />
                  </div>
                ) : (
                  !thinking && <span className="thinking">正在查看知识库…</span>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="chat-input">
          <textarea
            value={draft}
            disabled={busy || ended}
            placeholder={ended ? "会话已转人工，点击右侧「新会话」重新开始" : "输入您的问题，Enter 发送，Shift+Enter 换行"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button className="send-btn" disabled={busy || ended || !draft.trim()} onClick={() => void send()}>
            发送
          </button>
          <button className="new-sess" onClick={newSession}>
            新会话
          </button>
        </div>
        {ended && <div className="chat-ended">本会话已转人工，人工同事会按工单与对话记录跟进。</div>}
      </div>
      <aside className="ref-panel" ref={panelRef}>
        <h2>回答依据</h2>
        <p className="ref-sub">{REFERENCE_COPY}</p>
        {panelCitations.length === 0 ? (
          <div className="ref-empty">
            杉杉回答后，依据的知识库片段会显示在这里。
            <br />
            没有依据的回答，杉杉不会说。
          </div>
        ) : (
          panelCitations.map((c, i) => (
            <div key={c.id} data-ref={i + 1} className={litRef === i + 1 ? "ref-card lit" : "ref-card"}>
              <div className="ref-no">[{i + 1}]</div>
              <div>
                <div className="ref-title">
                  {c.title}
                  <span className="ref-tag">{c.category}</span>
                </div>
                <p className="ref-snippet">{c.snippet}</p>
                <div className="ref-meta">
                  条目 {c.id} · 相关度 {(c.score * 100).toFixed(0)}%
                </div>
              </div>
            </div>
          ))
        )}
      </aside>
    </div>
  );
}
