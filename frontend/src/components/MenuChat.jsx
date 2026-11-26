import { useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { ChatWindow, streamChat, useChatSession } from "@/components/ChatWindow";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SUGGESTIONS = ["Ne önerirsiniz?", "Acısız seçenekler neler?", "En hesaplı ürün hangisi?"];

export const MenuChat = () => {
  const [open, setOpen] = useState(false);
  const [sid] = useChatSession("menu-chat-session");
  const send = (message, onDelta) => streamChat(`${API}/public/menu-chat`, { session_id: sid, message }, {}, onDelta);
  return <>
    {open && <ChatWindow variant="menu" title="Menü Asistanı" subtitle="Menümüzle ilgili her şeyi sorabilirsiniz" greeting="Hoş geldiniz! Size menümüzden ne önermemi istersiniz?" suggestions={SUGGESTIONS} send={send} onClose={() => setOpen(false)} />}
    {!open && <button className="menu-chat-fab" onClick={() => setOpen(true)} data-testid="menu-chat-button"><MessageCircleQuestion size={18} /> Menüye sor</button>}
  </>;
};
