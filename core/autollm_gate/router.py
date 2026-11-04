"""请求特征分类 + 基于 YAML 评分的模型选择。"""
from __future__ import annotations
import os, re
from dataclasses import dataclass, field
from pathlib import Path
import yaml

DEFAULT_CONFIG = Path(__file__).with_name("scoring.yaml")
STRATEGIES = ("cost_optimized", "balanced", "quality_first", "latency_critical")

_CODE = re.compile(r"```|\bdef |\bclass |function\s*\(|\bimport |traceback|stack trace|编译|报错|代码|bug|refactor|SELECT .* FROM", re.I)
_REASON = re.compile(r"证明|推理|一步一步|step by step|prove|数学|calculate|计算|逻辑|analy[sz]e|分析", re.I)


def load_config(path: str | os.PathLike | None = None) -> dict:
    p = path or os.getenv("ROUTER_SCORING_FILE") or DEFAULT_CONFIG
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _text_of(messages: list) -> str:
    out = []
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    out.append(part["text"])
    return "\n".join(out)


def estimate_tokens(messages: list) -> int:
    return max(1, len(_text_of(messages)) // 3)


def classify(body: dict) -> str:
    msgs = body.get("messages", [])
    if estimate_tokens(msgs) > 30000:
        return "long_context"
    # 只看最近一条用户消息，避免长对话历史干扰
    last = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
    text = _text_of([last])
    if body.get("tools") or _CODE.search(text):
        return "coding"
    if _REASON.search(text):
        return "reasoning"
    return "chat"


@dataclass
class Decision:
    model: str
    candidates: list[str]
    strategy: str
    task: str
    reason: str
    scores: dict = field(default_factory=dict)


def parse_strategy(model: str, cfg: dict) -> str | None:
    """返回策略名；非 auto 模型返回 None。"""
    if model == "auto":
        return cfg.get("default_strategy", "cost_optimized")
    if model.startswith("auto:"):
        s = model.split(":", 1)[1]
        if s not in STRATEGIES:
            raise ValueError(f"未知策略: {s}，可选 {', '.join(STRATEGIES)}")
        return s
    return None


def select(body: dict, cfg: dict, available_providers: set[str] | None = None) -> Decision:
    model = body.get("model", "auto")
    models = cfg["models"]
    strategy = parse_strategy(model, cfg)
    if strategy is None:
        if model not in models:
            return Decision(model, [model], "explicit", "-", "用户指定模型（未在评分表中，直通）")
        return Decision(model, [model] + [m for m in _rank(body, cfg, "balanced", available_providers)[0] if m != model][: cfg.get("max_fallbacks", 3)],
                        "explicit", "-", "用户指定模型")
    ranked, scores, task = _rank(body, cfg, strategy, available_providers)
    if not ranked:
        raise LookupError("没有可用的上游模型（请检查上游 Key 配置）")
    top = ranked[0]
    reason = f"strategy={strategy}; task={task}; score={scores[top]:.3f}"
    return Decision(top, ranked[: 1 + cfg.get("max_fallbacks", 3)], strategy, task, reason, scores)


def _rank(body, cfg, strategy, available):
    w = cfg["strategies"][strategy]
    task = classify(body)
    dim = cfg.get("task_dimension", {}).get(task, "quality")
    need_ctx = estimate_tokens(body.get("messages", []))
    pool = {k: v for k, v in cfg["models"].items()
            if (available is None or v["provider"] in available) and v.get("context", 1e9) > need_ctx}
    if not pool:
        return [], {}, task
    blended = {k: v["price_in"] * 0.75 + v["price_out"] * 0.25 for k, v in pool.items()}
    lo, hi = min(blended.values()), max(blended.values())
    scores = {}
    for k, v in pool.items():
        cost = 1.0 if hi == lo else 1 - (blended[k] - lo) / (hi - lo)
        scores[k] = w.get("quality", 0) * v.get(dim, v["quality"]) / 10 + w.get("cost", 0) * cost + w.get("speed", 0) * v["speed"] / 10
    ranked = sorted(scores, key=lambda k: -scores[k])
    return ranked, scores, task
