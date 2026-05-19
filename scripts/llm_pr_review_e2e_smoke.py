#!/usr/bin/env python3
"""Run qaestro's live-provider PR review E2E smoke."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.smoke.llm_pr_review_e2e import run_llm_pr_review_e2e_smoke

from src.shared.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repo in owner/name form")
    parser.add_argument("--pr", type=int, required=True, help="Pull request number to review")
    parser.add_argument("--correlation-id", default="", help="Optional stable correlation id")
    args = parser.parse_args()

    result = run_llm_pr_review_e2e_smoke(
        config=load_config(),
        repo_full_name=args.repo,
        pr_number=args.pr,
        correlation_id=args.correlation_id,
        opt_in_live_smoke=True,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
