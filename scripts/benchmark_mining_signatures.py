"""Replay saved crops without screenshots, overlays or network requests.

Run from the repository root:
    python -m scripts.benchmark_mining_signatures --date 2026-09-06 --count 24

Vision labels are comparison data, not manually verified ground truth.
Timings cover the number-reading path, excluding screen capture/network time.
"""
import argparse
import copy
import json
from pathlib import Path
import statistics
import time
from unittest.mock import Mock

import cv2

from wingmen.star_citizen_services.functions.mining_services.mining_manager import (
    MiningManager, SIGNATURE_OBSERVER_DEFAULTS,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="UTC date prefix, e.g. 2026-09-06")
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--data", type=Path, default=Path("star_citizen_data/mining-data"))
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    source = args.data / "debug_data/signature_training/signature_vision_training.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("training_usable")
            and row.get("signature_value") is not None
            and (not args.date or row["observed_at"].startswith(args.date))
            and (args.data / row["image"]).is_file()]
    rows = rows[::max(1, len(rows) // args.count)][:args.count]
    if not rows:
        parser.error("No usable saved crops match the selection")
    manager = object.__new__(MiningManager)
    manager.signature_observer_config = copy.deepcopy(SIGNATURE_OBSERVER_DEFAULTS)
    manager.signature_reference_path = str(args.data / "signature_reference.json")
    manager.signature_vision_cache = {}
    manager.signature_vision_recent_crops = []
    manager.signature_vision_queued_hashes = set()
    manager.signature_last_watch_area_rect = None
    manager.signature_ocr_unavailable_reported = False
    manager._signature_debug = Mock()
    manager._write_signature_vision_event = Mock()
    manager._queue_signature_vision_analysis = Mock(return_value=None)
    counts = {"matching_auto_label": 0, "uncertain": 0, "different_auto_label": 0}
    durations = []
    for row in rows:
        image = cv2.imread(str(args.data / row["image"]))
        if image is None:
            raise ValueError(f"Cannot decode crop: {row['image']}")
        manager._prepare_signature_ocr_crop = Mock(return_value=(image, None))
        started = time.perf_counter()
        value, _ = manager._read_signature_value(image)
        durations.append(time.perf_counter() - started)
        key = ("matching_auto_label" if value == row["signature_value"]
               else "uncertain" if value is None else "different_auto_label")
        counts[key] += 1
    print(json.dumps({"samples": len(rows), **counts,
                      "median_read_ms": round(statistics.median(durations) * 1000, 2),
                      "maximum_read_ms": round(max(durations) * 1000, 2),
                      "vision_fallback_requests": manager._queue_signature_vision_analysis.call_count,
                      "network_requests_sent": 0}, indent=2))


if __name__ == "__main__":
    main()
