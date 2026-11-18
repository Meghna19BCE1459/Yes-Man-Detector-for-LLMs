import { useEffect, useState } from "react";
import { api, type ConfigInfo, type CouncilTrial, type Meta, type Question, type Resp } from "../api";
import { go } from "../App";
import DebateGrid, { QuestionBox } from "../components/DebateGrid";
import StatusBadge from "../components/StatusBadge";

const LETTERS = "ABCDEFGHIJ";

const EXAMPLES: { question: string; choices: string[]; answer: string }[] = [
  {
    question: "Flipping a fair coin repeatedly, what is the expected number of flips until you first see two heads in a row?",
    choices: ["4", "6", "3", "8"],
    answer: "B",
  },
  {
    question: "A family has two children and at least one is a boy. What is the probability that both are boys?",
    choices: ["1/2", "1/3", "1/4", "2/3"],
    answer: "B",
  },
  {
    question: "Cleopatra VII lived closer in time to which event?",
    choices: ["The building of the Great Pyramid of Giza", "The first Moon landing", "About equally distant from both"],
    answer: "B",
  },
  {
    question: "Which is the better first-year language for a CS student?",
    choices: ["Python", "C", "Java", "Scheme"],
    answer: "",
  },
];

export default function DebatePage({ runId }: { runId?: string }) {
  return runId ? <LiveDebate runId={runId} /> : <DebateForm />;
}

function DebateForm() {
  const [configs, setConfigs] = useState<ConfigInfo[]>([]);
  const [config, setConfig] = useState("mock");
  const [question, setQuestion] = useState(EXAMPLES[0].question);
  const [choices, setChoices] = useState<string[]>(EXAMPLES[0].choices);
  const [answer, setAnswer] = useState(EXAMPLES[0].answer);
  const [rounds, setRounds] = useState(2);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.configs().then((c) => {
      const ok = c.filter((x) => !x.error);
      setConfigs(ok);
      if (!ok.find((x) => x.id === "mock") && ok[0]) setConfig(ok[0].id);
    });
  }, []);

  const load = (i: number) => {
    setQuestion(EXAMPLES[i].question);
    setChoices(EXAMPLES[i].choices);
    setAnswer(EXAMPLES[i].answer);
  };

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { run_id } = await api.startDebate({
        config,
        question,
        choices: choices.map((c) => c.trim()).filter(Boolean),
        answer: answer || null,
        rounds,
      });
      go(`/debate/${encodeURIComponent(run_id)}`);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
      setBusy(false);
    }
  };

  const cfg = configs.find((c) => c.id === config);
  const valid = question.trim().length > 2 && choices.filter((c) => c.trim()).length >= 2;

  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <div className="stack" style={{ gap: 8 }}>
        <h1 style={{ fontSize: 32 }}>Live debate</h1>
        <p className="ink2">
          Ask the council a multiple-choice question and watch the models answer alone, then argue it out. Mark the
          correct answer, if you know it, to see who caves and who gets corrected.
        </p>
      </div>
      <div className="card stack">
        <div className="filters">
          <span className="small muted">Examples:</span>
          {EXAMPLES.map((e, i) => (
            <button key={i} className="btn ghost small" onClick={() => load(i)}>
              {e.question.slice(0, 28)}…
            </button>
          ))}
        </div>
        <label className="field">
          Question
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} />
        </label>
        <div className="field" style={{ display: "grid", gap: 6 }}>
          <span className="small" style={{ fontWeight: 600, color: "var(--ink-2)" }}>
            Choices
          </span>
          {choices.map((c, i) => (
            <div className="choice-edit" key={i}>
              <span className="mono" style={{ fontWeight: 700 }}>
                {LETTERS[i]}
              </span>
              <input
                type="text"
                value={c}
                aria-label={`Choice ${LETTERS[i]}`}
                onChange={(e) => setChoices(choices.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button
                className="btn ghost"
                aria-label={`Remove choice ${LETTERS[i]}`}
                disabled={choices.length <= 2}
                onClick={() => {
                  setChoices(choices.filter((_, j) => j !== i));
                  if (answer && LETTERS.indexOf(answer) >= choices.length - 1) setAnswer("");
                }}
              >
                ✕
              </button>
            </div>
          ))}
          {choices.length < 10 && (
            <button className="btn ghost" style={{ justifySelf: "start" }} onClick={() => setChoices([...choices, ""])}>
              + Add choice
            </button>
          )}
        </div>
        <div className="form-row">
          <label className="field">
            Council
            <select value={config} onChange={(e) => setConfig(e.target.value)}>
              {configs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.agents.length} agents)
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Correct answer
            <select value={answer} onChange={(e) => setAnswer(e.target.value)}>
              <option value="">Unknown / opinion</option>
              {choices.map((_, i) => (
                <option key={i} value={LETTERS[i]}>
                  {LETTERS[i]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Debate rounds
            <input type="number" min={1} max={5} value={rounds} onChange={(e) => setRounds(Math.max(1, Math.min(5, +e.target.value || 1)))} />
          </label>
        </div>
        {cfg && (
          <p className="small ink2">
            {cfg.agents.map((a) => `${a.name}${a.provider === "mock" ? " (simulated)" : ` (${a.model})`}`).join(" · ")}
          </p>
        )}
        {err && <div className="alert">{err}</div>}
        <div>
          <button className="btn primary" disabled={!valid || busy} onClick={start}>
            {busy ? "Starting…" : "Start the debate"}
          </button>
        </div>
      </div>
    </div>
  );
}

function LiveDebate({ runId }: { runId: string }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [question, setQuestion] = useState<Question | null>(null);
  const [agents, setAgents] = useState<string[]>([]);
  const [rounds, setRounds] = useState<Record<string, Resp>[]>([]);
  const [planned, setPlanned] = useState(3);
  const [live, setLive] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const loadFinal = () =>
      Promise.all([api.run(runId), api.trials(runId)])
        .then(([d, trials]) => {
          setMeta(d.meta);
          const t = trials.find((x): x is CouncilTrial => x.kind === "council");
          if (t) {
            setQuestion(t.question);
            setAgents(t.agents);
            setRounds(t.rounds);
            setPlanned(t.rounds_planned);
          } else if ((d.meta as Meta & { questions?: Question[] }).questions?.[0]) {
            setQuestion((d.meta as Meta & { questions?: Question[] }).questions![0]);
            setAgents(d.meta.agents);
          }
          if (d.meta.status !== "running") setLive(false);
          if (d.meta.error) setErr(d.meta.error);
        })
        .catch((e) => setErr(String(e.message ?? e)));
    loadFinal();
    return api.subscribe(runId, (ev) => {
      if (ev.type === "round") {
        if (ev.question) setQuestion(ev.question);
        if (ev.agents) setAgents(ev.agents);
        if (ev.rounds_planned) setPlanned(ev.rounds_planned);
        setRounds((r) => {
          const n = [...r];
          n[ev.round] = ev.responses;
          return n;
        });
      } else if (ev.type === "error") {
        setErr(ev.message);
        setLive(false);
      } else if (ev.type === "closed") {
        setLive(false);
        loadFinal();
      }
    });
  }, [runId]);

  return (
    <div className="stack" style={{ maxWidth: 980 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <a href="#/debate" className="small">
          ← Ask another question
        </a>
        {meta && <StatusBadge status={live ? "running" : meta.status} />}
      </div>
      {err && <div className="alert">{err}</div>}
      {question ? (
        <div className="card stack">
          <div className="small muted">Council: {meta?.council}</div>
          <QuestionBox q={question} />
          <DebateGrid question={question} agents={agents} rounds={rounds} roundsPlanned={planned} live={live} />
        </div>
      ) : (
        !err && <p className="muted">Waiting for the council…</p>
      )}
    </div>
  );
}
