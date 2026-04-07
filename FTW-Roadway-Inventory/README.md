## Source

This folder stores the Fort Worth roadway inventory subset used by
`Segment-Limits/Scripts/identify_segment_limits.py`.

Primary source service:

- `https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadway_Inventory/FeatureServer/0/query`

File in this folder:

- `roadway-inventory.ftw.geojson`

Notes:

- This is a project-local subset of the statewide TxDOT Roadway Inventory.
- The subset is downloaded for the counties touched by the FTW segmentation data.
- The script uses this local GeoJSON by default to avoid repeated live queries.

Refresh command:

```bash
python Segment-Limits/Scripts/identify_segment_limits.py --download-roadway-inventory-subset --limit 1
```
