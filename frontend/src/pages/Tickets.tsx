/** 工单页（M05.F03）：报障开单留痕列表。 */
import { useEffect, useState } from "react";
import { fetchTickets } from "../api";
import type { Ticket } from "../types";

export default function Tickets() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchTickets()
      .then(setTickets)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  if (error) return <div className="page page-error">工单加载失败：{error}</div>;
  if (!tickets) return <div className="page page-empty">加载中…</div>;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>工单</h2>
          <p>对话中登记的报障与诉求，人工同事按此跟进。共 {tickets.length} 条。</p>
        </div>
      </div>
      {tickets.length === 0 ? (
        <div className="page-empty">还没有工单——在对话里说「系统登不上了，帮我报障」试试。</div>
      ) : (
        <table className="ticket-table">
          <thead>
            <tr>
              <th>编号</th>
              <th>标题</th>
              <th>描述</th>
              <th>状态</th>
              <th>会话</th>
              <th>登记时间</th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((t) => (
              <tr key={t.id}>
                <td>#{t.id}</td>
                <td>{t.title}</td>
                <td>{t.description}</td>
                <td>
                  <span className="ticket-status">{t.status}</span>
                </td>
                <td>{t.session_id}</td>
                <td>{t.created_at.replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
