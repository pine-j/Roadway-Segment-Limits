#!/usr/bin/env python3
"""Generate batched visual-review prompts from the manifest.

Produces batch prompt files that instruct sub-agents to analyze
pre-captured screenshots (from batch-screenshots.py) rather than
driving a browser via Playwright MCP.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "_temp" / "visual-review"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "visual-review-manifest.json"
DEFAULT_BATCH_SIZE = 15


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=f"Manifest JSON path. Default: {DEFAULT_MANIFEST_PATH}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "batch-prompts",
        help=f"Prompt output directory. Default: {DEFAULT_OUTPUT_DIR / 'batch-prompts'}",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Endpoints per batch. Default: {DEFAULT_BATCH_SIZE}",
    )
    return parser.parse_args()


def ensure_dirs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    (output_dir.parent / "batch-results").mkdir(parents=True, exist_ok=True)
    (output_dir.parent / "screenshots").mkdir(parents=True, exist_ok=True)


def chunked(items: list[dict[str, object]], size: int) -> list[list[dict[str, object]]]:
    if size <= 0:
        raise ValueError("batch-size must be greater than zero")
    return [items[index : index + size] for index in range(0, len(items), size)]


def fmt_coord(value: object) -> str:
    if value is None:
        return "null"
    return f"{float(value):.6f}"


def endpoint_note(entry: dict[str, object]) -> str:
    endpoint_hint = str(entry.get("endpoint_hint", "")).strip()
    direction = str(entry.get("direction", "")).strip()
    if entry.get("type") == "Gap":
        return f"GAP segment - {endpoint_hint}; {direction}".strip("; ")
    return f"Continuous segment; {endpoint_hint}; {direction}".strip("; ")


def piece_display(entry: dict[str, object]) -> str:
    if entry.get("type") != "Gap":
        return "-"
    return f"{entry.get('piece')}/{entry.get('piece_count')}"


def render_endpoints_table(batch_name: str, batch_entries: list[dict[str, object]]) -> str:
    lines = [
        "| # | Segment | Side | Piece | Coordinates | Close screenshot | Context screenshot | Notes |",
        "|---|---------|------|-------|-------------|-----------------|-------------------|-------|",
    ]
    for endpoint_id, entry in enumerate(batch_entries, start=1):
        coords = f"({fmt_coord(entry.get('lon'))}, {fmt_coord(entry.get('lat'))})"
        close_file = f"`_temp/visual-review/screenshots/{batch_name}-ep-{endpoint_id:02d}-close.png`"
        context_file = f"`_temp/visual-review/screenshots/{batch_name}-ep-{endpoint_id:02d}-context.png`"
        lines.append(
            f"| {endpoint_id} | {entry['segment']} | {entry['side']} | {piece_display(entry)} | "
            f"{coords} | {close_file} | {context_file} | {endpoint_note(entry)} |"
        )
    return "\n".join(lines)


def render_prompt(batch_name: str, batch_entries: list[dict[str, object]]) -> str:
    table = render_endpoints_table(batch_name, batch_entries)
    results_path = f"_temp/visual-review/batch-results/{batch_name}-results.json"
    example_close = f"{batch_name}-ep-01-close.png"
    example_context = f"{batch_name}-ep-01-context.png"
    batch_label = batch_name.replace("-", " ").title()
    return f"""# Visual Review {batch_label} — Screenshot Analysis

You are performing INDEPENDENT visual verification of highway segment endpoints
by analyzing pre-captured map screenshots.

## CRITICAL: Visual-only assessment

- Do NOT look at any heuristic results files (heuristic-results.csv, etc.)
- Do NOT read any CSV, JSON, or data files in `_temp/` other than the screenshot
  image files listed in the endpoint table below
- ONLY use what you can visually read from the map screenshots: rendered road
  labels, route shield graphics, county boundary lines, and the segment highlight
- Do NOT fabricate observations — if a label is unreadable, say so

Your assessment must come purely from visual map reading, not data queries.

## How screenshots were captured

Each endpoint has two pre-captured screenshots taken from the FTW Segment
Explorer web app (https://pine-j.github.io/Roadway-Segment-Limits/):

- **Close** (zoom 17, ~200-300m radius): high detail, road labels and route
  shields should be readable
- **Context** (zoom 15, wider area): shows surrounding roads, interchanges,
  and county boundaries for spatial context

The selected segment is the **thick maroon/teal line**. Unselected segments
are thinner and should be ignored. The endpoint is where the thick segment
line terminates.

**Segment types visible in screenshots:**
- **Individual segments** (suffixed, e.g., "IH 20 - B"): one segment is
  highlighted. Its endpoints are where the thick line starts/ends.
- **Corridor segments** (unsuffixed, e.g., "SH 360"): the entire corridor is
  highlighted — all sub-segments (A, B, C, etc.) show as one continuous thick
  line. The endpoint is where the overall corridor line terminates.
- **GAP segments**: the thick line has one or more visible breaks. Each
  contiguous stretch is a "piece" with its own From/To endpoints. The Notes
  column in the endpoint table indicates which piece and the total count.

## Workflow per endpoint

For each row in the endpoint table:

1. **Read the CLOSE screenshot** using the Read tool with the file path from
   the table. This is an image file — the Read tool will display it visually.
2. **Read the CONTEXT screenshot** the same way.
3. **Quality-check both screenshots** before recording results:
   - If the screenshot is blank/grey/blue (tile rendering failure), note it as
     `visual_confidence: "low"` with reasoning explaining the issue
   - If no thick segment line is visible, note this in reasoning
   - If road labels are unreadable, use what you can see from the context view
     and set confidence accordingly
4. **Assess the endpoint** based on what you see (details below).
5. **Record your assessment** in the JSON output.

## What to look for at each endpoint

### A. Read all visible road labels near the endpoint
- Street name labels rendered along road lines (for example `W Vickery Blvd`, `E Euless Blvd`)
- Route shields with numbers (for example `IH 30`, `SH 114`, `US 281`)
- Local or alias names that appear on the map alongside route numbers
- Report BOTH the local name AND the route number if both are visible

### B. Identify which road is actually at the endpoint
- The endpoint is where the thick segment line ends — which road crosses or meets the segment at that exact point?
- A nearby road 200m away is not the limit
- If multiple roads are near the endpoint, identify which one the segment line actually terminates at
- Look carefully at frontage roads versus mainlines

### C. Check for offset situations
- If the endpoint is between intersections, note that explicitly
- Note the compass direction from the nearest identifiable road to the endpoint

### D. Look for county boundaries
- County boundary lines may appear as thin administrative lines on the map, or
  as a color change in the basemap tint (different counties have different
  background colors)
- If the endpoint itself is at a county boundary, set `county_boundary_at_endpoint: true` and use `"[County Name] County Line"` as `limit_identification`
- A county line that is merely nearby should be noted in `reasoning` but not flagged as `county_boundary_at_endpoint`

### E. For GAP segments specifically
- Does the thick segment line visibly end or restart at this endpoint? You
  should see the line terminating and a gap before the next piece begins.
- Is the gap a real physical discontinuity, or does the road continue but
  the segment highlight stops? (Both are valid — report what you see.)
- What road or boundary is at this specific piece's endpoint? Each piece's
  From and To limits are identified independently — do not assume they are
  the same as another piece's limits.
- If this is a corridor segment (unsuffixed name), the entire corridor is
  highlighted. The gap should be visible as a break in the thick line.

## Endpoints

{table}

## Output format

Write JSON, not markdown, to `{results_path}`.

```json
[
  {{
    "endpoint_id": 1,
    "segment": "SEGMENT_NAME",
    "side": "From",
    "piece": null,
    "close_screenshot": "{example_close}",
    "context_screenshot": "{example_context}",
    "visible_labels": ["Label 1", "Label 2"],
    "visible_shields": ["IH 30"],
    "county_boundary_at_endpoint": false,
    "limit_identification": "Road or County Line",
    "limit_alias": null,
    "is_offset": false,
    "offset_direction": null,
    "offset_from": null,
    "visual_confidence": "high",
    "reasoning": "Why the endpoint appears to end at this limit"
  }},
  {{
    "endpoint_id": 2,
    "segment": "GAP_SEGMENT_NAME",
    "side": "To",
    "piece": 1,
    "close_screenshot": "{batch_name}-ep-02-close.png",
    "context_screenshot": "{batch_name}-ep-02-context.png",
    "visible_labels": ["Route label"],
    "visible_shields": ["Route shield"],
    "county_boundary_at_endpoint": false,
    "limit_identification": "Route or road name",
    "limit_alias": null,
    "is_offset": false,
    "offset_direction": null,
    "offset_from": null,
    "visual_confidence": "high",
    "reasoning": "Why this gap-piece endpoint is bounded by the identified road"
  }}
]
```

Key fields for reconciliation:
- `piece`: null for continuous segments, 1-based integer for gap segments
- `limit_identification`: the primary road or boundary name
- `limit_alias`: local or street name shown alongside the route number, or null if none is visible
- `is_offset`, `offset_direction`, and `offset_from`: structured offset data
- `county_boundary_at_endpoint`: true only if the segment endpoint is the county line itself
- `visible_labels` and `visible_shields`: raw observations for the audit trail
"""


def main() -> None:
    args = parse_args()
    ensure_dirs(args.output_dir)

    manifest_entries = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest_entries, list):
        raise ValueError(f"Manifest must contain a JSON array: {args.manifest}")

    batches = chunked(manifest_entries, args.batch_size)
    for batch_number, batch_entries in enumerate(batches, start=1):
        batch_name = f"batch-{batch_number:02d}"
        prompt_path = args.output_dir / f"{batch_name}.md"
        prompt_path.write_text(render_prompt(batch_name, batch_entries), encoding="utf-8")
        print(f"Wrote file: {prompt_path}")

    print(f"Generated {len(batches)} batch prompt file(s).")


if __name__ == "__main__":
    main()
