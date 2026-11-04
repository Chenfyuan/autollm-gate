"""密码哈希（Argon2id）、会话（HS256 JWT 放在 HttpOnly Cookie）、CSRF 校验、登录/注册限流。"""
from __future__ import annotations
import os, secrets, time
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request, Response

_ph = PasswordHasher()
_DUMMY = _ph.hash("dummy-password-for-timing")
ADMIN_COOKIE, TENANT_COOKIE = "alg_admin_session", "alg_session"
CSRF_HEADER = "x-requested-with"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(h: str | None, pw: str) -> bool:
    try:
        return _ph.verify(h or _DUMMY, pw) and h is not None
    except (VerificationError, InvalidHashError):
        return False


def validate_password(pw: str):
    if len(pw) < 8 or pw.isdigit() or pw.isalpha():
        raise HTTPException(422, "密码至少 8 位，且需同时包含字母和数字")


_secret_cache: dict = {}


def session_secret() -> str:
    s = os.getenv("SESSION_SECRET")
    if s:
        return s
    # 开发 / 测试：进程内随机（多实例必须显式配置 SESSION_SECRET）
    return _secret_cache.setdefault("s", secrets.token_urlsafe(48))


def cookie_secure() -> bool:
    v = os.getenv("COOKIE_SECURE")
    if v is not None:
        return v == "1"
    return os.getenv("ENV", "").lower() == "production"


def issue(resp: Response, cookie: str, sub: str, kind: str, sv: int, hours: int):
    exp = int(time.time()) + hours * 3600
    tok = jwt.encode({"sub": sub, "kind": kind, "sv": sv, "exp": exp, "iat": int(time.time())}, session_secret(), algorithm="HS256")
    resp.set_cookie(cookie, tok, max_age=hours * 3600, httponly=True, secure=cookie_secure(), samesite="lax", path="/")


def clear(resp: Response, cookie: str):
    resp.delete_cookie(cookie, path="/")


def read(request: Request, cookie: str, kind: str) -> dict:
    tok = request.cookies.get(cookie)
    if not tok:
        raise HTTPException(401, "请先登录")
    try:
        claims = jwt.decode(tok, session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "登录已过期，请重新登录")
    if claims.get("kind") != kind:
        raise HTTPException(401, "请先登录")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "autollm":
        raise HTTPException(403, "缺少 CSRF 校验头")
    return claims


def client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "0") == "1":
        # nginx 以 $remote_addr 覆盖这两个头；取最右侧一跳，避免客户端伪造
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(state, key: str, limit: int, window: int, scope: str = "auth"):
    from autollm_gate.metrics import RATE_LIMITED
    bucket = int(time.time() // window)
    n = await state.incr(f"rl:{key}:{bucket}", window + 5)
    if n > limit:
        RATE_LIMITED.labels(scope).inc()
        retry = window - int(time.time()) % window
        raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(retry)})
