# Roadway Segment Limits

This repository identifies `Limits From` and `Limits To` values for Fort Worth roadway segments with a deterministic heuristic pass and an optional visual verification pass.

## Start Here

- [`Agent.md`](Agent.md): maintainer-oriented repo overview and current workflow notes
- [`orchestrator.md`](orchestrator.md): authoritative runtime document for the end-to-end hybrid pipeline
- [`Docs/Project-Plan/master-plan.md`](Docs/Project-Plan/master-plan.md): architecture, schemas, and pipeline design
- [`Docs/Segment-Limits-Heuristics-Logic.md`](Docs/Segment-Limits-Heuristics-Logic.md): heuristic engine internals
- [`Docs/SEGMENT_LIMITS_PLAYBOOK.md`](Docs/SEGMENT_LIMITS_PLAYBOOK.md): endpoint decision rules for visual review and human review

## Repository Layout

- [`Scripts/`](Scripts): heuristic, manifest, capture, validation, reconciliation, and dashboard scripts
- [`Web-App/`](Web-App): ArcGIS review surface plus automation hooks used by screenshot capture and the dashboard
- [`Docs/`](Docs): current technical docs, playbook, case study, and archived plans
- [`Cache/FTW-Roadway-Inventory/`](Cache/FTW-Roadway-Inventory): committed local roadway inventory subset
- `Cache/FTW-TxDOT-Labels/`: generated-on-demand local label tile cache; this folder may be absent in a fresh checkout
- `_temp/`: generated artifacts and pipeline outputs

## Common Workflows

### Heuristic-only run

```powershell
python Scripts/identify_segment_limits.py --compare-csv FTW-Segments-Limits-Amy.review.csv
```

### Heuristic evaluation

```powershell
python Scripts/trusted_review_eval.py
```

### Hybrid visual pipeline

```powershell
python Scripts/generate_visual_review_manifest.py
python Scripts/generate_visual_review_prompts.py
python Scripts/visual-review-screenshots.py
python Scripts/validate_visual_results.py
python Scripts/reconcile_results.py
```

### Web app

- Hosted app: <https://pine-j.github.io/Roadway-Segment-Limits/>
- For manual review or same-origin dashboard use, serve the repo root and open `/Web-App/`
- For `python Scripts/visual-review-screenshots.py --local`, serve `Web-App/` itself at the server root

## Notes

- Current runtime docs live in [`orchestrator.md`](orchestrator.md) and [`Docs/Project-Plan/master-plan.md`](Docs/Project-Plan/master-plan.md).
- [`Docs/Project-Plan/archive/`](Docs/Project-Plan/archive/) and parts of [`Docs/SEGMENT_LIMITS_CASE_STUDY.md`](Docs/SEGMENT_LIMITS_CASE_STUDY.md) describe historical MCP-based workflows and are not the current execution path.
