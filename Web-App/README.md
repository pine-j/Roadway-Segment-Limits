# FTW Segment Explorer

This is a standalone static ArcGIS JavaScript app that combines:

- `FTW_Segmentation_Master`
- `FTW_TMP_2026_Master` layer 0 (the 206 CSJ project lines)
- `TxDOT_Vector_Tile_Basemap`
- A paired `TxDOT_Roadways` feature layer used for roadway-name click queries
  and screenshot-capture road lookups
- Esri's public address lookup (`geocode.arcgis.com`), used only to name the street under a road
  click

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
- `?segment=IH0035WD` (the `Segment_ID`) or `?segment=IH%2035W%20-%20D` (the segment label)
  opens the app on that segment.
- The address follows the selection: `?csj=` while a CSJ is chosen, `?segment=<Segment_ID>` while
  one segment is selected, and the bare address when several or none are, so the address bar can
  be copied as a link at any time.
- A link that matches nothing says so in the status line under the search ("No CSJ 0014-16-299 in
  the FTW list"), and the app opens as it does without a link.

## Behavior

The app answers four questions: what are a segment's limits, which CSJs lie inside it, where
those CSJs are on the map, and how TxDOT words each CSJ's limits in DCIS and in the Project
Tracker.

- Tick a segment in the list to select it: the map draws it and zooms to it. Tick more than one
  to keep several selected; `Zoom to selection` fits them all.
- Each segment row shows its limits, or "No segment limits recorded" when the segment has none.
  A row with CSJs has an "n CSJs" button that opens the list of its CSJs.
- Each CSJ row shows two lines: `DCIS:` with DCIS's From and To, and `Tracker:` with the Project
  Tracker's wording. The Tracker line reads "same" when the two agree (case, spacing and
  punctuation aside), "no record" when the Tracker has no row for the CSJ, or its own wording when
  it differs, with the differing half in bold and a "Limits differ" flag on the CSJ number. A lone
  "." in a wording counts as empty. While TxDOT's layers are being read the row says so, and a
  read that fails says "not loaded" rather than looking like an answer.
- Click a CSJ row to select it: its segment is selected, the map draws just that CSJ and zooms to
  it (no closer than 1:5,000), and its popup opens.
- The search box finds segments by their name or limits, and CSJs by their limits wording. A CSJ
  number (digits and hyphens only, three digits or more) also finds CSJs by number. A segment
  whose CSJs match opens by itself and lists only the matching CSJs. The status line under the
  search counts what the list shows ("3 segments, 2 CSJs match '121'").
- The `Only CSJs whose limits differ` checkbox, with its count, lists only the CSJs whose DCIS and
  Tracker wordings differ. It reads "unavailable" when either TxDOT layer could not be read.
- `Clear` resets the selection, the search, the differing-limits filter, the popup and the
  address.
- Click a CSJ line on the map to select that CSJ, as from its row. Click a segment line to select
  that one segment; its name goes into the search box, so the list shows it. The pointer becomes a
  hand over the lines that can be clicked.
- The CSJ popup shows the segment the CSJ lies on and a From/To table: DCIS, Project Tracker (with
  its last update date) and the segment's own limits. Both TxDOT wordings are read live.
- The map lines: the selected segment is a solid wine line; the CSJs of the selected segment (or
  the one chosen CSJ) are dark blue lines with a white edge inside it. `All segments` (dashed
  wine) and `All CSJs` (dashed blue) are off when the app opens. The "Map lines" box at the bottom
  left names the selection and has a tick box for each of the four sets of lines; click a line's
  name or box to show or hide it.
- Click a TxDOT roadway on the map to view its route (the road is drawn black and dashed). The
  popup adds a "Street name" line, such as "NE 28th St" for SH 183, a moment later: TxDOT's roadway
  layer holds the route but no street names, so the name comes from Esri's address lookup, asked
  at the click and at four points along the road so a cross street at a crossing does not win (five
  requests per road click). If that lookup fails the line is left out. Click a county boundary line
  to view the county boundary popup.
- The automation helpers used by capture tooling live in `app.js`, including
  `__waitForSegments()`, `__selectCorridorSegments()`,
  `__navigateAndCapture()`, and `__queryRoadsNearPoint()`. The capture helpers hide the CSJ lines
  while they take a screenshot and put them back as they were.
