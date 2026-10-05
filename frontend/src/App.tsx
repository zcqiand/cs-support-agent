import { useState } from "react";
import Chat from "./pages/Chat";
import Knowledge from "./pages/Knowledge";
import Tickets from "./pages/Tickets";

type Tab = "chat" | "kb" | "tickets";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">杉</span>
          <div className="brand-text">
            <h1>杉杉 · 云杉科技智能客服</h1>
            <p>先查知识库 · 引用原文作答 · 查不到就转人工</p>
          </div>
        </div>
        <nav className="tabs">
          <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>
            对话
          </button>
          <button className={tab === "kb" ? "on" : ""} onClick={() => setTab("kb")}>
            知识库
          </button>
          <button className={tab === "tickets" ? "on" : ""} onClick={() => setTab("tickets")}>
            工单
          </button>
        </nav>
      </header>
      <main className="main">
        {tab === "chat" && <Chat />}
        {tab === "kb" && <Knowledge />}
        {tab === "tickets" && <Tickets />}
      </main>
    </div>
  );
}
