# FTW Segment Explorer

This is a standalone static ArcGIS JavaScript app that combines:

- `FTW_Segmentation_Master`
- `FTW_TMP_2026_Master` layer 0 (the 206 CSJ project lines, drawn in blue)
- `TxDOT_Vector_Tile_Basemap`
- A paired `TxDOT_Roadways` feature layer used for roadway-name click queries
  and screenshot-capture road lookups

Hosted app:

- `https://pine-j.github.io/Roadway-Segment-Limits/`

## Run locally

For manual review or same-origin dashboard testing, serve the repository root:

```powershell
python -m http.server 8080
```

Then open:

```text
http://localhost:8080/Web-App/
```

This is the mode to use when the review dashboard needs same-origin access to
the map iframe.

For `python ../Scripts/visual-review-screenshots.py --local`, serve `Web-App/` itself
at the server root instead:

```powershell
cd Web-App
python -m http.server 8080
```

## Direct links

- `?csj=0014-16-289` opens the app on that CSJ: its segment is selected, the map zooms to the CSJ
  and its popup opens. Hyphens are optional.
- `?segment=IH%2035W%20-%20D` (the segment label) or `?segment=IH0035WD` (its `Segment_ID`)
  opens the app on that segment.
- A value that matches nothing leaves the app as it opens without a link.

## Behavior

- Click a segment row or map segment to focus the map on that segment.
- Use the checkboxes to keep multiple segments selected.
- Click `Zoom selected` to fit all selected segments.
- A segment row that has CSJs shows a small "n CSJs" arrow. Open it to list its CSJs, each with
  the limits DCIS gives for it. Click a CSJ to select its segment, draw just that CSJ in dark blue,
  zoom to it and open its popup.
- The search box finds segments and CSJs. A CSJ number (hyphens optional, four digits or more) or
  any part of a CSJ's limits wording opens the segment it belongs to and lists the matching CSJs.
- A CSJ whose DCIS and Project Tracker limits are worded differently (case, spacing and punctuation
  aside) carries a "Tracker differs" flag and shows the Tracker's wording beneath. The
  "Limits differ between TxDOT sources" button lists only those CSJs.
- Click a CSJ line on the map to see the limits TxDOT's DCIS layer and Project Tracker each give
  for it, next to the limits of its segment. Both are read live from TxDOT.
- The CSJs of the selected segments are redrawn over the red segment line, so the stretch each
  CSJ covers shows inside the segment.
- Click a TxDOT roadway on the map to view the roadway name.
- Click a county boundary line to view the county boundary popup.
- The automation helpers used by capture tooling live in `app.js`, including
  `__waitForSegments()`, `__selectCorridorSegments()`,
  `__navigateAndCapture()`, and `__queryRoadsNearPoint()`.
