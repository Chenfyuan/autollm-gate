import * as React from "react";
import { History, Search } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Table, TBody, TD, TH, THead, TR, Empty } from "@/components/ui/table";
import { useApi } from "@/lib/hooks";
import type { AuditItem } from "@/lib/types";
import { dt, num } from "@/lib/utils";

const LABELS: Record<string, string> = {
  "key.create": "创建密钥", "key.update": "修改密钥策略", "key.revoke": "吊销密钥",
  "post tenants": "租户操作", "patch tenants": "修改租户", "put upstreams": "设置上游密钥", "delete upstreams": "删除上游密钥",
  "put tenants": "设置租户上游", "patch models": "修改模型价格", "put settings": "修改系统设置", "post admins": "新增管理员",
  "patch admins": "修改管理员", "post alerts": "告警操作",
};

export function AdminAudit() {
  const [f, setF] = React.useState({ actor: "", action: "" });
  const [q, setQ] = React.useState(f);
  const [page, setPage] = React.useState(1);
  const params = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
  const { data } = useApi<{ total: number; items: AuditItem[] }>(`/api/admin/audit?${params}&page=${page}&size=50`, { loginPath: "/admin/login" });
  const pages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;
  return (
    <>
      <PageHeader title="审计日志" desc="后台与租户控制台的每一次写操作都会留痕：谁、何时、从哪个 IP、做了什么。" />
      <Card className="mb-4 p-3">
        <form className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(f); }}>
          <Input value={f.actor} onChange={(e) => setF({ ...f, actor: e.target.value })} placeholder="操作人邮箱" />
          <Input value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })} placeholder="操作类型前缀，例如 key." />
          <Button><Search /> 查询</Button>
        </form>
      </Card>
      <Card>
        {!data ? (
          <div className="space-y-2 p-5"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
        ) : data.items.length === 0 ? (
          <Empty icon={<History />} title="暂无审计记录" />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH className="pl-5">时间</TH>
                  <TH>操作人</TH>
                  <TH>操作</TH>
                  <TH>对象</TH>
                  <TH className="pr-5">详情</TH>
                </TR>
              </THead>
              <TBody>
                {data.items.map((x) => (
                  <TR key={x.id}>
                    <TD className="whitespace-nowrap pl-5 tabular text-muted-foreground">{dt(x.created_at, true)}</TD>
                    <TD>
                      <div>{x.actor}</div>
                      <div className="text-xs text-muted-foreground">{x.actor_type === "admin" ? "管理员" : "租户成员"}</div>
                    </TD>
                    <TD><Badge variant="outline">{LABELS[x.action] || x.action}</Badge></TD>
                    <TD className="max-w-[220px] truncate font-mono text-xs text-muted-foreground">{x.target || "—"}</TD>
                    <TD className="max-w-[320px] truncate pr-5 font-mono text-xs text-muted-foreground">
                      {Object.keys(x.detail || {}).length ? JSON.stringify(x.detail) : "—"}
                    </TD>
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
