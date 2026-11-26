import { useEffect, useRef, useState } from "react";
import { Send, Sparkles, X, RotateCcw } from "lucide-react";
import { newSessionId, streamChat } from "@/lib/aiStream";

// Shared chat window used by the admin assistant and the QR menu assistant.
const EMPTY = [];
export const ChatWindow = ({ title, subtitle, suggestions, greeting, send, onClose, onReset, initial = EMPTY, variant = "admin", placeholder = "Sorunuzu yazın…" }) => {
  const [messages, setMessages] = useState(initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { setMessages(initial); }, [initial]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);
  const ask = async (q) => {
    const question = (q ?? text).trim();
    if (!question || busy) return;
    setText(""); setBusy(true);
    setMessages((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "" }]);
    const patch = (fn) => setMessages((m) => { const copy = [...m]; copy[copy.length - 1] = fn(copy[copy.length - 1]); return copy; });
    try { await send(question, (d) => patch((last) => ({ ...last, content: last.content + d }))); }
    catch (e) { patch(() => ({ role: "assistant", content: e.message, error: true })); }
    finally { setBusy(false); }
  };
  return (
    <div className={`chat-window chat-${variant}`} data-testid={`${variant}-chat-window`}>
      <header className="chat-head">
        <div className="chat-avatar"><Sparkles size={16} /></div>
        <div><b>{title}</b><small>{subtitle}</small></div>
        {onReset && <button className="chat-icon" aria-label="Yeni sohbet" onClick={() => { onReset(); setMessages([]); }} data-testid={`${variant}-chat-reset`}><RotateCcw size={15} /></button>}
        <button className="chat-icon" aria-label="Kapat" onClick={onClose} data-testid={`${variant}-chat-close`}><X size={17} /></button>
      </header>
      <div className="chat-body" data-testid={`${variant}-chat-messages`}>
        {!messages.length && <div className="chat-empty"><p>{greeting}</p><div className="chat-chips">{suggestions.map((s, i) => <button key={s} onClick={() => ask(s)} data-testid={`${variant}-chat-suggestion-${i}`}>{s}</button>)}</div></div>}
        {messages.map((m, i) => <div key={i} className={`chat-msg ${m.role} ${m.error ? "error" : ""}`} data-testid={`${variant}-chat-msg-${i}`}>{m.content || <span className="chat-typing"><i /><i /><i /></span>}</div>)}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input value={text} maxLength={1000} onChange={(e) => setText(e.target.value)} placeholder={placeholder} disabled={busy} data-testid={`${variant}-chat-input`} />
        <button disabled={busy || !text.trim()} aria-label="Gönder" data-testid={`${variant}-chat-send`}><Send size={16} /></button>
      </form>
    </div>
  );
};

export const useChatSession = (storageKey) => {
  const [sid, setSid] = useState(() => localStorage.getItem(storageKey) || newSessionId());
  useEffect(() => { localStorage.setItem(storageKey, sid); }, [sid, storageKey]);
  return [sid, () => setSid(newSessionId())];
};

export { streamChat };
