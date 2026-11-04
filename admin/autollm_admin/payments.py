"""支付渠道占位。真实渠道（Stripe / 支付宝 / 微信）实现 PaymentChannel 接口后注册即可。"""
from __future__ import annotations


class PaymentChannel:
    name = "base"

    def create_checkout(self, topup_id: str, amount_micro: int) -> dict:
        """返回给前端的支付信息（如跳转 URL / 二维码）。"""
        raise NotImplementedError

    def verify_webhook(self, headers: dict, payload: dict) -> tuple[str, str, bool]:
        """校验回调签名，返回 (topup_id, external_id, paid)。"""
        raise NotImplementedError


class MockChannel(PaymentChannel):
    label = "模拟支付（仅测试环境）"
    available = True

    """仅用于开发/测试：回调 payload {"topup_id":..., "paid": true} 即视为支付成功。生产环境务必关闭。"""
    name = "mock"

    def create_checkout(self, topup_id, amount_micro):
        return {"type": "mock", "pay_url": f"/billing/webhook/mock?topup_id={topup_id}"}

    def verify_webhook(self, headers, payload):
        return payload["topup_id"], payload.get("external_id", "mock-" + payload["topup_id"]), bool(payload.get("paid"))


class NotConfiguredChannel(PaymentChannel):
    LABELS = {"stripe": "Stripe 信用卡", "alipay": "支付宝", "wechat": "微信支付"}
    available = False

    def __init__(self, name):
        self.name = name
        self.label = self.LABELS.get(name, name)

    def create_checkout(self, topup_id, amount_micro):
        raise NotImplementedError(f"支付渠道 {self.name} 尚未接入")

    verify_webhook = create_checkout


def build_channels(enable_mock: bool) -> dict[str, PaymentChannel]:
    ch = {n: NotConfiguredChannel(n) for n in ("stripe", "alipay", "wechat")}
    if enable_mock:
        ch["mock"] = MockChannel()
    return ch
