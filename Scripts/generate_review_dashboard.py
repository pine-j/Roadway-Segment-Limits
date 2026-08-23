#!/usr/bin/env python3
"""Generate a self-contained human-review dashboard from visual-review outputs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VISUAL_REVIEW_DIR = ROOT / "_temp" / "visual-review"


@dataclass(frozen=True)
class EndpointKey:
    segment: str
    side: str
    piece: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--visual-review-dir",
        type=Path,
        default=DEFAULT_VISUAL_REVIEW_DIR,
        help=f"Root directory containing visual-review artifacts. Default: {DEFAULT_VISUAL_REVIEW_DIR}",
    )
    parser.add_argument("--final-results", type=Path, default=None)
    parser.add_argument("--heuristic-results", type=Path, default=None)
    parser.add_argument("--batch-results-dir", type=Path, default=None)
    parser.add_argument("--output-path", type=Path, default=None)
    return parser.parse_args()


def resolve_path(path: Path | None, fallback: Path) -> Path:
    return (path or fallback).resolve()


def require_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} was not found: {path}")


def safe_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def maybe_text(value: object) -> str | None:
    text = safe_text(value)
    return text or None


def parse_float(value: object, default: float | None = 0.0) -> float | None:
    text = safe_text(value)
    if not text:
        return default
    return float(text)


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return safe_text(value).lower() in {"1", "true", "yes", "y"}


def parse_piece(value: object) -> int | None:
    text = safe_text(value)
    if not text:
        return None
    return int(float(text))


def normalize_segment(value: object) -> str:
    return " ".join(safe_text(value).split())


def normalize_side(value: object) -> str:
    text = safe_text(value).lower()
    if text == "from":
        return "From"
    if text == "to":
        return "To"
    raise ValueError(f"Unsupported side value: {value!r}")


def endpoint_key(segment: object, side: object, piece: object) -> EndpointKey:
    return EndpointKey(
        segment=normalize_segment(segment),
        side=normalize_side(side),
        piece=parse_piece(piece),
    )


def validate_columns(dataframe: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(dataframe.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def load_csv_records(path: Path, *, required: set[str], label: str) -> list[dict[str, object]]:
    require_exists(path, label)
    dataframe = pd.read_csv(path)
    validate_columns(dataframe, required, label)
    return dataframe.to_dict("records")


def load_rows_by_key(
    records: list[dict[str, object]],
    *,
    label: str,
) -> dict[EndpointKey, dict[str, object]]:
    rows_by_key: dict[EndpointKey, dict[str, object]] = {}
    for row in records:
        key = endpoint_key(
            row.get("Segment") or row.get("segment"),
            row.get("Side") or row.get("side"),
            row.get("Piece") or row.get("piece"),
        )
        if key in rows_by_key:
            raise ValueError(f"Duplicate {label} row for {key}")
        rows_by_key[key] = row
    return rows_by_key


def load_visual_rows(batch_results_dir: Path) -> dict[EndpointKey, dict[str, object]]:
    require_exists(batch_results_dir, "Batch-results directory")
    batch_paths = sorted(batch_results_dir.glob("*.json"))
    if not batch_paths:
        raise FileNotFoundError(f"No batch result JSON files were found in {batch_results_dir}")

    visual_rows: dict[EndpointKey, dict[str, object]] = {}
    for path in batch_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON array in {path}")
        for entry in payload:
            if not isinstance(entry, dict):
                raise ValueError(f"Each visual-review entry must be an object in {path}")
            key = endpoint_key(entry.get("segment"), entry.get("side"), entry.get("piece"))
            if key in visual_rows:
                raise ValueError(f"Duplicate visual-review row for {key}")
            entry_copy = dict(entry)
            entry_copy["_source_file"] = path.name
            visual_rows[key] = entry_copy
    return visual_rows


def dedupe_text(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = safe_text(value)
        if not text:
            continue
        marker = text.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(text)
    return deduped


def build_visual_labels(entry: dict[str, object]) -> tuple[list[str], list[str], str]:
    visible_labels = dedupe_text(list(entry.get("visible_labels", []) or []))
    visible_shields = dedupe_text(list(entry.get("visible_shields", []) or []))
    rendered = visible_labels + [f"{shield} shield" for shield in visible_shields]
    return visible_labels, visible_shields, ", ".join(dedupe_text(rendered))


def relative_path(from_dir: Path, to_path: Path) -> str:
    return os.path.relpath(to_path, start=from_dir).replace("\\", "/")


def resolve_screenshot_path(
    filename: object,
    *,
    output_dir: Path,
    screenshots_dir: Path,
) -> str | None:
    text = safe_text(filename)
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        target = path
    elif path.parts and path.parts[0] == "screenshots":
        target = screenshots_dir.parent / path
    else:
        target = screenshots_dir / path.name
    return relative_path(output_dir, target)


def build_case_label(segment: str, side: str, piece: int | None) -> str:
    if piece is None:
        return f"{segment} / {side}"
    return f"{segment} / {side} / piece {piece}"


def required_value(row: dict[str, object] | None, key: EndpointKey, label: str) -> dict[str, object]:
    if row is None:
        raise ValueError(
            f"Missing {label} row for endpoint: {key.segment} / {key.side} / piece {key.piece or '-'}"
        )
    return row


def build_review_data(
    *,
    final_rows: list[dict[str, object]],
    heuristic_by_key: dict[EndpointKey, dict[str, object]],
    visual_by_key: dict[EndpointKey, dict[str, object]],
    output_path: Path,
) -> list[dict[str, object]]:
    screenshots_dir = DEFAULT_VISUAL_REVIEW_DIR / "screenshots"
    review_data: list[dict[str, object]] = []
    for index, final_row in enumerate(final_rows, start=1):
        key = endpoint_key(final_row.get("Segment"), final_row.get("Side"), final_row.get("Piece"))
        heuristic_row = required_value(heuristic_by_key.get(key), key, "heuristic")
        visual_row = required_value(visual_by_key.get(key), key, "visual-review")
        visible_labels, visible_shields, labels_seen_text = build_visual_labels(visual_row)
        segment = normalize_segment(final_row.get("Segment"))
        side = normalize_side(final_row.get("Side"))
        piece = parse_piece(final_row.get("Piece"))
        review_data.append(
            {
                "order": index,
                "case_key": f"{segment}::{side}::{piece if piece is not None else ''}",
                "label": build_case_label(segment, side, piece),
                "segment": segment,
                "direction": safe_text(heuristic_row.get("Direction")),
                "type": safe_text(final_row.get("Type") or heuristic_row.get("Type") or "Continuous"),
                "side": side,
                "piece": piece,
                "heuristic_limit": safe_text(final_row.get("Heuristic-Limit") or heuristic_row.get("Auto-Limit")),
                "heuristic_confidence": parse_float(final_row.get("Heuristic-Confidence"), 0.0),
                "heuristic_label": safe_text(heuristic_row.get("Heuristic")),
                "heuristic_confidence_bucket": safe_text(heuristic_row.get("Confidence-Bucket")),
                "visual_limit": safe_text(final_row.get("Visual-Limit")),
                "visual_alias": maybe_text(visual_row.get("limit_alias")),
                "visual_confidence": safe_text(final_row.get("Visual-Confidence") or visual_row.get("visual_confidence")),
                "visual_labels_seen": visible_labels,
                "visual_shields_seen": visible_shields,
                "visual_labels_seen_text": labels_seen_text or safe_text(final_row.get("Visual-Labels-Seen")),
                "visual_reasoning": safe_text(visual_row.get("reasoning")),
                "resolution": safe_text(final_row.get("Resolution")),
                "category": safe_text(final_row.get("Disagreement-Category")),
                "final_limit": safe_text(final_row.get("Final-Limit")),
                "final_confidence": parse_float(final_row.get("Final-Confidence"), 0.0),
                "close_screenshot": resolve_screenshot_path(
                    visual_row.get("close_screenshot"),
                    output_dir=output_path.parent,
                    screenshots_dir=screenshots_dir,
                ),
                "context_screenshot": resolve_screenshot_path(
                    visual_row.get("context_screenshot"),
                    output_dir=output_path.parent,
                    screenshots_dir=screenshots_dir,
                ),
                "lon": parse_float(heuristic_row.get("Lon"), None),
                "lat": parse_float(heuristic_row.get("Lat"), None),
                "county_boundary_at_endpoint": parse_bool(visual_row.get("county_boundary_at_endpoint")),
                "is_offset": parse_bool(visual_row.get("is_offset")),
                "offset_direction": maybe_text(visual_row.get("offset_direction")),
                "offset_from": maybe_text(visual_row.get("offset_from")),
                "visual_review_file": safe_text(visual_row.get("_source_file")),
            }
        )
    return review_data


def compute_run_id(review_data: list[dict[str, object]]) -> str:
    payload = json.dumps(review_data, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=True).replace("</", "<\\/")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Roadway Segment Review Dashboard</title>
  <link rel="stylesheet" href="https://js.arcgis.com/4.32/esri/themes/light/main.css">
  <style>
__PAGE_STYLE__
  </style>
  <script src="https://js.arcgis.com/4.32/"></script>
</head>
<body>
  <div class="summary-bar">
    <div class="summary-header">
      <div>
        <div class="summary-title">Roadway Segment Review Dashboard</div>
        <div class="summary-meta" id="summaryMeta"></div>
      </div>
      <div class="view-toggle" id="viewToggleGroup">
        <button type="button" id="tableViewButton">Table View</button>
        <button type="button" id="caseViewButton">Case View</button>
      </div>
    </div>
    <div class="summary-metrics" id="summaryMetrics"></div>
    <div class="summary-controls">
      <div class="controls-cluster">
        <div class="filter-group" id="scopeFilters">
          <button type="button" class="filter-pill" data-scope-filter="all" id="scopeAllButton"></button>
          <button type="button" class="filter-pill" data-scope-filter="disagreements" id="scopeDisagreementsButton"></button>
          <button type="button" class="filter-pill" data-scope-filter="conflicts" id="scopeConflictsButton"></button>
          <button type="button" class="filter-pill" data-scope-filter="unreviewed" id="scopeUnreviewedButton"></button>
        </div>
        <label class="control-label">
          Resolution
          <select id="resolutionFilter">
            <option value="all">All resolutions</option>
            <option value="confirmed">confirmed</option>
            <option value="enriched">enriched</option>
            <option value="visual_preferred">visual_preferred</option>
            <option value="conflict">conflict</option>
            <option value="visual_only">visual_only</option>
          </select>
        </label>
        <label class="control-label">
          Reviewer
          <input type="text" id="reviewerName" placeholder="Optional reviewer name">
        </label>
      </div>
      <div class="controls-cluster">
        <label class="checkbox-control" for="autoAdvanceToggle">
          <input type="checkbox" id="autoAdvanceToggle">
          <span>Auto-advance</span>
        </label>
        <button type="button" class="mini-button" id="themeToggleButton" aria-pressed="false">Theme: Auto</button>
        <button type="button" class="mini-button help-button" id="hotkeyHelpButton" aria-expanded="false" aria-controls="hotkeyOverlay" title="Keyboard shortcuts">?</button>
        <button type="button" class="mini-button" id="restartTourButton" title="Restart onboarding tour">Restart Tour</button>
        <button type="button" class="mini-button" id="importButton">Import Notes</button>
        <input type="file" id="importFile" accept=".json" hidden>
        <button type="button" class="mini-button" id="exportButton">Export Notes</button>
      </div>
    </div>
  </div>
  <main>
    <section id="tableView" class="view panel">
      <div class="table-toolbar">
        <div class="muted" id="tableSummary"></div>
        <input type="search" id="tableSearch" placeholder="Search segments...">
      </div>
      <div class="table-wrapper" id="tableWrapper"></div>
    </section>
    <section id="caseView" class="view hidden case-shell">
      <div class="panel case-toolbar" id="caseToolbar">
        <div>
          <div class="case-title" id="caseTitle"></div>
          <div class="case-subtitle" id="caseSubtitle"></div>
          <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
        </div>
        <div class="case-controls">
          <button type="button" class="nav-button" id="prevCaseButton">Prev</button>
          <button type="button" class="nav-button" id="nextCaseButton">Next</button>
          <label class="control-label jump-control">
            Jump to
            <select id="caseJumpSelect"></select>
          </label>
        </div>
      </div>
      <div class="panel card notes-card">
        <h3>Reviewer Notes</h3>
        <div class="notes-help">Changes are auto-saved in localStorage for this run. You can revisit any case and edit it at any time before export.</div>
        <div class="status-options" id="statusOptions"></div>
        <textarea id="reviewerNotes" placeholder="Type observations, rationale, or follow-up questions here."></textarea>
        <div class="override-grid" id="overrideGrid"></div>
        <div class="notes-help">`Corrected limit` is required later if you want adjudicated CSV output for a disagree case.</div>
      </div>
      <div class="details-and-map">
        <div class="detail-stack">
          <div class="card" id="heuristicCard"></div>
          <div class="card" id="visualCard"></div>
          <div class="card" id="decisionCard"></div>
        </div>
        <div class="panel map-card">
          <div id="mapContainer"></div>
        </div>
      </div>
      <div class="case-grid">
        <div class="panel image-card" id="closeImageCard"></div>
        <div class="panel image-card" id="contextImageCard"></div>
      </div>
    </section>
  </main>
  <div class="overlay hidden hotkey-overlay" id="hotkeyOverlay" aria-hidden="true">
    <div class="overlay-panel hotkey-panel" role="dialog" aria-modal="true" aria-labelledby="hotkeyOverlayTitle">
      <div class="overlay-header">
        <h3 id="hotkeyOverlayTitle">Keyboard Shortcuts</h3>
        <button type="button" class="mini-button" id="hotkeyOverlayCloseButton">Close</button>
      </div>
      <ul class="hotkey-list">
        <li><span><kbd>Left</kbd> / <kbd>Right</kbd></span><span>Previous or next case</span></li>
        <li><span><kbd>1</kbd></span><span>Mark as Not reviewed</span></li>
        <li><span><kbd>2</kbd></span><span>Mark as Agree</span></li>
        <li><span><kbd>3</kbd></span><span>Mark as Disagree</span></li>
        <li><span><kbd>4</kbd></span><span>Mark as Needs discussion</span></li>
        <li><span><kbd>Esc</kbd></span><span>Return to table view</span></li>
      </ul>
    </div>
  </div>
  <div class="overlay hidden tour-welcome-overlay" id="tourWelcomeOverlay" aria-hidden="true">
    <div class="overlay-panel tour-welcome-panel" role="dialog" aria-modal="true" aria-labelledby="tourWelcomeTitle">
      <div class="overlay-header">
        <h3 id="tourWelcomeTitle">Welcome to the Review Dashboard</h3>
      </div>
      <p>This dashboard helps you review automated speed-limit predictions for roadway segment endpoints. You can inspect heuristic and visual analysis results, view the location on a map, and record your agreement or corrections.</p>
      <p>Use <strong>Table View</strong> for an overview of all cases, then switch to <strong>Case View</strong> when you want detailed review controls for one case at a time.</p>
      <div class="tour-welcome-actions">
        <button type="button" class="tour-primary-button" id="tourStartButton">Start Tour</button>
        <button type="button" class="tour-link-button" id="tourWelcomeSkipButton">Skip</button>
      </div>
    </div>
  </div>
  <div class="overlay hidden tour-overlay" id="tourOverlay" aria-hidden="true">
    <div class="tour-tooltip" id="tourTooltip" role="dialog" aria-modal="false" aria-labelledby="tourTooltipTitle" data-position="bottom">
      <div class="tour-step-counter" id="tourStepCounter">1 of 8</div>
      <h3 id="tourTooltipTitle">Review Dashboard Tour</h3>
      <p id="tourTooltipText"></p>
      <div class="tour-tooltip-actions">
        <button type="button" class="tour-secondary-button" id="tourSkipButton">Skip Tour</button>
        <button type="button" class="tour-primary-button" id="tourNextButton">Next</button>
      </div>
    </div>
  </div>
  <div class="overlay hidden lightbox-overlay" id="imageLightbox" role="dialog" aria-modal="true" aria-label="Image lightbox" aria-hidden="true">
    <button type="button" class="lightbox-close" id="lightboxCloseButton" aria-label="Close lightbox">&times;</button>
    <img id="lightboxImage" alt="">
  </div>
  <script>
__PAGE_SCRIPT__
  </script>
</body>
</html>
"""

PAGE_STYLE = """
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-alt: #eef2f5;
      --border: #c7d0d8;
      --border-strong: #8fa1b2;
      --text: #1d2935;
      --muted: #5d6b78;
      --accent: #005f8f;
      --success: #216e39;
      --warn: #8a5600;
      --danger: #a02323;
      --shadow: 0 8px 22px rgba(20, 35, 52, 0.08);
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
    }
    :root[data-theme=dark] {
      color-scheme: dark;
      --bg: #1a1e24;
      --panel: #252a31;
      --panel-alt: #1e2329;
      --border: #3a424d;
      --border-strong: #556070;
      --text: #d8dee6;
      --muted: #8a95a3;
      --accent: #4da6d9;
      --success: #3fb950;
      --warn: #d29922;
      --danger: #f85149;
      --shadow: 0 8px 22px rgba(0,0,0,0.3);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --bg: #1a1e24;
        --panel: #252a31;
        --panel-alt: #1e2329;
        --border: #3a424d;
        --border-strong: #556070;
        --text: #d8dee6;
        --muted: #8a95a3;
        --accent: #4da6d9;
        --success: #3fb950;
        --warn: #d29922;
        --danger: #f85149;
        --shadow: 0 8px 22px rgba(0,0,0,0.3);
      }
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.45; }
    button, input, select, textarea { font: inherit; }
    .summary-bar { position: sticky; top: 0; z-index: 10; background: rgba(244,246,248,.96); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); padding: 16px 20px 14px; }
    .summary-header, .summary-metrics, .summary-controls, .controls-cluster, .view-toggle, .filter-group, .case-controls, .jump-control, .status-options { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; }
    .summary-header { justify-content: space-between; margin-bottom: 10px; }
    .summary-title { font-size: 20px; font-weight: 700; }
    .summary-meta { color: var(--muted); font-size: 13px; }
    .summary-controls { margin-top: 10px; justify-content: space-between; }
    .control-label { display: inline-flex; gap: 8px; align-items: center; color: var(--muted); font-size: 14px; }
    .control-label input, .control-label select, .override-field input { min-height: 38px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); padding: 8px 10px; color: var(--text); }
    .control-label input[type="checkbox"], .override-field input[type="checkbox"], .checkbox-control input[type="checkbox"] { width: 18px; height: 18px; min-height: auto; padding: 0; border-radius: 4px; accent-color: var(--accent); }
    .checkbox-control { display: inline-flex; gap: 10px; align-items: center; color: var(--muted); font-size: 14px; }
    .metric-pill, .filter-pill, .view-toggle button, .table-sort, .mini-button, .nav-button { border: 1px solid var(--border); background: var(--panel); color: var(--text); border-radius: 999px; padding: 8px 12px; cursor: pointer; transition: border-color .15s ease, background .15s ease, color .15s ease; }
    .metric-pill { cursor: default; box-shadow: var(--shadow); }
    .filter-pill.active, .view-toggle button.active, .table-sort.active, .mini-button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    .help-button { min-width: 38px; padding-inline: 0; font-weight: 700; }
    main { padding: 18px 20px 32px; }
    .view.hidden { display: none; }
    .panel, .card { background: var(--panel); border: 1px solid var(--border); border-radius: 18px; box-shadow: var(--shadow); }
    .panel { overflow: hidden; }
    .table-toolbar { display: flex; justify-content: space-between; gap: 10px; padding: 16px 18px 0; }
    .table-wrapper { overflow: auto; padding: 12px 18px 18px; }
    table { width: 100%; border-collapse: collapse; min-width: 860px; }
    thead th { position: sticky; top: 0; background: var(--panel); border-bottom: 1px solid var(--border); padding: 12px 10px; text-align: left; white-space: nowrap; z-index: 1; }
    tbody td { border-bottom: 1px solid var(--border); padding: 12px 10px; vertical-align: top; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: #f8fbfd; }
    tbody tr.selected { background: #edf6fb; }
    .resolution-badge, .status-badge, .category-badge { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 600; white-space: nowrap; }
    .resolution-confirmed, .status-agree { background: #e6f4ea; color: var(--success); }
    .resolution-enriched { background: #e5f1f8; color: var(--accent); }
    .resolution-visual_preferred { background: #fff2df; color: var(--warn); }
    .resolution-conflict, .status-disagree { background: #fde8e8; color: var(--danger); }
    .resolution-visual_only { background: #f2ebfb; color: #6c3fb4; }
    .status-not_reviewed { background: #eef2f5; color: var(--muted); }
    .status-needs_discussion { background: #fff5d9; color: #845900; }
    .category-badge { background: var(--panel-alt); color: var(--muted); margin-top: 8px; }
    .empty-state { padding: 28px 20px; color: var(--muted); }
    .case-shell { display: grid; gap: 16px; }
    .case-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; padding: 16px 18px; }
    .case-title { font-size: 20px; font-weight: 700; }
    .case-subtitle { color: var(--muted); font-size: 14px; margin-top: 4px; }
    .progress-bar { height: 4px; background: var(--panel-alt); border-radius: 2px; margin-top: 8px; }
    .progress-fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width .2s; }
    .case-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .details-and-map { display: grid; grid-template-columns: 2fr 3fr; gap: 16px; align-items: stretch; }
    .details-and-map > * { min-width: 0; }
    .detail-stack { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
    .image-card, .card, .map-card { padding: 16px 18px; }
    .image-card h3, .card h3, .map-card h3 { margin: 0 0 12px; font-size: 16px; }
    .image-card img { width: 100%; min-height: 220px; max-height: 440px; object-fit: contain; border-radius: 12px; border: 1px solid var(--border); background: var(--panel-alt); cursor: zoom-in; }
    .image-meta, .card p, .notes-help { margin: 8px 0 0; color: var(--muted); font-size: 14px; }
    .card dl { display: grid; grid-template-columns: minmax(0, 130px) minmax(0, 1fr); gap: 8px 10px; margin: 0; }
    .card dt { font-weight: 600; color: var(--muted); }
    .card dd { margin: 0; overflow-wrap: anywhere; }
    .map-card { display: flex; align-self: stretch; min-height: 500px; height: 100%; }
    #mapContainer {
      position: relative;
      width: 100%;
      min-height: 500px;
      height: 100%;
      flex: 1 1 auto;
      border: 1px solid var(--border);
      border-radius: 14px;
      overflow: hidden;
      background: #dfe7ee;
    }
    .map-message {
      position: absolute;
      inset: 0;
      z-index: 500;
      display: grid;
      place-items: center;
      padding: 18px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
      background: rgba(255, 255, 255, 0.72);
      pointer-events: none;
    }
    .map-message.hidden { display: none; }
    .notes-card textarea { width: 100%; min-height: 140px; resize: vertical; border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--panel); color: var(--text); }
    .status-options { margin: 14px 0; }
    .status-option { display: inline-flex; gap: 8px; align-items: center; padding: 8px 10px; border: 1px solid var(--border); border-radius: 999px; background: var(--panel); }
    .override-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
    .override-field { display: grid; gap: 6px; color: var(--muted); font-size: 14px; }
    .checkbox-field { display: flex; align-items: center; gap: 10px; padding: 0 4px; color: var(--text); }
    .muted { color: var(--muted); }
    .mono { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; }
    .image-placeholder { min-height: 220px; display: grid; place-items: center; border: 1px dashed var(--border-strong); border-radius: 12px; background: var(--panel-alt); color: var(--muted); text-align: center; padding: 18px; }
    .overlay { position: fixed; inset: 0; display: grid; place-items: center; padding: 20px; }
    .overlay.hidden { display: none; }
    .overlay-panel { width: min(460px, 100%); background: var(--panel); border: 1px solid var(--border); border-radius: 18px; box-shadow: var(--shadow); padding: 18px 20px; }
    .overlay-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
    .overlay-header h3 { margin: 0; font-size: 18px; }
    .hotkey-overlay { z-index: 200; background: rgba(10, 18, 28, 0.45); }
    .hotkey-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
    .hotkey-list li { display: flex; justify-content: space-between; align-items: center; gap: 10px 16px; flex-wrap: wrap; padding: 10px 12px; border-radius: 12px; background: var(--panel-alt); }
    .hotkey-list li span:last-child { color: var(--muted); text-align: right; }
    kbd { display: inline-block; padding: 3px 7px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-size: 13px; box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.06); }
    .lightbox-overlay { z-index: 100; background: rgba(0, 0, 0, 0.85); cursor: zoom-out; }
    .lightbox-overlay img { max-width: 95vw; max-height: 95vh; object-fit: contain; cursor: auto; }
    .lightbox-close { position: absolute; top: 16px; right: 20px; background: rgba(255,255,255,0.15); border: none; color: #fff; font-size: 28px; width: 40px; height: 40px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; }
    body.tour-active { overscroll-behavior: contain; }
    .tour-elevated-ancestor { z-index: 301 !important; }
    .tour-highlight {
      position: relative !important;
      z-index: 301 !important;
      border-radius: var(--tour-radius, 18px);
      box-shadow: 0 0 0 4px var(--accent), 0 18px 36px rgba(0, 0, 0, 0.22);
      isolation: isolate;
    }
    .tour-overlay {
      z-index: 300;
      background: rgba(7, 12, 18, 0.65);
      pointer-events: none;
      place-items: start;
    }
    .tour-tooltip {
      --tour-arrow-offset: 50%;
      position: fixed;
      top: 24px;
      left: 24px;
      width: min(360px, calc(100vw - 32px));
      border: 1px solid var(--border);
      border-radius: 18px;
      background: var(--panel);
      color: var(--text);
      box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
      padding: 18px 18px 16px;
      pointer-events: auto;
    }
    .tour-tooltip::after {
      content: "";
      position: absolute;
      width: 16px;
      height: 16px;
      background: var(--panel);
      border: 1px solid var(--border);
      transform: rotate(45deg);
    }
    .tour-tooltip[data-position="top"]::after {
      left: calc(var(--tour-arrow-offset) - 8px);
      bottom: -8px;
      border-top: none;
      border-left: none;
    }
    .tour-tooltip[data-position="bottom"]::after {
      left: calc(var(--tour-arrow-offset) - 8px);
      top: -8px;
      border-right: none;
      border-bottom: none;
    }
    .tour-tooltip[data-position="left"]::after {
      top: calc(var(--tour-arrow-offset) - 8px);
      right: -8px;
      border-left: none;
      border-bottom: none;
    }
    .tour-tooltip[data-position="right"]::after {
      top: calc(var(--tour-arrow-offset) - 8px);
      left: -8px;
      border-top: none;
      border-right: none;
    }
    .tour-tooltip h3 { margin: 0 0 10px; font-size: 18px; }
    .tour-tooltip p { margin: 0; color: var(--muted); font-size: 14px; }
    .tour-step-counter {
      display: inline-flex;
      align-items: center;
      margin-bottom: 10px;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .tour-tooltip-actions, .tour-welcome-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 18px;
    }
    .tour-primary-button, .tour-secondary-button, .tour-link-button {
      font: inherit;
      cursor: pointer;
    }
    .tour-primary-button, .tour-secondary-button {
      border-radius: 999px;
      padding: 9px 14px;
      border: 1px solid var(--border);
      transition: border-color .15s ease, background .15s ease, color .15s ease;
    }
    .tour-primary-button {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      box-shadow: var(--shadow);
    }
    .tour-secondary-button {
      background: var(--panel);
      color: var(--text);
    }
    .tour-link-button {
      border: none;
      background: transparent;
      color: var(--accent);
      padding: 0;
      text-decoration: underline;
      text-underline-offset: 3px;
    }
    .tour-welcome-overlay { z-index: 320; background: rgba(7, 12, 18, 0.72); }
    .tour-welcome-panel { width: min(560px, 100%); padding: 24px 26px; }
    .tour-welcome-panel p { margin: 0 0 14px; color: var(--muted); font-size: 15px; }
    :root[data-theme=dark] .summary-bar { background: rgba(26,30,36,.96); }
    :root[data-theme=dark] tbody tr:hover { background: #20262d; }
    :root[data-theme=dark] tbody tr.selected { background: #213547; }
    :root[data-theme=dark] .image-card, :root[data-theme=dark] .map-card { background: #2b3139; }
    :root[data-theme=dark] .image-card img { background: #252a31; }
    :root[data-theme=dark] #mapContainer {
      background: #13181d;
      filter: invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.95);
    }
    :root[data-theme=dark] .map-message { background: rgba(26, 30, 36, 0.76); }
    @media (prefers-color-scheme: dark) {
      .summary-bar { background: rgba(26,30,36,.96); }
      tbody tr:hover { background: #20262d; }
      tbody tr.selected { background: #213547; }
      .image-card, .map-card { background: #2b3139; }
      .image-card img { background: #252a31; }
      #mapContainer {
        background: #13181d;
        filter: invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.95);
      }
      .map-message { background: rgba(26, 30, 36, 0.76); }
    }
    :root[data-theme=light] {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --panel-alt: #eef2f5;
      --border: #c7d0d8;
      --border-strong: #8fa1b2;
      --text: #1d2935;
      --muted: #5d6b78;
      --accent: #005f8f;
      --success: #216e39;
      --warn: #8a5600;
      --danger: #a02323;
      --shadow: 0 8px 22px rgba(20, 35, 52, 0.08);
    }
    :root[data-theme=light] .summary-bar { background: rgba(244,246,248,.96); }
    :root[data-theme=light] tbody tr:hover { background: #f8fbfd; }
    :root[data-theme=light] tbody tr.selected { background: #edf6fb; }
    @media (max-width: 1100px) {
      .details-and-map, .override-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 900px) {
      .case-grid { grid-template-columns: 1fr; }
      .summary-controls, .case-toolbar { flex-direction: column; align-items: stretch; }
      .case-controls, .jump-control, .view-toggle, .controls-cluster { width: 100%; }
    }
"""

PAGE_SCRIPT = """
    const REVIEW_DATA = __REVIEW_DATA__;
    const STORAGE_KEY = __STORAGE_KEY__;
    const THEME_STORAGE_KEY = "review-dashboard-theme";
    const TOUR_COMPLETED_KEY = "review-dashboard-tour-completed";
    const GENERATED_AT = __GENERATED_AT__;
    const RUN_ID = __RUN_ID__;
    const STATUS_LABELS = {
      not_reviewed: "Not reviewed",
      agree: "Agree",
      disagree: "Disagree",
      needs_discussion: "Needs discussion",
    };
    const VALID_REVIEW_STATUSES = new Set(Object.keys(STATUS_LABELS));
    const TOUR_STEPS = [
      {
        step: 1,
        targetId: "scopeFilters",
        text: "Filter cases by status: show all, only disagreements, conflicts, or unreviewed cases.",
        view: "table",
        dataset: { position: "bottom" },
      },
      {
        step: 2,
        targetId: "viewToggleGroup",
        text: "Switch between Table View for an overview and Case View for detailed per-case review.",
        view: "table",
        dataset: { position: "bottom" },
      },
      {
        step: 3,
        targetId: "tableWrapper",
        text: "The table shows all cases with sortable columns. Click any row to open it in Case View.",
        view: "table",
        dataset: { position: "top" },
      },
      {
        step: 4,
        targetId: "caseToolbar",
        text: "Navigate between cases using arrow buttons, keyboard shortcuts, or the dropdown.",
        view: "case",
        dataset: { position: "bottom" },
      },
      {
        step: 5,
        targetId: "statusOptions",
        text: "Set your review status: Agree, Disagree, or Needs Discussion. Your choices auto-save.",
        view: "case",
        dataset: { position: "bottom" },
      },
      {
        step: 6,
        targetId: "mapContainer",
        text: "The map shows the endpoint location for the current case. It updates automatically as you navigate.",
        view: "case",
        dataset: { position: "left" },
      },
      {
        step: 7,
        targetId: "heuristicCard",
        text: "These cards show the heuristic analysis, visual review results, and orchestrator decision for each case.",
        view: "case",
        dataset: { position: "right" },
      },
      {
        step: 8,
        targetId: "exportButton",
        text: "When done, export your review notes as a JSON file for processing.",
        view: "case",
        dataset: { position: "bottom" },
      },
    ];

    const state = {
      view: "table",
      scopeFilter: "all",
      resolutionFilter: "all",
      searchQuery: "",
      selectedCaseKey: REVIEW_DATA.length ? REVIEW_DATA[0].case_key : null,
      tableSort: { key: "order", direction: "asc" },
      reviewState: loadReviewState(),
    };
    const tourState = {
      active: false,
      currentStepIndex: -1,
      highlightedElement: null,
      elevatedAncestors: [],
      refreshFrame: 0,
    };

    const elements = {
      tableView: document.getElementById("tableView"),
      caseView: document.getElementById("caseView"),
      tableWrapper: document.getElementById("tableWrapper"),
      tableSummary: document.getElementById("tableSummary"),
      tableSearch: document.getElementById("tableSearch"),
      summaryMeta: document.getElementById("summaryMeta"),
      summaryMetrics: document.getElementById("summaryMetrics"),
      resolutionFilter: document.getElementById("resolutionFilter"),
      reviewerName: document.getElementById("reviewerName"),
      tableViewButton: document.getElementById("tableViewButton"),
      caseViewButton: document.getElementById("caseViewButton"),
      themeToggleButton: document.getElementById("themeToggleButton"),
      restartTourButton: document.getElementById("restartTourButton"),
      exportButton: document.getElementById("exportButton"),
      importButton: document.getElementById("importButton"),
      importFile: document.getElementById("importFile"),
      scopeButtons: Array.from(document.querySelectorAll("[data-scope-filter]")),
      caseTitle: document.getElementById("caseTitle"),
      caseSubtitle: document.getElementById("caseSubtitle"),
      progressFill: document.querySelector(".progress-fill"),
      prevCaseButton: document.getElementById("prevCaseButton"),
      nextCaseButton: document.getElementById("nextCaseButton"),
      caseJumpSelect: document.getElementById("caseJumpSelect"),
      closeImageCard: document.getElementById("closeImageCard"),
      contextImageCard: document.getElementById("contextImageCard"),
      heuristicCard: document.getElementById("heuristicCard"),
      visualCard: document.getElementById("visualCard"),
      decisionCard: document.getElementById("decisionCard"),
      mapContainer: document.getElementById("mapContainer"),
      statusOptions: document.getElementById("statusOptions"),
      reviewerNotes: document.getElementById("reviewerNotes"),
      overrideGrid: document.getElementById("overrideGrid"),
      autoAdvanceToggle: document.getElementById("autoAdvanceToggle"),
      hotkeyHelpButton: document.getElementById("hotkeyHelpButton"),
      hotkeyOverlay: document.getElementById("hotkeyOverlay"),
      hotkeyOverlayCloseButton: document.getElementById("hotkeyOverlayCloseButton"),
      tourWelcomeOverlay: document.getElementById("tourWelcomeOverlay"),
      tourStartButton: document.getElementById("tourStartButton"),
      tourWelcomeSkipButton: document.getElementById("tourWelcomeSkipButton"),
      tourOverlay: document.getElementById("tourOverlay"),
      tourTooltip: document.getElementById("tourTooltip"),
      tourStepCounter: document.getElementById("tourStepCounter"),
      tourTooltipText: document.getElementById("tourTooltipText"),
      tourNextButton: document.getElementById("tourNextButton"),
      tourSkipButton: document.getElementById("tourSkipButton"),
      imageLightbox: document.getElementById("imageLightbox"),
      lightboxCloseButton: document.getElementById("lightboxCloseButton"),
      lightboxImage: document.getElementById("lightboxImage"),
    };

    let mapSyncToken = 0;
    let mapView = null;
    let mapMarker = null;
    let mapMessage = null;
    const DEFAULT_MAP_CENTER = [-97.33, 32.75];
    const DEFAULT_MAP_ZOOM = 10;

    function loadThemePreference() {
      try {
        const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
        return saved === "dark" || saved === "light" ? saved : "";
      } catch (error) {
        console.warn("Unable to load theme preference.", error);
        return "";
      }
    }

    function applyThemePreference(theme) {
      if (theme === "dark" || theme === "light") {
        document.documentElement.dataset.theme = theme;
      } else {
        delete document.documentElement.dataset.theme;
      }
    }

    function saveThemePreference(theme) {
      try {
        if (theme === "dark" || theme === "light") {
          window.localStorage.setItem(THEME_STORAGE_KEY, theme);
        } else {
          window.localStorage.removeItem(THEME_STORAGE_KEY);
        }
      } catch (error) {
        console.warn("Unable to save theme preference.", error);
      }
    }

    function hasCompletedTour() {
      try {
        return window.localStorage.getItem(TOUR_COMPLETED_KEY) === "true";
      } catch (error) {
        console.warn("Unable to load onboarding tour state.", error);
        return false;
      }
    }

    function markTourCompleted() {
      try {
        window.localStorage.setItem(TOUR_COMPLETED_KEY, "true");
      } catch (error) {
        console.warn("Unable to save onboarding tour state.", error);
      }
    }

    function clearScheduledTourRefresh() {
      if (!tourState.refreshFrame) return;
      window.cancelAnimationFrame(tourState.refreshFrame);
      tourState.refreshFrame = 0;
    }

    function hideTourWelcome() {
      setOverlayVisibility(elements.tourWelcomeOverlay, false);
    }

    function clearTourHighlight() {
      if (tourState.highlightedElement) {
        tourState.highlightedElement.classList.remove("tour-highlight");
        tourState.highlightedElement.style.removeProperty("--tour-radius");
      }
      tourState.elevatedAncestors.forEach((element) => {
        element.classList.remove("tour-elevated-ancestor");
      });
      tourState.highlightedElement = null;
      tourState.elevatedAncestors = [];
    }

    function closeTourOverlay() {
      clearScheduledTourRefresh();
      clearTourHighlight();
      tourState.active = false;
      tourState.currentStepIndex = -1;
      setOverlayVisibility(elements.tourOverlay, false);
      document.body.classList.remove("tour-active");
    }

    function showTourWelcome() {
      closeTourOverlay();
      closeLightbox();
      toggleHotkeyOverlay(false);
      setOverlayVisibility(elements.tourWelcomeOverlay, true);
    }

    function clampNumber(value, minimum, maximum) {
      return Math.min(Math.max(value, minimum), maximum);
    }

    function ensureTourTargetVisible(target) {
      if (!target || target.closest(".summary-bar")) return;
      const rect = target.getBoundingClientRect();
      const verticalPadding = 110;
      if (rect.top >= verticalPadding && rect.bottom <= window.innerHeight - 36) return;
      target.scrollIntoView({ block: "center", inline: "nearest" });
    }

    function applyTourHighlight(target) {
      clearTourHighlight();
      const computedStyle = window.getComputedStyle(target);
      const borderRadius = computedStyle.borderRadius && computedStyle.borderRadius !== "0px"
        ? computedStyle.borderRadius
        : "18px";
      target.style.setProperty("--tour-radius", borderRadius);
      target.classList.add("tour-highlight");
      const elevatedAncestor = target.closest(".summary-bar");
      if (elevatedAncestor) {
        elevatedAncestor.classList.add("tour-elevated-ancestor");
        tourState.elevatedAncestors = [elevatedAncestor];
      }
      tourState.highlightedElement = target;
    }

    function getTourPlacementOrder(preferredPosition) {
      return {
        top: ["top", "bottom", "right", "left"],
        bottom: ["bottom", "top", "right", "left"],
        left: ["left", "right", "bottom", "top"],
        right: ["right", "left", "bottom", "top"],
      }[preferredPosition] || ["bottom", "top", "right", "left"];
    }

    function positionTourTooltip(target, step) {
      const tooltip = elements.tourTooltip;
      const targetRect = target.getBoundingClientRect();
      const tooltipRect = tooltip.getBoundingClientRect();
      const preferredPosition = step && step.dataset && step.dataset.position ? step.dataset.position : "bottom";
      const gap = 18;
      const viewportPadding = 16;
      const spaces = {
        top: targetRect.top - gap,
        bottom: window.innerHeight - targetRect.bottom - gap,
        left: targetRect.left - gap,
        right: window.innerWidth - targetRect.right - gap,
      };
      const fits = {
        top: spaces.top >= tooltipRect.height,
        bottom: spaces.bottom >= tooltipRect.height,
        left: spaces.left >= tooltipRect.width,
        right: spaces.right >= tooltipRect.width,
      };
      const placementOrder = getTourPlacementOrder(preferredPosition);
      const placement = placementOrder.find((candidate) => fits[candidate])
        || Object.entries(spaces).sort((left, right) => right[1] - left[1])[0][0];
      let top = viewportPadding;
      let left = viewportPadding;
      if (placement === "top") {
        top = targetRect.top - tooltipRect.height - gap;
        left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);
      } else if (placement === "bottom") {
        top = targetRect.bottom + gap;
        left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);
      } else if (placement === "left") {
        top = targetRect.top + (targetRect.height / 2) - (tooltipRect.height / 2);
        left = targetRect.left - tooltipRect.width - gap;
      } else {
        top = targetRect.top + (targetRect.height / 2) - (tooltipRect.height / 2);
        left = targetRect.right + gap;
      }
      top = clampNumber(top, viewportPadding, Math.max(viewportPadding, window.innerHeight - tooltipRect.height - viewportPadding));
      left = clampNumber(left, viewportPadding, Math.max(viewportPadding, window.innerWidth - tooltipRect.width - viewportPadding));
      const arrowOffset = placement === "top" || placement === "bottom"
        ? clampNumber((targetRect.left + (targetRect.width / 2)) - left, 24, tooltipRect.width - 24)
        : clampNumber((targetRect.top + (targetRect.height / 2)) - top, 24, tooltipRect.height - 24);
      tooltip.dataset.position = placement;
      tooltip.style.setProperty("--tour-arrow-offset", `${arrowOffset}px`);
      tooltip.style.top = `${top}px`;
      tooltip.style.left = `${left}px`;
    }

    function refreshActiveTourStep() {
      clearScheduledTourRefresh();
      if (!tourState.active) return;
      const step = TOUR_STEPS[tourState.currentStepIndex];
      if (!step) {
        completeTour();
        return;
      }
      if (step.view && state.view !== step.view) {
        state.view = step.view;
        render();
        return;
      }
      const target = document.getElementById(step.targetId);
      if (!target) return;
      const targetRect = target.getBoundingClientRect();
      if (!targetRect.width && !targetRect.height) return;
      setOverlayVisibility(elements.tourOverlay, true);
      document.body.classList.add("tour-active");
      elements.tourStepCounter.textContent = `${step.step} of ${TOUR_STEPS.length}`;
      elements.tourTooltipText.textContent = step.text;
      elements.tourNextButton.textContent = step.step === TOUR_STEPS.length ? "Finish" : "Next";
      ensureTourTargetVisible(target);
      applyTourHighlight(target);
      positionTourTooltip(target, step);
    }

    function scheduleTourRefresh() {
      clearScheduledTourRefresh();
      if (!tourState.active) return;
      tourState.refreshFrame = window.requestAnimationFrame(() => {
        tourState.refreshFrame = 0;
        refreshActiveTourStep();
      });
    }

    function completeTour() {
      markTourCompleted();
      hideTourWelcome();
      closeTourOverlay();
    }

    function skipTour() {
      markTourCompleted();
      hideTourWelcome();
      closeTourOverlay();
    }

    function showTourStep(stepIndex) {
      if (stepIndex >= TOUR_STEPS.length) {
        completeTour();
        return;
      }
      hideTourWelcome();
      closeLightbox();
      toggleHotkeyOverlay(false);
      tourState.active = true;
      tourState.currentStepIndex = stepIndex;
      document.body.classList.add("tour-active");
      setOverlayVisibility(elements.tourOverlay, true);
      const step = TOUR_STEPS[stepIndex];
      if (step && step.view && state.view !== step.view) {
        state.view = step.view;
        render();
        return;
      }
      scheduleTourRefresh();
    }

    function startTour() {
      hideTourWelcome();
      showTourStep(0);
    }

    function maybeShowTourWelcome() {
      if (hasCompletedTour()) return;
      showTourWelcome();
    }

    function loadReviewState() {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (!raw) return { reviewer: "", autoAdvance: true, cases: {} };
        const parsed = JSON.parse(raw);
        return {
          reviewer: typeof parsed.reviewer === "string" ? parsed.reviewer : "",
          autoAdvance: typeof parsed.autoAdvance === "boolean" ? parsed.autoAdvance : true,
          cases: parsed.cases && typeof parsed.cases === "object" ? parsed.cases : {},
        };
      } catch (error) {
        console.warn("Unable to load review state.", error);
        return { reviewer: "", autoAdvance: true, cases: {} };
      }
    }

    function saveReviewState() {
      try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.reviewState)); }
      catch (error) { console.warn("Unable to save review state.", error); }
    }

    function defaultCaseState() {
      return {
        reviewer_status: "not_reviewed",
        reviewer_notes: "",
        reviewer_corrected_limit: "",
        reviewer_corrected_alias: "",
        reviewer_county_boundary_at_endpoint: false,
      };
    }

    function getCaseState(caseKey) {
      if (!state.reviewState.cases[caseKey]) state.reviewState.cases[caseKey] = defaultCaseState();
      return state.reviewState.cases[caseKey];
    }

    function getFilteredCases() {
      const query = state.searchQuery.trim().toLowerCase();
      return REVIEW_DATA.filter((item) => {
        if (state.resolutionFilter !== "all" && item.resolution !== state.resolutionFilter) return false;
        if (query && !item.segment.toLowerCase().includes(query) && !item.label.toLowerCase().includes(query)) return false;
        const caseState = getCaseState(item.case_key);
        if (state.scopeFilter === "disagreements") return item.resolution !== "confirmed";
        if (state.scopeFilter === "conflicts") return item.resolution === "conflict";
        if (state.scopeFilter === "unreviewed") return caseState.reviewer_status === "not_reviewed";
        return true;
      });
    }

    function getCurrentCase() {
      const filtered = getFilteredCases();
      if (!filtered.length) return null;
      let selected = filtered.find((item) => item.case_key === state.selectedCaseKey);
      if (!selected) {
        selected = filtered[0];
        state.selectedCaseKey = selected.case_key;
      }
      return selected;
    }

    function compareValues(left, right) {
      if (typeof left === "number" && typeof right === "number") return left - right;
      return String(left).localeCompare(String(right), undefined, { sensitivity: "base", numeric: true });
    }

    function isEditableTarget(target) {
      const tagName = target && target.tagName ? String(target.tagName).toUpperCase() : "";
      return tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT";
    }

    function setOverlayVisibility(element, visible) {
      element.classList.toggle("hidden", !visible);
      element.setAttribute("aria-hidden", String(!visible));
    }

    function toggleHotkeyOverlay(forceOpen) {
      const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : elements.hotkeyOverlay.classList.contains("hidden");
      setOverlayVisibility(elements.hotkeyOverlay, shouldOpen);
      elements.hotkeyHelpButton.setAttribute("aria-expanded", String(shouldOpen));
    }

    function openLightbox(src, alt) {
      elements.lightboxImage.src = src;
      elements.lightboxImage.alt = alt || "Expanded review image";
      setOverlayVisibility(elements.imageLightbox, true);
    }

    function closeLightbox() {
      if (elements.imageLightbox.classList.contains("hidden")) return;
      setOverlayVisibility(elements.imageLightbox, false);
      elements.lightboxImage.removeAttribute("src");
      elements.lightboxImage.alt = "";
    }

    function tableSortValue(item, key) {
      const caseState = getCaseState(item.case_key);
      if (key === "segment") return item.segment;
      if (key === "side") return item.side + String(item.piece || "");
      if (key === "heuristic") return item.heuristic_limit;
      if (key === "visual") return item.visual_limit;
      if (key === "resolution") return item.resolution;
      if (key === "confidence") return Number(item.final_confidence || 0);
      if (key === "status") return caseState.reviewer_status;
      if (key === "notes") return caseState.reviewer_notes;
      return Number(item.order || 0);
    }

    function getSortedTableCases() {
      const filtered = [...getFilteredCases()];
      const { key, direction } = state.tableSort;
      filtered.sort((left, right) => {
        const comparison = compareValues(tableSortValue(left, key), tableSortValue(right, key));
        return direction === "asc" ? comparison : -comparison;
      });
      return filtered;
    }

    function formatLabel(value) {
      if (!value) return "None";
      return String(value).replaceAll("_", " ").replace(/\\b\\w/g, (match) => match.toUpperCase());
    }

    function buildReviewSummary() {
      const total = REVIEW_DATA.length;
      const states = REVIEW_DATA.map((item) => getCaseState(item.case_key));
      const reviewed = states.filter((item) => item.reviewer_status !== "not_reviewed").length;
      const agree = states.filter((item) => item.reviewer_status === "agree").length;
      const disagree = states.filter((item) => item.reviewer_status === "disagree").length;
      const needsDiscussion = states.filter((item) => item.reviewer_status === "needs_discussion").length;
      return {
        total,
        reviewed,
        agree,
        disagree,
        needsDiscussion,
        unreviewed: total - reviewed,
      };
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function formatConfidence(value, bucket) {
      if (value == null || Number.isNaN(Number(value))) return bucket ? escapeHtml(bucket) : "None";
      const rendered = Number(value).toFixed(3).replace(/0+$/, "").replace(/\\.$/, "");
      return bucket ? `${rendered} (${escapeHtml(bucket)})` : rendered;
    }

    function resolutionClass(value) { return `resolution-${String(value || "").replaceAll(" ", "_")}`; }
    function statusClass(value) { return `status-${String(value || "").replaceAll(" ", "_")}`; }

    function renderSummary() {
      const summary = buildReviewSummary();
      elements.summaryMeta.textContent = `Run ${RUN_ID} | Generated ${GENERATED_AT}`;
      elements.summaryMetrics.innerHTML = `
        <span class="metric-pill">Total cases: ${summary.total}</span>
        <span class="metric-pill">Reviewed: ${summary.reviewed} of ${summary.total}</span>
        <span class="metric-pill">Agree: ${summary.agree}</span>
        <span class="metric-pill">Disagree: ${summary.disagree}</span>
        <span class="metric-pill">Needs discussion: ${summary.needsDiscussion}</span>
      `;
      document.getElementById("scopeAllButton").textContent = `Show All (${summary.total})`;
      document.getElementById("scopeDisagreementsButton").textContent = `Disagreements Only (${REVIEW_DATA.filter((item) => item.resolution !== "confirmed").length})`;
      document.getElementById("scopeConflictsButton").textContent = `Conflicts Only (${REVIEW_DATA.filter((item) => item.resolution === "conflict").length})`;
      document.getElementById("scopeUnreviewedButton").textContent = `Unreviewed (${summary.unreviewed})`;
      elements.scopeButtons.forEach((button) => button.classList.toggle("active", button.dataset.scopeFilter === state.scopeFilter));
      elements.tableViewButton.classList.toggle("active", state.view === "table");
      elements.caseViewButton.classList.toggle("active", state.view === "case");
      const forcedDarkTheme = document.documentElement.dataset.theme === "dark";
      const currentTheme = document.documentElement.dataset.theme || "";
      const themeLabel = currentTheme === "dark" ? "Dark" : currentTheme === "light" ? "Light" : "Auto";
      elements.themeToggleButton.classList.toggle("active", currentTheme !== "");
      elements.themeToggleButton.textContent = `Theme: ${themeLabel}`;
      elements.themeToggleButton.setAttribute("aria-pressed", String(currentTheme !== ""));
      elements.resolutionFilter.value = state.resolutionFilter;
      elements.reviewerName.value = state.reviewState.reviewer || "";
      elements.autoAdvanceToggle.checked = state.reviewState.autoAdvance !== false;
    }

    function renderTableView() {
      const rows = getSortedTableCases();
      elements.tableSummary.textContent = rows.length
        ? `${rows.length} case(s) match the current filters. Click a row to open the case view.`
        : "No cases match the current filters.";
      if (!rows.length) {
        elements.tableWrapper.innerHTML = `<div class="empty-state">No rows matched the current filter combination.</div>`;
        return;
      }
      const headers = [
        { key: "segment", label: "Segment" },
        { key: "side", label: "Side" },
        { key: "heuristic", label: "Heuristic" },
        { key: "visual", label: "Visual" },
        { key: "resolution", label: "Resolution" },
        { key: "confidence", label: "Confidence" },
        { key: "status", label: "Status" },
        { key: "notes", label: "Notes" },
      ];
      const thead = headers.map((header) => {
        const active = state.tableSort.key === header.key;
        const arrow = active ? (state.tableSort.direction === "asc" ? " ^" : " v") : "";
        return `<th><button type="button" class="table-sort${active ? " active" : ""}" data-sort-key="${header.key}">${escapeHtml(header.label + arrow)}</button></th>`;
      }).join("");
      const tbody = rows.map((item) => {
        const caseState = getCaseState(item.case_key);
        const selected = item.case_key === state.selectedCaseKey ? "selected" : "";
        const trimmedNotes = caseState.reviewer_notes.trim();
        const notesPreview = trimmedNotes
          ? trimmedNotes.length > 40
            ? `${trimmedNotes.slice(0, 40)}...`
            : trimmedNotes
          : null;
        return `
          <tr class="${selected}" data-case-key="${escapeHtml(item.case_key)}">
            <td>${escapeHtml(item.segment)}${item.piece ? `<div class="muted">piece ${item.piece}</div>` : ""}</td>
            <td>${escapeHtml(item.side)}</td>
            <td>${escapeHtml(item.heuristic_limit || "None")}</td>
            <td>${escapeHtml(item.visual_limit || "None")}</td>
            <td><span class="resolution-badge ${resolutionClass(item.resolution)}">${escapeHtml(formatLabel(item.resolution))}</span></td>
            <td>${formatConfidence(item.final_confidence)}</td>
            <td><span class="status-badge ${statusClass(caseState.reviewer_status)}">${escapeHtml(STATUS_LABELS[caseState.reviewer_status])}</span></td>
            <td class="muted" style="font-size:13px;">${notesPreview ? escapeHtml(notesPreview) : "&mdash;"}</td>
          </tr>`;
      }).join("");
      elements.tableWrapper.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
      Array.from(elements.tableWrapper.querySelectorAll("[data-sort-key]")).forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.dataset.sortKey;
          state.tableSort = state.tableSort.key === key
            ? { key, direction: state.tableSort.direction === "asc" ? "desc" : "asc" }
            : { key, direction: "asc" };
          render();
        });
      });
      Array.from(elements.tableWrapper.querySelectorAll("tbody tr")).forEach((row) => {
        row.addEventListener("click", () => {
          state.selectedCaseKey = row.dataset.caseKey;
          state.view = "case";
          render();
        });
      });
    }

    function renderImageCard(container, title, path, subtitle) {
      const pathHtml = path ? `<div class="image-meta mono">${escapeHtml(path)}</div>` : "";
      if (!path) {
        container.innerHTML = `<h3>${escapeHtml(title)}</h3><div class="image-placeholder">No screenshot path was provided.</div>${subtitle ? `<div class="image-meta">${escapeHtml(subtitle)}</div>` : ""}`;
        return;
      }
      container.innerHTML = `<h3>${escapeHtml(title)}</h3><img src="${escapeHtml(path)}" alt="${escapeHtml(title)}">${pathHtml}${subtitle ? `<div class="image-meta">${escapeHtml(subtitle)}</div>` : ""}`;
      const image = container.querySelector("img");
      image.addEventListener("click", () => { openLightbox(image.currentSrc || image.src, title); });
      image.addEventListener("error", () => {
        image.replaceWith(Object.assign(document.createElement("div"), { className: "image-placeholder", textContent: `Image not found: ${path}` }));
      }, { once: true });
    }

    function definitionRow(label, value) {
      const rendered = value == null || value === "" ? "None" : escapeHtml(value);
      return `<dt>${escapeHtml(label)}</dt><dd>${rendered}</dd>`;
    }

    function updateCaseNavigation(filtered, currentCase) {
      const currentIndex = filtered.findIndex((item) => item.case_key === currentCase.case_key);
      const reviewedCount = REVIEW_DATA.filter((item) => getCaseState(item.case_key).reviewer_status !== "not_reviewed").length;
      const progressPercent = REVIEW_DATA.length ? (reviewedCount / REVIEW_DATA.length) * 100 : 0;
      elements.caseTitle.textContent = `Case ${currentIndex + 1} of ${filtered.length}: ${currentCase.label}`;
      elements.caseSubtitle.textContent = `${currentCase.type} | ${currentCase.direction || "Direction unavailable"} | Reviewed ${reviewedCount} of ${REVIEW_DATA.length}`;
      elements.progressFill.style.width = `${progressPercent}%`;
      elements.prevCaseButton.disabled = currentIndex <= 0;
      elements.nextCaseButton.disabled = currentIndex >= filtered.length - 1;
      elements.caseJumpSelect.innerHTML = filtered.map((item) => `<option value="${escapeHtml(item.case_key)}"${item.case_key === currentCase.case_key ? " selected" : ""}>${escapeHtml(item.label)}</option>`).join("");
    }

    function moveCaseSelection(offset) {
      const filtered = getFilteredCases();
      const current = getCurrentCase();
      if (!current) return false;
      const index = filtered.findIndex((item) => item.case_key === current.case_key);
      const nextCase = filtered[index + offset];
      if (!nextCase) return false;
      state.selectedCaseKey = nextCase.case_key;
      render();
      return true;
    }

    function applyReviewerStatus(statusValue) {
      const current = getCurrentCase();
      if (!current) return;
      const filtered = getFilteredCases();
      const index = filtered.findIndex((item) => item.case_key === current.case_key);
      getCaseState(current.case_key).reviewer_status = statusValue;
      saveReviewState();
      if (state.reviewState.autoAdvance && statusValue !== "not_reviewed" && index >= 0 && index < filtered.length - 1) {
        state.selectedCaseKey = filtered[index + 1].case_key;
      }
      render();
    }

    function renderCaseDetails(currentCase) {
      renderImageCard(elements.closeImageCard, "Close Screenshot", currentCase.close_screenshot, currentCase.visual_review_file ? `Batch: ${currentCase.visual_review_file}` : "");
      renderImageCard(elements.contextImageCard, "Context Screenshot", currentCase.context_screenshot, "");
      elements.heuristicCard.innerHTML = `
        <h3>Heuristic Result</h3>
        <dl>
          ${definitionRow("Limit", currentCase.heuristic_limit)}
          ${definitionRow("Confidence", formatConfidence(currentCase.heuristic_confidence, currentCase.heuristic_confidence_bucket))}
          ${definitionRow("Heuristic", currentCase.heuristic_label)}
          ${definitionRow("Coordinates", currentCase.lon != null && currentCase.lat != null ? `${currentCase.lon}, ${currentCase.lat}` : null)}
          ${currentCase.is_offset === true ? definitionRow("is_offset", "true") : ""}
          ${currentCase.is_offset === true ? definitionRow("offset_direction", currentCase.offset_direction) : ""}
          ${currentCase.is_offset === true ? definitionRow("offset_from", currentCase.offset_from) : ""}
        </dl>`;
      elements.visualCard.innerHTML = `
        <h3>Visual Review Result</h3>
        <dl>
          ${definitionRow("Limit", currentCase.visual_limit)}
          ${definitionRow("Alias", currentCase.visual_alias)}
          ${definitionRow("Confidence", currentCase.visual_confidence)}
          ${definitionRow("visual_labels_seen", currentCase.visual_labels_seen && currentCase.visual_labels_seen.length ? currentCase.visual_labels_seen.join(", ") : null)}
          ${definitionRow("visual_shields_seen", currentCase.visual_shields_seen && currentCase.visual_shields_seen.length ? currentCase.visual_shields_seen.join(", ") : null)}
          ${definitionRow("Reasoning", currentCase.visual_reasoning)}
        </dl>`;
      const category = currentCase.category ? `<div class="category-badge">${escapeHtml(formatLabel(currentCase.category))}</div>` : "";
      elements.decisionCard.innerHTML = `
        <h3>Orchestrator Decision</h3>
        <dl>
          ${definitionRow("Resolution", formatLabel(currentCase.resolution))}
          ${definitionRow("Final", currentCase.final_limit)}
          ${definitionRow("Final confidence", formatConfidence(currentCase.final_confidence))}
          ${definitionRow("County boundary", currentCase.county_boundary_at_endpoint ? "Yes" : "No")}
        </dl>${category}`;
    }

    function renderStatusOptions(caseState) {
      elements.statusOptions.innerHTML = Object.entries(STATUS_LABELS).map(([value, label]) => `
        <label class="status-option">
          <input type="radio" name="reviewerStatus" value="${escapeHtml(value)}"${caseState.reviewer_status === value ? " checked" : ""}>
          <span>${escapeHtml(label)}</span>
        </label>`).join("");
      Array.from(elements.statusOptions.querySelectorAll('input[name="reviewerStatus"]')).forEach((input) => {
        input.addEventListener("change", () => { applyReviewerStatus(input.value); });
      });
    }

    function renderOverrideFields(caseState) {
      if (caseState.reviewer_status !== "disagree") {
        elements.overrideGrid.innerHTML = "";
        return;
      }
      elements.overrideGrid.innerHTML = `
        <label class="override-field">
          Corrected limit
          <input type="text" id="overrideLimit" placeholder="Required for disagree cases" value="${escapeHtml(caseState.reviewer_corrected_limit)}">
        </label>
        <label class="override-field">
          Corrected alias
          <input type="text" id="overrideAlias" placeholder="Optional local alias" value="${escapeHtml(caseState.reviewer_corrected_alias)}">
        </label>
        <label class="override-field checkbox-field">
          <input type="checkbox" id="overrideCountyBoundary"${caseState.reviewer_county_boundary_at_endpoint ? " checked" : ""}>
          <span>County boundary at endpoint</span>
        </label>`;
      const current = getCurrentCase();
      if (!current) return;
      document.getElementById("overrideLimit").addEventListener("input", (event) => {
        getCaseState(current.case_key).reviewer_corrected_limit = event.target.value;
        saveReviewState();
      });
      document.getElementById("overrideAlias").addEventListener("input", (event) => {
        getCaseState(current.case_key).reviewer_corrected_alias = event.target.value;
        saveReviewState();
      });
      document.getElementById("overrideCountyBoundary").addEventListener("change", (event) => {
        getCaseState(current.case_key).reviewer_county_boundary_at_endpoint = Boolean(event.target.checked);
        saveReviewState();
      });
    }

    function ensureMapMessage() {
      if (mapMessage || !elements.mapContainer) return;
      mapMessage = document.createElement("div");
      mapMessage.className = "map-message hidden";
      elements.mapContainer.appendChild(mapMessage);
    }

    function setMapMessage(message) {
      ensureMapMessage();
      if (!mapMessage) return;
      mapMessage.textContent = message || "";
      mapMessage.classList.toggle("hidden", !message);
    }

    function invalidateMapSize() {
      const activeMapView = window.__reviewMapView || mapView;
      if (!activeMapView) return;
      window.requestAnimationFrame(() => {
        if (activeMapView && typeof activeMapView.resize === "function") activeMapView.resize();
      });
    }

    function clearMapMarker(activeMapView) {
      const view = activeMapView || window.__reviewMapView || mapView;
      const marker = window.__reviewMarkerGraphic || mapMarker;
      if (view && marker) {
        view.graphics.remove(marker);
      }
      mapMarker = null;
      window.__reviewMarkerGraphic = null;
    }

    function updateMapForCase(currentCase) {
      const syncToken = ++mapSyncToken;
      const activeMapView = window.__reviewMapView || mapView;
      if (!activeMapView || !window.__esriGraphic) {
        const pendingMessage = currentCase && currentCase.lat != null && currentCase.lon != null
          ? "Loading map..."
          : currentCase
            ? `No coordinates are available for ${currentCase.label}.`
            : "No case is visible under the current filters.";
        setMapMessage(pendingMessage);
        return;
      }
      mapView = activeMapView;
      if (window.__reviewRoadHighlightLayer) {
        window.__reviewRoadHighlightLayer.removeAll();
      }
      if (typeof activeMapView.closePopup === "function") {
        activeMapView.closePopup();
      } else if (activeMapView.popup) {
        activeMapView.popup.close();
      }
      invalidateMapSize();
      if (currentCase && currentCase.lat != null && currentCase.lon != null) {
        clearMapMarker(activeMapView);
        const caseLabel = currentCase.label || "Selected case";
        const point = {
          type: "point",
          longitude: Number(currentCase.lon),
          latitude: Number(currentCase.lat),
        };
        const markerSymbol = {
          type: "simple-marker",
          color: [0, 95, 143],
          outline: { color: [255, 255, 255], width: 2 },
          size: 12,
        };
        const graphic = new window.__esriGraphic({
          geometry: point,
          symbol: markerSymbol,
          attributes: { label: caseLabel },
          popupTemplate: { title: "{label}" },
        });
        activeMapView.graphics.add(graphic);
        mapMarker = graphic;
        window.__reviewMarkerGraphic = graphic;
        setMapMessage("");
        activeMapView.goTo({ center: [point.longitude, point.latitude], zoom: 17 }).then(() => {
          if (syncToken !== mapSyncToken || window.__reviewMarkerGraphic !== graphic) return;
          activeMapView.popup.open({
            location: point,
            features: [graphic],
          });
        }).catch((error) => {
          if (syncToken !== mapSyncToken) return;
          const errorName = error && error.name ? error.name : "";
          if (errorName === "AbortError" || errorName === "view:goto-interrupted") return;
          console.warn("Unable to update ArcGIS map view.", error);
        });
        return;
      }
      clearMapMarker(activeMapView);
      activeMapView.popup.close();
      activeMapView.goTo({ center: DEFAULT_MAP_CENTER, zoom: DEFAULT_MAP_ZOOM }).catch((error) => {
        if (syncToken !== mapSyncToken) return;
        const errorName = error && error.name ? error.name : "";
        if (errorName === "AbortError" || errorName === "view:goto-interrupted") return;
        console.warn("Unable to reset ArcGIS map view.", error);
      });
      const emptyMessage = currentCase
        ? `No coordinates are available for ${currentCase.label}.`
        : "No case is visible under the current filters.";
      setMapMessage(emptyMessage);
    }

    function renderCaseView() {
      const filtered = getFilteredCases();
      let currentCase = null;
      if (!filtered.length) {
        elements.caseTitle.textContent = "No matching cases";
        elements.caseSubtitle.textContent = "Adjust the filters to review a case.";
        elements.closeImageCard.innerHTML = `<div class="empty-state">No case is available under the current filters.</div>`;
        elements.contextImageCard.innerHTML = "";
        elements.heuristicCard.innerHTML = "";
        elements.visualCard.innerHTML = "";
        elements.decisionCard.innerHTML = "";
        elements.statusOptions.innerHTML = "";
        elements.overrideGrid.innerHTML = "";
        elements.reviewerNotes.value = "";
        mapSyncToken++;
        elements.progressFill.style.width = "0%";
        elements.caseJumpSelect.innerHTML = "";
        elements.prevCaseButton.disabled = true;
        elements.nextCaseButton.disabled = true;
      } else {
        currentCase = getCurrentCase();
        const caseState = getCaseState(currentCase.case_key);
        updateCaseNavigation(filtered, currentCase);
        renderCaseDetails(currentCase);
        renderStatusOptions(caseState);
        elements.reviewerNotes.value = caseState.reviewer_notes;
        renderOverrideFields(caseState);
      }
      updateMapForCase(currentCase);
    }

    function buildExportPayload() {
      return {
        export_date: new Date().toISOString(),
        run_id: RUN_ID,
        reviewer: (state.reviewState.reviewer || "").trim(),
        cases: REVIEW_DATA.map((item) => {
          const caseState = getCaseState(item.case_key);
          return {
            case_key: item.case_key,
            segment: item.segment,
            side: item.side,
            piece: item.piece,
            resolution: item.resolution,
            reviewer_status: caseState.reviewer_status,
            reviewer_notes: caseState.reviewer_notes.trim(),
            reviewer_corrected_limit: caseState.reviewer_status === "disagree" && caseState.reviewer_corrected_limit.trim() ? caseState.reviewer_corrected_limit.trim() : null,
            reviewer_corrected_alias: caseState.reviewer_status === "disagree" && caseState.reviewer_corrected_alias.trim() ? caseState.reviewer_corrected_alias.trim() : null,
            reviewer_county_boundary_at_endpoint: caseState.reviewer_status === "disagree" ? Boolean(caseState.reviewer_county_boundary_at_endpoint) : null,
          };
        }),
      };
    }

    function exportConfirmationMessage() {
      const summary = buildReviewSummary();
      const reviewerName = (state.reviewState.reviewer || "").trim() || "Unspecified reviewer";
      return [
        `Export notes for run ${RUN_ID}?`,
        "",
        `Reviewer: ${reviewerName}`,
        `Total cases: ${summary.total}`,
        `Reviewed: ${summary.reviewed}`,
        `Agree: ${summary.agree}`,
        `Disagree: ${summary.disagree}`,
        `Needs discussion: ${summary.needsDiscussion}`,
      ].join("\\n");
    }

    function downloadExport() {
      const payload = buildExportPayload();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 19).replaceAll(":", "").replace("T", "-");
      link.href = URL.createObjectURL(blob);
      link.download = `review-notes-${RUN_ID}-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
    }

    function normalizeImportedCaseState(importedCase) {
      const nextState = defaultCaseState();
      if (VALID_REVIEW_STATUSES.has(importedCase.reviewer_status)) {
        nextState.reviewer_status = importedCase.reviewer_status;
      }
      nextState.reviewer_notes = typeof importedCase.reviewer_notes === "string" ? importedCase.reviewer_notes : "";
      nextState.reviewer_corrected_limit = typeof importedCase.reviewer_corrected_limit === "string" ? importedCase.reviewer_corrected_limit : "";
      nextState.reviewer_corrected_alias = typeof importedCase.reviewer_corrected_alias === "string" ? importedCase.reviewer_corrected_alias : "";
      nextState.reviewer_county_boundary_at_endpoint = importedCase.reviewer_county_boundary_at_endpoint === true;
      return nextState;
    }

    function importReviewState(file) {
      if (!file) return;
      const reader = new FileReader();
      reader.addEventListener("load", () => {
        try {
          const parsed = JSON.parse(typeof reader.result === "string" ? reader.result : "");
          if (!parsed || !Array.isArray(parsed.cases)) {
            throw new Error("Selected file does not contain a valid cases array.");
          }
          const importRunId = typeof parsed.run_id === "string" ? parsed.run_id : "";
          if (importRunId !== RUN_ID) {
            const proceed = window.confirm(`Imported notes are for run ${importRunId || "unknown"}, but this dashboard is run ${RUN_ID}. Continue importing matching case keys?`);
            if (!proceed) return;
          }
          const knownCaseKeys = new Set(REVIEW_DATA.map((item) => item.case_key));
          let importedCount = 0;
          parsed.cases.forEach((item) => {
            if (!item || typeof item !== "object" || typeof item.case_key !== "string") return;
            if (!knownCaseKeys.has(item.case_key)) return;
            state.reviewState.cases[item.case_key] = normalizeImportedCaseState(item);
            importedCount += 1;
          });
          if (typeof parsed.reviewer === "string") {
            state.reviewState.reviewer = parsed.reviewer;
          }
          saveReviewState();
          render();
          if (!importedCount) {
            window.alert("The selected file did not contain any matching case_key values for this dashboard.");
          }
        } catch (error) {
          window.alert(`Unable to import notes: ${error && error.message ? error.message : String(error)}`);
        } finally {
          elements.importFile.value = "";
        }
      });
      reader.addEventListener("error", () => {
        window.alert("Unable to read the selected file.");
        elements.importFile.value = "";
      });
      reader.readAsText(file);
    }

    function render() {
      renderSummary();
      elements.tableView.classList.toggle("hidden", state.view !== "table");
      elements.caseView.classList.toggle("hidden", state.view !== "case");
      renderTableView();
      ensureMapMessage();
      renderCaseView();
      if (window.__reviewMapView || mapView) {
        window.setTimeout(() => {
          invalidateMapSize();
        }, 100);
      }
      if (tourState.active) scheduleTourRefresh();
    }

    applyThemePreference(loadThemePreference());
    elements.tableViewButton.addEventListener("click", () => { state.view = "table"; render(); });
    elements.caseViewButton.addEventListener("click", () => { state.view = "case"; render(); });
    elements.themeToggleButton.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "";
      const nextTheme = current === "" ? "dark" : current === "dark" ? "light" : "";
      applyThemePreference(nextTheme);
      saveThemePreference(nextTheme);
      renderSummary();
    });
    elements.scopeButtons.forEach((button) => button.addEventListener("click", () => { state.scopeFilter = button.dataset.scopeFilter; render(); }));
    elements.resolutionFilter.addEventListener("change", (event) => { state.resolutionFilter = event.target.value; render(); });
    elements.tableSearch.addEventListener("input", (event) => { state.searchQuery = event.target.value; render(); });
    elements.reviewerName.addEventListener("input", (event) => { state.reviewState.reviewer = event.target.value; saveReviewState(); renderSummary(); });
    elements.autoAdvanceToggle.addEventListener("change", (event) => { state.reviewState.autoAdvance = Boolean(event.target.checked); saveReviewState(); });
    elements.hotkeyHelpButton.addEventListener("click", () => { toggleHotkeyOverlay(); });
    elements.hotkeyOverlayCloseButton.addEventListener("click", () => { toggleHotkeyOverlay(false); });
    elements.hotkeyOverlay.addEventListener("click", (event) => { if (event.target === elements.hotkeyOverlay) toggleHotkeyOverlay(false); });
    elements.restartTourButton.addEventListener("click", () => { startTour(); });
    elements.tourStartButton.addEventListener("click", () => { startTour(); });
    elements.tourWelcomeSkipButton.addEventListener("click", () => { skipTour(); });
    elements.tourNextButton.addEventListener("click", () => {
      if (tourState.currentStepIndex >= TOUR_STEPS.length - 1) {
        completeTour();
        return;
      }
      showTourStep(tourState.currentStepIndex + 1);
    });
    elements.tourSkipButton.addEventListener("click", () => { skipTour(); });
    elements.imageLightbox.addEventListener("click", (event) => { if (event.target === elements.imageLightbox) closeLightbox(); });
    elements.lightboxCloseButton.addEventListener("click", () => { closeLightbox(); });
    elements.importButton.addEventListener("click", () => { elements.importFile.click(); });
    elements.importFile.addEventListener("change", (event) => { importReviewState(event.target.files && event.target.files[0]); });
    elements.exportButton.addEventListener("click", () => {
      if (window.confirm(exportConfirmationMessage())) downloadExport();
    });
    elements.prevCaseButton.addEventListener("click", () => {
      moveCaseSelection(-1);
    });
    elements.nextCaseButton.addEventListener("click", () => {
      moveCaseSelection(1);
    });
    elements.caseJumpSelect.addEventListener("change", (event) => { state.selectedCaseKey = event.target.value; render(); });
    elements.reviewerNotes.addEventListener("input", (event) => {
      const current = getCurrentCase();
      if (!current) return;
      getCaseState(current.case_key).reviewer_notes = event.target.value;
      saveReviewState();
      renderTableView();
      renderSummary();
    });
    window.addEventListener("resize", () => { if (tourState.active) scheduleTourRefresh(); });
    window.addEventListener("scroll", () => { if (tourState.active) scheduleTourRefresh(); }, true);
    document.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (!elements.tourWelcomeOverlay.classList.contains("hidden")) {
        if (event.key === "Escape") {
          skipTour();
          event.preventDefault();
        }
        return;
      }
      if (tourState.active) {
        if (event.key === "Escape") {
          skipTour();
          event.preventDefault();
        }
        return;
      }
      if (!elements.imageLightbox.classList.contains("hidden")) {
        if (event.key === "Escape") {
          closeLightbox();
          event.preventDefault();
        }
        return;
      }
      if (isEditableTarget(event.target)) return;
      if (event.key === "Escape") {
        toggleHotkeyOverlay(false);
        if (state.view !== "table") {
          state.view = "table";
          render();
        }
        event.preventDefault();
        return;
      }
      if (state.view !== "case") return;
      if (event.key === "ArrowLeft") {
        if (moveCaseSelection(-1)) event.preventDefault();
        return;
      }
      if (event.key === "ArrowRight") {
        if (moveCaseSelection(1)) event.preventDefault();
        return;
      }
      const statusValue = {
        "1": "not_reviewed",
        "2": "agree",
        "3": "disagree",
        "4": "needs_discussion",
      }[event.key];
      if (statusValue) {
        applyReviewerStatus(statusValue);
        event.preventDefault();
      }
    });
    render();
    if (typeof require !== "function") {
      setMapMessage("Map failed to load because ArcGIS is unavailable.");
    } else {
      require([
        "esri/Map",
        "esri/views/MapView",
        "esri/layers/FeatureLayer",
        "esri/layers/GraphicsLayer",
        "esri/layers/VectorTileLayer",
        "esri/Graphic",
      ], function(EsriMap, MapView, FeatureLayer, GraphicsLayer, VectorTileLayer, Graphic) {
        var SEGMENTS_URL = "https://services9.arcgis.com/eNX73FDxjlKFtCtH/arcgis/rest/services/FTW_Segmentation_Master/FeatureServer/0";
        var TXDOT_VECTOR_URL = "https://tiles.arcgis.com/tiles/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Vector_Tile_Basemap/VectorTileServer";
        var TXDOT_ROADS_URL = "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadways/FeatureServer/0";
        var COUNTY_BOUNDARY_URL = "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/Texas_County_Boundaries/FeatureServer/0";

        var txdotVector = new VectorTileLayer({ url: TXDOT_VECTOR_URL, title: "TxDOT Roadways" });

        var segmentsLayer = new FeatureLayer({
          url: SEGMENTS_URL,
          title: "FTW Segments",
          visible: true,
          outFields: [
            "OBJECTID",
            "Readable_SegID",
            "Segment_ID",
            "Highway",
            "County",
            "HSYS",
            "Segment_Length_Mi",
          ],
          popupEnabled: false,
          renderer: {
            type: "simple",
            symbol: {
              type: "simple-line",
              color: [158, 50, 82, 230],
              width: 3,
              cap: "round",
              join: "round",
            },
          },
        });

        var roadsQueryLayer = new FeatureLayer({
          url: TXDOT_ROADS_URL,
          outFields: [
            "OBJECTID",
            "RTE_NM",
            "RTE_PRFX",
            "RTE_NBR",
            "MAP_LBL",
            "RDBD_TYPE",
            "DES_DRCT",
            "COUNTY",
            "BEGIN_DFO",
            "END_DFO",
          ],
          popupEnabled: false,
        });

        var roadHighlightLayer = new GraphicsLayer({
          title: "Road Highlight",
          listMode: "hide",
        });

        var countyLayer = new FeatureLayer({
          url: COUNTY_BOUNDARY_URL,
          title: "County Boundaries",
          renderer: {
            type: "simple",
            symbol: {
              type: "simple-fill",
              color: [0, 0, 0, 0],
              outline: { color: [180, 180, 180, 0.5], width: 1 },
            },
          },
        });

        var reviewMap = new EsriMap({
          basemap: "gray-vector",
          layers: [txdotVector, countyLayer, segmentsLayer, roadHighlightLayer],
        });

        mapView = new MapView({
          container: "mapContainer",
          map: reviewMap,
          center: DEFAULT_MAP_CENTER,
          zoom: DEFAULT_MAP_ZOOM,
          popup: {
            dockEnabled: true,
            dockOptions: { position: "bottom-right", breakpoint: false },
          },
          ui: { components: ["zoom", "attribution"] },
        });

        window.__reviewMapView = mapView;
        window.__reviewMarkerGraphic = null;
        window.__reviewRoadHighlightLayer = roadHighlightLayer;
        window.__esriGraphic = Graphic;
        mapMessage = null;
        ensureMapMessage();

        mapView.on("click", async function(event) {
          mapView.closePopup();
          roadHighlightLayer.removeAll();
          var query = roadsQueryLayer.createQuery();
          query.geometry = event.mapPoint;
          query.distance = Math.max(3, Math.min(mapView.resolution * 5, 20));
          query.units = "meters";
          query.spatialRelationship = "intersects";
          query.returnGeometry = true;
          query.outFields = ["OBJECTID", "RTE_NM", "RTE_PRFX", "RTE_NBR", "MAP_LBL", "RDBD_TYPE", "DES_DRCT", "COUNTY", "BEGIN_DFO", "END_DFO"];
          query.orderByFields = ["RTE_NM ASC"];
          query.num = 1;
          var result = await roadsQueryLayer.queryFeatures(query);
          if (!result.features.length) { mapView.closePopup(); return; }
          var hitFeature = result.features[0];
          if (hitFeature.geometry) {
            var highlight = hitFeature.clone();
            highlight.symbol = { type: "simple-line", color: [0, 180, 220, 255], width: 5, cap: "round", join: "round" };
            roadHighlightLayer.add(highlight);
          }
          var attrs = hitFeature.attributes;
          var roadName = attrs.MAP_LBL || attrs.RTE_NM || "Unknown Road";
          var routeName = attrs.RTE_NM || roadName;
          function formatDfo(v) { return typeof v === "number" && !isNaN(v) ? v.toFixed(3) : "N/A"; }
          var content = "<div><p><strong>" + escapeHtml(routeName) + "</strong></p><ul>" +
            "<li>Roadbed Type: " + escapeHtml(attrs.RDBD_TYPE || "Roadway") + "</li>" +
            "<li>Name/Number: " + escapeHtml(roadName) + "</li>" +
            "<li>Direction: " + escapeHtml(attrs.DES_DRCT || "N/A") + "</li>" +
            "<li>Begin DFO: " + formatDfo(attrs.BEGIN_DFO) + "</li>" +
            "<li>End DFO: " + formatDfo(attrs.END_DFO) + "</li>" +
            "</ul></div>";
          mapView.openPopup({ title: escapeHtml(roadName), content: content, location: event.mapPoint });
        });

        mapView.on("pointer-move", function(event) {
          mapView.container.style.cursor = "pointer";
        });

        mapView.when(function() {
          invalidateMapSize();
          updateMapForCase(getCurrentCase());
        }).catch(function(error) {
          console.warn("Map failed to initialize.", error);
          setMapMessage("Map failed to load because ArcGIS is unavailable.");
        });
      });
    }
    maybeShowTourWelcome();
"""


def render_html(
    *,
    review_data: list[dict[str, object]],
    storage_key: str,
    run_id: str,
    output_path: Path,
    generated_at: str,
) -> str:
    html = HTML_TEMPLATE
    html = html.replace("__PAGE_STYLE__", PAGE_STYLE)
    html = html.replace("__PAGE_SCRIPT__", PAGE_SCRIPT)
    html = html.replace("__REVIEW_DATA__", json_for_script(review_data))
    html = html.replace("__STORAGE_KEY__", json_for_script(storage_key))
    html = html.replace("__RUN_ID__", json_for_script(run_id))
    html = html.replace("__GENERATED_AT__", json_for_script(generated_at))
    return html


def generate_dashboard(
    *,
    final_results: Path,
    heuristic_results: Path,
    batch_results_dir: Path,
    output_path: Path,
) -> Path:
    final_rows = load_csv_records(
        final_results,
        required={
            "Segment",
            "Type",
            "Side",
            "Piece",
            "Heuristic-Limit",
            "Heuristic-Confidence",
            "Visual-Limit",
            "Visual-Confidence",
            "Final-Limit",
            "Final-Confidence",
            "Resolution",
            "Disagreement-Category",
            "Visual-Labels-Seen",
        },
        label="Final results CSV",
    )
    heuristic_rows = load_csv_records(
        heuristic_results,
        required={
            "Segment",
            "Direction",
            "Type",
            "Side",
            "Piece",
            "Auto-Limit",
            "Heuristic",
            "Confidence",
            "Confidence-Bucket",
        },
        label="Heuristic results CSV",
    )
    heuristic_by_key = load_rows_by_key(heuristic_rows, label="heuristic")
    visual_by_key = load_visual_rows(batch_results_dir)
    review_data = build_review_data(
        final_rows=final_rows,
        heuristic_by_key=heuristic_by_key,
        visual_by_key=visual_by_key,
        output_path=output_path,
    )
    run_id = compute_run_id(review_data)
    storage_key = f"review-dashboard:{run_id}"
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_html(
            review_data=review_data,
            storage_key=storage_key,
            run_id=run_id,
            output_path=output_path,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    args = parse_args()
    visual_review_dir = args.visual_review_dir.resolve()
    final_results = resolve_path(args.final_results, visual_review_dir / "final-segment-limits.csv")
    heuristic_results = resolve_path(args.heuristic_results, visual_review_dir / "heuristic-results.csv")
    batch_results_dir = resolve_path(args.batch_results_dir, visual_review_dir / "batch-results")
    output_path = resolve_path(args.output_path, ROOT / "review-dashboard.html")

    dashboard_path = generate_dashboard(
        final_results=final_results,
        heuristic_results=heuristic_results,
        batch_results_dir=batch_results_dir,
        output_path=output_path,
    )
    print(f"Wrote file: {dashboard_path}")


if __name__ == "__main__":
    main()
