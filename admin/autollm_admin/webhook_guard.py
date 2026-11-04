"""告警 Webhook 地址校验：防止 SSRF 访问内网/本机地址。"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit


class WebhookURLError(ValueError):
    pass


def _bad_ip(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified or not ip.is_global)


def check_scheme(url: str) -> tuple[str, int]:
    u = urlsplit(url.strip())
    prod = os.getenv("ENV", "").lower() == "production"
    allowed = ("https",) if prod else ("https", "http")
    if u.scheme not in allowed:
        raise WebhookURLError("Webhook 地址必须使用 https://" if prod else "Webhook 地址必须以 http:// 或 https:// 开头")
    if not u.hostname or u.username or u.password:
        raise WebhookURLError("Webhook 地址无效")
    try:
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        raise WebhookURLError("Webhook 端口无效")
    return u.hostname, port


def _resolve(host: str, port: int) -> list[str]:
    try:
        return [ipaddress.ip_address(host).compressed]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise WebhookURLError("Webhook 域名无法解析")
    return list({i[4][0].split("%")[0] for i in infos})


async def validate_webhook_url(url: str) -> None:
    host, port = check_scheme(url)
    ips = await asyncio.get_running_loop().run_in_executor(None, _resolve, host, port)
    if not ips:
        raise WebhookURLError("Webhook 域名无法解析")
    for a in ips:
        if _bad_ip(ipaddress.ip_address(a)):
            raise WebhookURLError("Webhook 地址不能指向内网、本机或保留地址")
