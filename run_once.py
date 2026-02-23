#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one collection pass")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out-dir", default="./data")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "src" / "collector.py"),
        "--config",
        args.config,
        "--output-json",
        str(out_dir / "latest.json"),
        "--output-md",
        str(out_dir / "latest.md"),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
