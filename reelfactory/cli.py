"""CLI entry: validate / run / daemon / resume / status / --version."""

import argparse
import json
import os
import sys

from . import GIT_SHA, __version__
from .manifest import ManifestError, load_manifest


def _state_paths(job):
    rf = os.path.join(job["output_dir"], ".reelfactory")
    return rf, os.path.join(rf, "state.json"), os.path.join(rf, "report.json")


def _read_json(path):
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reelfactory",
                                 description="Batch video generator daemon")
    ap.add_argument("--version", action="store_true", help="print version and exit")
    sub = ap.add_subparsers(dest="cmd")

    p_val = sub.add_parser("validate", help="validate a job manifest")
    p_val.add_argument("manifest")

    p_run = sub.add_parser("run", help="run a job manifest once")
    p_run.add_argument("manifest")
    p_run.add_argument("--workers", type=int, default=None)

    p_dae = sub.add_parser("daemon", help="watch manifest and re-run on change")
    p_dae.add_argument("manifest")

    p_res = sub.add_parser("resume", help="resume/inspect last job state")
    p_res.add_argument("manifest")

    p_st = sub.add_parser("status", help="print job state and report")
    p_st.add_argument("manifest")

    args = ap.parse_args(argv)

    if args.version:
        print(f"reelfactory {__version__} ({GIT_SHA})")
        return 0
    if not args.cmd:
        ap.print_help()
        return 1

    try:
        job = load_manifest(args.manifest)
    except ManifestError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.cmd == "validate":
        print(f"manifest OK: job_id={job['job_id']} "
              f"tracks={len(job['tracks'])} "
              f"segments={sum(len(t['segments']) for t in job['tracks'])}")
        return 0

    rf, state_p, report_p = _state_paths(job)

    if args.cmd == "status":
        state = _read_json(state_p) or {"status": "never run"}
        print(json.dumps(state, indent=2))
        report = _read_json(report_p)
        if report:
            print("\nreport:")
            print(json.dumps({k: report[k] for k in ("job_id", "tracks") if k in report}, indent=2))
        return 0

    if args.cmd == "resume":
        state = _read_json(state_p)
        if not state or state.get("status") != "running":
            print("no interrupted run to resume; running fresh")
        from .pipeline import run_pipeline
        run_pipeline(job, max_workers=args.workers if hasattr(args, "workers") else None)
        return 0

    if args.cmd == "run":
        from .pipeline import run_pipeline
        run_pipeline(job, max_workers=args.workers)
        return 0

    if args.cmd == "daemon":
        from .daemon import daemon_loop
        daemon_loop(args.manifest)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
