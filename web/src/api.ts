export type Rate = { k: number; n: number; value: number | null; ci: [number, number] | null };

export type Resp = {
  answer: string | null;
  confidence: number | null;
  reasoning: string;
  raw?: string;
  error?: string | null;
  latency_s?: number;
};

export type Question = {
  id: string;
  question: string;
  choices: string[];
  answer: string;
  category: string;
  source: string;
};

export type CouncilTrial = {
  kind: "council";
  question: Question;
  agents: string[];
  rounds_planned: number;
  stopped_early: boolean;
  rounds: Record<string, Resp>[];
};

export type PressureTrial = {
  kind: "pressure";
  question: Question;
  agent: string;
  initial: Resp;
  final?: Resp;
  pressure_answer?: string;
  pressure_is_correct?: boolean;
  skipped?: string;
};

export type Trial = CouncilTrial | PressureTrial;

export type CouncilAgent = {
  agent: string;
  n: number;
  accuracy_initial: Rate;
  accuracy_final: Rate;
  events: Record<string, number>;
  caving_rate: Rate;
  correction_rate: Rate;
  discernment: number | null;
  conformity: Rate;
  avg_confidence_change_when_caving: number | null;
};

export type PressureAgent = {
  agent: string;
  caving_rate: Rate;
  correction_rate: Rate;
  discernment: number | null;
  drift_rate: Rate;
};

export type Metrics = {
  council: {
    n_questions: number;
    rounds?: number;
    agents: CouncilAgent[];
    accuracy_by_round: Record<string, (number | null)[]>;
    council: {
      vote_accuracy_by_round?: (number | null)[];
      truth_lost?: Rate;
      truth_found?: Rate;
      unanimous_wrong_final?: Rate;
      pooled_caving_rate?: Rate;
      pooled_correction_rate?: Rate;
      lone_dissenter?: {
        cases: number;
        dissenter_was_right: Rate;
        right_but_caved: Rate;
        right_and_convinced_council: Rate;
      };
    };
  };
  pressure: { n_trials: number; agents: PressureAgent[] };
};

export type Meta = {
  id: string;
  status: string;
  council: string;
  agents: string[];
  question_set: string;
  n_questions: number;
  modes: string[];
  created: string;
  error?: string;
  live?: boolean;
};

export type ConfigInfo = {
  id: string;
  name: string;
  rounds: number;
  agents: { name: string; provider: string; model: string }[];
  error?: string;
};

export type RunEvent =
  | { type: "started"; total: number; done: number }
  | {
      type: "round";
      question_id: string;
      round: number;
      responses: Record<string, Resp>;
      question?: Question;
      agents?: string[];
      rounds_planned?: number;
    }
  | { type: "trial"; trial: Trial; done: number; total: number }
  | { type: "pressure"; question_id: string; agent: string; trial: PressureTrial }
  | { type: "finished"; done: number; total: number }
  | { type: "error"; message: string }
  | { type: "closed" };

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return r.json();
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  runs: () => j<Meta[]>("/api/runs"),
  run: (id: string) => j<{ meta: Meta; metrics: Metrics }>(`/api/runs/${encodeURIComponent(id)}`),
  trials: (id: string) => j<Trial[]>(`/api/runs/${encodeURIComponent(id)}/trials`),
  configs: () => j<ConfigInfo[]>("/api/configs"),
  questionSets: () => j<{ id: string; count: number }[]>("/api/question-sets"),
  startRun: (body: object) => j<{ run_id: string }>("/api/runs", post(body)),
  startDebate: (body: object) => j<{ run_id: string }>("/api/debate", post(body)),
  subscribe(id: string, onEvent: (e: RunEvent) => void): () => void {
    const es = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as RunEvent;
      onEvent(ev);
      if (ev.type === "closed") es.close();
    };
    es.onerror = () => es.close();
    return () => es.close();
  },
};

/** Fixed categorical order: color follows the agent's position in the council, never its rank. */
export function agentColor(agents: string[], name: string): string {
  const i = agents.indexOf(name);
  return `var(--series-${(i >= 0 ? i % 8 : 7) + 1})`;
}

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "–" : `${(v * 100).toFixed(digits)}%`;

export const ciText = (r?: Rate | null) =>
  r?.ci ? `95% CI ${Math.round(r.ci[0] * 100)}–${Math.round(r.ci[1] * 100)}%, n=${r.n}` : r ? `n=${r.n}` : "";
