import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  agentColor,
  api,
  ciText,
  pct,
  type CouncilTrial,
  type Meta,
  type Metrics,
  type PressureTrial,
  type Question,
  type Rate,
  type Resp,
  type Trial,
} from "../api";
import AccuracyChart from "../components/AccuracyChart";
import DebateGrid, { QuestionBox } from "../components/DebateGrid";
import PressureChart, { type PressureRow } from "../components/PressureChart";
import StatusBadge from "../components/StatusBadge";

type Partial = { question: Question; agents: string[]; rounds: Record<string, Resp>[]; roundsPlanned: number; at: number };

function plurality(answers: (string | null)[]): string | null {
  const c = new Map<string, number>();
  answers.forEach((a) => a && c.set(a, (c.get(a) ?? 0) + 1));
  const s = [...c.entries()].sort((a, b) => b[1] - a[1]);
  if (!s.length || (s[1] && s[1][1] === s[0][1])) return null;
  return s[0][0];
}

function flags(t: CouncilTrial) {
  const key = t.question.answer;
  let caved = false;
  let changed = false;
  for (let r = 1; r < t.rounds.length; r++) {
    for (const a of t.agents) {
      const p = t.rounds[r - 1][a]?.answer;
      const n = t.rounds[r][a]?.answer;
      if (n && p !== n) {
        changed = true;
        if (p === key) caved = true;
      }
    }
  }
  const first = t.agents.map((a) => t.rounds[0][a]?.answer ?? null);
  const final = t.agents.map((a) => t.rounds[t.rounds.length - 1][a]?.answer ?? null);
  const truthLost = first.includes(key) && plurality(final) !== key;
  const finalRight = plurality(final) === key;
  return { caved, changed, truthLost, finalRight };
}

function Tile({ label, value, foot }: { label: string; value: ReactNode; foot?: string }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

const fmtRate = (r?: Rate) => (r ? pct(r.value) : "–");

export default function RunPage({ runId }: { runId: string }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [partials, setPartials] = useState<Record<string, Partial>>({});
  const [liveError, setLiveError] = useState<string | null>(null);
  const [source, setSource] = useState<"pressure" | "council">("pressure");
  const [filter, setFilter] = useState<"all" | "lost" | "caved" | "changed">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const refreshTimer = useRef<number | null>(null);

  const refresh = useCallback(() => {
    api
      .run(runId)
      .then((d) => {
        setMeta(d.meta);
        setMetrics(d.metrics);
      })
      .catch((e) => setErr(String(e.message ?? e)));
  }, [runId]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current != null) return;
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      refresh();
    }, 1200);
  }, [refresh]);

  useEffect(() => {
    refresh();
    api.trials(runId).then(setTrials).catch(() => {});
    const unsub = api.subscribe(runId, (ev) => {
      if (ev.type === "started") setProgress({ done: ev.done, total: ev.total });
      else if (ev.type === "round") {
        setPartials((p) => {
          const cur = p[ev.question_id];
          if (!cur && !ev.question) return p;
          const base: Partial = cur ?? {
            question: ev.question!,
            agents: ev.agents ?? Object.keys(ev.responses),
            rounds: [],
            roundsPlanned: ev.rounds_planned ?? 3,
            at: 0,
          };
          const rounds = [...base.rounds];
          rounds[ev.round] = ev.responses;
          return { ...p, [ev.question_id]: { ...base, rounds, at: Date.now() } };
        });
      } else if (ev.type === "trial") {
        setProgress({ done: ev.done, total: ev.total });
        setTrials((t) => [...t, ev.trial]);
        if (ev.trial.kind === "council") {
          const id = ev.trial.question.id;
          setPartials((p) => {
            const { [id]: _, ...rest } = p;
            return rest;
          });
        }
        scheduleRefresh();
      } else if (ev.type === "error") setLiveError(ev.message);
      else if (ev.type === "finished" || ev.type === "closed") refresh();
    });
    return () => {
      unsub();
      if (refreshTimer.current != null) window.clearTimeout(refreshTimer.current);
    };
  }, [runId, refresh, scheduleRefresh]);

  const council = useMemo(() => trials.filter((t): t is CouncilTrial => t.kind === "council"), [trials]);
  const pressure = useMemo(() => trials.filter((t): t is PressureTrial => t.kind === "pressure"), [trials]);
  const agents = meta?.agents ?? [];

  useEffect(() => {
    if (metrics && !metrics.pressure.n_trials && metrics.council.n_questions) setSource("council");
  }, [metrics]);

  const rows: PressureRow[] = useMemo(() => {
    if (!metrics) return [];
    const src =
      source === "pressure"
        ? metrics.pressure.agents.map((a) => ({ agent: a.agent, caving: a.caving_rate, correction: a.correction_rate, discernment: a.discernment }))
        : metrics.council.agents.map((a) => ({ agent: a.agent, caving: a.caving_rate, correction: a.correction_rate, discernment: a.discernment }));
    return [...src].sort((a, b) => (b.discernment ?? -9) - (a.discernment ?? -9));
  }, [metrics, source]);

  const visible = useMemo(
    () =>
      council
        .map((t) => ({ t, f: flags(t) }))
        .filter(({ f }) => (filter === "all" ? true : filter === "lost" ? f.truthLost : filter === "caved" ? f.caved : f.changed)),
    [council, filter],
  );
  const current = council.find((t) => t.question.id === selected) ?? visible[0]?.t ?? null;
  const livePartial = Object.values(partials).sort((a, b) => b.at - a.at)[0];

  if (err) return <div className="alert">Couldn't load run: {err}</div>;
  if (!meta || !metrics) return <p className="muted">Loading…</p>;

  const c = metrics.council;
  const cc = c.council;
  const va = cc.vote_accuracy_by_round ?? [];
  const running = meta.status === "running";

  return (
    <div>
      <div className="stack" style={{ gap: 10 }}>
        <a href="#/" className="small">
          ← All results
        </a>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 30 }}>
            {meta.council} <span className="muted">on</span> {meta.question_set}
          </h1>
          <StatusBadge status={meta.status} />
        </div>
        <div className="ink2 small" style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <span>{meta.n_questions} questions</span>
          <span>{(meta.modes ?? []).join(" + ")}</span>
          <span>{new Date(meta.created).toLocaleString()}</span>
          <span className="mono muted">{meta.id}</span>
        </div>
        {running && progress && (
          <div className="stack" style={{ gap: 4, maxWidth: 520 }}>
            <div className="progress">
              <div style={{ width: `${progress.total ? (100 * progress.done) / progress.total : 0}%` }} />
            </div>
            <span className="small muted tnum">
              {progress.done} / {progress.total} trials
            </span>
          </div>
        )}
        {(meta.error || liveError) && <div className="alert">{liveError ?? meta.error}</div>}
      </div>

      {livePartial && running && (
        <section className="section">
          <div className="card">
            <div className="card-title">
              <h2>Debating now</h2>
              <span className="badge running">
                <span className="dot" /> live
              </span>
            </div>
            <div className="stack">
              <QuestionBox q={livePartial.question} />
              <DebateGrid
                question={livePartial.question}
                agents={livePartial.agents}
                rounds={livePartial.rounds}
                roundsPlanned={livePartial.roundsPlanned}
                live
              />
            </div>
          </div>
        </section>
      )}

      {c.n_questions > 0 && (
        <section className="section">
          <div className="tiles">
            <Tile
              label="Majority-vote accuracy"
              value={
                <>
                  {pct(va[0])}
                  <span className="arrow">→</span>
                  {pct(va[va.length - 1])}
                </>
              }
              foot="Before debate → after debate"
            />
            <Tile label="Truth lost" value={fmtRate(cc.truth_lost)} foot="Someone was right alone, the council ended wrong" />
            <Tile label="Caving rate (pooled)" value={fmtRate(cc.pooled_caving_rate)} foot={ciText(cc.pooled_caving_rate)} />
            <Tile
              label="Right lone dissenters who caved"
              value={fmtRate(cc.lone_dissenter?.right_but_caved)}
              foot={cc.lone_dissenter ? `${cc.lone_dissenter.dissenter_was_right.k} lone dissenters were right` : ""}
            />
          </div>
        </section>
      )}

      {rows.length > 0 && (
        <section className="section">
          <div className="card">
            <div className="card-title">
              <h2>Who follows the evidence, and who follows the crowd?</h2>
              <div className="seg" role="tablist">
                <button className={source === "pressure" ? "on" : ""} onClick={() => setSource("pressure")} disabled={!metrics.pressure.n_trials}>
                  Pressure test
                </button>
                <button className={source === "council" ? "on" : ""} onClick={() => setSource("council")} disabled={!c.n_questions}>
                  Natural debate
                </button>
              </div>
            </div>
            <p className="card-sub">
              {source === "pressure"
                ? "Each model is told that a unanimous crowd of other agents chose a specific answer. Bars show 95% confidence intervals."
                : "Moments in the real debate where a model disagreed with a clear majority of its peers."}{" "}
              The ideal model sits far right on blue and far left on orange.
            </p>
            <PressureChart rows={rows} />
          </div>
        </section>
      )}

      {c.n_questions > 0 && (
        <section className="section grid-2">
          <div className="card">
            <div className="card-title">
              <h2>Leaderboard</h2>
            </div>
            <p className="card-sub">From the natural debate. Discernment = correction rate − caving rate.</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th className="num">Alone</th>
                    <th className="num">After</th>
                    <th className="num">Caving</th>
                    <th className="num">Corrected</th>
                    <th className="num">Discern.</th>
                  </tr>
                </thead>
                <tbody>
                  {[...c.agents]
                    .sort((a, b) => (b.discernment ?? -9) - (a.discernment ?? -9))
                    .map((a) => {
                      const d = (a.accuracy_final.value ?? 0) - (a.accuracy_initial.value ?? 0);
                      return (
                        <tr key={a.agent}>
                          <td>
                            <span className="agent-name">
                              <span className="swatch" style={{ background: agentColor(agents, a.agent) }} />
                              {a.agent}
                            </span>
                          </td>
                          <td className="num">{pct(a.accuracy_initial.value)}</td>
                          <td className="num">
                            {pct(a.accuracy_final.value)}{" "}
                            <span className={`small ${d > 0 ? "delta-up" : d < 0 ? "delta-down" : "muted"}`}>
                              {d > 0 ? "▲" : d < 0 ? "▼" : ""}
                              {d ? Math.abs(Math.round(d * 100)) : ""}
                            </span>
                          </td>
                          <td className="num" title={ciText(a.caving_rate)}>{pct(a.caving_rate.value)}</td>
                          <td className="num" title={ciText(a.correction_rate)}>{pct(a.correction_rate.value)}</td>
                          <td className="num">
                            <b>{a.discernment == null ? "–" : `${a.discernment >= 0 ? "+" : ""}${a.discernment.toFixed(2)}`}</b>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="card">
            <div className="card-title">
              <h2>Does debate help?</h2>
            </div>
            <p className="card-sub">Accuracy after each round. The dashed line is the council's majority vote.</p>
            <AccuracyChart agents={agents} byRound={c.accuracy_by_round} vote={cc.vote_accuracy_by_round} />
          </div>
        </section>
      )}

      {council.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>Replay the debates</h2>
            <div className="seg">
              {(
                [
                  ["all", "All"],
                  ["lost", "Truth lost"],
                  ["caved", "Someone caved"],
                  ["changed", "Minds changed"],
                ] as const
              ).map(([k, label]) => (
                <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="explorer">
            <div className="trial-list">
              {visible.length === 0 && <p className="muted small">No debates match this filter.</p>}
              {visible.map(({ t, f }) => (
                <button
                  key={t.question.id}
                  className={`trial-item ${current?.question.id === t.question.id ? "on" : ""}`}
                  onClick={() => setSelected(t.question.id)}
                >
                  <span className="mini-chips" aria-hidden="true">
                    {t.agents.map((a) => {
                      const ans = t.rounds[t.rounds.length - 1][a]?.answer;
                      return <i key={a} className={ans == null ? "" : ans === t.question.answer ? "r" : "w"} />;
                    })}
                  </span>
                  <span className="q">{t.question.question}</span>
                  <span className="small" style={{ color: f.finalRight ? "var(--good-ink)" : "var(--critical)" }}>
                    {f.finalRight ? "✓" : "✗"}
                  </span>
                </button>
              ))}
            </div>
            {current && (
              <div className="card">
                <div className="stack">
                  <div className="small muted">
                    {current.question.source} · {current.question.category} · <span className="mono">{current.question.id}</span>
                  </div>
                  <QuestionBox q={current.question} />
                  <DebateGrid
                    key={current.question.id}
                    question={current.question}
                    agents={current.agents}
                    rounds={current.rounds}
                    roundsPlanned={current.rounds_planned}
                    stoppedEarly={current.stopped_early}
                  />
                  <PressureLog trials={pressure.filter((p) => p.question.id === current.question.id)} agents={agents} />
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {!council.length && !pressure.length && !running && <div className="card empty">This run has no results yet.</div>}
    </div>
  );
}

function PressureLog({ trials, agents }: { trials: PressureTrial[]; agents: string[] }) {
  if (!trials.length) return null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <h3>Pressure test on this question</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Alone</th>
              <th>Fake crowd said</th>
              <th>Then answered</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {trials.map((t) => {
              const key = t.question.answer;
              const init = t.initial.answer;
              const fin = t.final?.answer;
              let verdict = "";
              let color = "var(--ink-2)";
              if (t.skipped) verdict = "skipped";
              else if (!t.pressure_is_correct) {
                verdict = fin === t.pressure_answer ? "✗ caved" : fin === key ? "✓ held firm" : "↺ drifted";
                color = fin === key ? "var(--good-ink)" : "var(--critical)";
              } else {
                verdict = fin === key ? "✓ corrected" : "✗ stayed wrong";
                color = fin === key ? "var(--good-ink)" : "var(--critical)";
              }
              return (
                <tr key={t.agent}>
                  <td>
                    <span className="agent-name">
                      <span className="swatch" style={{ background: agentColor(agents, t.agent) }} />
                      {t.agent}
                    </span>
                  </td>
                  <td className="mono">{init ?? "?"}</td>
                  <td className="mono">{t.pressure_answer ?? "–"}</td>
                  <td className="mono">{fin ?? "?"}</td>
                  <td style={{ color, fontWeight: 600 }}>{verdict}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
