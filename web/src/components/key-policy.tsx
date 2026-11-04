import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import type { ApiKey } from "@/lib/types";
import { dt, usd } from "@/lib/utils";

export type PolicyForm = { models: string; ips: string; expiry: string; spend: string; rpm: string };
export const emptyPolicy: PolicyForm = { models: "", ips: "", expiry: "", spend: "", rpm: "" };

const csv = (v: string) => v.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean);

export function policyFromKey(k: ApiKey): PolicyForm {
  return {
    models: (k.allowed_models || []).join(", "),
    ips: (k.ip_allowlist || []).join(", "),
    expiry: k.expires_at ? "keep" : "",
    spend: k.spend_limit_usd != null ? String(k.spend_limit_usd) : "",
    rpm: k.rpm_limit != null ? String(k.rpm_limit) : "",
  };
}

export function policyBody(f: PolicyForm, editing = false) {
  const b: Record<string, unknown> = { allowed_models: csv(f.models), ip_allowlist: csv(f.ips) };
  if (f.expiry === "" && editing) b.clear_expiry = true;
  else if (f.expiry && f.expiry !== "keep") b.expires_in_days = Number(f.expiry);
  if (f.spend.trim() === "") { if (editing) b.clear_spend_limit = true; }
  else b.spend_limit_usd = Number(f.spend);
  if (f.rpm.trim()) b.rpm_limit = Number(f.rpm);
  return b;
}

export function PolicyFields({ value, onChange, editing }: { value: PolicyForm; onChange: (v: PolicyForm) => void; editing?: boolean }) {
  const set = (k: keyof PolicyForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="grid gap-3 rounded-lg border bg-muted/30 p-3">
      <div className="text-[13px] font-medium">访问策略 <span className="font-normal text-muted-foreground">（均可留空，表示不限制）</span></div>
      <Field label="允许的模型" hint="逗号分隔，支持前缀通配，例如 gpt-4o-mini, deepseek*">
        <Input value={value.models} onChange={set("models")} placeholder="不限" />
      </Field>
      <Field label="IP 白名单" hint="逗号分隔的 IP 或 CIDR，例如 203.0.113.0/24">
        <Input value={value.ips} onChange={set("ips")} placeholder="不限" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="有效期">
          <NativeSelect value={value.expiry} onChange={set("expiry")}>
            {editing && value.expiry === "keep" && <option value="keep">保持不变</option>}
            <option value="">永久有效</option>
            <option value="7">7 天</option>
            <option value="30">30 天</option>
            <option value="90">90 天</option>
            <option value="365">1 年</option>
          </NativeSelect>
        </Field>
        <Field label="消费上限（美元）">
          <Input type="number" min={0} step="0.01" value={value.spend} onChange={set("spend")} placeholder="不限" />
        </Field>
        <Field label="每分钟请求数">
          <Input type="number" min={1} value={value.rpm} onChange={set("rpm")} placeholder="默认" />
        </Field>
      </div>
    </div>
  );
}

export function PolicyBadges({ k }: { k: ApiKey }) {
  const out: React.ReactNode[] = [];
  const expired = k.expires_at && new Date(k.expires_at) < new Date();
  if (k.allowed_models?.length) out.push(<Badge key="m" variant="outline" title={k.allowed_models.join(", ")}>{k.allowed_models.length} 个模型</Badge>);
  if (k.ip_allowlist?.length) out.push(<Badge key="i" variant="outline" title={k.ip_allowlist.join(", ")}>IP 白名单</Badge>);
  if (k.expires_at) out.push(<Badge key="e" variant={expired ? "outline" : "outline"} className={expired ? "text-destructive" : ""}>{expired ? "已过期" : `至 ${dt(k.expires_at).slice(0, 10)}`}</Badge>);
  if (k.spend_limit_usd != null) out.push(<Badge key="s" variant="outline">{usd(k.spent_usd ?? 0, 2)} / {usd(k.spend_limit_usd, 2)}</Badge>);
  if (k.rpm_limit) out.push(<Badge key="r" variant="outline">{k.rpm_limit} 次/分</Badge>);
  return out.length ? <div className="flex flex-wrap gap-1">{out}</div> : <span className="text-xs text-muted-foreground">不限</span>;
}
