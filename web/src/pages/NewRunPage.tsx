import { useEffect, useState } from "react";
import { api, type ConfigInfo } from "../api";
import { go } from "../App";

export default function NewRunPage() {
  const [configs, setConfigs] = useState<ConfigInfo[]>([]);
  const [sets, setSets] = useState<{ id: string; count: number }[]>([]);
  const [config, setConfig] = useState("");
  const [qset, setQset] = useState("");
  const [mode, setMode] = useState<"both" | "council" | "pressure">("both");
  const [limit, setLimit] = useState<number | "">(10);
  const [rounds, setRounds] = useState(3);
  const [share, setShare] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.configs().then((c) => {
      setConfigs(c);
      const first = c.find((x) => x.id === "mock" && !x.error) ?? c.find((x) => !x.error);
      if (first) {
        setConfig(first.id);
        setRounds(first.rounds);
      }
    });
    api.questionSets().then((s) => {
      setSets(s);
      if (s[0]) setQset((s.find((x) => x.id === "traps") ?? s[0]).id);
    });
  }, []);

  const cfg = configs.find((c) => c.id === config);
  const qs = sets.find((s) => s.id === qset);
  const n = Math.min(qs?.count ?? 0, limit || Infinity);
  const nAgents = cfg?.agents.length ?? 0;
  const maxCalls = (mode !== "pressure" ? n * nAgents * (rounds + 1) : 0) + (mode !== "council" ? n * nAgents * (mode === "both" ? 1 : 2) : 0);
  const realModels = cfg?.agents.some((a) => a.provider !== "mock");

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { run_id } = await api.startRun({
        config,
        question_set: qset,
        mode,
        limit: limit || null,
        rounds,
        share_reasoning: share,
      });
      go(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <div className="stack" style={{ gap: 8 }}>
        <h1 style={{ fontSize: 32 }}>New experiment</h1>
        <p className="ink2">
          Pick a council and a question set. Runs are saved as you go and can be resumed from the command line with{" "}
          <code>yesman run --run-id …</code>.
        </p>
      </div>
      <div className="card stack">
        <div className="form-row">
          <label className="field">
            Council
            <select
              value={config}
              onChange={(e) => {
                setConfig(e.target.value);
                const c = configs.find((x) => x.id === e.target.value);
                if (c?.rounds) setRounds(c.rounds);
              }}
            >
              {configs.map((c) => (
                <option key={c.id} value={c.id} disabled={!!c.error}>
                  {c.error ? `${c.id} (invalid config)` : `${c.name} (${c.agents.length} agents)`}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Question set
            <select value={qset} onChange={(e) => setQset(e.target.value)}>
              {sets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id} ({s.count})
                </option>
              ))}
            </select>
          </label>
        </div>
        {cfg && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Provider</th>
                  <th>Model</th>
                </tr>
              </thead>
              <tbody>
                {cfg.agents.map((a) => (
                  <tr key={a.name}>
                    <td>{a.name}</td>
                    <td>{a.provider}</td>
                    <td className="mono">{a.provider === "mock" ? "simulated" : a.model}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="form-row">
          <label className="field">
            Experiment
            <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="both">Debate + pressure test</option>
              <option value="council">Debate only</option>
              <option value="pressure">Pressure test only</option>
            </select>
          </label>
          <label className="field">
            Questions (max)
            <input type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value ? Math.max(1, +e.target.value) : "")} placeholder="all" />
          </label>
          <label className="field">
            Debate rounds
            <input type="number" min={1} max={10} value={rounds} onChange={(e) => setRounds(Math.max(1, Math.min(10, +e.target.value || 1)))} />
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
          Agents see each other's reasoning (off = answers and confidence only)
        </label>
        <div className="alert note small">
          Up to <b className="tnum">{maxCalls.toLocaleString()}</b> model calls ({n} questions × {nAgents} agents). Debates stop early
          when everyone already agrees.
          {realModels && " This council uses real APIs: make sure the keys are in your .env file and run `yesman check` first."}
        </div>
        {err && <div className="alert">{err}</div>}
        <div>
          <button className="btn primary" onClick={start} disabled={busy || !config || !qset}>
            {busy ? "Starting…" : "Start experiment"}
          </button>
        </div>
      </div>
    </div>
  );
}
