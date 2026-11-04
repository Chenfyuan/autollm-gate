import * as React from "react";
import { CheckCircle2, CircleDashed, Lock } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorNote, PageHeader } from "@/components/ui/misc";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import { dt, PROVIDER_NAMES } from "@/lib/utils";

type U = { provider: string; configured: boolean; id: string | null; masked: string | null; updated_at: string | null };

export function AdminUpstreams() {
  const { data, reload } = useApi<U[]>("/api/admin/upstreams", { loginPath: "/admin/login" });
  const [edit, setEdit] = React.useState<U | null>(null);
  const [key, setKey] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await api.put("/api/admin/upstreams", { provider: edit!.provider, api_key: key });
      toast.success(`${PROVIDER_NAMES[edit!.provider]} 密钥已保存`);
      setEdit(null);
      setKey("");
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const remove = async (u: U) => {
    await api.del(`/api/admin/upstreams/${u.id}`);
    toast.success("已停用");
    reload();
  };
  return (
    <>
      <PageHeader title="上游密钥" desc="平台统一使用的上游厂商密钥。填入即启用，租户按用量付费。" />
      <div className="mb-4 flex items-center gap-2 rounded-lg border bg-muted/40 px-4 py-3 text-[13px] text-muted-foreground">
        <Lock className="size-4 shrink-0" /> 密钥使用主密钥加密后存入数据库，保存后任何人（包括管理员）都只能看到末 4 位。
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((u) => (
          <Card key={u.provider} className="flex flex-col p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-medium">{PROVIDER_NAMES[u.provider]}</div>
                <div className="mt-0.5 font-mono text-xs text-muted-foreground">{u.provider}</div>
              </div>
              {u.configured ? (
                <span className="flex items-center gap-1 text-xs text-success"><CheckCircle2 className="size-4" /> 已启用</span>
              ) : (
                <span className="flex items-center gap-1 text-xs text-muted-foreground"><CircleDashed className="size-4" /> 未配置</span>
              )}
            </div>
            <div className="mt-4 flex-1">
              {u.configured ? (
                <>
                  <code className="font-mono text-[13px]">{u.masked}</code>
                  <div className="mt-1 text-xs text-muted-foreground">更新于 {dt(u.updated_at)}</div>
                </>
              ) : (
                <div className="text-[13px] text-muted-foreground">未配置时，路由会自动跳过该厂商的模型。</div>
              )}
            </div>
            <div className="mt-4 flex gap-2">
              <Button variant={u.configured ? "outline" : "default"} size="sm" onClick={() => setEdit(u)}>{u.configured ? "更换密钥" : "填写密钥"}</Button>
              {u.configured && <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => remove(u)}>停用</Button>}
            </div>
          </Card>
        ))}
      </div>
      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent>
          <form onSubmit={save} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>{edit && PROVIDER_NAMES[edit.provider]} 密钥</DialogTitle>
              <DialogDescription>保存后立即对所有实例生效，旧密钥自动停用。</DialogDescription>
            </DialogHeader>
            <Field label="API Key"><Input type="password" autoComplete="off" required minLength={8} value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-…" /></Field>
            <ErrorNote msg={err} />
            <DialogFooter><Button type="button" variant="outline" onClick={() => setEdit(null)}>取消</Button><Button>保存</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
