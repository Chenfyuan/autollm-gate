import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART_COLORS, usd } from "@/lib/utils";

const axis = { stroke: "hsl(var(--muted-foreground))", fontSize: 11, tickLine: false, axisLine: false } as const;

function TipBox({ active, payload, label, fmt }: { active?: boolean; payload?: any[]; label?: string; fmt: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p) => p.value);
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-medium">{label}</div>
      {(rows.length ? rows : payload).map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-muted-foreground">
          <span className="size-2 rounded-sm" style={{ background: p.color }} />
          <span className="flex-1">{p.name}</span>
          <span className="tabular font-medium text-foreground">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

const short = (d: string) => d.slice(5).replace("-", "/");
const moneyTick = (v: number) => {
  if (!v) return "$0";
  if (Math.abs(v) >= 1) return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  if (Math.abs(v) >= 0.01) return "$" + v.toFixed(2);
  return "$" + v.toPrecision(1);
};
const countTick = (v: number) => (v >= 10000 ? `${+(v / 10000).toFixed(1)}万` : v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(v));

export function SpendArea({ data, dataKey = "charge_usd", name = "消费", money = true, height = 240 }: { data: any[]; dataKey?: string; name?: string; money?: boolean; height?: number }) {
  const fmt = money ? (v: number) => usd(v) : (v: number) => v.toLocaleString("zh-CN");
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <defs>
          <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_COLORS[0]} stopOpacity={0.18} />
            <stop offset="100%" stopColor={CHART_COLORS[0]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
        <XAxis dataKey="date" tickFormatter={short} {...axis} minTickGap={24} />
        <YAxis {...axis} width={56} tickFormatter={(v) => (money ? moneyTick(+v) : countTick(+v))} />
        <Tooltip content={<TipBox fmt={fmt} />} cursor={{ stroke: "hsl(var(--border))" }} />
        <Area type="monotone" dataKey={dataKey} name={name} stroke={CHART_COLORS[0]} strokeWidth={2} fill={`url(#g-${dataKey})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function StackedBars({ data, keys, height = 280 }: { data: any[]; keys: string[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
        <XAxis dataKey="date" tickFormatter={short} {...axis} minTickGap={16} />
        <YAxis {...axis} width={56} tickFormatter={(v) => moneyTick(+v)} />
        <Tooltip content={<TipBox fmt={(v) => usd(v)} />} cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} name={k} stackId="a" fill={CHART_COLORS[i % CHART_COLORS.length]} radius={i === keys.length - 1 ? [3, 3, 0, 0] : 0} maxBarSize={28} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Lines({ data, lines, height = 220, fmt = (v: number) => String(v) }: { data: any[]; lines: { key: string; name: string; color?: string }[]; height?: number; fmt?: (v: number) => string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
        <XAxis dataKey="label" {...axis} minTickGap={24} />
        <YAxis {...axis} width={48} allowDecimals={false} tickFormatter={(v) => countTick(+v)} />
        <Tooltip content={<TipBox fmt={fmt} />} />
        {lines.map((l, i) => (
          <Line key={l.key} dataKey={l.key} name={l.name} type="monotone" dot={false} strokeWidth={2} stroke={l.color || CHART_COLORS[i % CHART_COLORS.length]} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Legend({ keys }: { keys: string[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5">
      {keys.map((k, i) => (
        <span key={k} className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="size-2 rounded-sm" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
          {k}
        </span>
      ))}
    </div>
  );
}
