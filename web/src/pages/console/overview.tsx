import { Link } from "react-router-dom";
import { ArrowUpRight, Coins, Hash, KeyRound, Wallet } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, Skeleton, Stat } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { SpendArea } from "@/components/charts";
import { useApi } from "@/lib/hooks";
import type { BillItem, Daily, ModelRow, TenantBrief, Totals } from "@/lib/types";
import { CodeBlock } from "@/components/ui/misc";
import { compact, dt, num, usd } from "@/lib/utils";

type Overview = { tenant: TenantBrief; month: Totals; today: Totals; series: Daily[]; models: ModelRow[]; active_keys: number };

export function ConsoleOverview() {
  const { data } = useApi<Overview>("/api/console/overview", { loginPath: "/login" });
  const recent = useApi<{ items: BillItem[] }>("/api/console/billing?size=6");
  const total30 = data?.series.reduce((a, d) => a + d.charge_usd, 0) ?? 0;
  return (
    <>
      <PageHeader
        title={data ? `你好，${data.tenant.name}` : "概览"}
        desc="最近 30 天的调用与消费情况"
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/console/docs">接入文档</Link>
            </Button>
            <Button asChild>
              <Link to="/console/topup">充值</Link>
            </Button>
          </>
        }
      />
      {!data ? (
        <div className="grid gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[108px]" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="可用余额" icon={<Wallet />} value={usd(data.tenant.balance_usd, 2)} sub={data.tenant.reserved_usd ? `另有 ${usd(data.tenant.reserved_usd)} 正在结算中` : "按实际用量扣费"} />
          <Stat label="本月消费" icon={<Coins />} value={usd(data.month.charge_usd, 2)} sub={`今日 ${usd(data.today.charge_usd)}`} />
          <Stat label="本月请求" icon={<Hash />} value={num(data.month.requests)} sub={`共 ${compact(data.month.tokens)} tokens`} />
          <Stat label="有效密钥" icon={<KeyRound />} value={data.active_keys} sub={<Link to="/console/keys" className="hover:text-foreground">管理密钥 →</Link>} />
        </div>
      )}
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-start justify-between">
            <div className="space-y-1">
              <CardTitle>每日消费</CardTitle>
              <CardDescription>近 30 天合计 {usd(total30, 2)}</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/console/usage">
                详细分析 <ArrowUpRight />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>{data ? <SpendArea data={data.series} /> : <Skeleton className="h-[240px]" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>常用模型</CardTitle>
            <CardDescription>按近 30 天消费排序</CardDescription>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {data && data.models.length === 0 && <Empty title="还没有调用记录" desc="创建密钥并发出第一个请求后，这里会显示模型用量。" />}
            {data && data.models.length > 0 && (
              <Table>
                <THead>
                  <TR>
                    <TH className="pl-5">模型</TH>
                    <TH className="text-right">请求</TH>
                    <TH className="pr-5 text-right">消费</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.models.map((m) => (
                    <TR key={m.model}>
                      <TD className="pl-5 font-medium">{m.model}</TD>
                      <TD className="text-right tabular text-muted-foreground">{num(m.requests)}</TD>
                      <TD className="pr-5 text-right tabular">{usd(m.charge_usd)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-start justify-between">
            <div className="space-y-1">
              <CardTitle>最近调用</CardTitle>
              <CardDescription>每次请求实际使用的模型与费用</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/console/billing">
                全部账单 <ArrowUpRight />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            {recent.data && recent.data.items.length === 0 ? (
              <Empty title="还没有调用记录" />
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH className="pl-5">时间</TH>
                    <TH>模型</TH>
                    <TH>密钥</TH>
                    <TH className="text-right">tokens</TH>
                    <TH className="pr-5 text-right">费用</TH>
                  </TR>
                </THead>
                <TBody>
                  {recent.data?.items.map((x) => (
                    <TR key={x.id}>
                      <TD className="pl-5 tabular text-muted-foreground">{dt(x.created_at)}</TD>
                      <TD className="font-medium">{x.model}</TD>
                      <TD className="text-muted-foreground">{x.key_name}</TD>
                      <TD className="text-right tabular">{num(x.prompt_tokens + x.completion_tokens)}</TD>
                      <TD className="pr-5 text-right tabular">{usd(x.charge_usd)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>接入只需一步</CardTitle>
            <CardDescription>把 Base URL 指向网关，model 填 auto</CardDescription>
          </CardHeader>
          <CardContent>
            <CodeBlock code={`from openai import OpenAI\n\nclient = OpenAI(\n  base_url="${window.location.origin}/v1",\n  api_key="sk-lr-…",\n)\nclient.chat.completions.create(\n  model="auto", messages=[…])`} />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
