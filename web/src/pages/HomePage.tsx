import { useEffect, useState } from "react";
import { api, type Meta } from "../api";
import StatusBadge from "../components/StatusBadge";

export default function HomePage() {
  const [runs, setRuns] = useState<Meta[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.runs().then(setRuns).catch((e) => setErr(String(e.message ?? e)));
  }, []);

  const experiments = runs?.filter((r) => !r.live) ?? [];
  const debates = runs?.filter((r) => r.live) ?? [];

  return (
    <div>
      <section className="hero">
        <div className="eyebrow">Multi-LLM conformity research</div>
        <h1>Do AI models abandon the truth under peer pressure?</h1>
        <p className="lede">
          Several language models from different labs answer hard questions on their own, then see each other's answers
          and debate. We measure who <b>caves</b> to a wrong majority, who gets <b>corrected</b> by a right one, and
          whether debate actually beats a simple vote.
        </p>
        <div className="cta">
          <a className="btn primary" href="#/debate">
            Watch a live debate
          </a>
          <a className="btn" href="#/new">
            Run an experiment
          </a>
        </div>
        <div className="how">
          <div className="card">
            <div className="step-n">1 · ALONE</div>
            <h3>Independent answers</h3>
            <p className="small ink2">Each model answers with no knowledge of the others.</p>
          </div>
          <div className="card">
            <div className="step-n">2 · DEBATE</div>
            <h3>Anonymous peer review</h3>
            <p className="small ink2">Models see the others' answers and reasoning, then revise over several rounds.</p>
          </div>
          <div className="card">
            <div className="step-n">3 · PRESSURE TEST</div>
            <h3>A fake unanimous crowd</h3>
            <p className="small ink2">
              A model that was right is told everyone disagrees. Does it hold firm? A model that was wrong is shown the
              right crowd. Does it listen?
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Experiments</h2>
          <span className="muted small">{experiments.length} run{experiments.length === 1 ? "" : "s"}</span>
        </div>
        {err && <div className="alert">Couldn't reach the API: {err}. Is the server running (`yesman serve`)?</div>}
        {runs && !experiments.length && (
          <div className="card empty">
            No experiments yet. Start one from <a href="#/new">New experiment</a>, or run <code>yesman demo</code> in
            a terminal.
          </div>
        )}
        <div className="run-list">
          {experiments.map((r) => (
            <RunRow key={r.id} r={r} />
          ))}
        </div>
      </section>

      {debates.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>Live debates</h2>
          </div>
          <div className="run-list">
            {debates.slice(0, 8).map((r) => (
              <RunRow key={r.id} r={r} href={`#/debate/${encodeURIComponent(r.id)}`} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function RunRow({ r, href }: { r: Meta; href?: string }) {
  return (
    <a className="card run-row" href={href ?? `#/runs/${encodeURIComponent(r.id)}`}>
      <div>
        <div style={{ fontWeight: 650 }}>
          {r.council} <span className="muted">·</span> {r.question_set}
        </div>
        <div className="meta">
          <span>{new Date(r.created).toLocaleString()}</span>
          <span>{r.n_questions} question{r.n_questions === 1 ? "" : "s"}</span>
          <span>{(r.agents ?? []).join(", ")}</span>
        </div>
      </div>
      <StatusBadge status={r.status} />
    </a>
  );
}
