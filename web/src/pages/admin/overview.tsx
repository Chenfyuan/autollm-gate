import { Link } from "react-router-dom";
import { Coins, Hash, TrendingUp, Users } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader, Skeleton, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { SpendArea } from "@/components/charts";
import { useApi } from "@/lib/hooks";
import type { Daily, ModelRow, Totals } from "@/lib/types";
import { compact, num, SOURCE_NAMES, usd } from "@/lib/utils";

type O = {
  totals: Totals; month: Totals; today: Totals; series: Daily[]; models: ModelRow[]; tenants: number; balance_usd: number;
  top_tenants: { id: string; name: string; requests: number; charge_usd: number }[];
  by_source: { key_source: string; requests: number; charge_usd: number; cost_usd: number }[];
};

export function AdminOverview() {
  const { data } = useApi<O>("/api/admin/overview", { loginPath: "/admin/login" });
  const margin = data && data.month.charge_usd ? ((data.month.charge_usd - data.month.cost_usd) / data.month.charge_usd) * 100 : 0;
  return (
    <>
      <PageHeader title="运营概览" desc="平台收入、成本与调用量（近 30 天）" />
      {!data ? (
        <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[108px]" />)}</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="本月收入" icon={<Coins />} value={usd(data.month.charge_usd, 2)} sub={`今日 ${usd(data.today.charge_usd, 2)}`} />
          <Stat label="本月毛利" icon={<TrendingUp />} value={usd(data.month.charge_usd - data.month.cost_usd, 2)} sub={`毛利率 ${margin.toFixed(1)}%`} />
          <Stat label="本月请求" icon={<Hash />} value={num(data.month.requests)} sub={`${compact(data.month.tokens)} tokens`} />
          <Stat label="租户" icon={<Users />} value={data.tenants} sub={`预付余额合计 ${usd(data.balance_usd, 2)}`} />
        </div>
      )}
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>每日收入</CardTitle>
            <CardDescription>租户实际扣费金额</CardDescription>
          </CardHeader>
          <CardContent>{data ? <SpendArea data={data.series} name="收入" /> : <Skeleton className="h-[240px]" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>收入最高的租户</CardTitle>
            <CardDescription>近 30 天</CardDescription>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {data && data.top_tenants.length === 0 && <Empty title="暂无数据" />}
            <Table>
              <TBody>
                {data?.top_tenants.map((t, i) => (
                  <TR key={t.id}>
                    <TD className="w-8 pl-5 tabular text-muted-foreground">{i + 1}</TD>
                    <TD>
                      <Link to={`/admin/tenants/${t.id}`} className="font-medium hover:underline">{t.name}</Link>
                      <div className="text-xs text-muted-foreground">{num(t.requests)} 次请求</div>
                    </TD>
                    <TD className="pr-5 text-right tabular font-medium">{usd(t.charge_usd, 2)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>模型收入与成本</CardTitle></CardHeader>
          <CardContent className="px-0 pb-2">
            <Table>
              <THead>
                <TR>
                  <TH className="pl-5">模型</TH>
                  <TH className="text-right">请求</TH>
                  <TH className="text-right">收入</TH>
                  <TH className="text-right">上游成本</TH>
                  <TH className="pr-5 text-right">平均延迟</TH>
                </TR>
              </THead>
              <TBody>
                {data?.models.map((m) => (
                  <TR key={m.model}>
                    <TD className="pl-5 font-medium">{m.model}</TD>
                    <TD className="text-right tabular">{num(m.requests)}</TD>
                    <TD className="text-right tabular">{usd(m.charge_usd)}</TD>
                    <TD className="text-right tabular text-muted-foreground">{usd(m.cost_usd)}</TD>
                    <TD className="pr-5 text-right tabular text-muted-foreground">{(m.avg_latency_ms / 1000).toFixed(2)}s</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>计费来源</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {data?.by_source.map((s) => {
              const pct = data.totals.charge_usd ? (s.charge_usd / data.totals.charge_usd) * 100 : 0;
              return (
                <div key={s.key_source}>
                  <div className="flex justify-between text-[13px]">
                    <span>{SOURCE_NAMES[s.key_source] || s.key_source}</span>
                    <span className="tabular text-muted-foreground">{usd(s.charge_usd, 2)} · {num(s.requests)} 次</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-muted">
                    <div className="h-full rounded-full bg-[hsl(var(--chart-1))]" style={{ width: `${Math.max(pct, 1)}%` }} />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
