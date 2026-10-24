import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, SectionTitle } from "../ui";
import type { RiskTier } from "../../types";

const colors: Record<RiskTier, string> = {
  GREEN: "#34d399",
  AMBER: "#fbbf24",
  RED: "#f87171",
  GREY: "#94a3b8",
};

export function TierChart({ sessions }: { sessions: { tier: RiskTier }[] }) {
  const data = (["GREEN", "AMBER", "RED", "GREY"] as RiskTier[]).map((t) => ({
    tier: t,
    count: sessions.filter((s) => s.tier === t).length,
  }));
  return (
    <Card>
      <SectionTitle>Sessions by risk tier</SectionTitle>
      <div
        className="h-40"
        role="img"
        aria-label={data.map((d) => `${d.tier}: ${d.count}`).join(", ")}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <XAxis
              dataKey="tier"
              stroke="#64748b"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              allowDecimals={false}
              stroke="#64748b"
              fontSize={12}
              width={24}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
              contentStyle={{
                background: "#0b1220",
                border: "1px solid #1c2a44",
                borderRadius: 12,
              }}
            />
            <Bar dataKey="count" radius={[6, 6, 0, 0]}>
              {data.map((d) => (
                <Cell key={d.tier} fill={colors[d.tier]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
