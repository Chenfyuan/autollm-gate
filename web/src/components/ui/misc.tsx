import * as React from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {desc && <p className="text-[13px] text-muted-foreground">{desc}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CopyButton({ value, className, label }: { value: string; className?: string; label?: string }) {
  const [ok, setOk] = React.useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      size={label ? "sm" : "icon"}
      className={cn(!label && "size-8", className)}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch {
          const ta = document.createElement("textarea");
          ta.value = value;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
        }
        setOk(true);
        toast.success("已复制到剪贴板");
        setTimeout(() => setOk(false), 1500);
      }}
    >
      {ok ? <Check /> : <Copy />}
      {label}
    </Button>
  );
}

export function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  return (
    <div className="group relative overflow-hidden rounded-lg border bg-muted/40">
      {lang && <div className="border-b px-4 py-2 text-xs text-muted-foreground">{lang}</div>}
      <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed">
        <code>{code}</code>
      </pre>
      <CopyButton value={code} className="absolute right-2 top-2 bg-background opacity-0 transition-opacity group-hover:opacity-100" />
    </div>
  );
}

export function Stat({ label, value, sub, icon }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex items-center justify-between text-[13px] text-muted-foreground">
        <span>{label}</span>
        {icon && <span className="[&_svg]:size-4">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function ErrorNote({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{msg}</div>;
}
