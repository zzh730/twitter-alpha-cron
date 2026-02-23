#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from pathlib import Path


MIN_SECONDS = 10 * 60
MAX_SECONDS = 24 * 60 * 60


def parse_interval(s: str) -> int:
    m = re.fullmatch(r"(\d+)([mhd])", s.strip().lower())
    if not m:
        raise ValueError("interval must look like 10m, 1h, 6h, 1d")
    n = int(m.group(1))
    unit = m.group(2)
    mult = {"m": 60, "h": 3600, "d": 86400}[unit]
    sec = n * mult
    if sec < MIN_SECONDS or sec > MAX_SECONDS:
        raise ValueError("interval must be between 10m and 1d")
    return sec


def main() -> int:
    parser = argparse.ArgumentParser(description="Install/update OpenClaw cron job for twitter collector")
    parser.add_argument("--interval", default="1h", help="10m to 1d, e.g. 10m, 1h, 1d")
    parser.add_argument("--job-name", default="x-trading-scan")
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--to", default="channel:1475025575533084730", help="delivery target")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    parse_interval(args.interval)

    root = Path(__file__).resolve().parent
    cmd_text = (
        "Run this command with the exec tool, then return only the markdown report content:\n"
        f"cd {root} && python3 run_once.py --config {args.config}"
    )

    cmd = [
        "openclaw",
        "cron",
        "add",
        "--name",
        args.job_name,
        "--every",
        args.interval,
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

    print("Command:", " ".join(cmd))
    if args.dry_run:
        return 0

    rc = subprocess.call(cmd)
    if rc == 0:
        print("\nCurrent jobs:")
        subprocess.call(["openclaw", "cron", "list"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
