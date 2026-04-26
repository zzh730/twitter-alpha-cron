#!/usr/bin/env python3
import argparse
import shlex
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/update OpenClaw cron job for TradingView portfolio monitor")
    parser.add_argument("--job-name", default="tradingview-portfolio-monitor")
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--to", default="channel:1475025575533084730", help="delivery target")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    cmd_text = (
        "Run this command with the exec tool. If it prints markdown, return only that markdown. "
        "If it prints nothing, return nothing:\n"
        f"cd {root} && python3 -m fetch_haohuang_portfolio.run_once --config {args.config}"
    )

    cmd = [
        "openclaw",
        "cron",
        "add",
        "--name",
        args.job_name,
        "--cron",
        "*/10 9-16 * * 1-5",
        "--tz",
        "America/New_York",
        "--session",
        "isolated",
        "--message",
        cmd_text,
        "--announce",
        "--channel",
        args.channel,
        "--to",
        args.to,
    ]

    print("Command:", shlex.join(cmd))
    if args.dry_run:
        return 0

    rc = subprocess.call(cmd)
    if rc == 0:
        print("\nCurrent jobs:")
        subprocess.call(["openclaw", "cron", "list"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
