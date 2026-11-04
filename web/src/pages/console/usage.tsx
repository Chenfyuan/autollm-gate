import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader, Skeleton, Stat } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { Legend, SpendArea, StackedBars } from "@/components/charts";
import { useApi } from "@/lib/hooks";
import type { Daily, ModelRow, Totals } from "@/lib/types";
import { CHART_COLORS, compact, num, usd } from "@/lib/utils";

type Usage = { daily: Daily[]; by_model_daily: { models: string[]; series: any[] }; models: ModelRow[]; totals: Totals };

export function ConsoleUsage() {
  const [days, setDays] = React.useState("30");
  const { data } = useApi<Usage>(`/api/console/usage?days=${days}`, { loginPath: "/login" });
  const totalCharge = data?.totals.charge_usd || 0;
  return (
    <>
      <PageHeader
        title="用量分析"
        desc="按天、按模型查看调用量与费用"
        actions={
          <Tabs value={days} onValueChange={setDays}>
            <TabsList>
              <TabsTrigger value="7">7 天</TabsTrigger>
              <TabsTrigger value="30">30 天</TabsTrigger>
              <TabsTrigger value="90">90 天</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="总消费" value={data ? usd(data.totals.charge_usd, 2) : "—"} />
        <Stat label="总请求" value={data ? num(data.totals.requests) : "—"} />
        <Stat label="总 tokens" value={data ? compact(data.totals.tokens) : "—"} />
      </div>
      <Card className="mt-4">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle>按模型的每日消费</CardTitle>
            <CardDescription>堆叠显示每个模型的花费</CardDescription>
          </div>
          {data && <Legend keys={data.by_model_daily.models} />}
        </CardHeader>
        <CardContent>{data ? <StackedBars data={data.by_model_daily.series} keys={data.by_model_daily.models} /> : <Skeleton className="h-[280px]" />}</CardContent>
      </Card>
      <div className="mt-4 grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>每日请求数</CardTitle>
          </CardHeader>
          <CardContent>{data ? <SpendArea data={data.daily} dataKey="requests" name="请求" money={false} height={220} /> : <Skeleton className="h-[220px]" />}</CardContent>
        </Card>
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>模型明细</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {data && data.models.length === 0 ? (
              <Empty title="这段时间没有调用" />
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH className="pl-5">模型</TH>
                    <TH className="text-right">请求</TH>
                    <TH className="text-right">输入 / 输出 tokens</TH>
                    <TH className="text-right">平均延迟</TH>
                    <TH className="pr-5 text-right">消费</TH>
                  </TR>
                </THead>
                <TBody>
                  {data?.models.map((m, i) => (
                    <TR key={m.model}>
                      <TD className="pl-5">
                        <div className="flex items-center gap-2 font-medium">
                          <span className="size-2 rounded-sm" style={{ background: CHART_COLORS[data.by_model_daily.models.indexOf(m.model) % CHART_COLORS.length] ?? CHART_COLORS[i] }} />
                          {m.model}
                        </div>
                      </TD>
                      <TD className="text-right tabular">{num(m.requests)}</TD>
                      <TD className="text-right tabular text-muted-foreground">
                        {compact(m.prompt_tokens)} / {compact(m.completion_tokens)}
                      </TD>
                      <TD className="text-right tabular text-muted-foreground">{(m.avg_latency_ms / 1000).toFixed(2)} 秒</TD>
                      <TD className="pr-5 text-right tabular">
                        {usd(m.charge_usd)}
                        <span className="ml-1.5 text-xs text-muted-foreground">{totalCharge ? Math.round((m.charge_usd / totalCharge) * 100) : 0}%</span>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
