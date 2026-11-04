import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Gauge, Route, ShieldCheck } from "lucide-react";
import { AuthLayout } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorNote } from "@/components/ui/misc";
import { api } from "@/lib/api";

function SidePanel({ admin }: { admin?: boolean }) {
  const items = admin
    ? [
        { icon: <Gauge />, t: "实时监控", d: "各上游错误率、延迟与熔断状态一目了然" },
        { icon: <ShieldCheck />, t: "安全合规", d: "上游密钥加密存储，界面只显示掩码" },
        { icon: <Route />, t: "灵活定价", d: "按模型调价、按租户设置加价与限流" },
      ]
    : [
        { icon: <Route />, t: "一个接口，所有模型", d: "兼容 OpenAI、Anthropic 与 Responses 协议" },
        { icon: <Gauge />, t: "自动选择最优模型", d: "按任务类型与成本策略智能路由，失败自动切换" },
        { icon: <ShieldCheck />, t: "用多少付多少", d: "按 token 精确计费，账单明细随时可查" },
      ];
  return (
    <div className="flex h-full flex-col justify-center px-14">
      <div className="max-w-md">
        <div className="rounded-xl border bg-background p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-border" />
            <span className="size-2.5 rounded-full bg-border" />
            <span className="size-2.5 rounded-full bg-border" />
          </div>
          <pre className="font-mono text-[12px] leading-relaxed text-muted-foreground">
            <span className="text-foreground">curl</span> https://gate.example.com/v1/chat/completions \{"\n"}
            {"  "}-H <span className="text-[hsl(var(--chart-2))]">"Authorization: Bearer sk-lr-…"</span> \{"\n"}
            {"  "}-d <span className="text-[hsl(var(--chart-2))]">'{"{"}"model": "auto", …{"}"}'</span>
            {"\n\n"}
            <span className="text-foreground">X-Router-Model:</span> deepseek-chat{"\n"}
            <span className="text-foreground">X-Router-Reason:</span> task=chat; cost_optimized
          </pre>
        </div>
        <div className="mt-10 space-y-6">
          {items.map((it) => (
            <div key={it.t} className="flex gap-3.5">
              <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-background [&_svg]:size-4">{it.icon}</div>
              <div>
                <div className="text-[13.5px] font-medium">{it.t}</div>
                <div className="mt-0.5 text-[13px] text-muted-foreground">{it.d}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function useSubmit(fn: () => Promise<void>) {
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, submit };
}

export function LoginPage({ admin = false }: { admin?: boolean }) {
  const nav = useNavigate();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const { busy, err, submit } = useSubmit(async () => {
    await api.post(admin ? "/api/admin/auth/login" : "/api/auth/login", { email, password });
    nav(admin ? "/admin" : "/console", { replace: true });
  });
  return (
    <AuthLayout
      title={admin ? "管理后台登录" : "登录控制台"}
      desc={admin ? "仅限平台管理员使用" : "欢迎回来，登录后管理你的 API 密钥与用量"}
      side={<SidePanel admin={admin} />}
      footer={
        admin ? null : (
          <>
            还没有账号？
            <Link to="/signup" className="font-medium text-foreground underline-offset-4 hover:underline">
              免费注册
            </Link>
          </>
        )
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="邮箱">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" />
        </Field>
        <Field label="密码">
          <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorNote msg={err} />
        <Button className="w-full" disabled={busy}>
          {busy ? "登录中…" : "登录"}
          {!busy && <ArrowRight />}
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SignupPage() {
  const nav = useNavigate();
  const [f, setF] = React.useState({ company: "", name: "", email: "", password: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const { busy, err, submit } = useSubmit(async () => {
    await api.post("/api/auth/signup", f);
    nav("/console", { replace: true });
  });
  return (
    <AuthLayout
      title="创建账号"
      desc="一分钟开通，立即获得 API 密钥"
      side={<SidePanel />}
      footer={
        <>
          已有账号？
          <Link to="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
            直接登录
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="公司 / 团队名称">
            <Input required value={f.company} onChange={set("company")} placeholder="例如：星河科技" />
          </Field>
          <Field label="你的称呼">
            <Input value={f.name} onChange={set("name")} placeholder="选填" />
          </Field>
        </div>
        <Field label="工作邮箱">
          <Input type="email" required value={f.email} onChange={set("email")} placeholder="name@company.com" />
        </Field>
        <Field label="密码" hint="至少 8 位，需同时包含字母和数字">
          <Input type="password" autoComplete="new-password" required value={f.password} onChange={set("password")} />
        </Field>
        <ErrorNote msg={err} />
        <Button className="w-full" disabled={busy}>
          {busy ? "创建中…" : "创建账号"}
        </Button>
      </form>
    </AuthLayout>
  );
}
