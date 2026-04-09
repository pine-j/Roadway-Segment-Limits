"""
Batch screenshot capture for the FTW Segment Explorer visual review pipeline.

Uses Playwright as a Python library (NOT MCP) to open the web app once,
then iterates through every endpoint in the manifest and captures close/context
screenshots using ArcGIS MapView.takeScreenshot() - the GPU-native capture path.

Depends on helper functions defined in Web-App/app.js:
    __waitForSegments, __waitForTiles, __captureView,
    __selectCorridorSegments, __navigateAndCapture, __queryRoadsNearPoint
If you change or rename those functions in app.js, update REQUIRED_HELPERS
below and any page.evaluate calls that reference them.

Usage:
    python Scripts/visual-review-screenshots.py [options]

Options:
    --url URL           Web app URL (default: GitHub Pages)
    --local             Use local server at http://localhost:8080
    --manifest PATH     Path to visual-review-manifest.json
    --outdir PATH       Screenshot output directory
    --batch-size N      Endpoints per batch (default: 15)
    --start-batch N     First batch to process (1-indexed, default: 1)
    --end-batch N       Last batch to process (inclusive, default: all)
    --overwrite         Re-capture existing screenshots
    --headless          Run browser headless (default: headed for tile rendering)
    --close-zoom N      Zoom level for close screenshots (default: 17)
    --context-zoom N    Zoom level for context screenshots (default: 15)
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://pine-j.github.io/Roadway-Segment-Limits/"
LOCAL_URL = "http://localhost:8080"
DEFAULT_MANIFEST = _REPO_ROOT / "_temp" / "visual-review" / "visual-review-manifest.json"
DEFAULT_OUTDIR = _REPO_ROOT / "_temp" / "visual-review" / "screenshots"
BATCH_SIZE = 15


def parse_args():
    parser = argparse.ArgumentParser(description="Batch screenshot capture for visual review")
    parser.add_argument("--url", default=DEFAULT_URL, help="Web app URL")
    parser.add_argument("--local", action="store_true", help="Use local server")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--start-batch", type=int, default=1, help="First batch (1-indexed)")
    parser.add_argument("--end-batch", type=int, default=0, help="Last batch (0 = all)")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--close-zoom", type=int, default=17)
    parser.add_argument("--context-zoom", type=int, default=15)
    return parser.parse_args()


MIN_SCREENSHOT_KB = 10


def save_data_url(data_url: str, path: Path):
    """Decode a data:image/png;base64,... URL and write the PNG file."""
    _header, encoded = data_url.split(",", 1)
    path.write_bytes(base64.b64decode(encoded))


def js_str(value: str) -> str:
    """Safely encode a string for embedding in JavaScript source code."""
    return json.dumps(value)


REQUIRED_HELPERS = [
    "__waitForSegments",
    "__waitForTiles",
    "__captureView",
    "__selectCorridorSegments",
    "__navigateAndCapture",
    "__queryRoadsNearPoint",
]


def main():
    args = parse_args()
    url = LOCAL_URL if args.local else args.url

    if not args.manifest.exists():
        print(f"ERROR: Manifest not found at {args.manifest}")
        sys.exit(1)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    total_endpoints = len(manifest)
    print(f"Loaded manifest: {total_endpoints} endpoints")

    batches = []
    for i in range(0, total_endpoints, args.batch_size):
        batches.append(manifest[i : i + args.batch_size])

    total_batches = len(batches)
    start = args.start_batch
    end = args.end_batch if args.end_batch > 0 else total_batches

    print(f"Total batches: {total_batches} (processing {start}-{end})")

    args.outdir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        print(f"Loading {url} ...")
        page.goto(url, wait_until="networkidle", timeout=60000)

        missing = page.evaluate(
            "(" + json.dumps(REQUIRED_HELPERS) + ").filter(function(n) {"
            "  return typeof window[n] !== 'function';"
            "})"
        )
        if missing:
            print(f"ERROR: app.js is missing required helpers: {missing}")
            print("The deployed app.js is outdated. Use --local with a local server,")
            print("or push the latest app.js to GitHub Pages.")
            browser.close()
            sys.exit(1)
        print("Verified app helpers: all present")

        seg_count = page.evaluate("window.__waitForSegments()")
        print(f"App ready - {seg_count} segments loaded")

        captured = 0
        skipped = 0
        errors = 0
        t_start = time.time()

        for batch_idx in range(start - 1, end):
            batch_num = batch_idx + 1
            batch = batches[batch_idx]
            print(f"\n{'=' * 60}")
            print(f"BATCH {batch_num:02d} - {len(batch)} endpoints")
            print(f"{'=' * 60}")

            current_segment = None

            for ep_idx, ep in enumerate(batch):
                ep_num = ep_idx + 1
                close_path = args.outdir / f"batch-{batch_num:02d}-ep-{ep_num:02d}-close.png"
                context_path = args.outdir / f"batch-{batch_num:02d}-ep-{ep_num:02d}-context.png"

                if not args.overwrite and close_path.exists() and context_path.exists():
                    skipped += 1
                    print(f"  [{ep_num:02d}] {ep['segment']} ({ep['side']}) - SKIP (exists)")
                    continue

                seg_name = ep["segment"]
                lon = ep["lon"]
                lat = ep["lat"]

                print(f"  [{ep_num:02d}] {seg_name} ({ep['side']}) @ ({lon:.4f}, {lat:.4f})")

                try:
                    if seg_name != current_segment:
                        result = page.evaluate(
                            f"window.__selectCorridorSegments({js_str(seg_name)})"
                        )
                        if not result:
                            print(
                                f"       WARNING: Segment '{seg_name}' not found - capturing without highlight"
                            )
                        elif isinstance(result, int) and result > 1:
                            print(
                                f"       Corridor: selected {result} sub-segments for '{seg_name}'"
                            )
                        current_segment = seg_name

                    data = page.evaluate(
                        f"window.__navigateAndCapture({js_str(seg_name)}, {lon}, {lat}, {args.close_zoom}, {args.context_zoom})"
                    )

                    save_data_url(data["close"], close_path)
                    save_data_url(data["context"], context_path)

                    roads_path = args.outdir / f"batch-{batch_num:02d}-ep-{ep_num:02d}-roads.json"
                    roads_50 = page.evaluate(f"window.__queryRoadsNearPoint({lon}, {lat}, 50)")
                    roads_200 = page.evaluate(
                        f"window.__queryRoadsNearPoint({lon}, {lat}, 200)"
                    )
                    roads_500 = page.evaluate(
                        f"window.__queryRoadsNearPoint({lon}, {lat}, 500)"
                    )
                    roads_data = {
                        "endpoint": {"lon": lon, "lat": lat},
                        "roads_within_50m": roads_50,
                        "roads_within_200m": roads_200,
                        "roads_within_500m": roads_500,
                    }
                    roads_path.write_text(json.dumps(roads_data, indent=2), encoding="utf-8")

                    close_kb = close_path.stat().st_size / 1024
                    context_kb = context_path.stat().st_size / 1024

                    blank_warning = ""
                    if close_kb < MIN_SCREENSHOT_KB:
                        blank_warning += " BLANK-CLOSE"
                    if context_kb < MIN_SCREENSHOT_KB:
                        blank_warning += " BLANK-CONTEXT"
                    if blank_warning:
                        print(
                            f"       WARNING:{blank_warning} - tiles may have failed to render"
                        )

                    n50 = len(roads_50)
                    n200 = len(roads_200)
                    n500 = len(roads_500)
                    print(
                        f"       close: {close_kb:.0f}KB  context: {context_kb:.0f}KB  roads: {n50}@50m {n200}@200m {n500}@500m"
                    )
                    captured += 1

                except Exception as exc:
                    print(f"       ERROR: {exc}")
                    errors += 1

        elapsed = time.time() - t_start
        browser.close()

    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed:.1f}s")
    print(f"  Captured: {captured}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    print(f"  Output:   {args.outdir.resolve()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
