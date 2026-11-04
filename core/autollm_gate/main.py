"""开源内核单独运行：uvicorn autollm_gate.main:app（单租户，上游 Key 读环境变量）。"""
from .gateway import create_app
app = create_app()
