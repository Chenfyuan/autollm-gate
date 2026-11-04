import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "./api";

export function useApi<T>(url: string | null, opts: { loginPath?: string; refreshMs?: number } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!url) return;
    try {
      const d = await api.get<T>(url);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && opts.loginPath) nav(opts.loginPath, { replace: true });
      else if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [url, opts.loginPath, nav]);
  useEffect(() => {
    alive.current = true;
    load();
    let t: number | undefined;
    if (opts.refreshMs) t = window.setInterval(load, opts.refreshMs);
    return () => {
      alive.current = false;
      if (t) clearInterval(t);
    };
  }, [load, opts.refreshMs]);
  return { data, error, loading, reload: load, setData };
}

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
    setDark(next);
  };
  return { dark, toggle };
}
