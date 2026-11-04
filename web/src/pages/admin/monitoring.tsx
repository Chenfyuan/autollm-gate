import { BellRing, CircleAlert, Info, TriangleAlert } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Dot } from "@/components/ui/badge";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { Lines } from "@/components/charts";
import { useApi } from "@/lib/hooks";
import { cn, dt, num, PROVIDER_NAMES } from "@/lib/utils";

type P = {
  provider: string; configured: boolean; breaker: { state: string; failures: number }; req: number; err: number; error_rate: number;
  avg_ms: number | null; p50_ms: number | null; p95_ms: number | null; series: { t: number; req: number; err: number }[];
};
type Alert = { id: number; kind: string; severity: string; title: string; message: string; delivered: boolean; delivery_error: string; created_at: string };
type Mon = { minutes: number; state_backend: string; providers: P[]; alerts: Alert[] };

const BREAKER: Record<string, { t: string; v: "success" | "warning" | "destructive" }> = {
  closed: { t: "正常", v: "success" },
  half_open: { t: "探测恢复中", v: "warning" },
  open: { t: "已熔断", v: "destructive" },
};
const ms = (v: number | null) => (v == null ? "—" : v >= 1000 ? `≤${v / 1000}s` : `≤${v}ms`);

export function AdminMonitoring() {
  const { data } = useApi<Mon>("/api/admin/monitoring?minutes=30", { loginPath: "/admin/login", refreshMs: 10000 });
  const providers = data?.providers.filter((p) => p.configured || p.req > 0) ?? [];
  const chart =
    data && providers.length
      ? providers[0].series.map((_, i) => {
          const row: Record<string, number | string> = { label: new Date(providers[0].series[i].t * 1000).toTimeString().slice(0, 5) };
          providers.forEach((p) => {
            row[p.provider] = p.series[i].req;
            row[p.provider + "_err"] = p.series[i].err;
          });
          return row;
        })
      : [];
  const totalReq = providers.reduce((a, p) => a + p.req, 0);
  const totalErr = providers.reduce((a, p) => a + p.err, 0);
  return (
    <>
      <PageHeader
        title="监控告警"
        desc={<>最近 30 分钟上游健康状况，每 10 秒自动刷新 · 监控数据汇总自所有实例（{data?.state_backend === "redis" ? "Redis" : "单进程内存"}）</>}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <div className="text-[13px] text-muted-foreground">上游调用</div>
          <div className="mt-2 text-2xl font-semibold tabular">{num(totalReq)}</div>
        </Card>
        <Card className="p-5">
          <div className="text-[13px] text-muted-foreground">失败次数</div>
          <div className={cn("mt-2 text-2xl font-semibold tabular", totalErr > 0 && "text-destructive")}>{num(totalErr)}</div>
        </Card>
        <Card className="p-5">
          <div className="text-[13px] text-muted-foreground">整体成功率</div>
          <div className="mt-2 text-2xl font-semibold tabular">{totalReq ? (((totalReq - totalErr) / totalReq) * 100).toFixed(2) : "100.00"}%</div>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>各上游状态</CardTitle>
          <CardDescription>熔断：连续失败达到阈值后暂停调用该上游，冷却后放行一个探测请求，成功即恢复</CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {!data ? (
            <div className="px-5"><Skeleton className="h-32" /></div>
          ) : providers.length === 0 ? (
            <Empty title="暂无上游调用" desc="配置上游密钥并产生调用后，这里会显示各上游的错误率与延迟。" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH className="pl-5">上游</TH><TH>熔断器</TH><TH className="text-right">调用</TH><TH className="text-right">失败</TH>
                  <TH className="text-right">错误率</TH><TH className="text-right">平均延迟</TH><TH className="text-right">P50</TH><TH className="pr-5 text-right">P95</TH>
                </TR>
              </THead>
              <TBody>
                {providers.map((p) => (
                  <TR key={p.provider}>
                    <TD className="pl-5 font-medium">{PROVIDER_NAMES[p.provider] || p.provider}</TD>
                    <TD><Badge variant={BREAKER[p.breaker.state]?.v}><Dot /> {BREAKER[p.breaker.state]?.t}</Badge></TD>
                    <TD className="text-right tabular">{num(p.req)}</TD>
                    <TD className="text-right tabular">{num(p.err)}</TD>
                    <TD className={cn("text-right tabular font-medium", p.error_rate >= 0.2 ? "text-destructive" : p.error_rate > 0.05 ? "text-warning" : "")}>
                      {(p.error_rate * 100).toFixed(1)}%
                    </TD>
                    <TD className="text-right tabular text-muted-foreground">{p.avg_ms == null ? "—" : `${p.avg_ms}ms`}</TD>
                    <TD className="text-right tabular text-muted-foreground">{ms(p.p50_ms)}</TD>
                    <TD className="pr-5 text-right tabular text-muted-foreground">{ms(p.p95_ms)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>每分钟调用量</CardTitle></CardHeader>
          <CardContent>{chart.length ? <Lines data={chart} lines={providers.map((p) => ({ key: p.provider, name: PROVIDER_NAMES[p.provider] }))} /> : <Skeleton className="h-[220px]" />}</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>每分钟失败数</CardTitle></CardHeader>
          <CardContent>{chart.length ? <Lines data={chart} lines={providers.map((p) => ({ key: p.provider + "_err", name: PROVIDER_NAMES[p.provider] }))} /> : <Skeleton className="h-[220px]" />}</CardContent>
        </Card>
      </div>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>告警记录</CardTitle>
          <CardDescription>上游错误率突增、租户余额不足、月度额度即将用尽时触发，阈值与 Webhook 在「计费与告警设置」中配置</CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {data && data.alerts.length === 0 ? (
            <Empty icon={<BellRing />} title="暂无告警" desc="一切正常。" />
          ) : (
            <div className="divide-y">
              {data?.alerts.map((a) => (
                <div key={a.id} className="flex gap-3 px-5 py-3.5">
                  <div className="mt-0.5">
                    {a.severity === "critical" ? <CircleAlert className="size-4 text-destructive" /> : a.severity === "info" ? <Info className="size-4 text-muted-foreground" /> : <TriangleAlert className="size-4 text-warning" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{a.title}</span>
                      {a.delivered ? <Badge variant="success">已推送</Badge> : a.delivery_error ? <Badge variant="destructive" title={a.delivery_error}>推送失败</Badge> : <Badge variant="outline">未配置推送</Badge>}
                    </div>
                    <div className="mt-0.5 text-[13px] text-muted-foreground">{a.message}</div>
                  </div>
                  <div className="shrink-0 text-xs tabular text-muted-foreground">{dt(a.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}
