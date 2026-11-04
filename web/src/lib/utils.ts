import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function usd(v: number | null | undefined, digits?: number) {
  const n = v ?? 0;
  const d = digits ?? (Math.abs(n) >= 100 ? 2 : Math.abs(n) >= 1 ? 2 : Math.abs(n) >= 0.01 ? 4 : n === 0 ? 2 : 6);
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function num(v: number | null | undefined) {
  return (v ?? 0).toLocaleString("zh-CN");
}

export function compact(v: number | null | undefined) {
  const n = v ?? 0;
  if (n >= 1e8) return (n / 1e8).toFixed(1) + " 亿";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
  return n.toLocaleString("zh-CN");
}

export function dt(iso: string | null | undefined, withSeconds = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (x: number) => String(x).padStart(2, "0");
  const s = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return withSeconds ? s + ":" + pad(d.getSeconds()) : s;
}

export function relTime(iso: string | null | undefined) {
  if (!iso) return "从未";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return dt(iso).slice(0, 10);
}

export const PROVIDER_NAMES: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  deepseek: "DeepSeek",
  selfhosted: "自部署模型",
};

export const SOURCE_NAMES: Record<string, string> = { platform: "平台密钥", byok: "自带密钥", selfhosted: "自部署" };

export const CHART_COLORS = [1, 2, 3, 4, 5, 6].map((i) => `hsl(var(--chart-${i}))`);
