import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Plus } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, Dot } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { CopyButton, ErrorNote, PageHeader, Skeleton, Stat } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { SpendArea } from "@/components/charts";
import { KeysTable } from "../console/keys";
import { CHANNEL_NAMES, STATUS } from "../console/topup";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import type { ApiKey, Daily, ModelRow, Topup, Totals } from "@/lib/types";
import { compact, dt, num, PROVIDER_NAMES, relTime, SOURCE_NAMES, usd } from "@/lib/utils";

type Detail = {
  id: string; name: string; balance_usd: number; reserved_usd: number; active: boolean; created_at: string; markup_pct: number | null;
  rpm_limit: number | null; monthly_token_limit: number | null; users: { email: string; name: string; last_login_at: string | null }[];
  keys: ApiKey[]; topups: Topup[]; byok: { id: string; provider: string; masked: string }[]; series: Daily[]; models: ModelRow[]; month: Totals;
  recent: { id: number; created_at: string; model: string; key_name: string; prompt_tokens: number; completion_tokens: number; charge_usd: number; key_source: string; latency_ms: number }[];
};

export function AdminTenantDetail() {
  const { id } = useParams();
  const { data, reload } = useApi<Detail>(`/api/admin/tenants/${id}`, { loginPath: "/admin/login" });
  const [topup, setTopup] = React.useState(false);
  const [amount, setAmount] = React.useState("10");
  const [note, setNote] = React.useState("");
  const [form, setForm] = React.useState<{ name: string; markup: string; rpm: string; limit: string } | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [newKey, setNewKey] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (data) setForm({ name: data.name, markup: data.markup_pct?.toString() ?? "", rpm: data.rpm_limit?.toString() ?? "", limit: data.monthly_token_limit?.toString() ?? "" });
  }, [data]);
  if (!data || !form) return <Skeleton className="h-96" />;

  const save = async () => {
    setErr(null);
    try {
      await api.patch(`/api/admin/tenants/${id}`, {
        name: form.name,
        markup_pct: form.markup === "" ? null : Number(form.markup),
        rpm_limit: form.rpm === "" ? null : Number(form.rpm),
        monthly_token_limit: form.limit === "" ? null : Number(form.limit),
      });
      toast.success("已保存");
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const doTopup = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.post(`/api/admin/tenants/${id}/topups`, { amount_usd: Number(amount), note });
    toast.success(`已为「${data.name}」入账 ${usd(Number(amount), 2)}`);
    setTopup(false);
    setNote("");
    reload();
  };
  const toggleActive = async (v: boolean) => {
    await api.patch(`/api/admin/tenants/${id}`, { active: v });
    toast.success(v ? "已启用" : "已停用，该租户所有密钥将无法调用");
    reload();
  };
  const createKey = async () => {
    const k = await api.post<ApiKey>(`/api/admin/tenants/${id}/keys`, { name: "后台创建" });
    setNewKey(k.api_key || null);
    reload();
  };
  const revoke = async (k: ApiKey) => {
    await api.del(`/api/admin/keys/${k.id}`);
    toast.success("已吊销");
    reload();
  };

  return (
    <>
      <Link to="/admin/tenants" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> 租户列表
      </Link>
      <PageHeader
        title={data.name}
        desc={
          <span className="flex items-center gap-2">
            {data.active ? <Badge variant="success"><Dot /> 正常</Badge> : <Badge variant="outline">已停用</Badge>}
            <span>{data.users[0]?.email || "后台创建"} · 注册于 {dt(data.created_at).slice(0, 10)}</span>
          </span>
        }
        actions={<Button onClick={() => setTopup(true)}><Plus /> 人工入账</Button>}
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="可用余额" value={usd(data.balance_usd, 2)} sub={data.reserved_usd ? `结算中 ${usd(data.reserved_usd)}` : "无进行中请求"} />
        <Stat label="本月消费" value={usd(data.month.charge_usd, 2)} sub={`上游成本 ${usd(data.month.cost_usd, 2)}`} />
        <Stat label="本月请求" value={num(data.month.requests)} sub={`${compact(data.month.tokens)} tokens`} />
        <Stat label="有效密钥" value={data.keys.filter((k) => k.active).length} sub={`最近登录 ${relTime(data.users[0]?.last_login_at)}`} />
      </div>
      <Tabs defaultValue="usage" className="mt-6">
        <TabsList>
          <TabsTrigger value="usage">用量</TabsTrigger>
          <TabsTrigger value="keys">密钥</TabsTrigger>
          <TabsTrigger value="topups">充值记录</TabsTrigger>
          <TabsTrigger value="settings">设置</TabsTrigger>
        </TabsList>
        <TabsContent value="usage" className="space-y-4">
          <Card>
            <CardHeader><CardTitle>近 30 天消费</CardTitle></CardHeader>
            <CardContent><SpendArea data={data.series} height={200} /></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>最近调用</CardTitle></CardHeader>
            <CardContent className="px-0 pb-2">
              {data.recent.length === 0 ? <Empty title="暂无调用" /> : (
                <Table>
                  <THead><TR><TH className="pl-5">时间</TH><TH>模型</TH><TH>密钥</TH><TH>计费方式</TH><TH className="text-right">tokens（入/出）</TH><TH className="pr-5 text-right">费用</TH></TR></THead>
                  <TBody>
                    {data.recent.map((r) => (
                      <TR key={r.id}>
                        <TD className="pl-5 tabular text-muted-foreground">{dt(r.created_at, true)}</TD>
                        <TD className="font-medium">{r.model}</TD>
                        <TD>{r.key_name}</TD>
                        <TD><Badge>{SOURCE_NAMES[r.key_source] || r.key_source}</Badge></TD>
                        <TD className="text-right tabular">{num(r.prompt_tokens)} / {num(r.completion_tokens)}</TD>
                        <TD className="pr-5 text-right tabular">{usd(r.charge_usd, 6)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="keys">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div className="space-y-1"><CardTitle>API 密钥</CardTitle><CardDescription>租户也可在自己的控制台管理</CardDescription></div>
              <Button variant="outline" size="sm" onClick={createKey}><Plus /> 代为创建</Button>
            </CardHeader>
            <CardContent className="px-0 pb-2">
              {data.keys.length ? <KeysTable keys={data.keys} onRevoke={revoke} /> : <Empty title="暂无密钥" />}
            </CardContent>
          </Card>
          {data.byok.length > 0 && (
            <Card className="mt-4">
              <CardHeader><CardTitle>自带上游密钥（BYOK）</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {data.byok.map((b) => (
                  <div key={b.id} className="flex justify-between text-[13px]"><span>{PROVIDER_NAMES[b.provider]}</span><code className="font-mono text-muted-foreground">{b.masked}</code></div>
                ))}
              </CardContent>
            </Card>
          )}
        </TabsContent>
        <TabsContent value="topups">
          <Card>
            {data.topups.length === 0 ? <Empty title="暂无充值" /> : (
              <Table>
                <THead><TR><TH className="pl-5">时间</TH><TH>方式</TH><TH>状态</TH><TH>备注</TH><TH className="pr-5 text-right">金额</TH></TR></THead>
                <TBody>
                  {data.topups.map((t) => (
                    <TR key={t.id}>
                      <TD className="pl-5 tabular text-muted-foreground">{dt(t.created_at)}</TD>
                      <TD>{CHANNEL_NAMES[t.channel] || t.channel}</TD>
                      <TD><Badge variant={STATUS[t.status]?.v}>{STATUS[t.status]?.t}</Badge></TD>
                      <TD className="text-muted-foreground">{t.note || "—"}</TD>
                      <TD className="pr-5 text-right tabular font-medium">{usd(t.amount_usd, 2)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>
        </TabsContent>
        <TabsContent value="settings">
          <Card>
            <CardContent className="grid max-w-2xl gap-5 pt-5 sm:grid-cols-2">
              <Field label="租户名称"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="专属加价（%）" hint="留空则使用全局加价"><Input type="number" value={form.markup} onChange={(e) => setForm({ ...form, markup: e.target.value })} /></Field>
              <Field label="每个密钥每分钟请求上限" hint="留空使用系统默认（600）"><Input type="number" value={form.rpm} onChange={(e) => setForm({ ...form, rpm: e.target.value })} /></Field>
              <Field label="每月 token 额度" hint="留空表示不限"><Input type="number" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} /></Field>
              <div className="flex items-center justify-between rounded-md border p-3 sm:col-span-2">
                <div><div className="text-[13px] font-medium">启用租户</div><div className="text-xs text-muted-foreground">停用后该租户所有密钥立即无法调用</div></div>
                <Switch checked={data.active} onCheckedChange={toggleActive} />
              </div>
              <div className="sm:col-span-2"><ErrorNote msg={err} /></div>
              <div><Button onClick={save}>保存设置</Button></div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      <Dialog open={topup} onOpenChange={setTopup}>
        <DialogContent>
          <form onSubmit={doTopup} className="grid gap-4">
            <DialogHeader><DialogTitle>为「{data.name}」人工入账</DialogTitle><DialogDescription>用于线下转账等场景，提交后立即到账。</DialogDescription></DialogHeader>
            <Field label="金额（美元）"><Input type="number" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="备注"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如：对公转账 #2026-11-001" /></Field>
            <DialogFooter><Button type="button" variant="outline" onClick={() => setTopup(false)}>取消</Button><Button>确认入账</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={!!newKey} onOpenChange={(o) => !o && setNewKey(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>密钥已创建</DialogTitle><DialogDescription>请复制后安全地交给租户，关闭后无法再次查看。</DialogDescription></DialogHeader>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2 pl-3"><code className="flex-1 break-all font-mono text-xs">{newKey}</code><CopyButton value={newKey || ""} /></div>
          <DialogFooter><Button onClick={() => setNewKey(null)}>完成</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
