import { Outlet } from "react-router-dom";
import { Activity, Boxes, History, KeyRound, LayoutDashboard, ScrollText, Settings, ShieldCheck, Users } from "lucide-react";
import { AppShell } from "@/components/shell";
import { useApi } from "@/lib/hooks";

const items = [
  { to: "/admin", label: "运营概览", icon: <LayoutDashboard />, end: true },
  { to: "/admin/tenants", label: "租户管理", icon: <Users /> },
  { to: "/admin/models", label: "模型与价格", icon: <Boxes /> },
  { to: "/admin/upstreams", label: "上游密钥", icon: <KeyRound /> },
  { to: "/admin/logs", label: "请求日志", icon: <ScrollText /> },
  { to: "/admin/monitoring", label: "监控告警", icon: <Activity /> },
  { to: "/admin/settings", label: "计费与告警设置", icon: <Settings /> },
  { to: "/admin/admins", label: "管理员", icon: <ShieldCheck /> },
  { to: "/admin/audit", label: "审计日志", icon: <History /> },
];

export function AdminLayout() {
  const { data } = useApi<{ email: string; name: string }>("/api/admin/me", { loginPath: "/admin/login" });
  return (
    <AppShell items={items} sub="管理后台" user={data} logoutUrl="/api/admin/auth/logout" loginPath="/admin/login">
      <Outlet />
    </AppShell>
  );
}
