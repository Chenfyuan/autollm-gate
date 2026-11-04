import * as React from "react";
import { Download, Search, ScrollText } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, NativeSelect } from "@/components/ui/input";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import type { LogItem } from "@/lib/types";
import { dt, num, usd } from "@/lib/utils";

type Resp = { total: number; page: number; size: number; items: LogItem[] };

export function RequestLogs({ base, admin, loginPath }: { base: string; admin?: boolean; loginPath: string }) {
  const [f, setF] = React.useState({ model: "", status: "", start: "", end: "" });
  const [q, setQ] = React.useState(f);
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
  const { data } = useApi<Resp>(`${base}?${params}&page=${page}&size=50`, { loginPath });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <>
      <PageHeader
        title="请求日志"
        desc="逐条查看每次调用的模型、上游、用量、费用与耗时；可按条件筛选并导出 CSV。"
        actions={
          <Button variant="outline" asChild>
            <a href={`${base}?${params}&format=csv`} download>
              <Download /> 导出 CSV
            </a>
          </Button>
        }
      />
      <Card className="mb-4 p-3">
        <form
          className="grid gap-2 sm:grid-cols-[1fr_140px_150px_150px_auto]"
          onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(f); }}
        >
          <Input value={f.model} onChange={set("model")} placeholder="按模型名搜索，例如 gpt-4o" />
          <NativeSelect value={f.status} onChange={set("status")}>
            <option value="">全部状态</option>
            <option value="ok">成功</option>
            <option value="stream_error">流中断</option>
          </NativeSelect>
          <Input type="date" value={f.start} onChange={set("start")} aria-label="开始日期" />
          <Input type="date" value={f.end} onChange={set("end")} aria-label="结束日期" />
          <Button><Search /> 查询</Button>
        </form>
      </Card>
      <Card>
        {!data ? (
          <div className="space-y-2 p-5"><Skeleton className="h-8" /><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
        ) : data.items.length === 0 ? (
          <Empty icon={<ScrollText />} title="没有符合条件的请求" desc="换个筛选条件试试。" />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH className="pl-5">时间</TH>
                  {admin && <TH>租户</TH>}
                  <TH>密钥</TH>
                  <TH>模型</TH>
                  <TH>上游</TH>
                  <TH className="text-right">输入 / 输出</TH>
                  <TH className="text-right">费用</TH>
                  <TH className="text-right">耗时</TH>
                  <TH className="pr-5">状态</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((x) => (
                  <TR key={x.id}>
                    <TD className="whitespace-nowrap pl-5 tabular text-muted-foreground">{dt(x.created_at, true)}</TD>
                    {admin && <TD>{x.tenant_name}</TD>}
                    <TD className="text-muted-foreground">{x.key_name || "—"}</TD>
                    <TD className="font-mono text-xs">{x.model}</TD>
                    <TD>
                      <span className="text-muted-foreground">{x.provider}</span>
                      {x.key_source === "byok" && <Badge variant="outline" className="ml-1.5">自带 Key</Badge>}
                    </TD>
                    <TD className="text-right tabular">{num(x.prompt_tokens)} / {num(x.completion_tokens)}</TD>
                    <TD className="text-right tabular">{usd(x.charge_usd, 6)}</TD>
                    <TD className="text-right tabular text-muted-foreground">{num(x.latency_ms)} ms</TD>
                    <TD className="pr-5">{x.status === "ok" ? <Badge variant="success">成功</Badge> : <Badge variant="outline" className="text-destructive">{x.status}</Badge>}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        )}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t px-5 py-3 text-[13px] text-muted-foreground">
            <span>共 {num(data.total)} 条</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
              <span className="tabular">{page} / {pages}</span>
              <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
