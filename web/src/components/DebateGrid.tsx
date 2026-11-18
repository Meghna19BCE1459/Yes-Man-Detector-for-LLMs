import { useState } from "react";
import { agentColor, type Question, type Resp } from "../api";

const LETTERS = "ABCDEFGHIJKLMNOP";

type Props = {
  question: Question;
  agents: string[]; // council order (drives colors)
  rounds: Record<string, Resp>[];
  roundsPlanned: number;
  live?: boolean;
  stoppedEarly?: boolean;
};

function plurality(answers: (string | null)[]): string | null {
  const c = new Map<string, number>();
  answers.forEach((a) => a && c.set(a, (c.get(a) ?? 0) + 1));
  const sorted = [...c.entries()].sort((a, b) => b[1] - a[1]);
  if (!sorted.length || (sorted[1] && sorted[1][1] === sorted[0][1])) return null;
  return sorted[0][0];
}

export function QuestionBox({ q }: { q: Question }) {
  return (
    <div className="question-box">
      <div className="question-text">{q.question}</div>
      <div className="choices">
        {q.choices.map((c, i) => {
          const l = LETTERS[i];
          const key = q.answer === l;
          return (
            <div key={l} className={`choice ${key ? "key" : ""}`}>
              <span className="letter">{l}</span>
              <span>
                {c}
                {key && <span className="tag corrected"> ✓ correct</span>}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function DebateGrid({ question, agents, rounds, roundsPlanned, live, stoppedEarly }: Props) {
  const [sel, setSel] = useState<{ agent: string; round: number } | null>(null);
  const key = question.answer || null;
  const nCols = live ? roundsPlanned + 1 : rounds.length;
  const cols = Array.from({ length: nCols }, (_, i) => i);
  const selected = sel ? rounds[sel.round]?.[sel.agent] : null;

  return (
    <div className="stack">
      <div className="debate">
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              {cols.map((r) => (
                <th key={r}>{r === 0 ? "Alone" : `Round ${r}`}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a}>
                <td className="agent-cell">
                  <span className="agent-name">
                    <span className="swatch" style={{ background: agentColor(agents, a) }} />
                    {a}
                  </span>
                </td>
                {cols.map((r) => {
                  const resp = rounds[r]?.[a];
                  if (!resp) {
                    const pending = live && r === rounds.length;
                    return (
                      <td key={r}>
                        {pending ? (
                          <span className="thinking" aria-label="thinking">
                            <i />
                            <i />
                            <i />
                          </span>
                        ) : (
                          <span className="muted small">{live ? "" : "–"}</span>
                        )}
                      </td>
                    );
                  }
                  const prev = r > 0 ? rounds[r - 1]?.[a]?.answer ?? null : null;
                  const ans = resp.answer;
                  const changed = r > 0 && prev !== ans && ans != null;
                  const isRight = key ? ans === key : null;
                  let tag: { cls: string; text: string } | null = null;
                  if (changed && key) {
                    if (prev === key) tag = { cls: "caved", text: `✗ caved (was ${prev})` };
                    else if (ans === key) tag = { cls: "corrected", text: `✓ corrected (was ${prev ?? "?"})` };
                    else tag = { cls: "switched", text: `↺ was ${prev}` };
                  } else if (changed) tag = { cls: "switched", text: `↺ was ${prev}` };
                  const isSel = sel?.agent === a && sel.round === r;
                  return (
                    <td key={r}>
                      <button
                        className={`cell-btn ${isSel ? "selected" : ""}`}
                        onClick={() => setSel(isSel ? null : { agent: a, round: r })}
                        aria-label={`${a}, ${r === 0 ? "alone" : "round " + r}: answer ${ans ?? "none"}${
                          isRight == null ? "" : isRight ? ", correct" : ", wrong"
                        }. Show reasoning`}
                      >
                        <span className={`chip ${ans == null ? "none" : isRight == null ? "" : isRight ? "right" : "wrong"}`}>
                          {ans ?? "?"}
                        </span>
                        <span className="cell-meta">
                          <span className="tnum">{resp.confidence != null ? `${Math.round(resp.confidence)}% sure` : resp.error ? "error" : ""}</span>
                          {tag && <span className={`tag ${tag.cls}`}>{tag.text}</span>}
                        </span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="vote-row">
              <td className="agent-cell">Majority vote</td>
              {cols.map((r) => {
                const rr = rounds[r];
                if (!rr) return <td key={r} />;
                const v = plurality(agents.map((a) => rr[a]?.answer ?? null));
                return (
                  <td key={r}>
                    <span style={{ paddingLeft: 8 }}>
                      <b className="tnum" style={{ color: key && v ? (v === key ? "var(--good-ink)" : "var(--critical)") : undefined }}>
                        {v ?? "tie"}
                      </b>
                      {key && v && <span className="muted">{v === key ? " ✓" : " ✗"}</span>}
                    </span>
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
      {stoppedEarly && !live && rounds.length === 1 && (
        <p className="small muted">Everyone agreed from the start, so no debate was needed.</p>
      )}
      {sel && selected ? (
        <div className="stack" style={{ gap: 8 }}>
          <h3>
            <span className="agent-name">
              <span className="swatch" style={{ background: agentColor(agents, sel.agent) }} />
              {sel.agent}, {sel.round === 0 ? "answering alone" : `round ${sel.round}`}
            </span>
          </h3>
          <div className="reasoning">{selected.error && !selected.reasoning ? `Error: ${selected.error}` : selected.reasoning || "(no reasoning)"}</div>
        </div>
      ) : (
        <p className="small muted">Click any cell to read that agent's reasoning.</p>
      )}
    </div>
  );
}
