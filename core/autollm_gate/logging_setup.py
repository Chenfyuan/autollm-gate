"""结构化 JSON 日志（LOG_FORMAT=json，默认）；LOG_FORMAT=text 用于本地调试。"""
from __future__ import annotations
import json, logging, os, sys, time


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + f".{int(r.msecs):03d}Z",
             "level": r.levelname.lower(), "logger": r.name, "msg": r.getMessage()}
        for k, v in r.__dict__.items():
            if k.startswith("f_"):
                d[k[2:]] = v
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False, default=str)


def setup_logging():
    root = logging.getLogger()
    if getattr(root, "_autollm", False):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if os.getenv("LOG_FORMAT", "json") == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers = [h]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    root._autollm = True


def fields(**kw):
    """log.info("msg", extra=fields(tenant=..., model=...))"""
    return {f"f_{k}": v for k, v in kw.items()}
