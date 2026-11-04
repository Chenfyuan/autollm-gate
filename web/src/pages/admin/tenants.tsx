import * as React from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, Users } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, Dot } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/input";
import { ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import { compact, dt, num, usd } from "@/lib/utils";

export type TenantRow = {
  id: string; name: string; email: string | null; balance_usd: number; reserved_usd: number; active: boolean; created_at: string;
  markup_pct: number | null; month_requests: number; month_charge_usd: number; month_tokens: number; active_keys: number; monthly_token_limit: number | null;
};

export function AdminTenants() {
  const [q, setQ] = React.useState("");
  const { data, reload } = useApi<TenantRow[]>("/api/admin/tenants", { loginPath: "/admin/login" });
  const nav = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const rows = (data ?? []).filter((t) => (t.name + (t.email || "")).toLowerCase().includes(q.toLowerCase()));
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const t = await api.post<{ id: string }>("/api/admin/tenants", { name });
      toast.success("租户已创建");
      setOpen(false);
      reload();
      nav(`/admin/tenants/${t.id}`);
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <>
      <PageHeader
        title="租户管理"
        desc={data ? `共 ${data.length} 个租户，本月数据按自然月统计` : "所有注册和后台创建的租户"}
        actions={
          <>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input className="w-56 pl-8" placeholder="搜索名称或邮箱" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <Button onClick={() => setOpen(true)}><Plus /> 新建租户</Button>
          </>
        }
      />
      <Card>
        {!data ? (
          <div className="space-y-2 p-5">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : rows.length === 0 ? (
          <Empty icon={<Users />} title="没有匹配的租户" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="pl-5">租户</TH>
                <TH>状态</TH>
                <TH className="text-right">余额</TH>
                <TH className="text-right">本月消费</TH>
                <TH className="text-right">本月请求</TH>
                <TH className="text-right">本月 tokens</TH>
                <TH className="text-right">密钥</TH>
                <TH className="pr-5">注册时间</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((t) => (
                <TR key={t.id} data-clickable onClick={() => nav(`/admin/tenants/${t.id}`)}>
                  <TD className="pl-5">
                    <div className="flex items-center gap-3">
                      <div className="flex size-8 items-center justify-center rounded-md bg-secondary text-xs font-semibold">{t.name.slice(0, 1)}</div>
                      <div>
                        <div className="font-medium">{t.name}</div>
                        <div className="text-xs text-muted-foreground">{t.email || "后台创建"}</div>
                      </div>
                    </div>
                  </TD>
                  <TD>
                    {t.active ? <Badge variant="success"><Dot /> 正常</Badge> : <Badge variant="outline">已停用</Badge>}
                  </TD>
                  <TD className={`text-right tabular ${t.balance_usd < 1 ? "text-warning" : ""}`}>{usd(t.balance_usd, 2)}</TD>
                  <TD className="text-right tabular font-medium">{usd(t.month_charge_usd, 2)}</TD>
                  <TD className="text-right tabular">{num(t.month_requests)}</TD>
                  <TD className="text-right tabular text-muted-foreground">{compact(t.month_tokens)}</TD>
                  <TD className="text-right tabular">{t.active_keys}</TD>
                  <TD className="pr-5 tabular text-muted-foreground">{dt(t.created_at).slice(0, 10)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={create} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>新建租户</DialogTitle>
              <DialogDescription>用于线下签约的客户。自助注册的客户会自动出现在列表中。</DialogDescription>
            </DialogHeader>
            <Field label="租户名称"><Input autoFocus required value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <ErrorNote msg={err} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button>
              <Button>创建</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
