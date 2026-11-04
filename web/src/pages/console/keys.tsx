import * as React from "react";
import { KeyRound, Plus, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, Dot } from "@/components/ui/badge";
import { Field, Input } from "@/components/ui/input";
import { CopyButton, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import { api } from "@/lib/api";
import type { ApiKey } from "@/lib/types";
import { dt, relTime } from "@/lib/utils";
import { PolicyBadges, PolicyFields, emptyPolicy, policyBody, policyFromKey, type PolicyForm } from "@/components/key-policy";

export function KeysTable({ keys, onRevoke, onEdit }: { keys: ApiKey[]; onRevoke: (k: ApiKey) => void; onEdit?: (k: ApiKey) => void }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH className="pl-5">名称</TH>
          <TH>密钥</TH>
          <TH>状态</TH>
          <TH>访问策略</TH>
          <TH>创建时间</TH>
          <TH>最近使用</TH>
          <TH className="pr-5" />
        </TR>
      </THead>
      <TBody>
        {keys.map((k) => (
          <TR key={k.id}>
            <TD className="pl-5 font-medium">{k.name}</TD>
            <TD className="font-mono text-xs text-muted-foreground">{k.prefix}••••••••</TD>
            <TD>
              {k.active ? (
                <Badge variant="success">
                  <Dot /> 有效
                </Badge>
              ) : (
                <Badge variant="outline">已吊销</Badge>
              )}
            </TD>
            <TD><PolicyBadges k={k} /></TD>
            <TD className="tabular text-muted-foreground">{dt(k.created_at)}</TD>
            <TD className="text-muted-foreground">{relTime(k.last_used_at)}</TD>
            <TD className="whitespace-nowrap pr-5 text-right">
              {k.active && onEdit && (
                <Button variant="ghost" size="sm" onClick={() => onEdit(k)}>
                  策略
                </Button>
              )}
              {k.active && (
                <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => onRevoke(k)}>
                  吊销
                </Button>
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function ConsoleKeys() {
  const { data, reload } = useApi<ApiKey[]>("/api/console/keys", { loginPath: "/login" });
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [created, setCreated] = React.useState<ApiKey | null>(null);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [policy, setPolicy] = React.useState<PolicyForm>(emptyPolicy);
  const [editing, setEditing] = React.useState<ApiKey | null>(null);
  const [editPolicy, setEditPolicy] = React.useState<PolicyForm>(emptyPolicy);
  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setErr(null);
    try {
      await api.patch(`/api/console/keys/${editing.id}`, policyBody(editPolicy, true));
      toast.success(`已更新「${editing.name}」的访问策略`);
      setEditing(null);
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const k = await api.post<ApiKey>("/api/console/keys", { name, ...policyBody(policy) });
      setCreated(k);
      setName("");
      setPolicy(emptyPolicy);
      reload();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const revoke = async () => {
    if (!revoking) return;
    await api.del(`/api/console/keys/${revoking.id}`);
    toast.success(`已吊销「${revoking.name}」`);
    setRevoking(null);
    reload();
  };
  const active = data?.filter((k) => k.active) ?? [];
  const revoked = data?.filter((k) => !k.active) ?? [];
  return (
    <>
      <PageHeader
        title="API 密钥"
        desc="用密钥调用网关接口。请妥善保管，不要提交到代码仓库或发给他人。"
        actions={
          <Button onClick={() => { setCreated(null); setOpen(true); }}>
            <Plus /> 创建密钥
          </Button>
        }
      />
      <Card>
        {!data ? (
          <div className="space-y-2 p-5">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : data.length === 0 ? (
          <Empty icon={<KeyRound />} title="还没有密钥" desc="创建第一个密钥，即可开始调用。" />
        ) : (
          <KeysTable keys={[...active, ...revoked]} onRevoke={setRevoking} onEdit={(k) => { setErr(null); setEditPolicy(policyFromKey(k)); setEditing(k); }} />
        )}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          {!created ? (
            <form onSubmit={create} className="grid gap-4">
              <DialogHeader>
                <DialogTitle>创建 API 密钥</DialogTitle>
                <DialogDescription>起一个便于识别的名字，例如用途或环境。</DialogDescription>
              </DialogHeader>
              <Field label="名称">
                <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：生产环境、Claude Code" maxLength={100} />
              </Field>
              <PolicyFields value={policy} onChange={setPolicy} />
              <ErrorNote msg={err} />
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button>创建</Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="grid gap-4">
              <DialogHeader>
                <DialogTitle>密钥已创建</DialogTitle>
                <DialogDescription>请立即复制保存。关闭此窗口后将无法再次查看完整密钥。</DialogDescription>
              </DialogHeader>
              <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2 pl-3">
                <code className="flex-1 break-all font-mono text-xs">{created.api_key}</code>
                <CopyButton value={created.api_key || ""} />
              </div>
              <div className="flex gap-2 rounded-md bg-warning/10 px-3 py-2 text-[13px] text-warning">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" /> 我们只保存密钥的哈希值，丢失后只能吊销并重新创建。
              </div>
              <DialogFooter>
                <Button onClick={() => setOpen(false)}>我已保存</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <form onSubmit={saveEdit} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>访问策略 ·「{editing?.name}」</DialogTitle>
              <DialogDescription>修改后立即生效，无需更换密钥。</DialogDescription>
            </DialogHeader>
            <PolicyFields value={editPolicy} onChange={setEditPolicy} editing />
            <ErrorNote msg={err} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditing(null)}>
                取消
              </Button>
              <Button>保存</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!revoking} onOpenChange={(o) => !o && setRevoking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>吊销密钥「{revoking?.name}」？</DialogTitle>
            <DialogDescription>吊销后立即失效，使用该密钥的程序会收到 401 错误。此操作不可撤销。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevoking(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={revoke}>
              确认吊销
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
