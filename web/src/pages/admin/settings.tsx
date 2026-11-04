import * as React from "react";
import { Send } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";

type S = {
  platform_markup_pct: number; byok_fee_per_request_usd: number; byok_fee_per_1k_tokens_usd: number; alert_enabled: boolean; alert_webhook_url: string;
  alert_webhook_format: string; alert_error_rate_pct: number; alert_min_requests: number; alert_low_balance_usd: number; alert_quota_pct: number;
  alert_cooldown_minutes: number; mock_payment: boolean; env: string;
};

export function AdminSettings() {
  const { data, reload } = useApi<S>("/api/admin/settings", { loginPath: "/admin/login" });
  const [f, setF] = React.useState<S | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => setF(data), [data]);
  if (!f) return <Skeleton className="h-96" />;
  const set = (k: keyof S) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    setErr(null);
    setSaving(true);
    try {
      const { mock_payment: _m, env: _e, ...body } = f;
      const numeric = Object.fromEntries(Object.entries(body).map(([k, v]) => [k, typeof v === "string" && k !== "alert_webhook_url" && k !== "alert_webhook_format" ? Number(v) : v]));
      await api.put("/api/admin/settings", numeric);
      toast.success("设置已保存，已同步到所有实例");
      reload();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const test = async () => {
    await save();
    const r = await api.post<{ delivered: boolean; error: string }>("/api/admin/alerts/test");
    r.delivered ? toast.success("测试告警已送达") : toast.error(`推送失败：${r.error || "未配置 Webhook"}`);
  };
  return (
    <>
      <PageHeader
        title="计费与告警设置"
        desc="修改后立即生效，并通过 Redis 广播同步到所有网关实例"
        actions={<Button onClick={save} disabled={saving}>{saving ? "保存中…" : "保存更改"}</Button>}
      />
      <ErrorNote msg={err} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>计费</CardTitle>
            <CardDescription>平台统一密钥按「上游成本 ×（1 + 加价）」向租户收费</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5">
            <Field label="全局加价（%）" hint="租户详情页可单独覆盖"><Input type="number" min={0} value={f.platform_markup_pct} onChange={set("platform_markup_pct")} /></Field>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="自带密钥 · 每次请求服务费（美元）"><Input type="number" min={0} step="0.0001" value={f.byok_fee_per_request_usd} onChange={set("byok_fee_per_request_usd")} /></Field>
              <Field label="自带密钥 · 每千 tokens 服务费（美元）"><Input type="number" min={0} step="0.0001" value={f.byok_fee_per_1k_tokens_usd} onChange={set("byok_fee_per_1k_tokens_usd")} /></Field>
            </div>
            <div className="flex items-center justify-between rounded-md border p-3 text-[13px]">
              <div>
                <div className="font-medium">模拟支付</div>
                <div className="text-xs text-muted-foreground">仅用于测试环境，生产环境开启会拒绝启动</div>
              </div>
              <Badge variant={f.mock_payment ? "warning" : "outline"}>{f.mock_payment ? "已开启" : "已关闭"}</Badge>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-start justify-between">
            <div className="space-y-1">
              <CardTitle>告警</CardTitle>
              <CardDescription>同一告警在冷却时间内只推送一次</CardDescription>
            </div>
            <Switch checked={f.alert_enabled} onCheckedChange={(v) => setF({ ...f, alert_enabled: v })} />
          </CardHeader>
          <CardContent className="grid gap-5">
            <div className="grid gap-5 sm:grid-cols-[1fr_140px]">
              <Field label="Webhook 地址"><Input value={f.alert_webhook_url} onChange={set("alert_webhook_url")} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/…" /></Field>
              <Field label="消息格式">
                <NativeSelect value={f.alert_webhook_format} onChange={set("alert_webhook_format")}>
                  <option value="generic">通用 JSON</option>
                  <option value="feishu">飞书</option>
                  <option value="wecom">企业微信</option>
                  <option value="dingtalk">钉钉</option>
                  <option value="slack">Slack</option>
                </NativeSelect>
              </Field>
            </div>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="上游错误率阈值（%）" hint="最近 5 分钟"><Input type="number" value={f.alert_error_rate_pct} onChange={set("alert_error_rate_pct")} /></Field>
              <Field label="最少请求数" hint="请求太少时不判定"><Input type="number" value={f.alert_min_requests} onChange={set("alert_min_requests")} /></Field>
              <Field label="余额不足阈值（美元）"><Input type="number" value={f.alert_low_balance_usd} onChange={set("alert_low_balance_usd")} /></Field>
              <Field label="月度额度使用率（%）"><Input type="number" value={f.alert_quota_pct} onChange={set("alert_quota_pct")} /></Field>
              <Field label="冷却时间（分钟）"><Input type="number" value={f.alert_cooldown_minutes} onChange={set("alert_cooldown_minutes")} /></Field>
            </div>
            <div>
              <Button variant="outline" onClick={test}><Send /> 发送测试告警</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
