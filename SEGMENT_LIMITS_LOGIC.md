# Segment Limit Detection Logic

This document explains how [`identify_segment_limits.py`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py) identifies `Limits From` and `Limits To` for FTW segments, what data sources it uses, and how the heuristics decide between county lines, route intersections, and specific roadway names.

## Purpose

The script is designed to infer segment limits from ArcGIS and TxDOT data rather than from manual inspection alone. It can:

- generate auto-detected limits for requested FTW segments
- compare those auto-detected limits against the existing CSV
- write a review file showing matches, corrections, and rows that still need manual review

The goal is not just to find a nearby route. The goal is to identify the actual roadway or boundary that forms the segment endpoint.

## High-Level Flow

For each FTW segment row:

1. Load the segment geometry from the FTW segmentation layer.
2. Orient the segment so it has a start side and an end side.
3. Build endpoint geometry for both sides.
4. For each endpoint, gather candidate limits from:
   - county boundaries
   - FTW route intersections
   - TxDOT road-network labels from the basemap tiles
   - fallback TxDOT roadway label tiles
   - TxDOT Roadway Inventory geometry
5. Run heuristic selection on that gathered candidate set.
6. If a comparison CSV is supplied, compare the auto result to the existing `Limits From` and `Limits To`.
7. Write a review CSV with auto-detected limits, statuses, and notes.

The top-level orchestration happens in [`verify_limits()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).
Candidate gathering happens in [`gather_candidates()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py), and the endpoint decision plus heuristic labeling happens in [`select_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

## Data Sources

The script uses four primary sources.

### 1. FTW Segmentation Master

Source:
- `FTW_Segmentation_Master`

Used for:
- the FTW segment geometry
- segment IDs and readable segment names

Relevant functions:
- [`load_segment_features()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`resolve_row_features()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

### 2. Texas County Boundaries

Source:
- Texas county boundary ArcGIS feature layer

Used for:
- detecting county-line limits such as `Tarrant County Line`

Relevant functions:
- [`load_counties()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`infer_county_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

### 3. TxDOT Road-Network Label Tiles

Primary source:
- `TxDOT_Vector_Tile_Basemap`

Fallback source:
- `TxDOT_Roadways_and_Shields_2`

Used for:
- the displayed roadway names from the TxDOT map
- exact specific labels such as:
  - `Left Frontage US 81`
  - `Right Frontage US 81`
  - `Morris Dido Newark Rd`
  - `County Road 2745`

Relevant functions:
- [`fetch_tile_labels()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`nearby_labels()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`infer_local_label_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

### 4. TxDOT Roadway Inventory

Source:
- `TxDOT_Roadway_Inventory`

Used for:
- confirming route geometry and route identity
- finding route candidates such as:
  - `IH 20`
  - `US 287`
  - `BU 81E`
- finding local street geometry when available

Important limitation:
- the inventory layer is often good at corridor identification, but it may be less specific than the TxDOT label layer when the true limit is a frontage road or similar named variant

Relevant functions:
- [`fetch_roadway_inventory_features()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`infer_inventory_route_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`infer_inventory_local_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

## Segment Orientation

Before identifying `From` and `To`, the script has to orient each segment line.

This is handled in [`orient_feature_sequence()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

### Current orientation convention

The direction heuristic is:

- mostly horizontal segments: west to east
- mostly vertical segments: north to south
- near-diagonal segments: treated as north to south

That decision is made in [`cardinal_start_should_be_reversed()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

### Why orientation matters

Once the segment is oriented:

- the start endpoint becomes the `From` side
- the end endpoint becomes the `To` side

If the orientation is different, the same physical endpoints may swap between `From` and `To`.

## Geometry Built for Each Endpoint

For each side of the segment, the script computes three geometric inputs.

### 1. Endpoint point

This is the actual endpoint coordinate of the segment line.

Used for:
- measuring distance to nearby roads and labels
- checking which route or label is closest
- deciding what the segment is touching at the end

### 2. Interior sample point

This is a point a short distance inside the segment from the endpoint.

Used mainly for:
- county-line detection

Reason:
- the endpoint may sit exactly on a county boundary
- the interior point helps determine which county the segment lies within

Computed by:
- [`point_along_line()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

### 3. Local angle

This is the local direction of the segment near the endpoint.

Used for:
- comparing the segment direction to nearby route or label geometry
- favoring likely crossing roads over parallel roads

Computed by:
- [`line_angle_deg()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`local_line_angle_for_point()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

## Candidate Types

The script produces `LimitCandidate` objects. Each candidate includes:

- `value`: final candidate name
- `normalized`: normalized version used for comparisons
- `method`: how it was found
- `confidence`: a numeric score from 0.0 to 1.0 reflecting how certain the script is about this candidate (see [Confidence Model](#confidence-model) below)
- `distance_m`
- `detail`
- `heuristic`: the heuristic family or families that governed the final endpoint output

The main methods are:

- `county_boundary`
- `route_intersection`
- `basemap_label`
- `fallback_label`
- `txdot_inventory_route`
- `txdot_inventory_local`

## County Boundary Logic

County lines are checked first, because they are high-confidence and simple to validate.

Logic in [`infer_county_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py):

1. Find the county containing the interior sample point.
2. Measure the distance from the endpoint to that county boundary.
3. If the endpoint is close enough to the boundary, create a county-line candidate.

Why this works:
- it distinguishes a segment ending at a county line from a segment merely running near one

## Route Intersection Logic

Route candidates come from nearby FTW route geometries and are evaluated in [`infer_route_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

### Inputs

- endpoint geometry
- local segment angle
- set of current FTW segment IDs, to avoid choosing the segment itself
- current route family
- all FTW segment features
- nearby TxDOT labels

### Route-candidate filtering

A nearby FTW route is considered if:

- it is not the current segment
- it is not the same route family as the current segment
- it is within the configured route search radius
- it is either close enough geometrically or confirmed by nearby labels

### Route-candidate scoring

Confidence is influenced by distance, crossing angle, label confirmation, and route-system priority. See [Confidence Model](#confidence-model) for the full scoring details.

This favors:
- true crossing routes
- strongly confirmed route intersections

### Route aliases

The script can also use a specific labeled route alias from the TxDOT label layer.

Example:
- instead of plain `US 81`, it may preserve `Business US 81`

Frontage and service-road labels are not used to rename a route-intersection candidate to the parent route name. Those labels stay in the local-label lane and must win on their own merits.

This happens in:
- [`find_route_alias_label()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)
- [`format_named_route()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

## Local and Specific Label Logic

Specific roadway names from the TxDOT road-network label layer are evaluated in [`infer_local_label_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

### What counts as a local/specific label

Examples:

- `Morris Dido Newark Rd`
- `County Road 2745`
- `Left Frontage US 81`
- `Right Frontage US 81`
- `Left Frontage US 287`

### What gets filtered out

The script tries to discard labels that are likely map clutter or lane descriptors rather than usable limits.

Examples of filtered labels:

- `Supplemental`
- `Main Lane`
- `Auxiliary Lane`
- bare route-number-only labels like `81` or `287`

This is controlled by:
- [`should_skip_local_label()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

### Why specific labels matter

This is the most important recent heuristic change:

If the actual endpoint connects to a specific named roadway variant, the script tries to keep that exact name instead of collapsing it to the parent route.

Examples:

- use `Business US 81` instead of `US 81`
- use `Spur 580` instead of `US 81` when that is the actual intersecting route

Frontage and service-road names are handled more conservatively: a nearby label alone should not override a strong same-corridor mainline route intersection.

### How left/right frontage variants are chosen

For side-specific frontage or service-road labels, the script does not rely only on the nearest vector-tile label fragment.

Instead it:

- finds the `Left` or `Right` hint in the TxDOT label text
- finds nearby roadway-inventory features in the same route corridor
- compares the endpoint to the matching inventory roadbed side, such as `LG` vs `RG`
- keeps the TxDOT label text verbatim, but uses the inventory geometry to decide which side-specific label is the better match

This is what helps the script choose `Left Frontage US 81` instead of `Right Frontage US 81` when both labels exist in the same corridor but the vector-tile label placement is misleading.

## Inventory Layer Logic

The inventory layer is used as a second source, not as the only source.

### Route inventory candidates

Handled in [`infer_inventory_route_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

These are useful when:

- the endpoint clearly touches a route corridor
- the label layer is sparse or missing
- a route confirmation is needed

### Local inventory candidates

Handled in [`infer_inventory_local_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

These help when:

- the road-network labels are weak
- the inventory has a useful street geometry and name nearby

### Important role of the inventory layer

The inventory layer is especially useful for:

- validating route corridors
- identifying official route families
- recovering missing route candidates

But the inventory layer can be less specific than the TxDOT label layer. For that reason, specific TxDOT label names are preferred when they are judged to be the actual limit.

## Candidate Selection Logic

The final endpoint decision is made in [`choose_candidate()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py).

`choose_candidate()` is only a wrapper. The actual decision flow is now:

1. [`gather_candidates()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py) collects all possible endpoint anchors.
2. [`select_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py) decides which candidate wins.
3. The winning candidate may be post-formatted into an offset phrase such as `South of Old Airport Rd`.
4. The returned candidate is annotated with deterministic heuristic labels.

### Main decision rules

The chooser compares the county, route, local-label, local-inventory, and interchange candidates together rather than treating any single source as ground truth.

The high-level rules are:

- keep county-line candidates when the endpoint is genuinely boundary-anchored
- let explicit route-variant labels such as business routes win when they clearly describe the crossing route
- prefer the mainline crossing route over a same-corridor frontage label when the frontage label is acting as interchange context rather than the true endpoint anchor
- allow a confirmed local road to beat a nearby route when both the basemap labels and roadway inventory agree on that local anchor
- convert selected markers into offset phrasing like `North of SH 183` or `South of Old Airport Rd` when the endpoint is close to, but not best described by, a bare marker name
- otherwise use the strongest route or local candidate based on confidence, distance, and crossing angle

### Heuristic Taxonomy

The script now emits explicit heuristic labels so each endpoint can be filtered and audited by decision family. The current taxonomy includes:

- `offset_from_marker`
- `county_boundary`
- `route_intersection`
- `interchange_context`
- `frontage_service_road_variant`
- `local_labeled_road`
- `orientation_direction_effect`
- `route_alias_or_business_label`
- `shared_endpoint_with_adjacent_segment`
- `fallback_or_unclear`

Multiple heuristic families may apply to one endpoint. When that happens, they are joined deterministically with ` | `.

This is the core logic that makes the script choose:

- `Business US 81` over `US 81`
- `County Road 2745` over a less specific nearby route

## Confidence Model

Each `LimitCandidate` carries a numeric `confidence` score (0.0–1.0) that reflects how certain the script is that this candidate is the correct endpoint limit. Confidence is **per-endpoint, not per-segment** — each From and To side gets its own score based on the winning candidate.

The score is built from four signals: source type, distance, crossing angle, and corroborating evidence.

### Signal 1: Source type (base confidence)

Each candidate method starts with a different base confidence reflecting the inherent reliability of that data source:

| Method | Condition | Base confidence |
|--------|-----------|-----------------|
| `county_boundary` | Endpoint at county line (<= 50m) | 0.99 |
| `county_boundary_offset` | Endpoint near county line (50–100m) | 0.85 |
| `route_intersection` | Strong match (<= 180m) | 0.92 |
| `route_intersection` | Weak match (> 180m, label-confirmed) | 0.82 |
| `basemap_label` / `fallback_label` | Local road name from TxDOT tiles | 0.75–0.94 (distance-based) |
| `txdot_inventory_route` | Roadway Inventory route | 0.78–0.90 |
| `txdot_inventory_local` | Roadway Inventory local street | 0.70–0.88 |

### Signal 2: Distance from endpoint

Closer candidates are more likely to be the actual limit. For local labels ([`infer_local_label_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)):

| Effective distance | Confidence |
|-------------------|------------|
| <= 40m | 0.94 |
| <= 90m | 0.92 |
| <= 150m | 0.86 |
| <= 225m | 0.80 |
| > 225m | 0.75 (baseline) |

For inventory routes ([`infer_inventory_route_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)):

| Distance | Confidence |
|----------|------------|
| <= 40m | 0.90 |
| <= 90m | 0.86 |
| <= 150m | 0.82 |
| > 150m | 0.78 |

### Signal 3: Crossing angle adjustments

The angle between the segment and the candidate road affects confidence. A perpendicular crossing is a strong signal that the road is a true limit; a near-parallel angle suggests the candidate may be a continuation or service road rather than a boundary.

For route intersections ([`infer_route_limit()`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)):

| Angle difference | Adjustment |
|-----------------|------------|
| >= 55° (perpendicular) | +0.08 |
| >= 35° (moderate) | +0.04 |
| <= 12° (near-parallel) | -0.08 |

For local labels:

| Angle difference | Adjustment |
|-----------------|------------|
| < 20° (sharp/parallel) | -0.08 |

An additional -0.08 penalty applies when a route candidate overlaps the current route family and the crossing angle is <= 15° (near-continuation).

### Signal 4: Corroborating evidence (bonuses)

When multiple independent data sources agree, confidence increases:

| Evidence | Adjustment |
|----------|------------|
| Nearby TxDOT label text confirms the route | +0.05 |
| High-priority route system (IH, US) at >= 45° | +0.04 |
| Route alias visible on basemap (e.g., "Business US 81") | confidence floor raised to 0.93 |
| Roadway inventory confirms same-side geometry (LG/RG match) | +0.06 |
| Roadway inventory confirms opposite side only | -0.06 |
| Inventory side match present (either side) | confidence floor raised to 0.84 |

### Final clamping

All confidence scores are clamped to the range [0.50, 0.98] to prevent any single signal from producing absolute certainty or total rejection:

```python
confidence = min(max(confidence, 0.5), 0.98)
```

### Confidence buckets

For human-readable reporting, scores map to buckets:

| Bucket | Score range | Interpretation |
|--------|-----------|----------------|
| `high` | >= 0.90 | Strong candidate — multiple signals agree or very close match |
| `medium` | 0.78–0.89 | Reasonable candidate — some uncertainty in distance, angle, or source |
| `low` | < 0.78 | Weak candidate — may need visual verification |

### How confidence is used

Currently, confidence drives candidate selection: when `select_limit()` compares competing candidates, higher-confidence candidates are preferred (along with distance and angle). However, the confidence score is **not yet exposed in the output CSV** — the plan in [`hybrid-visual-verification-plan.md`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/hybrid-visual-verification-plan.md) adds this as a new output field to enable the hybrid visual verification workflow.

## Verbatim Naming Rule

When the TxDOT road-network label layer provides the actual roadway name for the endpoint, the script tries to preserve that text verbatim.

That means:

- if the label says `Business US 81`, use `Business US 81`
- if the label says `Spur 580`, use `Spur 580`

For frontage and service-road labels, the script keeps the exact text only when that label remains the strongest overall endpoint candidate; it does not automatically replace a strong mainline route match.

## Normalization and Comparison

The script normalizes names to compare auto-detected values against existing CSV values.

Examples of normalization goals:

- compare route forms consistently
- compare county-line text consistently
- allow exact or equivalent-route matches

Relevant helpers:

- `normalize_limit_key()`
- `route_number_token()`
- `route_number_parts()`
- `route_overlap()`
- `limits_equivalent()`

Important note:
- normalization is used for comparison logic
- the displayed auto-detected value should remain as specific as possible

## Review Output Logic

When a comparison CSV is supplied, the script writes:

- `Auto Limits From`
- `Auto Limits To`
- `Heuristic-From`
- `Heuristic-To`
- review statuses
- possible corrected values
- notes describing how the candidate was derived

### Review statuses

Per side and per row, the script now classifies results as:

- `matched`
- `needs_review`

Suggested replacements can still appear in the corrected-value columns, but they do not create a separate status bucket.

### Why a row still needs review

A row stays in `needs_review` if:

- no confident candidate is found
- the auto result differs from the existing CSV, even if the script has a plausible suggested correction
- the result is ambiguous

This conservative behavior is intentional. The script is designed to reduce manual review, not to blindly overwrite uncertain cases.

## Common Failure Modes

These are the main ways results can still be imperfect.

### 1. Orientation issues

If the segment orientation heuristic does not match the intended real-world `From/To` direction, the correct physical endpoints may appear on the opposite side.

### 2. Label-placement ambiguity

The TxDOT label text may be placed near more than one nearby alignment, especially in dense interchange areas.

### 3. Parallel corridor complexity

Frontage roads, mainlanes, ramps, and business routes can all run close together. Choosing the actual endpoint roadway is harder in those cases.

### 4. Sparse or inconsistent label coverage

Some map tiles may not expose the same level of label detail at all zooms or in all locations.

### 5. Inventory generalization

The inventory layer may confirm the route corridor but still be less specific than the label layer.

## Design Principles Behind the Heuristics

The script is built around these principles.

### Principle 1: pick the actual limit, not just a nearby corridor

The endpoint should resolve to the roadway or county boundary that actually forms the segment end.

### Principle 2: prefer true route variants over parent routes

If the endpoint is on a business route, spur, loop, bypass, or similarly distinct route variant, that exact roadway is more correct than the parent route. Frontage and service roads need stronger evidence because their map labels often sit next to the mainline corridor.

### Principle 3: use the TxDOT road-network label as the naming authority

When the map layer gives a specific roadway name, preserve that exact name in the output.

### Principle 4: use inventory geometry as confirmation, not blind override

The inventory layer is strong evidence for route corridor identity, but it should not erase a more specific labeled road that is clearly the actual limit.

For side-specific frontage labels, inventory geometry is still used as a side selector when the frontage-road label remains the best local candidate.

### Principle 5: be conservative when unsure

If the script cannot confidently justify a correction, it should leave the row in `needs_review`.

## Recommended Team Explanation

If you need a short explanation for teammates, use this:

> The script finds each segment's two endpoints, checks whether an endpoint hits a county line or another roadway, and uses TxDOT map labels plus roadway inventory geometry to identify the actual limit. When the TxDOT road network gives a specific roadway name like a frontage road, the script keeps that exact name instead of simplifying it to the parent route.

## Related Files

- Main script:
  [`Scripts/identify_segment_limits.py`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Scripts/identify_segment_limits.py)

- Review CSV:
  [`FTW-Segments-Limits-Amy.review.csv`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/FTW-Segments-Limits-Amy.review.csv)

- Web app used for visual QA:
  [`Web-App/README.md`](d:/Jacobs/FTW_Stakeholder_Maps/Segment-Limits/Web-App/README.md)
