import * as React from "react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PageHeader } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import { PROVIDER_NAMES } from "@/lib/utils";

type M = { model: string; provider: string; context: number; enabled: boolean; price_in: number; price_out: number; default_price_in: number; default_price_out: number };

function Row({ m, markup, onSaved }: { m: M; markup: number; onSaved: () => void }) {
  const [pi, setPi] = React.useState(String(m.price_in));
  const [po, setPo] = React.useState(String(m.price_out));
  const dirty = pi !== String(m.price_in) || po !== String(m.price_out);
  const mult = m.provider === "selfhosted" ? 1 : 1 + markup / 100;
  const save = async (body: object) => {
    await api.patch(`/api/admin/models/${m.model}`, body);
    toast.success(`已更新 ${m.model}`);
    onSaved();
  };
  return (
    <TR className={m.enabled ? "" : "opacity-55"}>
      <TD className="pl-5 font-mono text-[13px] font-medium">{m.model}</TD>
      <TD><Badge variant="outline">{PROVIDER_NAMES[m.provider]}</Badge></TD>
      <TD><Input className="h-8 w-24 text-right tabular" value={pi} onChange={(e) => setPi(e.target.value)} /></TD>
      <TD><Input className="h-8 w-24 text-right tabular" value={po} onChange={(e) => setPo(e.target.value)} /></TD>
      <TD className="text-right tabular text-muted-foreground">${(m.price_in * mult).toFixed(2)} / ${(m.price_out * mult).toFixed(2)}</TD>
      <TD><Switch checked={m.enabled} onCheckedChange={(v) => save({ enabled: v })} /></TD>
      <TD className="pr-5 text-right">
        {dirty && <Button size="sm" onClick={() => save({ price_in: Number(pi), price_out: Number(po) })}>保存</Button>}
      </TD>
    </TR>
  );
}

export function AdminModels() {
  const { data, reload } = useApi<{ markup_pct: number; models: M[] }>("/api/admin/models", { loginPath: "/admin/login" });
  return (
    <>
      <PageHeader title="模型与价格" desc={`上游成本价（美元 / 百万 tokens）。租户售价 = 成本 × (1 + 全局加价 ${data?.markup_pct ?? "–"}%)，自部署模型直接按此价出售。`} />
      <Card>
        <Table>
          <THead>
            <TR>
              <TH className="pl-5">模型</TH><TH>提供方</TH><TH>输入成本</TH><TH>输出成本</TH><TH className="text-right">租户售价（入 / 出）</TH><TH>启用</TH><TH className="pr-5" />
            </TR>
          </THead>
          <TBody>{data?.models.map((m) => <Row key={m.model + m.price_in + m.price_out + m.enabled} m={m} markup={data.markup_pct} onSaved={reload} />)}</TBody>
        </Table>
      </Card>
    </>
  );
}
