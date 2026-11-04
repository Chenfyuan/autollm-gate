import * as React from "react";
import { Outlet } from "react-router-dom";
import { BookOpen, ScrollText, CreditCard, KeyRound, LayoutDashboard, LineChart, ReceiptText, Boxes } from "lucide-react";
import { AppShell } from "@/components/shell";
import { useApi } from "@/lib/hooks";
import type { Me } from "@/lib/types";
import { usd } from "@/lib/utils";

export const MeContext = React.createContext<{ me: Me | null; reload: () => void }>({ me: null, reload: () => undefined });

const items = [
  { to: "/console", label: "概览", icon: <LayoutDashboard />, end: true },
  { to: "/console/usage", label: "用量分析", icon: <LineChart /> },
  { to: "/console/billing", label: "账单明细", icon: <ReceiptText /> },
  { to: "/console/logs", label: "请求日志", icon: <ScrollText /> },
  { to: "/console/keys", label: "API 密钥", icon: <KeyRound /> },
  { to: "/console/topup", label: "余额充值", icon: <CreditCard /> },
  { to: "/console/models", label: "模型与价格", icon: <Boxes /> },
  { to: "/console/docs", label: "快速开始", icon: <BookOpen /> },
];

export function ConsoleLayout() {
  const { data, reload } = useApi<Me>("/api/me", { loginPath: "/login" });
  const footer = data && (
    <div className="rounded-lg border bg-background p-3">
      <div className="text-xs text-muted-foreground">可用余额</div>
      <div className="mt-0.5 text-lg font-semibold tabular">{usd(data.tenant.balance_usd, 2)}</div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">{data.tenant.name}</div>
    </div>
  );
  return (
    <MeContext.Provider value={{ me: data, reload }}>
      <AppShell items={items} sub="开发者控制台" user={data ? { name: data.user.name || data.tenant.name, email: data.user.email } : null} logoutUrl="/api/auth/logout" loginPath="/login" footer={footer}>
        <Outlet />
      </AppShell>
    </MeContext.Provider>
  );
}
