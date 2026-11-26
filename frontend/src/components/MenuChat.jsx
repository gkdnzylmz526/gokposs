import { useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { ChatWindow, streamChat, useChatSession } from "@/components/ChatWindow";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const MenuChat = ({ t }) => {
  const [open, setOpen] = useState(false);
  const [sid, reset] = useChatSession("menu-chat-session");
  const send = (message, onDelta) => streamChat(`${API}/public/menu-chat`, { session_id: sid, message }, {}, onDelta);
  return <>
    {open && <ChatWindow variant="menu" title={t.title} subtitle={t.subtitle} greeting={t.greeting} placeholder={t.placeholder} suggestions={t.suggestions} send={send} onClose={() => setOpen(false)} onReset={reset} />}
    {!open && <button className="menu-chat-fab" onClick={() => setOpen(true)} data-testid="menu-chat-button"><MessageCircleQuestion size={18} /> {t.button}</button>}
  </>;
};
