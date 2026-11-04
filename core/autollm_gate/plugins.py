"""核心逻辑插件接口。

公开仓库只包含接口和一个简单的默认实现（router.select / admin Pricing），保证开箱可运行。
私有核心包（如 autollm-gate-core）以插件形式安装后自动替换默认实现：

  * 通过 entry point 注册：  [project.entry-points."autollm_gate.core"] core = "pkg.module:plugin"
  * 或通过环境变量指定：     AUTOLLM_CORE_PLUGIN=pkg.module:plugin

插件对象可提供以下任意属性（缺失的使用默认实现）：
  name: str
  select(body, cfg, available_providers) -> router.Decision     # 路由决策
  pricing_class: type                                            # 继承 autollm_admin.billing.Pricing 的计价类
"""
from __future__ import annotations
import importlib, logging, os
from importlib.metadata import entry_points

log = logging.getLogger("autollm_gate.plugins")
GROUP = "autollm_gate.core"
_cache: dict = {}


class DefaultCore:
    name = "default"
    select = None
    pricing_class = None


def _load(spec: str):
    mod, _, attr = spec.partition(":")
    obj = importlib.import_module(mod)
    return getattr(obj, attr) if attr else obj


def load_core():
    if "core" in _cache:
        return _cache["core"]
    core = DefaultCore()
    spec = os.getenv("AUTOLLM_CORE_PLUGIN", "").strip()
    try:
        if spec.lower() in ("off", "none", "default"):
            pass
        elif spec:
            core = _load(spec)
        else:
            eps = list(entry_points(group=GROUP))
            if eps:
                core = eps[0].load()
    except Exception:
        log.exception("加载核心插件失败，回退到默认实现")
        core = DefaultCore()
    log.info("core plugin: %s", getattr(core, "name", "custom"))
    _cache["core"] = core
    return core


def reset():
    _cache.clear()
