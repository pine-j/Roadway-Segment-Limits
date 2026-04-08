# FTW Segment Explorer

This is a standalone static ArcGIS JavaScript app that combines:

- `FTW_Segmentation_Master`
- `TxDOT_Vector_Tile_Basemap`
- A paired `TxDOT_Roadways` feature layer used only for roadway-name click queries

## Run locally

From the repository root:

```powershell
python -m http.server 8080
```

Then open:

```text
http://localhost:8080/Segment-Limits/Web-App/
```

## Behavior

- Click a segment row or map segment to focus the map on that segment.
- Use the checkboxes to keep multiple segments selected.
- Click `Zoom selected` to fit all selected segments.
- Click a TxDOT roadway on the map to view the roadway name.
- Click a county boundary line to view the county boundary popup.
