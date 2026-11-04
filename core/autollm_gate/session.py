"""会话粘性：同一会话固定使用首次选中的模型，提高上游缓存命中并保证体验一致。存储在共享状态（Redis）中，多实例一致。"""
from __future__ import annotations
import hashlib, os

HEADER_CANDIDATES = ("x-session-id", "x-claude-code-session-id", "session_id", "x-codex-session-id", "conversation_id")


def extract_session_id(headers, body: dict) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    for name in HEADER_CANDIDATES:
        if h.get(name):
            return h[name]
    # Claude Code：metadata.user_id 形如 "user_<hash>_account_<id>_session_<uuid>"
    uid = (body.get("metadata") or {}).get("user_id")
    if isinstance(uid, str) and uid:
        if "_session_" in uid:
            return "cc:" + uid.rsplit("_session_", 1)[1]
        return "meta:" + uid
    # Codex（Responses/Chat）：prompt_cache_key 或 user 字段
    for k in ("prompt_cache_key", "user"):
        if isinstance(body.get(k), str) and body[k]:
            return f"{k}:{body[k]}"
    # 兜底：system + 第一条 user 消息指纹（同一对话前缀一致）
    msgs = body.get("messages") or []
    first_user = next((m for m in msgs if m.get("role") == "user"), None)
    if first_user is not None and len(msgs) > 1:
        seed = repr(body.get("system")) + repr(first_user.get("content"))
        return "fp:" + hashlib.sha256(seed.encode()).hexdigest()[:24]
    return None


class SessionStore:
    def __init__(self, state, ttl: int | None = None):
        self.state = state
        self.ttl = ttl or int(os.getenv("SESSION_STICKY_TTL", "3600"))

    @staticmethod
    def _k(sid):
        return "sticky:" + hashlib.sha256(sid.encode()).hexdigest()[:32]

    async def get(self, sid: str, scope: str = ""):
        try:
            return await self.state.get(self._k(scope + "|" + sid))
        except Exception:
            return None

    async def set(self, sid: str, model: str, scope: str = ""):
        try:
            await self.state.set(self._k(scope + "|" + sid), model, ttl=self.ttl)
        except Exception:
            pass
