import * as React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useApi } from "@/lib/hooks";
import type { PublicModel } from "@/lib/types";
import { PROVIDER_NAMES } from "@/lib/utils";

const price = (v: number) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

export function ConsoleModels() {
  const { data } = useApi<{ markup_pct: number; models: PublicModel[] }>("/api/models");
  const [q, setQ] = React.useState("");
  const rows = (data?.models ?? []).filter((m) => (m.model + m.provider).toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <PageHeader title="模型与价格" desc="价格单位：美元 / 百万 tokens。model 填 auto 时由网关按任务自动选择最合适的模型。" actions={<Input className="w-56" placeholder="搜索模型" value={q} onChange={(e) => setQ(e.target.value)} />} />
      <Card className="mb-4 grid gap-4 p-5 sm:grid-cols-4">
        {[
          ["auto", "默认，成本优先"],
          ["auto:balanced", "质量与成本平衡"],
          ["auto:quality_first", "质量优先"],
          ["auto:latency_critical", "速度优先"],
        ].map(([id, d]) => (
          <div key={id}>
            <code className="font-mono text-[13px] font-medium">{id}</code>
            <div className="mt-1 text-xs text-muted-foreground">{d}</div>
          </div>
        ))}
      </Card>
      <Card>
        <Table>
          <THead>
            <TR>
              <TH className="pl-5">模型</TH>
              <TH>提供方</TH>
              <TH className="text-right">上下文</TH>
              <TH className="text-right">输入价格</TH>
              <TH className="pr-5 text-right">输出价格</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((m) => (
              <TR key={m.model}>
                <TD className="pl-5 font-mono text-[13px] font-medium">{m.model}</TD>
                <TD>
                  <Badge variant="outline">{PROVIDER_NAMES[m.provider] || m.provider}</Badge>
                </TD>
                <TD className="text-right tabular text-muted-foreground">{m.context >= 1000000 ? `${m.context / 1000000}M` : `${Math.round(m.context / 1000)}K`}</TD>
                <TD className="text-right tabular">{price(m.price_in)}</TD>
                <TD className="pr-5 text-right tabular">{price(m.price_out)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </>
  );
}
