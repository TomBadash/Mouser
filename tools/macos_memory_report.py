#!/usr/bin/env python3
"""Collect aggregate macOS memory diagnostics without dumping event contents."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys


CLASSES = ("CGEvent", "CGSEventAppendix", "HIDEvent", "IOHIDManager",
           "GPProcessMonitor", "NSXPCConnection")


def parse_footprint(output):
    match = re.search(r"\bFootprint:\s*([\d.]+)\s*(B|KB|MB|GB)\b", output)
    if not match:
        raise ValueError("footprint output has no recognized Footprint total")
    return round(float(match[1]) * 1024 ** ("B", "KB", "MB", "GB").index(match[2]))


def parse_heap(output):
    # Missing classes are zero only after recognizing a complete class table.
    if not re.search(r"COUNT\s+BYTES\s+AVG\s+CLASS_NAME", output):
        raise ValueError("heap output has no class table; inspection may be restricted")
    classes = {name: {"count": 0, "bytes": 0} for name in CLASSES}
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+[\d.]+\s+(\S+)\s+", line)
        if match and match[3] in classes:
            classes[match[3]]["count"] += int(match[1])
            classes[match[3]]["bytes"] += int(match[2])
    return classes


def run_tool(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise ValueError(f"{arguments[0]} failed: {result.stderr.strip() or 'inspection denied'}")
    return result.stdout


def collect(pid):
    identity_args = ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "comm="]
    identity = run_tool(identity_args).strip()
    if not identity:
        raise ValueError("target process is no longer running")
    footprint = parse_footprint(run_tool(["/usr/bin/footprint", str(pid)]))
    classes = parse_heap(run_tool(["/usr/bin/heap", "-s", str(pid)]))
    if run_tool(identity_args).strip() != identity:
        raise ValueError("target process changed during collection; retry with its new PID")
    return {"schema_version": 1, "pid": pid, "process_identity": identity,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "footprint_bytes": footprint, "classes": classes}


def compare(before, after):
    if (before["pid"], before["process_identity"]) != (after["pid"], after["process_identity"]):
        raise ValueError("snapshots belong to different process instances; restart comparison needs a new baseline")
    return {"footprint_bytes": after["footprint_bytes"] - before["footprint_bytes"],
            "classes": {name: {key: after["classes"][name][key] - before["classes"][name][key]
                               for key in ("count", "bytes")} for name in CLASSES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the running Mouser instance")
    parser.add_argument("--output", type=Path, required=True, help="new JSON report file")
    parser.add_argument("--baseline", type=Path, help="earlier report from the same process instance")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("collection requires macOS (footprint and heap)")
    if args.pid <= 0:
        parser.error("PID must be positive")
    try:
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        report = collect(args.pid)
        if baseline is not None:
            report["delta"] = compare(baseline, report)
        # Keep the baseline safe if the user accidentally reuses its filename.
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Memory report failed: {exc}\n")
    print(f"Saved {args.output}: footprint {report['footprint_bytes'] / 1024**2:.1f} MiB")
    for name, values in report["classes"].items():
        delta = f" ({report['delta']['classes'][name]['count']:+d})" if "delta" in report else ""
        print(f"  {name}: {values['count']:,}{delta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
