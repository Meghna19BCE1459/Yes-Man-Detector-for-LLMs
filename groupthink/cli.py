"""Command line interface: `yesman <command>`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_config
from .metrics import compute_metrics
from .questions import fetch_mmlu_pro, load_questions, save_questions
from .store import RunStore, list_runs, new_run_id


def _pct(r: dict | None) -> str:
    if not r or r.get("value") is None:
        return "   -  "
    return f"{100 * r['value']:5.1f}%"


def _ci(r: dict | None) -> str:
    if not r or not r.get("ci"):
        return ""
    lo, hi = r["ci"]
    return f"[{100 * lo:.0f}-{100 * hi:.0f}] n={r['n']}"


def print_report(run_id: str) -> None:
    store = RunStore(run_id)
    meta = store.read_meta()
    m = compute_metrics(store.trials())
    c = m["council"]
    print(f"\nRun {run_id}  ({meta.get('council', '?')}, {meta.get('question_set', '?')}, status={meta.get('status')})")

    if c["n_questions"]:
        print(f"\nCOUNCIL DEBATE  -  {c['n_questions']} questions, up to {c['rounds']} revision rounds")
        hdr = f"{'agent':<22}{'acc r0':>8}{'final':>8}{'caving':>9}{'correct':>9}{'discern':>9}{'conform':>9}"
        print(hdr)
        print("-" * len(hdr))
        for a in c["agents"]:
            d = a["discernment"]
            print(
                f"{a['agent'][:21]:<22}{_pct(a['accuracy_initial']):>8}{_pct(a['accuracy_final']):>8}"
                f"{_pct(a['caving_rate']):>9}{_pct(a['correction_rate']):>9}"
                f"{(f'{d:+.2f}' if d is not None else '-'):>9}{_pct(a['conformity']):>9}"
            )
        cc = c["council"]
        va = cc["vote_accuracy_by_round"]
        print(f"\n  Majority-vote accuracy: round 0 {100 * va[0]:.1f}%  ->  final {100 * va[-1]:.1f}%")
        print(f"  Truth lost (someone was right at r0, council ended wrong): {_pct(cc['truth_lost'])}  {_ci(cc['truth_lost'])}")
        print(f"  Truth found (council wrong at r0, right at the end):       {_pct(cc['truth_found'])}  {_ci(cc['truth_found'])}")
        print(f"  Ended unanimous AND wrong:                                 {_pct(cc['unanimous_wrong_final'])}")
        ld = cc["lone_dissenter"]
        if ld["cases"]:
            print(f"  Lone dissenters: {ld['cases']} cases, right {_pct(ld['dissenter_was_right'])}, "
                  f"of those caved {_pct(ld['right_but_caved'])}, convinced the council {_pct(ld['right_and_convinced_council'])}")

    p = m["pressure"]
    if p["n_trials"]:
        print(f"\nSYNTHETIC PRESSURE  -  {p['n_trials']} trials (unanimous fake crowd)")
        hdr = f"{'agent':<22}{'caving':>9}{'  95% CI':<18}{'correct':>9}{'  95% CI':<18}{'discern':>9}"
        print(hdr)
        print("-" * len(hdr))
        for a in p["agents"]:
            d = a["discernment"]
            print(
                f"{a['agent'][:21]:<22}{_pct(a['caving_rate']):>9}  {_ci(a['caving_rate']):<16}"
                f"{_pct(a['correction_rate']):>9}  {_ci(a['correction_rate']):<16}"
                f"{(f'{d:+.2f}' if d is not None else '-'):>9}"
            )
    print("\ncaving = abandoned a correct answer for a wrong majority (lower is better)")
    print("correct = adopted a correct majority after being wrong (higher is better)")
    print("discern = correct - caving: follows evidence (+) vs follows the crowd (0 or -)\n")


async def _run(args) -> str:
    from .runner import execute

    cfg = load_config(args.config)
    if args.rounds is not None:
        cfg.rounds = args.rounds
    if args.no_reasoning:
        cfg.share_reasoning = False
    qs = load_questions(args.questions, limit=args.limit, shuffle_seed=args.shuffle_seed)
    modes = ("council", "pressure") if args.mode == "both" else (args.mode,)
    run_id = args.run_id or new_run_id(cfg.name)
    store = RunStore(run_id)

    def on_event(ev: dict) -> None:
        if ev["type"] == "started":
            print(f"Run {run_id}: {ev['total']} trials ({ev['done']} already done)")
        elif ev["type"] == "trial_failed":
            t = ev["trial"]
            who = t.get("agent") or "a council member"
            print(f"  [!] API error on {t['question']['id']} ({who}); not saved, will retry when you rerun this command")
        elif ev["type"] == "finished" and ev.get("failed"):
            print(f"\n{ev['failed']} trial(s) hit API errors (often a rate limit). "
                  f"Rerun the same command with --run-id {run_id} to retry just those.")
        elif ev["type"] == "trial":
            t = ev["trial"]
            q = t["question"]
            if t["kind"] == "council":
                final = t["rounds"][-1]
                summary = " ".join(f"{k.split()[0]}={v.get('answer') or '?'}" for k, v in final.items())
                mark = "agree" if t["stopped_early"] and len(t["rounds"]) == 1 else f"{len(t['rounds']) - 1} rounds"
                print(f"  [{ev['done']}/{ev['total']}] council  {q['id']:<16} key={q['answer']}  {summary}  ({mark})")
            else:
                if t.get("skipped"):
                    print(f"  [{ev['done']}/{ev['total']}] pressure {q['id']:<16} {t['agent']}: skipped")
                else:
                    print(f"  [{ev['done']}/{ev['total']}] pressure {q['id']:<16} {t['agent']}: "
                          f"{t['initial']['answer']} -> crowd says {t['pressure_answer']} -> {t['final']['answer']}")

    await execute(cfg, qs, store, modes, question_set=Path(args.questions).stem, emit=on_event)
    return run_id


async def _check(args) -> None:
    from dotenv import load_dotenv

    from .parsing import parse_response
    from .providers import ChatClient

    load_dotenv()
    cfg = load_config(args.config)
    client = ChatClient(cfg.providers)
    msgs = [{"role": "user", "content": "What is 2+2? Options: A. 3  B. 4  C. 5\nEnd with:\nANSWER: <letter>\nCONFIDENCE: <0-100>"}]
    ok = True
    try:
        for a in cfg.agents:
            if a.provider == "mock":
                print(f"  ok    {a.name:<22} (simulated)")
                continue
            try:
                res = await client.chat(a.provider, a.model, msgs, max_tokens=cfg.max_tokens, max_attempts=2)
                letter, conf, _ = parse_response(res.text, 3)
                status = "ok  " if letter == "B" else "WARN"
                ok &= letter == "B"
                print(f"  {status}  {a.name:<22} {a.provider}/{a.model}  answer={letter} conf={conf} {res.latency_s:.1f}s")
            except Exception as e:
                ok = False
                print(f"  FAIL  {a.name:<22} {a.provider}/{a.model}  {str(e)[:200]}")
    finally:
        await client.aclose()
    sys.exit(0 if ok else 1)


async def _models(args) -> None:
    from dotenv import load_dotenv

    from .providers import ChatClient

    load_dotenv()
    client = ChatClient()
    try:
        ids = await client.list_models(args.provider)
    finally:
        await client.aclose()
    for i in ids:
        if not args.filter or args.filter.lower() in i.lower():
            print(i)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="yesman", description="Measure LLM conformity in multi-agent debates.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run an experiment (resumable with --run-id)")
    r.add_argument("--config", "-c", default="configs/free.toml")
    r.add_argument("--questions", "-q", default="data/questions/traps.jsonl")
    r.add_argument("--mode", choices=["council", "pressure", "both"], default="both")
    r.add_argument("--limit", "-n", type=int)
    r.add_argument("--rounds", type=int, help="override number of debate rounds")
    r.add_argument("--no-reasoning", action="store_true", help="agents only see peers' answers, not reasoning")
    r.add_argument("--shuffle-seed", type=int)
    r.add_argument("--run-id", help="resume or name a run")

    sub.add_parser("demo", help="run the offline simulated council and print the report")

    rep = sub.add_parser("report", help="print metrics for a run")
    rep.add_argument("run_id", nargs="?", help="defaults to the latest run")
    rep.add_argument("--json", action="store_true")

    sub.add_parser("runs", help="list runs")

    ch = sub.add_parser("check", help="ping every model in a config")
    ch.add_argument("config")

    mo = sub.add_parser("models", help="list model IDs a provider currently offers")
    mo.add_argument("provider")
    mo.add_argument("filter", nargs="?")

    fm = sub.add_parser("fetch-mmlu-pro", help="download a random MMLU-Pro sample")
    fm.add_argument("--n", type=int, default=200)
    fm.add_argument("--seed", type=int, default=0)
    fm.add_argument("--category", action="append", help="e.g. math, physics, law (repeatable)")
    fm.add_argument("--out")

    sv = sub.add_parser("serve", help="start the web dashboard")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)

    if args.cmd == "run":
        run_id = asyncio.run(_run(args))
        print_report(run_id)
    elif args.cmd == "demo":
        ns = argparse.Namespace(config="configs/mock.toml", questions="data/questions/traps.jsonl", mode="both",
                                limit=None, rounds=None, no_reasoning=False, shuffle_seed=None, run_id=None)
        print_report(asyncio.run(_run(ns)))
    elif args.cmd == "report":
        run_id = args.run_id or (list_runs() or [{}])[0].get("id")
        if not run_id:
            sys.exit("No runs yet. Try `yesman demo`.")
        if args.json:
            print(json.dumps(compute_metrics(RunStore(run_id).trials()), indent=2))
        else:
            print_report(run_id)
    elif args.cmd == "runs":
        for m in list_runs():
            print(f"{m['id']:<40} {m.get('status', '?'):<9} {m.get('question_set', ''):<20} {', '.join(m.get('agents', []))}")
    elif args.cmd == "check":
        asyncio.run(_check(args))
    elif args.cmd == "models":
        asyncio.run(_models(args))
    elif args.cmd == "fetch-mmlu-pro":
        qs = asyncio.run(fetch_mmlu_pro(args.n, args.seed, args.category))
        out = args.out or f"data/questions/mmlu_pro_{args.n}_s{args.seed}.jsonl"
        save_questions(qs, out)
        print(f"Saved {len(qs)} questions to {out}")
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("groupthink.server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
