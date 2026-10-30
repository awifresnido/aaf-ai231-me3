"""Run the transport experiment and decoded-peer analysis with one interpreter."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=root / "artifacts",
        help="Parent for a fresh run directory containing logs and results.",
    )
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.artifacts_dir.resolve() / f"{stamp}-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    results = run_dir / "results"
    commands = [
        [sys.executable, "-B", str(root / "lab.py"), "--output-dir", str(results)],
        [sys.executable, "-B", str(root / "analyze_receiver.py"), str(results)],
    ]
    report = {"run_directory": str(run_dir), "commands": []}
    print(f"Run directory: {run_dir}", flush=True)
    for command, log_name in zip(commands, ["lab.log", "analysis.log"]):
        # A failing lab can still provide data for decoded-peer diagnostics.
        if log_name == "analysis.log" and not (results / "summary.json").exists():
            report["commands"].append(
                {
                    "argv": command,
                    "status": "unrun",
                    "reason": "No lab summary produced",
                }
            )
            break
        with (run_dir / log_name).open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        report["commands"].append(
            {"argv": command, "exit_code": result.returncode, "log": log_name}
        )
        print(f"{log_name}: exit {result.returncode}", flush=True)
    report["passed"] = len(report["commands"]) == 2 and all(
        command.get("exit_code") == 0 for command in report["commands"]
    )
    (run_dir / "run.json").write_text(json.dumps(report, indent=2) + "\n")
    if (results / "summary.json").exists():
        summary = json.loads((results / "summary.json").read_text())
        checks = summary["checks"]
        print(f"Checks passed: {sum(c['passed'] for c in checks)}/{len(checks)}")
        metrics = summary.get("receiver_analysis", {}).get(
            "handoff_request_to_receiver_delivery_ms"
        )
        if metrics:
            print(f"Decoded-peer transition p95: {metrics['p95']:.1f} ms")
    print("PASS" if report["passed"] else "FAIL", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
