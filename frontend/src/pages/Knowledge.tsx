/** 知识库页（M05.F02）：种子 FAQ 分组展示 + 本地过滤。 */
import { useEffect, useMemo, useState } from "react";
import { fetchKb } from "../api";
import type { KbArticle } from "../types";

const GROUP_ORDER = ["售后", "账号", "报销", "通用"];

export default function Knowledge() {
  const [items, setItems] = useState<KbArticle[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    fetchKb()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  const filtered = useMemo(() => {
    if (!items) return [];
    const kw = q.trim();
    if (!kw) return items;
    return items.filter((a) => a.title.includes(kw) || a.content.includes(kw));
  }, [items, q]);

  const groups = useMemo(() => {
    const map = new Map<string, KbArticle[]>();
    for (const a of filtered) {
      const list = map.get(a.category) ?? [];
      list.push(a);
      map.set(a.category, list);
    }
    return GROUP_ORDER.filter((g) => map.has(g)).map((g) => [g, map.get(g)!] as const);
  }, [filtered]);

  if (error) return <div className="page page-error">知识库加载失败：{error}</div>;
  if (!items) return <div className="page page-empty">加载中…</div>;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>知识库</h2>
          <p>杉杉回答的唯一依据。共 {items.length} 条（示例数据，均为虚构）。</p>
        </div>
        <div className="tabs-search">
          <input value={q} placeholder="过滤标题或内容…" onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      {groups.map(([cat, list]) => (
        <section key={cat} className="kb-group">
          <h3>{cat}</h3>
          {list.map((a) => (
            <div key={a.id} className="kb-row">
              <div className="kb-id">{a.id}</div>
              <div>
                <div className="kb-title">{a.title}</div>
                <div className="kb-content">{a.content}</div>
              </div>
            </div>
          ))}
        </section>
      ))}
      {groups.length === 0 && <div className="page-empty">没有匹配「{q}」的条目。</div>}
    </div>
  );
}
