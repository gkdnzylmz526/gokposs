import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage

MODEL = ("openai", "gpt-6-luna")
HISTORY_TURNS = 12

ADMIN_PROMPT = """Sen GÖKBOSS POS'un işletme asistanısın. Restoran sahibine Türkçe, kısa ve net cevap ver.
Sadece aşağıdaki VERİ'ye dayan; veride olmayan bir rakamı uydurma, yoksa "bu bilgi panelde yok" de.
Para birimi Türk lirasıdır (₺). Gerekirse kısa maddeler ve basit hesaplar kullan, öneri istenirse pratik öneriler ver.
Bugünün tarihi: {today}. Seçili restoran: {restaurant}.

VERİ (JSON):
{data}"""

MENU_PROMPT = """Sen {name} restoranının QR menü asistanısın. Müşterilere Türkçe (müşteri başka dilde yazarsa o dilde), sıcak, kısa ve kibar cevap ver.
Sadece aşağıdaki MENÜ'deki ürünler, fiyatlar ve açıklamalar hakkında bilgi ver; menüde olmayan ürün, fiyat veya içerik uydurma.
İçerik/alerjen bilgisi açıklamada yoksa "Bu konuda en doğru bilgiyi garsonumuzdan alabilirsiniz" de.
Sipariş alamazsın; sipariş için garsona seslenmelerini söyle. Restoranla ilgisiz konulara kibarca menüye dönerek cevap ver.

MENÜ (JSON):
{data}"""

_hits: Dict[str, List[float]] = {}


def rate_limited(key: str, limit: int, window: int) -> bool:
    now = time.time()
    if len(_hits) > 5000:
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 3600]:
            _hits.pop(k, None)
    hits = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = hits + [now]
    return len(hits) >= limit


async def history(coll, session_id: str, owner: str) -> List[Dict[str, str]]:
    rows = await coll.find({"session_id": session_id, "owner": owner}, {"_id": 0, "role": 1, "content": 1}).sort("created_at", -1).to_list(HISTORY_TURNS * 2)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def stream_answer(coll, session_id: str, owner: str, system: str, message: str, extra: Dict[str, Any] | None = None) -> AsyncIterator[str]:
    """Stream SSE lines for one turn and persist both messages once the answer is complete."""
    past = await history(coll, session_id, owner)
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=session_id, system_message=system,
                   initial_messages=[{"role": "system", "content": system}, *past]).with_model(*MODEL)
    answer = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=message)):
            if isinstance(ev, TextDelta):
                answer += ev.content
                yield f"data: {json.dumps({'delta': ev.content}, ensure_ascii=False)}\n\n"
            elif isinstance(ev, StreamDone):
                break
    except Exception:
        logging.exception("AI chat failed")
        yield f"data: {json.dumps({'error': 'Asistan şu an cevap veremiyor, lütfen biraz sonra tekrar deneyin.'}, ensure_ascii=False)}\n\n"
        return
    now = datetime.now(timezone.utc).isoformat()
    base = {"session_id": session_id, "owner": owner, **(extra or {})}
    await coll.insert_many([{**base, "id": str(uuid.uuid4()), "role": "user", "content": message, "created_at": now},
                            {**base, "id": str(uuid.uuid4()), "role": "assistant", "content": answer, "created_at": datetime.now(timezone.utc).isoformat()}])
    yield f"data: {json.dumps({'done': True})}\n\n"
