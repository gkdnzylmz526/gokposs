import { useEffect, useState } from "react";
import axios from "axios";
import { useAuth } from "@clerk/react";
import { Sparkles } from "lucide-react";
import { ChatWindow, streamChat, useChatSession } from "@/components/ChatWindow";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const SUGGESTIONS = ["Bu ay kârım ne durumda?", "En çok hangi giderim var?", "Maliyeti en yüksek ürünüm hangisi?", "Kritik stokta neler var?"];

export const AiAssistant = ({ restaurantKey }) => {
  const { getToken } = useAuth();
  const [open, setOpen] = useState(false);
  const [sid, reset] = useChatSession("gokboss-ai-session");
  const [initial, setInitial] = useState([]);
  useEffect(() => { if (open) axios.get(`${API}/ai/history`, { params: { session_id: sid } }).then(({ data }) => setInitial(data)).catch(() => setInitial([])); }, [open, sid, restaurantKey]);
  const send = async (message, onDelta) => {
    const common = axios.defaults.headers.common;
    const headers = { Authorization: `Bearer ${await getToken()}`, "X-Restaurant": common["X-Restaurant"] || "" };
    if (common["X-Restaurant-Key"]) headers["X-Restaurant-Key"] = common["X-Restaurant-Key"];
    await streamChat(`${API}/ai/chat`, { session_id: sid, message }, headers, onDelta);
  };
  return <>
    {open && <ChatWindow title="Yapay Zeka Asistanı" subtitle="Ciro, gider, maliyet ve stok verilerinize bakarak cevaplar" greeting="Merhaba! İşletmenizle ilgili ne merak ediyorsunuz?" suggestions={SUGGESTIONS} send={send} initial={initial} onClose={() => setOpen(false)} onReset={() => { reset(); setInitial([]); }} />}
    {!open && <button className="ai-fab" onClick={() => setOpen(true)} data-testid="ai-assistant-button"><Sparkles size={18} /> Asistana sor</button>}
  </>;
};
