#!/usr/bin/env python3
"""Phase 3c deterministic validation for visual review batch results.

Performs schema validation, endpoint count checks, and heuristic-vs-visual
comparison.  Outputs a disagreements JSON that the GPT-5.4 Medium sub-agent
uses for visual adjudication — so it only sees disputed endpoints, not every
result.

Usage:
    python Scripts/validate_visual_results.py

Outputs (in _temp/visual-review/):
    validation-report.json   — full validation report (errors, warnings, stats)
    disagreements.json       — endpoints where heuristic and visual limits differ
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "Scripts" / "identify_segment_limits.py"
DEFAULT_VISUAL_REVIEW_DIR = ROOT / "_temp" / "visual-review"
DEFAULT_HEURISTIC_RESULTS = DEFAULT_VISUAL_REVIEW_DIR / "heuristic-results.csv"
DEFAULT_BATCH_RESULTS_DIR = DEFAULT_VISUAL_REVIEW_DIR / "batch-results"
DEFAULT_BATCH_PROMPTS_DIR = DEFAULT_VISUAL_REVIEW_DIR / "batch-prompts"
SCREENSHOTS_DIR = DEFAULT_VISUAL_REVIEW_DIR / "screenshots"

REQUIRED_FIELDS = {
    "endpoint_id": int,
    "segment": str,
    "side": str,
    "piece": (int, type(None)),
    "close_screenshot": str,
    "context_screenshot": str,
    "visible_labels": list,
    "visible_shields": list,
    "county_boundary_at_endpoint": bool,
    "limit_identification": str,
    "limit_alias": (str, type(None)),
    "is_offset": bool,
    "offset_direction": (str, type(None)),
    "offset_from": (str, type(None)),
    "visual_confidence": str,
    "reasoning": str,
}

VALID_SIDES = {"From", "To"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_DIRECTIONS = {
    "North", "South", "East", "West", "NE", "NW", "SE", "SW", None,
}


# ---------------------------------------------------------------------------
# Import heuristic module (same pattern as reconcile_results.py)
# ---------------------------------------------------------------------------

def load_module():
    spec = importlib.util.spec_from_file_location(
        "identify_segment_limits", SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helpers (reused from reconcile_results.py)
# ---------------------------------------------------------------------------

def safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def parse_piece(value: object) -> int | None:
    text = safe_text(value)
    if not text:
        return None
    return int(float(text))


def normalize_side(value: object) -> str:
    text = safe_text(value).lower()
    if text == "from":
        return "From"
    if text == "to":
        return "To"
    return text.title()


@dataclass(frozen=True)
class EndpointKey:
    segment: str
    side: str
    piece: int | None


def endpoint_key(module, segment, side, piece) -> EndpointKey:
    return EndpointKey(
        segment=module.normalize_spacing(safe_text(segment)),
        side=normalize_side(side),
        piece=parse_piece(piece),
    )


def build_fake_candidate(module, value: str):
    return module.LimitCandidate(
        value=value,
        normalized=module.normalize_limit_key(value),
        method="visual",
        confidence=0.0,
        distance_m=0.0,
        detail="validation",
    )


def limits_match(module, value_a: str, value_b: str) -> bool:
    if not value_a or not value_b:
        return False
    if module.canonical(value_a) == module.canonical(value_b):
        return True
    if module.normalize_limit_key(value_a) == module.normalize_limit_key(value_b):
        return True
    if module.local_limits_equivalent(value_a, value_b):
        return True
    return bool(
        module.limits_equivalent(value_a, build_fake_candidate(module, value_b))
        or module.limits_equivalent(value_b, build_fake_candidate(module, value_a))
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_entry_schema(entry: dict, batch_num: int) -> list[str]:
    """Return list of error strings for a single endpoint entry."""
    errors: list[str] = []
    ep_id = entry.get("endpoint_id", "?")
    prefix = f"batch-{batch_num:02d} ep-{ep_id}"

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(f"{prefix}: missing required field '{field}'")
            continue
        value = entry[field]
        if isinstance(expected_type, tuple):
            if not isinstance(value, expected_type):
                errors.append(
                    f"{prefix}: field '{field}' has type {type(value).__name__}, "
                    f"expected {' or '.join(t.__name__ for t in expected_type)}"
                )
        else:
            if not isinstance(value, expected_type):
                errors.append(
                    f"{prefix}: field '{field}' has type {type(value).__name__}, "
                    f"expected {expected_type.__name__}"
                )

    side = entry.get("side")
    if side not in VALID_SIDES:
        errors.append(f"{prefix}: side '{side}' not in {VALID_SIDES}")

    confidence = entry.get("visual_confidence")
    if confidence not in VALID_CONFIDENCE:
        errors.append(f"{prefix}: visual_confidence '{confidence}' not in {VALID_CONFIDENCE}")

    direction = entry.get("offset_direction")
    if direction not in VALID_DIRECTIONS:
        errors.append(f"{prefix}: offset_direction '{direction}' not in {VALID_DIRECTIONS}")

    reasoning = entry.get("reasoning", "")
    if isinstance(reasoning, str) and len(reasoning.strip()) < 20:
        errors.append(f"{prefix}: reasoning is too short ({len(reasoning.strip())} chars)")

    return errors


# ---------------------------------------------------------------------------
# Endpoint count check
# ---------------------------------------------------------------------------

def count_prompt_endpoints(prompt_path: Path) -> int | None:
    """Count endpoint rows in a batch prompt markdown table."""
    if not prompt_path.exists():
        return None
    text = prompt_path.read_text(encoding="utf-8")
    # Endpoint rows start with "| <number> |"
    rows = re.findall(r"^\|\s*\d+\s*\|", text, re.MULTILINE)
    return len(rows)


# ---------------------------------------------------------------------------
# Screenshot existence check
# ---------------------------------------------------------------------------

def check_screenshots(entry: dict, batch_num: int) -> list[str]:
    """Check that referenced screenshot files exist and are non-empty."""
    warnings: list[str] = []
    ep_id = entry.get("endpoint_id", "?")
    prefix = f"batch-{batch_num:02d} ep-{ep_id}"

    for field in ("close_screenshot", "context_screenshot"):
        path_str = entry.get(field, "")
        if not path_str:
            warnings.append(f"{prefix}: {field} is empty")
            continue
        path = ROOT / path_str
        if not path.exists():
            warnings.append(f"{prefix}: {field} not found: {path_str}")
        elif path.stat().st_size < 10_000:
            warnings.append(
                f"{prefix}: {field} is suspiciously small "
                f"({path.stat().st_size} bytes): {path_str}"
            )

    return warnings


# ---------------------------------------------------------------------------
# Gap/corridor checks
# ---------------------------------------------------------------------------

def check_gap_segments(entries: list[dict], batch_num: int) -> list[str]:
    """Check that gap segment pieces have different From/To limits."""
    warnings: list[str] = []
    by_segment: dict[str, list[dict]] = {}
    for entry in entries:
        seg = safe_text(entry.get("segment"))
        if entry.get("piece") is not None:
            by_segment.setdefault(seg, []).append(entry)

    for seg, pieces in by_segment.items():
        for piece_entry in pieces:
            piece_num = piece_entry.get("piece")
            same_piece = [
                e for e in pieces
                if e.get("piece") == piece_num and e is not piece_entry
            ]
            for other in same_piece:
                if (safe_text(piece_entry.get("limit_identification"))
                        == safe_text(other.get("limit_identification"))):
                    ep_a = piece_entry.get("endpoint_id", "?")
                    ep_b = other.get("endpoint_id", "?")
                    warnings.append(
                        f"batch-{batch_num:02d}: gap segment '{seg}' piece {piece_num} "
                        f"has same limit at From (ep {ep_a}) and To (ep {ep_b}): "
                        f"'{safe_text(piece_entry.get('limit_identification'))}'"
                    )

    return warnings


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--heuristic-results", type=Path,
        default=DEFAULT_HEURISTIC_RESULTS,
    )
    parser.add_argument(
        "--batch-results-dir", type=Path,
        default=DEFAULT_BATCH_RESULTS_DIR,
    )
    parser.add_argument(
        "--batch-prompts-dir", type=Path,
        default=DEFAULT_BATCH_PROMPTS_DIR,
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=DEFAULT_VISUAL_REVIEW_DIR,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    module = load_module()

    # Load heuristic results
    heuristic_df = pd.read_csv(args.heuristic_results)
    heuristic_by_key: dict[EndpointKey, dict] = {}
    for row in heuristic_df.to_dict("records"):
        key = endpoint_key(
            module, row.get("Segment"), row.get("Side"), row.get("Piece"),
        )
        heuristic_by_key[key] = row

    # Find batch result files
    batch_files = sorted(args.batch_results_dir.glob("batch-*-results.json"))
    if not batch_files:
        print("ERROR: No batch result files found.")
        sys.exit(1)

    all_errors: list[str] = []
    all_warnings: list[str] = []
    disagreements: list[dict] = []
    agreements: list[dict] = []
    stats = {
        "total_endpoints": 0,
        "total_batches": len(batch_files),
        "schema_errors": 0,
        "endpoint_count_mismatches": 0,
        "disagreements": 0,
        "agreements": 0,
        "missing_heuristic": 0,
        "needs_rescan": 0,
        "low_confidence": 0,
        "screenshot_warnings": 0,
        "gap_warnings": 0,
    }

    for batch_file in batch_files:
        # Extract batch number
        match = re.search(r"batch-(\d+)", batch_file.name)
        if not match:
            all_errors.append(f"Cannot parse batch number from {batch_file.name}")
            continue
        batch_num = int(match.group(1))

        # Load batch results
        with open(batch_file, encoding="utf-8") as f:
            entries = json.load(f)

        if not isinstance(entries, list):
            all_errors.append(f"batch-{batch_num:02d}: root is not an array")
            continue

        stats["total_endpoints"] += len(entries)

        # Check 1: Schema validation
        for entry in entries:
            entry_errors = validate_entry_schema(entry, batch_num)
            all_errors.extend(entry_errors)
            stats["schema_errors"] += len(entry_errors)

        # Check 2: Endpoint count
        prompt_path = args.batch_prompts_dir / f"batch-{batch_num:02d}.md"
        expected_count = count_prompt_endpoints(prompt_path)
        if expected_count is not None and expected_count != len(entries):
            all_errors.append(
                f"batch-{batch_num:02d}: endpoint count mismatch — "
                f"prompt has {expected_count} rows, results has {len(entries)}"
            )
            stats["endpoint_count_mismatches"] += 1

        # Check 3: Screenshot existence
        for entry in entries:
            screenshot_warnings = check_screenshots(entry, batch_num)
            all_warnings.extend(screenshot_warnings)
            stats["screenshot_warnings"] += len(screenshot_warnings)

        # Check 4: Heuristic comparison
        for entry in entries:
            key = endpoint_key(
                module,
                entry.get("segment"),
                entry.get("side"),
                entry.get("piece"),
            )
            heuristic_row = heuristic_by_key.get(key)

            # Track rescan/low-confidence
            if entry.get("needs_rescan"):
                stats["needs_rescan"] += 1
            if entry.get("visual_confidence") == "low":
                stats["low_confidence"] += 1

            if heuristic_row is None:
                stats["missing_heuristic"] += 1
                continue

            heuristic_limit = safe_text(heuristic_row.get("Auto-Limit"))
            visual_limit = safe_text(entry.get("limit_identification"))

            if limits_match(module, heuristic_limit, visual_limit):
                stats["agreements"] += 1
                agreements.append({
                    "batch": batch_num,
                    "endpoint_id": entry.get("endpoint_id"),
                    "segment": safe_text(entry.get("segment")),
                    "side": entry.get("side"),
                    "piece": entry.get("piece"),
                    "heuristic_limit": heuristic_limit,
                    "visual_limit": visual_limit,
                    "visual_confidence": entry.get("visual_confidence"),
                    "close_screenshot": entry.get("close_screenshot"),
                    "context_screenshot": entry.get("context_screenshot"),
                })
            else:
                stats["disagreements"] += 1
                disagreements.append({
                    "batch": batch_num,
                    "endpoint_id": entry.get("endpoint_id"),
                    "segment": safe_text(entry.get("segment")),
                    "side": entry.get("side"),
                    "piece": entry.get("piece"),
                    "heuristic_limit": heuristic_limit,
                    "heuristic_confidence": safe_text(
                        heuristic_row.get("Confidence-Bucket")
                    ),
                    "visual_limit": visual_limit,
                    "visual_confidence": entry.get("visual_confidence"),
                    "visual_reasoning": entry.get("reasoning"),
                    "visible_labels": entry.get("visible_labels"),
                    "visible_shields": entry.get("visible_shields"),
                    "county_boundary_at_endpoint": entry.get(
                        "county_boundary_at_endpoint"
                    ),
                    "is_offset": entry.get("is_offset"),
                    "offset_direction": entry.get("offset_direction"),
                    "offset_from": entry.get("offset_from"),
                    "close_screenshot": entry.get("close_screenshot"),
                    "context_screenshot": entry.get("context_screenshot"),
                })

        # Check 5: Gap/corridor checks
        gap_warnings = check_gap_segments(entries, batch_num)
        all_warnings.extend(gap_warnings)
        stats["gap_warnings"] += len(gap_warnings)

    # Select ~10% of agreements for spot-check sampling
    sample_size = max(1, len(agreements) // 10)
    import random
    random.seed(42)
    spot_check_sample = random.sample(
        agreements, min(sample_size, len(agreements)),
    ) if agreements else []

    # Write outputs
    report = {
        "stats": stats,
        "errors": all_errors,
        "warnings": all_warnings,
        "spot_check_sample": spot_check_sample,
    }

    report_path = args.output_dir / "validation-report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    disagreements_path = args.output_dir / "disagreements.json"
    with open(disagreements_path, "w", encoding="utf-8") as f:
        json.dump(disagreements, f, indent=2)

    # Print summary
    print(f"\n{'=' * 60}")
    print("Phase 3c Validation Report")
    print(f"{'=' * 60}")
    print(f"Batches validated:       {stats['total_batches']}")
    print(f"Total endpoints:         {stats['total_endpoints']}")
    print(f"Schema errors:           {stats['schema_errors']}")
    print(f"Endpoint count mismatches: {stats['endpoint_count_mismatches']}")
    print(f"Agreements:              {stats['agreements']}")
    print(f"Disagreements:           {stats['disagreements']}")
    print(f"Missing heuristic match: {stats['missing_heuristic']}")
    print(f"Needs rescan:            {stats['needs_rescan']}")
    print(f"Low confidence:          {stats['low_confidence']}")
    print(f"Screenshot warnings:     {stats['screenshot_warnings']}")
    print(f"Gap/corridor warnings:   {stats['gap_warnings']}")
    print(f"Spot-check sample size:  {len(spot_check_sample)}")
    print(f"\nOutputs:")
    print(f"  {report_path}")
    print(f"  {disagreements_path}")

    if all_errors:
        print(f"\n{'!' * 60}")
        print(f"ERRORS ({len(all_errors)}):")
        for error in all_errors[:20]:
            print(f"  - {error}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more (see validation-report.json)")

    if stats["schema_errors"] > 0 or stats["endpoint_count_mismatches"] > 0:
        print("\nWARNING: Schema errors or count mismatches found.")
        print("Fix these before proceeding to visual adjudication.")
        sys.exit(1)

    print(f"\nDisagreements ready for GPT-5.4 Medium sub-agent adjudication.")


if __name__ == "__main__":
    main()
