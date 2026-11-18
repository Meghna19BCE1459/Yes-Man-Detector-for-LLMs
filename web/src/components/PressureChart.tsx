import { useState } from "react";
import { ciText, pct, type Rate } from "../api";

export type PressureRow = {
  agent: string;
  caving: Rate;
  correction: Rate;
  discernment: number | null;
};

const W = 900;
const ROW = 46;
const M = { top: 8, right: 24, bottom: 34, left: 170 };

/**
 * Dumbbell plot: for each agent, how often it caved to a wrong crowd (orange) vs how often it
 * accepted a right crowd (blue), with 95% CI whiskers. The gap between the two is "discernment".
 */
export default function PressureChart({ rows }: { rows: PressureRow[] }) {
  const [tip, setTip] = useState<{ x: number; y: number; title: string; body: string } | null>(null);
  const H = M.top + rows.length * ROW + M.bottom;
  const iw = W - M.left - M.right;
  const x = (v: number) => M.left + v * iw;
  const CAVE = "var(--series-2)";
  const CORR = "var(--series-1)";

  const dot = (r: PressureRow, rate: Rate, cy: number, color: string, label: string, dy: number) => {
    if (rate.value == null) return null;
    const cx = x(rate.value);
    return (
      <g
        onMouseEnter={() => setTip({ x: cx, y: cy + dy, title: `${r.agent}: ${label}`, body: `${pct(rate.value, 1)} · ${ciText(rate)}` })}
        onMouseLeave={() => setTip(null)}
      >
        {rate.ci && (
          <line x1={x(rate.ci[0])} x2={x(rate.ci[1])} y1={cy + dy} y2={cy + dy} stroke={color} strokeWidth={2} strokeLinecap="round" opacity={0.35} />
        )}
        <circle cx={cx} cy={cy + dy} r={6} fill={color} stroke="var(--surface)" strokeWidth={2} />
        <rect x={cx - 14} y={cy + dy - 12} width={28} height={24} fill="transparent" />
      </g>
    );
  };

  return (
    <div>
      <div className="legend">
        <span>
          <i className="swatch" style={{ background: CAVE, borderRadius: 99 }} /> Caved to a wrong crowd (lower is better)
        </span>
        <span>
          <i className="swatch" style={{ background: CORR, borderRadius: 99 }} /> Accepted a correct crowd (higher is better)
        </span>
      </div>
      <div className="chart-wrap">
        <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Caving rate and correction rate per agent with 95% confidence intervals">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={M.top} y2={H - M.bottom} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
              <text x={x(t)} y={H - M.bottom + 18} textAnchor="middle" fontSize={11} fill="var(--muted)">
                {t * 100}%
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const cy = M.top + i * ROW + ROW / 2;
            const a = r.caving.value;
            const b = r.correction.value;
            return (
              <g key={r.agent}>
                <text x={0} y={cy - 4} dy="0.32em" fontSize={12} fontWeight={600} fill="var(--ink)">
                  {r.agent.length > 20 ? r.agent.slice(0, 19) + "…" : r.agent}
                </text>
                <text x={0} y={cy + 11} dy="0.32em" fontSize={11} fill="var(--muted)">
                  {r.discernment == null ? "" : `discernment ${r.discernment >= 0 ? "+" : ""}${r.discernment.toFixed(2)}`}
                </text>
                {a != null && b != null && <line x1={x(a)} x2={x(b)} y1={cy} y2={cy} stroke="var(--axis)" strokeWidth={2} />}
                {dot(r, r.caving, cy, CAVE, "caved to wrong crowd", 0)}
                {dot(r, r.correction, cy, CORR, "accepted correct crowd", 0)}
              </g>
            );
          })}
        </svg>
        {tip && (
          <div
            className="tooltip"
            style={{
              left: `${(tip.x / W) * 100}%`,
              top: `${(tip.y / H) * 100}%`,
              transform: tip.x > W * 0.6 ? "translate(calc(-100% - 12px), -50%)" : "translate(12px, -50%)",
            }}
          >
            <div style={{ fontWeight: 650 }}>{tip.title}</div>
            <div className="ink2">{tip.body}</div>
          </div>
        )}
      </div>
    </div>
  );
}
