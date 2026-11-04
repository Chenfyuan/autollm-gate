import * as React from "react";
import { ChevronLeft, ChevronRight, ReceiptText } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import type { BillItem } from "@/lib/types";
import { dt, num, SOURCE_NAMES, usd } from "@/lib/utils";

export function ConsoleBilling() {
  const [page, setPage] = React.useState(1);
  const size = 20;
  const { data } = useApi<{ total: number; items: BillItem[] }>(`/api/console/billing?page=${page}&size=${size}`, { loginPath: "/login" });
  const pages = data ? Math.max(1, Math.ceil(data.total / size)) : 1;
  return (
    <>
      <PageHeader title="账单明细" desc="每一次调用的模型、token 与费用，按时间倒序" />
      <Card>
        {!data ? (
          <div className="space-y-2 p-5">
            {[...Array(8)].map((_, i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <Empty icon={<ReceiptText />} title="暂无账单" desc="发出第一个 API 请求后，这里会出现逐条计费记录。" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="pl-5">时间</TH>
                <TH>模型</TH>
                <TH>密钥</TH>
                <TH>计费方式</TH>
                <TH className="text-right">输入</TH>
                <TH className="text-right">输出</TH>
                <TH className="text-right">耗时</TH>
                <TH className="pr-5 text-right">费用</TH>
              </TR>
            </THead>
            <TBody>
              {data.items.map((x) => (
                <TR key={x.id}>
                  <TD className="pl-5 tabular text-muted-foreground">{dt(x.created_at, true)}</TD>
                  <TD className="font-medium">{x.model}</TD>
                  <TD>{x.key_name}</TD>
                  <TD>
                    <Badge variant={x.key_source === "byok" ? "info" : "default"}>{SOURCE_NAMES[x.key_source] || x.key_source}</Badge>
                  </TD>
                  <TD className="text-right tabular">{num(x.prompt_tokens)}</TD>
                  <TD className="text-right tabular">{num(x.completion_tokens)}</TD>
                  <TD className="text-right tabular text-muted-foreground">{(x.latency_ms / 1000).toFixed(2)}s</TD>
                  <TD className="pr-5 text-right tabular font-medium">{usd(x.charge_usd, 6)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t px-5 py-3 text-[13px] text-muted-foreground">
            <span>共 {num(data.total)} 条</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" className="size-8" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft />
              </Button>
              <span className="tabular">
                {page} / {pages}
              </span>
              <Button variant="outline" size="icon" className="size-8" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
