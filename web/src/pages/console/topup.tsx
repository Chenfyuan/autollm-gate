import * as React from "react";
import { CreditCard } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ErrorNote, PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import type { Topup } from "@/lib/types";
import { cn, dt, usd } from "@/lib/utils";
import { MeContext } from "./layout";

type Channel = { id: string; name: string; available: boolean };
const PRESETS = [10, 50, 100, 500];
export const STATUS: Record<string, { t: string; v: "success" | "warning" | "destructive" }> = {
  paid: { t: "已到账", v: "success" },
  pending: { t: "待支付", v: "warning" },
  failed: { t: "失败", v: "destructive" },
};
export const CHANNEL_NAMES: Record<string, string> = { manual: "人工入账", stripe: "Stripe", alipay: "支付宝", wechat: "微信支付", mock: "模拟支付" };

export function ConsoleTopup() {
  const { me, reload: reloadMe } = React.useContext(MeContext);
  const { data, reload } = useApi<{ items: Topup[]; channels: Channel[] }>("/api/console/topups", { loginPath: "/login" });
  const [amount, setAmount] = React.useState("50");
  const [channel, setChannel] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const ch = channel ?? data?.channels.find((c) => c.available)?.id ?? null;

  const pay = async () => {
    setErr(null);
    setBusy(true);
    try {
      const t = await api.post<Topup>("/api/console/topups", { amount_usd: Number(amount), channel: ch });
      if (ch === "mock") {
        await api.post(`/api/console/topups/${t.id}/mock-pay`);
        toast.success(`已充值 ${usd(Number(amount), 2)}（模拟支付）`);
      }
      reload();
      reloadMe();
    } catch (x) {
      setErr((x as Error).message);
      reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="余额充值" desc="预付费模式：先充值，调用时按实际 token 扣费，余额不会被扣成负数。" />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>当前余额</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight tabular">{usd(me?.tenant.balance_usd, 2)}</div>
            {!!me?.tenant.reserved_usd && <p className="mt-1 text-xs text-muted-foreground">另有 {usd(me.tenant.reserved_usd)} 正在结算中</p>}
            <p className="mt-4 text-[13px] leading-relaxed text-muted-foreground">
              每次请求前会按所选模型的最高价预先冻结一小笔金额，请求完成后按实际用量结算并退回多余部分。
            </p>
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>充值金额</CardTitle>
            <CardDescription>单位：美元</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid grid-cols-4 gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  onClick={() => setAmount(String(p))}
                  className={cn("h-10 rounded-md border text-sm font-medium tabular transition-colors hover:bg-accent", amount === String(p) && "border-foreground bg-accent")}
                >
                  ${p}
                </button>
              ))}
            </div>
            <Input type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="自定义金额" />
            <div className="space-y-2">
              <div className="text-[13px] font-medium">支付方式</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {data?.channels.map((c) => (
                  <button
                    key={c.id}
                    disabled={!c.available}
                    onClick={() => setChannel(c.id)}
                    className={cn(
                      "flex h-10 items-center justify-between rounded-md border px-3 text-[13px] transition-colors enabled:hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
                      ch === c.id && "border-foreground bg-accent",
                    )}
                  >
                    <span>{c.name}</span>
                    {!c.available && <span className="text-xs text-muted-foreground">即将开通</span>}
                  </button>
                ))}
              </div>
            </div>
            <ErrorNote msg={err} />
            <Button className="w-full" disabled={busy || !ch || !(Number(amount) > 0)} onClick={pay}>
              {busy ? "处理中…" : `支付 ${usd(Number(amount) || 0, 2)}`}
            </Button>
            {!data?.channels.some((c) => c.available) && <p className="text-xs text-muted-foreground">在线支付尚未开通，如需充值请联系平台管理员人工入账。</p>}
          </CardContent>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>充值记录</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {data && data.items.length === 0 ? (
            <Empty icon={<CreditCard />} title="还没有充值记录" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH className="pl-5">时间</TH>
                  <TH>方式</TH>
                  <TH>状态</TH>
                  <TH>备注</TH>
                  <TH className="pr-5 text-right">金额</TH>
                </TR>
              </THead>
              <TBody>
                {data?.items.map((t) => (
                  <TR key={t.id}>
                    <TD className="pl-5 tabular text-muted-foreground">{dt(t.created_at)}</TD>
                    <TD>{CHANNEL_NAMES[t.channel] || t.channel}</TD>
                    <TD>
                      <Badge variant={STATUS[t.status]?.v}>{STATUS[t.status]?.t || t.status}</Badge>
                    </TD>
                    <TD className="max-w-[280px] truncate text-muted-foreground">{t.note || "—"}</TD>
                    <TD className="pr-5 text-right tabular font-medium">{usd(t.amount_usd, 2)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
