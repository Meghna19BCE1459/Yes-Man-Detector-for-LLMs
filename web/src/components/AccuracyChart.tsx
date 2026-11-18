import { useMemo, useState } from "react";
import { agentColor, pct } from "../api";

type Props = {
  agents: string[];
  byRound: Record<string, (number | null)[]>;
  vote?: (number | null)[];
};

const W = 640;
const H = 300;
const M = { top: 16, right: 120, bottom: 36, left: 44 };

export default function AccuracyChart({ agents, byRound, vote }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const nRounds = Math.max(...agents.map((a) => byRound[a]?.length ?? 0), vote?.length ?? 0);
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const x = (r: number) => M.left + (nRounds <= 1 ? iw / 2 : (r / (nRounds - 1)) * iw);
  const y = (v: number) => M.top + (1 - v) * ih;

  const series = useMemo(() => {
    const s = agents.map((a) => ({ name: a, color: agentColor(agents, a), values: byRound[a] ?? [], dashed: false }));
    if (vote) s.push({ name: "Majority vote", color: "var(--ink)", values: vote, dashed: true });
    return s;
  }, [agents, byRound, vote]);

  // End labels with simple collision avoidance (min 15px apart).
  const labels = useMemo(() => {
    const items = series
      .map((s) => {
        const last = s.values[s.values.length - 1];
        return last == null ? null : { name: s.name, color: s.color, y: y(last), v: last };
      })
      .filter(Boolean) as { name: string; color: string; y: number; v: number }[];
    items.sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) items[i].y = Math.max(items[i].y, items[i - 1].y + 15);
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series]);

  if (!nRounds) return null;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div>
      <div className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i className={`line-key ${s.dashed ? "dashed" : ""}`} style={{ borderColor: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      <div className="chart-wrap">
        <svg
          className="chart"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Accuracy by debate round for each agent and the majority vote"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = ((e.clientX - rect.left) / rect.width) * W;
            let best = 0;
            for (let r = 0; r < nRounds; r++) if (Math.abs(x(r) - px) < Math.abs(x(best) - px)) best = r;
            setHover(best);
          }}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
              <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--muted)">
                {t * 100}%
              </text>
            </g>
          ))}
          {Array.from({ length: nRounds }, (_, r) => (
            <text key={r} x={x(r)} y={H - M.bottom + 20} textAnchor="middle" fontSize={11} fill="var(--muted)">
              {r === 0 ? "Alone" : `Round ${r}`}
            </text>
          ))}
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + ih} stroke="var(--axis)" strokeWidth={1} />}
          {series.map((s) => {
            const pts = s.values.map((v, r) => (v == null ? null : [x(r), y(v)] as const)).filter(Boolean) as (readonly [number, number])[];
            return (
              <g key={s.name}>
                <path
                  d={pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join("")}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dashed ? "5 4" : undefined}
                  strokeLinejoin="round"
                />
                {pts.map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={hover === i ? 5 : 4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                ))}
              </g>
            );
          })}
          {labels.map((l) => (
            <text key={l.name} x={W - M.right + 10} y={l.y} dy="0.32em" fontSize={11} fill="var(--ink-2)">
              {l.name.length > 16 ? l.name.slice(0, 15) + "…" : l.name}
            </text>
          ))}
        </svg>
        {hover != null && (
          <div
            className="tooltip"
            style={{
              left: `${(x(hover) / W) * 100}%`,
              top: 8,
              transform: x(hover) > W * 0.55 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
            }}
          >
            <div style={{ fontWeight: 650, marginBottom: 4 }}>{hover === 0 ? "Answering alone" : `After round ${hover}`}</div>
            {[...series]
              .sort((a, b) => (b.values[hover] ?? -1) - (a.values[hover] ?? -1))
              .map((s) => (
                <div className="row" key={s.name}>
                  <span>
                    <i className="swatch" style={{ background: s.color }} />
                    {s.name}
                  </span>
                  <b className="tnum">{pct(s.values[hover], 1)}</b>
                </div>
              ))}
          </div>
        )}
      </div>
      <button className="btn ghost table-toggle" onClick={() => setShowTable((v) => !v)}>
        {showTable ? "Hide table" : "Show as table"}
      </button>
      {showTable && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Series</th>
                {Array.from({ length: nRounds }, (_, r) => (
                  <th key={r} className="num">{r === 0 ? "Alone" : `R${r}`}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {series.map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td>
                  {Array.from({ length: nRounds }, (_, r) => (
                    <td key={r} className="num">{pct(s.values[r], 1)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
