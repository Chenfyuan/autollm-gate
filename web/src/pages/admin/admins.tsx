import * as React from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, Dot } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/input";
import { ErrorNote, PageHeader } from "@/components/ui/misc";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import { dt, relTime } from "@/lib/utils";

type A = { id: string; email: string; name: string; active: boolean; created_at: string; last_login_at: string | null };

export function AdminAdmins() {
  const { data, reload } = useApi<A[]>("/api/admin/admins", { loginPath: "/admin/login" });
  const me = useApi<{ id: string }>("/api/admin/me");
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({ email: "", name: "", password: "" });
  const [err, setErr] = React.useState<string | null>(null);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await api.post("/api/admin/admins", f);
      toast.success("管理员已添加");
      setOpen(false);
      setF({ email: "", name: "", password: "" });
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const toggle = async (a: A) => {
    try {
      await api.patch(`/api/admin/admins/${a.id}`, { active: !a.active });
      reload();
    } catch (x) {
      toast.error((x as Error).message);
    }
  };
  return (
    <>
      <PageHeader title="管理员" desc="每位管理员使用自己的邮箱和密码登录，密码以 Argon2 哈希存储" actions={<Button onClick={() => setOpen(true)}><Plus /> 添加管理员</Button>} />
      <Card>
        <Table>
          <THead><TR><TH className="pl-5">管理员</TH><TH>状态</TH><TH>添加时间</TH><TH>最近登录</TH><TH className="pr-5" /></TR></THead>
          <TBody>
            {data?.map((a) => (
              <TR key={a.id}>
                <TD className="pl-5"><div className="font-medium">{a.name || a.email}</div><div className="text-xs text-muted-foreground">{a.email}</div></TD>
                <TD>{a.active ? <Badge variant="success"><Dot /> 正常</Badge> : <Badge variant="outline">已停用</Badge>}</TD>
                <TD className="tabular text-muted-foreground">{dt(a.created_at)}</TD>
                <TD className="text-muted-foreground">{relTime(a.last_login_at)}</TD>
                <TD className="pr-5 text-right">
                  {me.data?.id !== a.id && <Button variant="ghost" size="sm" onClick={() => toggle(a)}>{a.active ? "停用" : "启用"}</Button>}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={create} className="grid gap-4">
            <DialogHeader><DialogTitle>添加管理员</DialogTitle><DialogDescription>请通过安全渠道把初始密码告知对方。</DialogDescription></DialogHeader>
            <Field label="邮箱"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="姓名"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="初始密码" hint="至少 8 位，需同时包含字母和数字"><Input type="password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <ErrorNote msg={err} />
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>取消</Button><Button>添加</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
