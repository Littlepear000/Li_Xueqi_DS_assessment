"""Command-line entry point: ``piaa <command> [options]``.

Commands
--------
  piaa info      --raw-dir RAW                    validate projects.csv and index the documents
  piaa screen    --raw-dir RAW [--ids ...]        keyword screening only (no LLM), prints tiers
  piaa run       --raw-dir RAW --out OUT --id P1  single-record run (prints the JSON record)
  piaa batch     --raw-dir RAW --out OUT [--ids ...] [--mode reuse|missing|refresh]
  piaa export    --raw-dir RAW --out OUT [--label L]   write the two tables from cached records
  piaa workflows                                   list workflow versions
  piaa ingest    --raw-dir RAW --out OUT                 rebuild pia_review.db from the cached records
  piaa compare   --run-a OUT_A --run-b OUT_B --out QC_DIR   flag differences between two runs (Note 1 QC)
  piaa serve     --raw-dir RAW --out OUT [--port 18765] [--provider mock] [--dev]   start the review web app (--dev: R+Enter restarts)

Every command that calls the model takes ``--provider anthropic|deepseek|openai|mock`` and ``--model``;
keys come from ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY in the environment or a .env file.
Typical test run of workflow v5 on two projects with DeepSeek::

  piaa batch --raw-dir ../raw_data --out ../output_v5 --workflow v5 --provider deepseek --ids P176935 P171777 --mode refresh
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import LLMSettings, Settings


def _settings(args) -> Settings:
    provider = args.provider
    if provider is None and args.cmd == "serve":   # the web app remembers the provider chosen on its Setup page
        from .webapp.server import stored_provider
        provider = stored_provider(args.out)
    step_models = {}
    for item in getattr(args, "step_model", None) or []:
        if "=" not in item:
            raise SystemExit(f"--step-model expects STEP=MODEL, got {item!r}")
        k, v = item.split("=", 1)
        step_models[k.strip()] = v.strip()
    llm = LLMSettings(provider=provider or "anthropic", model=getattr(args, "model", None) or None, base_url=getattr(args, "base_url", None) or None,
                      step_models=step_models, response_cache=getattr(args, "reuse_answers", False),
                      warm_cache=not getattr(args, "no_warm_cache", False))
    return Settings(raw_dir=args.raw_dir, output_dir=getattr(args, "out", None) or f"{args.raw_dir}/../output",
                    workflow=getattr(args, "workflow", "v1"), llm=llm, debug=getattr(args, "debug", False),
                    workers=getattr(args, "workers", 4))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="piaa", description="PIA Analysis - Project Innovation Approach Analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, out=True):
        p.add_argument("--raw-dir", required=True)
        if out:
            p.add_argument("--out", required=True)
        p.add_argument("--workflow", default="v1")
        p.add_argument("--provider", default=None, choices=["anthropic", "deepseek", "openai", "mock"],
                       help="LLM provider; the key is read from ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY (env or .env)")
        p.add_argument("--model", default=None, help="model name (default: claude-sonnet-4-5 / deepseek-flash / gpt-4.1-mini)")
        p.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint for --provider openai (default: LLM_BASE_URL or api.openai.com)")
        p.add_argument("--debug", action="store_true", help="keep raw LLM exchanges and verbose trace")
        p.add_argument("--workers", type=int, default=16)
        p.add_argument("--step-model", action="append", metavar="STEP=MODEL",
                       help="cheaper model for one step, same provider; repeatable (e.g. --step-model codes=claude-haiku-4-5 --step-model merge=claude-haiku-4-5)")
        p.add_argument("--reuse-answers", action="store_true",
                       help="reuse stored model answers for requests identical to an earlier run (<out>/cache/llm); leave off for A/B QC runs")
        p.add_argument("--no-warm-cache", action="store_true", help="do not send the first call of each system prompt alone before the parallel calls")

    common(sub.add_parser("info"), out=False)
    p = sub.add_parser("screen"); common(p, out=False); p.add_argument("--ids", nargs="*")
    p = sub.add_parser("run"); common(p); p.add_argument("--id", required=True)
    p = sub.add_parser("batch"); common(p); p.add_argument("--ids", nargs="*"); p.add_argument("--mode", default="reuse", choices=["reuse", "missing", "refresh"])
    p = sub.add_parser("export"); common(p); p.add_argument("--label", default="")
    sub.add_parser("workflows", help="list workflow folders with their version tag and hash")
    p = sub.add_parser("release", help="tag the current state of a workflow folder as its next version (v1.1 -> v1.2)")
    p.add_argument("workflow", help="folder name: v1 ... v5 (approach workflows) or r1, r2 (pattern workflows)")
    p.add_argument("--note", required=True, help="one line: what changed")
    p.add_argument("--tag", default=None, help="explicit tag instead of the next number")
    p = sub.add_parser("ingest", help="rebuild the web-app database from the cached records in --out"); common(p)
    p = sub.add_parser("compare", help="QC: compare two output folders (Run A / Run B) of the same workflow")
    p.add_argument("--run-a", required=True); p.add_argument("--run-b", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("serve"); common(p); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=int(__import__("os").environ.get("PIAA_PORT") or 18765))
    p.add_argument("--dev", action="store_true", help="development mode: press R + Enter in the terminal to restart the server after code changes")
    args = ap.parse_args(argv)

    if args.cmd == "workflows":
        from . import __version__
        from .patterns import list_pattern_workflows
        from .workflows import list_workflows
        print(f"piaa {__version__}")
        for w in list_workflows() + list_pattern_workflows():
            print(f"{w.version:4s} {w.tag:12s} {w.hash}  {w.name}")
        return 0

    if args.cmd == "release":
        from .patterns import load_pattern_workflow
        from .versioning import release
        from .workflows import load_workflow
        w = load_pattern_workflow(args.workflow) if args.workflow.startswith("r") else load_workflow(args.workflow)
        before = w.tag
        r = release(w, args.note, args.tag)
        print(f"{w.version}: {before} -> {r['tag']} (hash {r['hash']})" if before != r["tag"] else f"{w.version}: already released as {r['tag']}")
        return 0

    if args.cmd == "compare":
        from .qc import compare
        print(json.dumps(compare(args.run_a, args.run_b, args.out), indent=2))
        return 0
    s = _settings(args)
    if args.cmd == "info":
        from .catalog import validate_projects_csv
        from .documents import build_index
        print(json.dumps({"projects_csv": validate_projects_csv(s.projects_csv), "documents": build_index(s.documents_dirs).summary()}, indent=2))
        return 0
    if args.cmd == "screen":
        from .catalog import load_projects
        from .documents import build_index, read_text
        from .taxonomy import innovation_keywords as ik
        projects, index = load_projects(s.projects_csv), build_index(s.documents_dirs)
        for pid in (args.ids or list(projects)):
            terms = set()
            for d in index.for_project(pid):
                terms |= {h.term for h in ik.scan(read_text(d.path))}
            print(f"{pid}\t{len(terms)}\t{ik.tier(len(terms))}\t{', '.join(sorted(terms))[:120]}")
        return 0
    if args.cmd == "ingest":
        from .catalog import load_projects
        from .documents import build_index
        from .runner import Pipeline
        from .webapp.db import DB
        dbp = s.output_dir / "pia_review.db"
        if dbp.exists():
            dbp.rename(dbp.with_suffix(".db.bak"))
        db = DB(dbp)
        db.load_catalog(load_projects(s.projects_csv), build_index(s.documents_dirs))
        pipe = Pipeline(s)
        n = 0
        for pid in pipe.projects:
            rec = pipe.cached(pid)
            if rec is not None:
                db.ingest_record(rec)
                n += 1
        print(f"ingested {n} cached records into {dbp} (previous database kept as .db.bak)")
        return 0
    if args.cmd == "run":
        from .catalog import load_projects
        from .documents import build_index
        from .runner import run_project
        from .webapp.db import DB
        rec = run_project(args.id, s)
        db = DB(s.output_dir / "pia_review.db")
        db.load_catalog(load_projects(s.projects_csv), build_index(s.documents_dirs))
        db.ingest_record(rec)
        print(rec.to_json())
        print(_usage_line([rec]), file=sys.stderr)
        return 1 if rec.error else 0
    if args.cmd == "batch":
        from .catalog import load_projects
        from .documents import build_index
        from .runner import run_batch
        from .webapp.db import DB
        db = DB(s.output_dir / "pia_review.db")  # the same database the web app reads
        db.load_catalog(load_projects(s.projects_csv), build_index(s.documents_dirs))

        done = []

        def progress(pid, st, r):
            u = (r.llm_usage if r else {}) or {}
            cost = f"${u['est_cost_usd']:.3f}" if u.get("est_cost_usd") is not None else ""
            print(f"{pid}\t{st}\t{r.innovative if r else ''}\t{len(r.approaches) if r else ''}\t{u.get('calls', '')} calls\t{cost}", flush=True)
            if r is not None:
                db.ingest_record(r)  # idempotent: a reused record already in the DB is skipped
                if st != "reused":
                    done.append(r)

        from .llm import deepseek_peak_note
        if note := deepseek_peak_note(s.llm.provider):
            print(note, file=sys.stderr)
        run_batch(args.ids, s, mode=args.mode, progress=progress)
        print(_usage_line(done), file=sys.stderr)
        return 0
    if args.cmd == "serve" and args.dev:
        return _serve_dev(args, s)
    if args.cmd == "serve":
        import webbrowser
        import uvicorn
        from .webapp.server import app, configure
        configure(str(s.raw_dir), str(s.output_dir), s.llm.provider, args.model, s.workflow, args.base_url)
        url = f"http://{args.host}:{args.port}"
        from . import __version__
        print(f"PIA Review {__version__} running at {url}  (Ctrl+C to stop)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0
    if args.cmd == "export":
        from .catalog import load_projects
        from .export import export
        from .runner import Pipeline
        pipe = Pipeline(s)
        records = {pid: r for pid in pipe.projects if (r := pipe.cached(pid))}
        print(json.dumps(export(records, pipe.projects, s.output_dir, args.label), indent=2))
        return 0
    return 0


def _usage_line(records) -> str:
    """Token totals and list-price cost estimate over the records produced in this invocation."""
    us = [r.llm_usage for r in records if r.llm_usage]
    if not us:
        return "[piaa] no LLM usage recorded"
    tot = {k: sum(u.get(k, 0) or 0 for u in us) for k in ("calls", "input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens", "reused_answers")}
    costs = [u.get("est_cost_usd") for u in us]
    cost = f"; est. cost ${sum(c for c in costs if c is not None):.2f} (list price)" if any(c is not None for c in costs) else ""
    reused = f" ({tot['reused_answers']} answers reused, no tokens)" if tot["reused_answers"] else ""
    write = f" + {tot['cache_write_tokens']:,} cache-write" if tot["cache_write_tokens"] else ""
    models = ", ".join(dict.fromkeys(m for u in us for m in str(u.get("model", "")).split(", ") if m))
    return (f"[piaa] {len(us)} project(s): {tot['calls']} LLM calls{reused}, {tot['input_tokens']:,} input{write} + {tot['cached_tokens']:,} cached "
            f"+ {tot['output_tokens']:,} output tokens{cost}; model {models}")


def _serve_dev(args, s) -> int:
    """Run the server in a child process; R restarts it, Q quits. Works on macOS, Linux and Windows."""
    import os
    import subprocess
    import time
    import webbrowser

    import socket

    def _free_port(host: str, start: int, span: int = 10) -> int | None:
        for cand in range(start, start + span + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
                sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sk.bind((host, cand))
                    return cand
                except OSError:
                    continue
        return None

    port = _free_port(args.host, int(args.port))
    if port is None:
        print(f"[piaa] ports {args.port}-{args.port + 10} are all in use on {args.host}. "
              f"Close whatever is using them, or set PIAA_PORT to a free port, then try again.", flush=True)
        return 1
    if port != int(args.port):
        print(f"[piaa] port {args.port} is busy; using {port} instead.", flush=True)

    env = {**os.environ, "PIAA_RAW_DIR": str(s.raw_dir), "PIAA_OUTPUT_DIR": str(s.output_dir), "PIAA_PROVIDER": s.llm.provider,
           "PIAA_MODEL": args.model or "", "PIAA_WORKFLOW": s.workflow, "PIAA_HOST": args.host, "PIAA_PORT": str(port)}
    url = f"http://{args.host}:{port}"
    child = None

    def start():
        proc = subprocess.Popen([sys.executable, "-m", "piaa.webapp.server"], env=env)
        print(f"[piaa] server started (pid {proc.pid}) at {url}", flush=True)
        return proc

    def stop(proc):
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    child = start()
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("[piaa] dev mode: type R + Enter to restart after code changes, Q + Enter to quit. Front-end files reload on browser refresh.", flush=True)
    try:
        while True:
            try:
                cmd = input().strip().lower()
            except EOFError:
                time.sleep(1)
                continue
            if cmd in ("r", "restart"):
                stop(child)
                child = start()
            elif cmd in ("q", "quit", "exit"):
                break
            elif child.poll() is not None:
                print("[piaa] server exited; restarting", flush=True)
                child = start()
    except KeyboardInterrupt:
        pass
    finally:
        stop(child)
    return 0


if __name__ == "__main__":
    sys.exit(main())
