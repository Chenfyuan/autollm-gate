import * as React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import * as DM from "@radix-ui/react-dropdown-menu";
import { LogOut, Menu, Moon, Sun, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/hooks";
import { api } from "@/lib/api";
import { Button } from "./ui/button";

export type NavItem = { to: string; label: string; icon: React.ReactNode; end?: boolean };

export function Logo({ sub }: { sub?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7 shrink-0">
        <rect width="32" height="32" rx="8" className="fill-foreground" />
        <path d="M9 22 16 9l7 13" fill="none" className="stroke-background" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="16" cy="18.5" r="2" fill="#3b82f6" />
      </svg>
      <div className="leading-tight">
        <div className="text-[14px] font-semibold tracking-tight">AutoLLM Gate</div>
        {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
      </div>
    </div>
  );
}

function Nav({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-0.5">
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13.5px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-4",
              isActive && "bg-accent font-medium text-foreground",
            )
          }
        >
          {it.icon}
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell({
  items,
  sub,
  user,
  logoutUrl,
  loginPath,
  footer,
  children,
}: {
  items: NavItem[];
  sub: string;
  user: { name: string; email: string } | null;
  logoutUrl: string;
  loginPath: string;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { dark, toggle } = useTheme();
  const [open, setOpen] = React.useState(false);
  const nav = useNavigate();
  const logout = async () => {
    await api.post(logoutUrl).catch(() => undefined);
    nav(loginPath, { replace: true });
  };
  const initials = (user?.name || user?.email || "?").slice(0, 1).toUpperCase();
  const side = (
    <div className="flex h-full flex-col gap-6 p-4">
      <div className="px-1 pt-1">
        <Logo sub={sub} />
      </div>
      <Nav items={items} onNavigate={() => setOpen(false)} />
      <div className="mt-auto">{footer}</div>
    </div>
  );
  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r bg-sidebar lg:block">{side}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-sidebar">
            <button className="absolute right-3 top-4 opacity-60" onClick={() => setOpen(false)}>
              <X className="size-4" />
            </button>
            {side}
          </aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)}>
            <Menu />
          </Button>
          <div className="flex-1" />
          <Button variant="ghost" size="icon" onClick={toggle} title={dark ? "切换到浅色" : "切换到深色"}>
            {dark ? <Sun /> : <Moon />}
          </Button>
          <DM.Root>
            <DM.Trigger asChild>
              <button className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent">
                <span className="flex size-7 items-center justify-center rounded-full bg-secondary text-xs font-semibold">{initials}</span>
                <span className="hidden text-[13px] sm:block">{user?.name || user?.email}</span>
              </button>
            </DM.Trigger>
            <DM.Portal>
              <DM.Content align="end" sideOffset={6} className="z-50 min-w-52 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg">
                <div className="px-2.5 py-2">
                  <div className="text-[13px] font-medium">{user?.name || "账户"}</div>
                  <div className="text-xs text-muted-foreground">{user?.email}</div>
                </div>
                <DM.Separator className="my-1 h-px bg-border" />
                <DM.Item onSelect={logout} className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[13px] outline-none hover:bg-accent">
                  <LogOut className="size-4" />
                  退出登录
                </DM.Item>
              </DM.Content>
            </DM.Portal>
          </DM.Root>
        </header>
        <main className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-8">{children}</main>
      </div>
    </div>
  );
}

export function AuthLayout({ title, desc, children, footer, side }: { title: string; desc: string; children: React.ReactNode; footer?: React.ReactNode; side?: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-[13px] text-muted-foreground">{desc}</p>
          <div className="mt-8">{children}</div>
          {footer && <div className="mt-6 text-center text-[13px] text-muted-foreground">{footer}</div>}
        </div>
      </div>
      <div className="relative hidden overflow-hidden border-l bg-sidebar lg:block">{side}</div>
    </div>
  );
}
