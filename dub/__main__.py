"""CPU half of the dubbing pipeline (Codespaces).

    python3 -m dub init  --job jobs/demo --url https://... --language en --target zh
    python3 -m dub run   --job jobs/demo --stages s1,s2,s3,s4
    python3 -m dub bundle --job jobs/demo
    python3 -m dub status --job jobs/demo
"""

import argparse
import sys
from pathlib import Path

from . import stages
from .job import STAGES, STAGE_NAMES, Job


def cmd_init(args):
    root = Path(args.job).resolve()
    if (root / "manifest.json").exists() and not args.force:
        raise SystemExit(f"{root} already has a manifest (use --force to reset)")
    job = Job.create(root, url=args.url, language=args.language, target=args.target)
    print(f"created {root}")
    print(f"  source language : {args.language}")
    print(f"  target language : {args.target}")
    if args.url:
        print(f"  url             : {args.url}")
    return 0


def cmd_run(args):
    root = Path(args.job).resolve()
    if (root / "manifest.json").exists():
        job = Job.load(root)
    elif args.url:
        job = Job.create(root, url=args.url)
    else:
        raise SystemExit(f"{root} has no manifest and no --url was given")

    if args.url and not job.url:
        job.data["source"]["url"] = args.url
        job.save()

    selected = STAGES if args.stages == "all" else [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = [s for s in selected if s not in STAGES]
    if unknown:
        raise SystemExit(f"unknown stages: {', '.join(unknown)} (expected {', '.join(STAGES)})")

    for stage in selected:
        if job.done(stage) and not args.force:
            print(f"[skip] {stage} {STAGE_NAMES[stage]} already done")
            continue
        print(f"\n== {stage} {STAGE_NAMES[stage]}")
        job.mark(stage, "running")
        try:
            info = stages.REGISTRY[stage](job) or {}
        except SystemExit as exc:
            job.mark(stage, "failed", error=str(exc))
            print(f"[fail] {stage}: {exc}")
            return 1
        job.mark(stage, "done", **info)
        print(f"[ok] {stage}")
    print("\nall requested stages finished")
    return 0


def cmd_bundle(args):
    job = Job.load(Path(args.job).resolve())
    info = stages.bundle(job, args.out)
    print(f"bundle: {info['bundle']} ({info['size_mb']} MB)")
    print("upload it to Colab and run `python3 -m dub unpack --bundle <zip>` there")
    return 0


def cmd_status(args):
    job = Job.load(Path(args.job).resolve())
    print(f"job  {job.data.get('id')}")
    print(f"url  {job.url or '-'}")
    for stage in STAGES:
        record = job.data.get("stages", {}).get(stage, {})
        print(f"  {stage} {STAGE_NAMES[stage]:16} {record.get('status', 'pending'):8} {record.get('error', '')}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dub", description="download, separate, transcribe and translate")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a job directory")
    init.add_argument("--job", required=True)
    init.add_argument("--url", default="")
    init.add_argument("--language", default="en")
    init.add_argument("--target", default="zh")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    run = sub.add_parser("run", help="run stages s1..s4")
    run.add_argument("--job", required=True)
    run.add_argument("--stages", default="all")
    run.add_argument("--url", default="")
    run.add_argument("--force", action="store_true")
    run.set_defaults(func=cmd_run)

    bundle = sub.add_parser("bundle", help="zip the job for the Colab repo")
    bundle.add_argument("--job", required=True)
    bundle.add_argument("--out", default="")
    bundle.set_defaults(func=cmd_bundle)

    status = sub.add_parser("status", help="show stage progress")
    status.add_argument("--job", required=True)
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
