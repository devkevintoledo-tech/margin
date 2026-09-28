"""``python -m pipeline run [--from STAGE] [--to STAGE] --version YYYY.MM.N [--upload]``"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from pipeline import runner
from pipeline.config import STAGES, BuildContext
from pipeline.db import connect

VERSION = re.compile(r"^\d{4}\.\d{2}\.\d+$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a range of stages")
    run.add_argument("--from", dest="start", choices=STAGES, default=STAGES[0])
    run.add_argument("--to", dest="stop", choices=STAGES, default=STAGES[-1])
    run.add_argument("--build-dir", type=Path, default=Path("build"))
    run.add_argument("--version", help="release version, e.g. 2026.10.1 (required for publish)")
    run.add_argument("--upload", action="store_true", help="attach the release to a GitHub Release")
    draft = sub.add_parser("golden-draft", help="draft a golden entry from a Wikidata series")
    draft.add_argument("qid", help="Wikidata series item, e.g. Q45875")
    draft.add_argument("--build-dir", type=Path, default=Path("build"))
    args = parser.parse_args(argv)

    if args.command == "golden-draft":
        from pipeline.golden import draft_from_wikidata

        con = connect(args.build_dir)
        try:
            sys.stdout.write(draft_from_wikidata(con, args.qid))
        finally:
            con.close()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    stages = runner.stage_range(args.start, args.stop)
    if "publish" in stages and not (args.version and VERSION.match(args.version)):
        parser.error("publish needs --version YYYY.MM.N")
    ctx = BuildContext(build_dir=args.build_dir, con=connect(args.build_dir),
                       version=args.version, upload=args.upload)
    try:
        runner.run(ctx, args.start, args.stop)
    finally:
        ctx.con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
