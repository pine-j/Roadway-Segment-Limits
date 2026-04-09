# Verification Log

Persistent run history for the hybrid heuristic + visual verification pipeline.

The Orchestrator appends a new timestamped `## Run:` section after each completed
pipeline run. This file is never deleted.

## Run: 2026-04-08 19:26:36 -05:00

- Input: `FTW-Segments-Limits-Amy.review.csv`
- Capture:
  - `batch-screenshots.py --local --overwrite` failed in this sandbox with `PermissionError: [WinError 5] Access is denied` during Playwright pipe creation.
  - Re-captured real screenshots and road-query JSON from the local `Web-App` using Playwright MCP against `http://127.0.0.1:8080/Web-App/index.html` plus the app-native `__navigateAndCapture` and `__queryRoadsNearPoint` helpers.
  - Verified `104` endpoints captured, `0` capture errors, and `3` artifacts per endpoint (`close.png`, `context.png`, `roads.json`).
- Visual-analysis execution:
  - Re-generated prompts with `python Scripts/generate_visual_review_prompts.py`.
  - Ran `7` dedicated visual-analysis sub-agents sequentially, one batch at a time.
  - Verified all `7` batch JSON files exist and match prompt counts (`15, 15, 15, 15, 15, 15, 14` endpoints).
- Phase 3c spot-check:
  - Schema/count checks passed for every batch result file.
  - All screenshot references in batch results resolved to non-empty files on disk.
  - Gap sanity check passed: every gap piece has distinct `From` and `To` limits.
  - Agreement sample reviewed directly against screenshots:
    - `batch-01-ep-01` `IH 820 - D / From -> SH 26`
    - `batch-01-ep-10` `FM 2331 - B / To / piece 1 -> FM 4`
    - `batch-04-ep-07` `FM 51 - E / To -> FM 167`
    - `batch-04-ep-13` `IH 30 - B / To -> IH 820`
    - `batch-05-ep-06` `SH 6 - B / To -> US 281`
    - `batch-06-ep-01` `FM 4 - H / To -> SH 171`
    - `batch-06-ep-11` `US 380 - A / To -> Denton / Wise County Line`
    - `batch-07-ep-13` `BS 114J / From -> Left Frontage US 81`
  - Conflict screenshots reviewed directly:
    - `batch-07-ep-08` `SH 171 - D / To`
    - `batch-07-ep-12` `FM 407 / To`
  - Result: both conflict screenshots clearly show a county-boundary line at the endpoint, but neither the screenshot labels nor the road-query JSON identify the county name.

### Summary Counts

| Metric | Count |
|---|---:|
| Total endpoints evaluated | 104 |
| Confirmed | 41 |
| Enriched | 29 |
| Visual preferred | 32 |
| Conflict | 2 |
| Visual only | 0 |

### Disagreement Categories

| Category | Count |
|---|---:|
| `different_road` | 24 |
| `offset_missing` | 7 |
| `offset_extra` | 2 |
| `offset_direction` | 1 |

### Visual Overrides

| Segment | Side | Piece | Heuristic | Visual | Category | Visual confidence |
|---|---|---:|---|---|---|---|
| US 287 - A | From | - | BU 287P | 157 | different_road | high |
| FM 730 - A | From | - | Wise County Line | COUNTY ROAD 2845 | different_road | high |
| IH 35W - D | To | - | S of E Altamesa Blvd | North of Highland Ter S | different_road | medium |
| IH 35W - A | From | - | N of US 67 | North of BI 35V | different_road | medium |
| IH 35W - B | To | - | N of US 67 | North of BI 35V | different_road | medium |
| IH 35W - C | From | - | S of E Altamesa Blvd | North of Highland Ter S | different_road | medium |
| SH 360 | To | - | N of W Camp Wisdom Rd | 360 Tollway | offset_extra | medium |
| SH 10 | To | - | Dickey Dr | Right Frontage SH 183 | different_road | medium |
| US 81/287 - B | From | - | N of FM 407 | North of 407 | offset_direction | medium |
| US 81/287 - B | To | - | Wise County Line | Tarrant County Line | different_road | medium |
| BU 287P - B | To | - | Grove St | 280 | different_road | high |
| IH 20 - B | From | - | E of Benbrook Pkwy | West of RIDGLEA COUNTRY CLUB DR | different_road | medium |
| FM 917 - B | From | - | Chisholm Trail Pkwy (TL 38) | West of Chisholm Trail Parkway | offset_missing | medium |
| US 377 - D | From | - | 100m E of Parker County Line | Parker / Tarrant County Line | different_road | high |
| US 377 - D | To | - | SW of BU 377F | 377F | offset_extra | medium |
| FM 731 - A | To | - | 85m N of Tarrant County Line | North of Tarrant County Line | offset_missing | medium |
| SH 183 - C | From | - | Tyra Ln | East of ALMENA RD | offset_missing | medium |
| SH 183 - D | From | - | Tyra Ln | East of ALMENA RD | offset_missing | medium |
| FM 730 - D | From | - | Right Frontage SH 199 | 199 | different_road | high |
| FM 1810 - B | To | - | US 81/287 | 81 | different_road | medium |
| SH 183 - A | To | - | Tarrant County Line | Tarrant / Dallas County Line | different_road | medium |
| FM 2280 | From | - | CR 807 (FM 917) | 917 | different_road | high |
| FM 4 - H | From | - | CR 1227 | East of COUNTY ROAD 1227 | offset_missing | medium |
| US 287 - B | To | - | BU 287P | 157 | different_road | medium |
| FM 219 - B | To | - | Erath County Line | COUNTY ROAD 767 | different_road | high |
| US 380 - A | From | - | BU 380F | E HWY 380 | different_road | medium |
| US 380 - B | From | - | SH 114 | 101 | different_road | high |
| US 380 - B | To | - | BU 380F | E HWY 380 | different_road | medium |
| FM 4 - G | To | - | CR 1227 | East of COUNTY ROAD 1227 | offset_missing | medium |
| SS 465 | To | - | IH 20 | SW Loop 820 | different_road | medium |
| FM 1187 - A | From | - | Left Frontage IH 20 | E Interstate 20 Service Rd N | different_road | medium |
| US 377 - C | From | - | Sunset Acres Ct | East of COLONY RD | offset_missing | medium |

### Unresolved Conflicts

| Segment | Side | Piece | Heuristic | Visual | Category | Visual confidence |
|---|---|---:|---|---|---|---|
| SH 171 - D | To | - | Parker County Line | County Line | different_road | low |
| FM 407 | To | - | Wise County Line | County Line | different_road | low |

### Heuristic Improvement Notes

- County-line naming still fails when the county boundary is visible but the county text is absent from both the screenshot and the road-query output. The fallback should preserve uncertainty instead of overcommitting to one county name.
- Offset selection still drifts to the wrong nearby anchor in dense freeway corridors. Repeated misses were `BI 35V` vs `US 67`, `Highland Ter S` vs `E Altamesa Blvd`, and `RIDGLEA COUNTRY CLUB DR` vs `Benbrook Pkwy`.
- Frontage-vs-mainline disambiguation remains weak in interchange complexes. Several disagreements collapsed to a corridor-level call because the capture and query were sufficient to identify the route family but not the exact roadbed.
- Route normalization should consistently upgrade bare `map_label` values like `26`, `917`, `101`, and `67M` into their route-prefixed forms when the route system is unambiguous.

### Traceability

- Heuristic results: `_temp/visual-review/heuristic-results.csv`
- Batch prompts: `_temp/visual-review/batch-prompts/`
- Batch results: `_temp/visual-review/batch-results/`
- Final outputs:
  - `_temp/visual-review/final-segment-limits.csv`
  - `_temp/visual-review/final-segment-limits-collapsed.csv`
- Git commit: `d6eec0fe0335c78bced8d5911c0b0f23d1410349`
