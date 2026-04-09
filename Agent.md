# Project: Roadway Segment Limits

## Core workflow

- Use [Scripts/identify_segment_limits.py](Scripts/identify_segment_limits.py)
  for deterministic segment-endpoint inference. It combines FTW segmentation
  geometry, county boundaries, TxDOT vector-tile labels, and TxDOT Roadway
  Inventory geometry.
- Treat
  [FTW-Segments-Limits-Amy.review.csv](FTW-Segments-Limits-Amy.review.csv) as
  the working review sheet for segment metadata and From/To values.
- Use [Scripts/trusted_review_eval.py](Scripts/trusted_review_eval.py) to score
  the current heuristics against the review sheet. The current evaluator treats
  all reviewed sides as trusted and writes mismatch CSVs under `_temp/`.
- Prefer the local caches in `Cache/FTW-TxDOT-Labels/` and
  `Cache/FTW-Roadway-Inventory/`. Only use `--download-label-tiles`,
  `--download-roadway-inventory-subset`, `--live-label-tiles`, or
  `--live-roadway-inventory` when refreshing caches or explicitly validating
  against live services.
- For targeted reruns, use `--segment-name`, `--limit`, and `--workers`.

## Hybrid visual verification pipeline

- The current pipeline is documented in:
  - [Docs/Project-Plan/master-plan.md](Docs/Project-Plan/master-plan.md)
  - [orchestrator.md](orchestrator.md)
- Archived design documents live under
  [Docs/Project-Plan/archive/](Docs/Project-Plan/archive/) and are reference-only.
- The active pipeline stages are:
  1. Generate heuristic endpoint results and the anti-bias manifest with
     [Scripts/generate_visual_review_manifest.py](Scripts/generate_visual_review_manifest.py).
  2. Generate visual-review batch prompts with
     [Scripts/generate_visual_review_prompts.py](Scripts/generate_visual_review_prompts.py).
  3. Capture screenshot pairs plus per-endpoint road-query JSON with
     [visual-review-screenshots.py](visual-review-screenshots.py).
  4. Run independent Visual Review Agents against the screenshot and road-query
     evidence only.
  5. Merge heuristic and visual outputs with
     [Scripts/reconcile_results.py](Scripts/reconcile_results.py).
  6. Optionally generate the review dashboard with
     [Scripts/generate_review_dashboard.py](Scripts/generate_review_dashboard.py).

## Agent roles and boundaries

- Heuristic work is deterministic and script-driven. Use the Python scripts and
  existing data sources first.
- Visual Review Agents must be independent of heuristic answers.
- Visual Review Agents get only manifest-derived batch prompt content plus the
  referenced screenshots and `roads.json` files, not `heuristic-results.csv`.
- Visual Review Agents must not inspect heuristic CSV or JSON files, API
  responses, network traffic, GeoJSON, or roadway popups.
- Manual human review in the web app can still use broader inspection when
  needed. The restrictions above are for the independent visual-agent pass.

## Visual-review artifacts

- All visual-review intermediates live under `_temp/visual-review/`.
- Key files:
  - `_temp/visual-review/heuristic-results.csv`
  - `_temp/visual-review/visual-review-manifest.json`
  - `_temp/visual-review/batch-prompts/`
  - `_temp/visual-review/batch-results/`
  - `_temp/visual-review/screenshots/`
  - `_temp/visual-review/final-segment-limits.csv`
  - `_temp/visual-review/final-segment-limits-collapsed.csv`
- The repo no longer keeps a committed `verification-log.md`. Treat the final
  CSV outputs, dashboard exports, and git history as the durable record.
- Screenshots must be kept until human review is finished if a dashboard is in
  use, because the dashboard references them by relative path.

## Gap segments

- Gap segments are first-class citizens in the pipeline.
- Piece indexing is 1-based everywhere.
- The heuristic engine emits structured `gap_piece_endpoints`.
- Manifest, prompt, visual JSON, and reconciled outputs all preserve piece-level
  endpoint rows.
- Collapsed final outputs still use first piece `From` and last piece `To` as
  the segment-level limits.

## Web app usage

- Use `Web-App/` and the hosted app at
  `https://pine-j.github.io/Roadway-Segment-Limits/` for manual inspection and
  review.
- Local serving modes:
  - Manual review or same-origin dashboard use:
    `python -m http.server 8080`, then open `/Web-App/`.
  - Screenshot capture with `python visual-review-screenshots.py --local`:
    serve `Web-App/` itself at the server root, for example
    `cd Web-App && python -m http.server 8080`.
- The programmatic browser hooks used by capture and review are:
  - `window.__waitForSegments()`
  - `window.__selectAndZoomSegment(segmentName)`
  - `window.__selectCorridorSegments(segmentName)`
  - `window.__queryRoadsNearPoint(lon, lat, radiusMeters)`
  - `window.__mapView.goTo(...)`

## Documentation

- [Docs/Segment-Limits-Heuristics-Logic.md](Docs/Segment-Limits-Heuristics-Logic.md)
  is the authoritative explanation of the current heuristic engine, confidence
  model, gap handling, and hybrid pipeline integration.
- [Docs/SEGMENT_LIMITS_CASE_STUDY.md](Docs/SEGMENT_LIMITS_CASE_STUDY.md)
  contains the project narrative and historical rationale.
- When changing orchestration or pipeline behavior, keep
  [orchestrator.md](orchestrator.md) and
  [Docs/Project-Plan/master-plan.md](Docs/Project-Plan/master-plan.md) in sync.

## Cleanup

- Put temporary artifacts under `_temp/`.
- Do not treat `Cache/FTW-TxDOT-Labels/` or
  `Cache/FTW-Roadway-Inventory/` as disposable temp data.
- Delete ad hoc scratch artifacts before finishing unless the user explicitly
  asks to keep them.
- For the visual-review pipeline, follow the staged cleanup rules in
  [orchestrator.md](orchestrator.md) instead of deleting everything
  immediately.

## Project structure

- [Scripts/identify_segment_limits.py](Scripts/identify_segment_limits.py) -
  heuristic engine
- [Scripts/trusted_review_eval.py](Scripts/trusted_review_eval.py) -
  evaluation harness
- [Scripts/generate_visual_review_manifest.py](Scripts/generate_visual_review_manifest.py) -
  heuristic results + anti-bias manifest generator
- [Scripts/generate_visual_review_prompts.py](Scripts/generate_visual_review_prompts.py) -
  visual batch prompt generator
- [Scripts/reconcile_results.py](Scripts/reconcile_results.py) -
  heuristic/visual reconciliation
- [Scripts/generate_review_dashboard.py](Scripts/generate_review_dashboard.py) -
  human review dashboard generator
- [visual-review-screenshots.py](visual-review-screenshots.py) -
  screenshot and road-query capture
- [orchestrator.md](orchestrator.md) - orchestrator runtime prompt
- [Docs/Segment-Limits-Heuristics-Logic.md](Docs/Segment-Limits-Heuristics-Logic.md) -
  technical logic doc
- [Docs/SEGMENT_LIMITS_CASE_STUDY.md](Docs/SEGMENT_LIMITS_CASE_STUDY.md) -
  case study
- [Docs/Project-Plan/](Docs/Project-Plan/) - current plan plus archived design docs
- [Web-App/](Web-App/) - inspection and review surface
- [_temp/](_temp/) - scratch and pipeline artifacts

## Tech stack

- Python 3.13
- GIS / spatial analysis: geopandas, shapely, requests, pandas, pyproj,
  mercantile, mapbox-vector-tile
- ArcGIS REST services and vector tiles
