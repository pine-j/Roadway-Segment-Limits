require([
  "esri/Map",
  "esri/views/MapView",
  "esri/layers/FeatureLayer",
  "esri/layers/GraphicsLayer",
  "esri/layers/VectorTileLayer",
  "esri/Graphic",
  "esri/geometry/Extent",
  "esri/geometry/Polyline",
  "esri/geometry/geometryEngine",
  "esri/geometry/operators/boundaryOperator",
  "esri/geometry/operators/labelPointOperator",
  "esri/widgets/Home",
  "esri/widgets/Expand",
  "esri/widgets/LayerList",
], function (
  EsriMap,
  MapView,
  FeatureLayer,
  GraphicsLayer,
  VectorTileLayer,
  Graphic,
  Extent,
  Polyline,
  geometryEngine,
  boundaryOperator,
  labelPointOperator,
  Home,
  Expand,
  LayerList,
) {
  const SEGMENTS_URL =
    "https://services9.arcgis.com/eNX73FDxjlKFtCtH/arcgis/rest/services/FTW_Segmentation_Master/FeatureServer/0";
  const TXDOT_VECTOR_URL =
    "https://tiles.arcgis.com/tiles/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Vector_Tile_Basemap/VectorTileServer";
  const TXDOT_ROADS_URL =
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadways/FeatureServer/0";
  // CSJ project lines: layer 0 of the public FTW TMP master service. Its CSJ field holds the nine
  // digits with no hyphens (001416289) and CSJ_Dashed the usual form (0014-16-289).
  const CSJ_URL =
    "https://services9.arcgis.com/eNX73FDxjlKFtCtH/arcgis/rest/services/FTW_TMP_2026_Master/FeatureServer/0";
  // The two TxDOT layers that each carry a limits wording for a CSJ. They are read live when a
  // CSJ is clicked, so the popup shows what TxDOT publishes today.
  const TXDOT_DCIS_URL =
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_DCIS_All_Projects/FeatureServer/0";
  const TXDOT_TRACKER_URL =
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Projects_Info/FeatureServer/0";
  const COUNTY_BOUNDARY_URL =
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/Texas_County_Boundaries/FeatureServer/0";
  const HIGHWAY_DESIGNATION_BASE_URL = "https://www.dot.state.tx.us/tpp/hdf_search.html";
  const COUNTY_LABEL_SWITCH_SCALE = 1250000;
  const COUNTY_LABEL_VIEW_PADDING = 72;
  const COUNTY_LABEL_EDGE_MARGIN = 18;
  const COUNTY_LABEL_OFFSET_PX = 20;
  const COUNTY_LABEL_MIN_VISIBLE_PATH_PX = 96;
  const COUNTY_LABEL_SEGMENT_ENDPOINT_MARGIN_PX = 26;
  const COUNTY_STYLE_LAYER_PATTERN = /(?:county|cnty|admin[-_ ]?2|adm[-_ ]?2)/i;

  const state = {
    activeCategory: "All",
    searchTerm: "",
    selectedSegmentIds: new Set(),
    segments: [],
    csjs: [],
    csjsBySegment: new globalThis.Map(),
    selectedCsj: null,
    expandedSegmentIds: new Set(),
    onlyDiffering: false,
    limitsLoaded: false,
  };

  const elements = {
    categoryList: document.getElementById("category-list"),
    segmentList: document.getElementById("segment-list"),
    searchInput: document.getElementById("segment-search"),
    visibleCount: document.getElementById("visible-count"),
    selectedCount: document.getElementById("selected-count"),
    clearSelectionButton: document.getElementById("clear-selection"),
    zoomSelectedButton: document.getElementById("zoom-selected"),
    differFilter: document.getElementById("differ-filter"),
    differCount: document.getElementById("differ-count"),
  };

  let countyBoundaryLayer = null;
  let countyBoundaryHitLayer = null;
  let countyBoundaryHoverToken = 0;
  let countyLabelOverlay = null;
  let countyLabelRefreshHandle = 0;
  let countyLabelRecords = [];

  const txdotVectorLayer = new VectorTileLayer({
    url: TXDOT_VECTOR_URL,
    title: "TxDOT Roadways",
  });

  const segmentsLayer = new FeatureLayer({
    url: SEGMENTS_URL,
    title: "FTW Segments",
    visible: false,
    outFields: [
      "OBJECTID",
      "Readable_SegID",
      "Segment_ID",
      "Highway",
      "County",
      "HSYS",
      "Segment_Length_Mi",
      "Segment_Limits",
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

  const selectedSegmentsLayer = new GraphicsLayer({
    title: "Selected FTW Segments",
    listMode: "hide",
  });

  const csjLayer = new FeatureLayer({
    url: CSJ_URL,
    title: "FTW CSJs",
    outFields: ["OBJECTID", "CSJ", "CSJ_Dashed", "Segment_ID", "Segment_Label"],
    popupEnabled: false,
    renderer: {
      type: "simple",
      symbol: {
        type: "simple-line",
        color: [0, 90, 200, 220],
        width: 2.5,
        cap: "round",
        join: "round",
      },
    },
  });

  // The CSJs of the selected segments, drawn over the red segment line so the stretch each CSJ
  // covers shows inside the segment.
  const selectedCsjLayer = new GraphicsLayer({
    title: "CSJs of Selected Segments",
    listMode: "hide",
  });

  const roadHighlightLayer = new GraphicsLayer({
    title: "Road Highlight",
    listMode: "hide",
  });

  const roadsQueryLayer = new FeatureLayer({
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

  const map = new EsriMap({
    basemap: "gray-vector",
    layers: [
      txdotVectorLayer,
      segmentsLayer,
      csjLayer,
      roadHighlightLayer,
      selectedSegmentsLayer,
      selectedCsjLayer,
    ],
  });

  const view = new MapView({
    container: "viewDiv",
    map,
    center: [-97.45, 32.72],
    zoom: 9,
    constraints: {
      snapToZoom: false,
    },
    popup: {
      dockEnabled: true,
      dockOptions: {
        position: "bottom-right",
        breakpoint: false,
      },
    },
  });

  window.__mapView = view;

  view.ui.add(new Home({ view }), "top-left");

  const layerList = new LayerList({
    view,
    listItemCreatedFunction(event) {
      const item = event.item;
      if (item.layer === selectedSegmentsLayer || item.layer === selectedCsjLayer) {
        item.hidden = true;
      }
    },
  });

  view.ui.add(
    new Expand({
      view,
      content: layerList,
      expandTooltip: "Layer list",
    }),
    "top-right",
  );

  const sortByLabel = (a, b) => a.label.localeCompare(b.label, undefined, { numeric: true });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function normalizeCountyName(value) {
    return String(value ?? "")
      .trim()
      .replace(/\s+County$/i, "");
  }

  function getRelevantCountyNames() {
    const countyNames = new Set();

    state.segments.forEach((segment) => {
      String(segment.county ?? "")
        .split(/\s*(?:,|;|\/|&|\band\b)\s*/i)
        .map(normalizeCountyName)
        .filter(Boolean)
        .forEach((countyName) => countyNames.add(countyName));
    });

    return Array.from(countyNames).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }

  function buildCountyWhereClause(countyNames) {
    if (!countyNames.length) {
      return "1=0";
    }

    const escapedNames = countyNames.map((countyName) => `'${countyName.replaceAll("'", "''")}'`);
    return `CNTY_NM IN (${escapedNames.join(", ")})`;
  }

  function getCountyStyleLayerIds(vectorTileLayer) {
    const styleLayers = vectorTileLayer?.currentStyleInfo?.style?.layers ?? [];
    return Array.from(
      new Set(
        styleLayers
          .map((styleLayer) => styleLayer?.id)
          .filter((id) => typeof id === "string" && COUNTY_STYLE_LAYER_PATTERN.test(id)),
      ),
    );
  }

  async function hideCountyStyleLayers(vectorTileLayer) {
    if (!vectorTileLayer || vectorTileLayer.type !== "vector-tile") {
      return;
    }

    try {
      await vectorTileLayer.when();
      getCountyStyleLayerIds(vectorTileLayer).forEach((layerId) => {
        vectorTileLayer.setStyleLayerVisibility(layerId, "none");
      });
    } catch (error) {
      console.warn("Unable to hide county style layers.", error);
    }
  }

  async function hideCountyStyleLayersFromMap() {
    const vectorTileLayers = [
      ...(map.basemap?.baseLayers?.toArray?.() ?? []),
      ...(map.basemap?.referenceLayers?.toArray?.() ?? []),
      txdotVectorLayer,
    ];

    await Promise.all(vectorTileLayers.map((layer) => hideCountyStyleLayers(layer)));
  }

  function createCountyPopupTemplate() {
    return {
      title: "{COUNTY_LABEL}",
      content: '<div class="county-popup">County line</div>',
    };
  }

  function createCountyLabelAttributes(countyName, objectId) {
    return {
      OBJECTID: objectId,
      CNTY_NM: countyName,
      COUNTY_LABEL: countyName ? `${countyName} County` : "County",
    };
  }

  function formatCountyDisplayLabel(countyName) {
    return countyName ? `${countyName} County` : "County";
  }

  function ensureCountyLabelOverlay() {
    if (countyLabelOverlay?.isConnected) {
      return countyLabelOverlay;
    }

    if (!view.container) {
      return null;
    }

    countyLabelOverlay = document.createElement("div");
    countyLabelOverlay.className = "county-label-overlay";
    view.container.appendChild(countyLabelOverlay);
    return countyLabelOverlay;
  }

  function setCountyLabelOverlaySuspended(isSuspended) {
    const overlay = ensureCountyLabelOverlay();
    if (!overlay) {
      return;
    }

    overlay.classList.toggle("is-suspended", Boolean(isSuspended));
  }

  function scheduleCountyLabelRefresh() {
    if (!countyLabelRecords.length || countyLabelRefreshHandle || !view.stationary) {
      return;
    }

    countyLabelRefreshHandle = requestAnimationFrame(() => {
      countyLabelRefreshHandle = 0;
      refreshCountyLabelOverlay();
    });
  }

  function syncCountyLabelOverlayWithView() {
    if (!countyLabelRecords.length) {
      return;
    }

    const shouldSuspend = !view.stationary;
    setCountyLabelOverlaySuspended(shouldSuspend);

    if (!shouldSuspend) {
      scheduleCountyLabelRefresh();
    }
  }

  function extentsIntersect(firstExtent, secondExtent) {
    return Boolean(
      firstExtent &&
        secondExtent &&
        firstExtent.xmin <= secondExtent.xmax &&
        firstExtent.xmax >= secondExtent.xmin &&
        firstExtent.ymin <= secondExtent.ymax &&
        firstExtent.ymax >= secondExtent.ymin,
    );
  }

  function isScreenPointFinite(point) {
    return Boolean(point && Number.isFinite(point.x) && Number.isFinite(point.y));
  }

  function isScreenPointInRect(point, rect) {
    return Boolean(
      isScreenPointFinite(point) &&
        point.x >= rect.xmin &&
        point.x <= rect.xmax &&
        point.y >= rect.ymin &&
        point.y <= rect.ymax,
    );
  }

  function getExpandedScreenRect(padding = 0) {
    return {
      xmin: -padding,
      ymin: -padding,
      xmax: view.width + padding,
      ymax: view.height + padding,
    };
  }

  function getInsetScreenRect(margin = 0) {
    return {
      xmin: margin,
      ymin: margin,
      xmax: Math.max(margin, view.width - margin),
      ymax: Math.max(margin, view.height - margin),
    };
  }

  function pointsAlmostEqual(firstPoint, secondPoint, epsilon = 0.5) {
    return (
      Math.abs(firstPoint.x - secondPoint.x) <= epsilon &&
      Math.abs(firstPoint.y - secondPoint.y) <= epsilon
    );
  }

  function clipSegmentToRect(startPoint, endPoint, rect) {
    let startRatio = 0;
    let endRatio = 1;
    const deltaX = endPoint.x - startPoint.x;
    const deltaY = endPoint.y - startPoint.y;
    const edges = [
      [-deltaX, startPoint.x - rect.xmin],
      [deltaX, rect.xmax - startPoint.x],
      [-deltaY, startPoint.y - rect.ymin],
      [deltaY, rect.ymax - startPoint.y],
    ];

    for (const [p, q] of edges) {
      if (p === 0) {
        if (q < 0) {
          return null;
        }
        continue;
      }

      const ratio = q / p;
      if (p < 0) {
        if (ratio > endRatio) {
          return null;
        }
        if (ratio > startRatio) {
          startRatio = ratio;
        }
      } else {
        if (ratio < startRatio) {
          return null;
        }
        if (ratio < endRatio) {
          endRatio = ratio;
        }
      }
    }

    if (startRatio > endRatio) {
      return null;
    }

    return {
      start: {
        x: startPoint.x + deltaX * startRatio,
        y: startPoint.y + deltaY * startRatio,
      },
      end: {
        x: startPoint.x + deltaX * endRatio,
        y: startPoint.y + deltaY * endRatio,
      },
    };
  }

  function createMapPoint(x, y, spatialReference) {
    return {
      type: "point",
      x,
      y,
      spatialReference,
    };
  }

  function buildVisibleCountyScreenPaths(countyRecord, clipRect) {
    const screenPaths = [];
    const spatialReference = countyRecord.boundaryGeometry.spatialReference;

    countyRecord.boundaryGeometry.paths.forEach((path) => {
      let currentVisiblePath = [];
      let previousScreenPoint = null;

      path.forEach((coordinates) => {
        const currentScreenPoint = view.toScreen(
          createMapPoint(coordinates[0], coordinates[1], spatialReference),
        );

        if (isScreenPointFinite(previousScreenPoint) && isScreenPointFinite(currentScreenPoint)) {
          const clippedSegment = clipSegmentToRect(previousScreenPoint, currentScreenPoint, clipRect);

          if (clippedSegment) {
            const lastPoint = currentVisiblePath[currentVisiblePath.length - 1];
            if (!lastPoint || !pointsAlmostEqual(lastPoint, clippedSegment.start)) {
              currentVisiblePath.push(clippedSegment.start);
            }
            currentVisiblePath.push(clippedSegment.end);
          } else if (currentVisiblePath.length > 1) {
            screenPaths.push(currentVisiblePath);
            currentVisiblePath = [];
          }
        } else if (currentVisiblePath.length > 1) {
          screenPaths.push(currentVisiblePath);
          currentVisiblePath = [];
        }

        previousScreenPoint = currentScreenPoint;
      });

      if (currentVisiblePath.length > 1) {
        screenPaths.push(currentVisiblePath);
      }
    });

    return screenPaths;
  }

  function getPathLength(path) {
    let totalLength = 0;

    for (let index = 1; index < path.length; index += 1) {
      const previousPoint = path[index - 1];
      const currentPoint = path[index];
      totalLength += Math.hypot(currentPoint.x - previousPoint.x, currentPoint.y - previousPoint.y);
    }

    return totalLength;
  }

  function projectPointOntoPath(path, targetPoint) {
    let traversedLength = 0;
    let closestPoint = null;

    for (let index = 1; index < path.length; index += 1) {
      const startPoint = path[index - 1];
      const endPoint = path[index];
      const segmentDeltaX = endPoint.x - startPoint.x;
      const segmentDeltaY = endPoint.y - startPoint.y;
      const segmentLength = Math.hypot(segmentDeltaX, segmentDeltaY);

      if (!segmentLength) {
        continue;
      }

      const rawRatio =
        ((targetPoint.x - startPoint.x) * segmentDeltaX +
          (targetPoint.y - startPoint.y) * segmentDeltaY) /
        (segmentLength * segmentLength);
      const ratio = Math.max(0, Math.min(1, rawRatio));
      const projectedPoint = {
        x: startPoint.x + segmentDeltaX * ratio,
        y: startPoint.y + segmentDeltaY * ratio,
      };
      const distance = Math.hypot(targetPoint.x - projectedPoint.x, targetPoint.y - projectedPoint.y);

      if (!closestPoint || distance < closestPoint.distance) {
        closestPoint = {
          point: projectedPoint,
          distance,
          ratio,
          segmentLength,
          tangentX: segmentDeltaX,
          tangentY: segmentDeltaY,
          startPoint,
          endPoint,
        };
      }

      traversedLength += segmentLength;
    }

    return closestPoint;
  }

  function normalizeCountyLabelAngle(angle) {
    let normalizedAngle = ((angle % 360) + 360) % 360;

    if (normalizedAngle > 180) {
      normalizedAngle -= 360;
    }

    if (normalizedAngle > 90) {
      normalizedAngle -= 180;
    } else if (normalizedAngle < -90) {
      normalizedAngle += 180;
    }

    return normalizedAngle;
  }

  function getCountyBoundaryLabelDirection(countyRecord, anchorPoint, normalX, normalY) {
    const positiveScreenPoint = {
      x: anchorPoint.x + normalX * COUNTY_LABEL_OFFSET_PX,
      y: anchorPoint.y + normalY * COUNTY_LABEL_OFFSET_PX,
    };
    const negativeScreenPoint = {
      x: anchorPoint.x - normalX * COUNTY_LABEL_OFFSET_PX,
      y: anchorPoint.y - normalY * COUNTY_LABEL_OFFSET_PX,
    };
    const positiveMapPoint = view.toMap(positiveScreenPoint);
    const negativeMapPoint = view.toMap(negativeScreenPoint);
    const positiveInside =
      positiveMapPoint && geometryEngine.contains(countyRecord.polygonGeometry, positiveMapPoint);
    const negativeInside =
      negativeMapPoint && geometryEngine.contains(countyRecord.polygonGeometry, negativeMapPoint);

    if (positiveInside !== negativeInside) {
      return positiveInside ? 1 : -1;
    }

    const countyCenterScreenPoint = view.toScreen(countyRecord.labelPointGeometry);
    const fallbackSide =
      (countyCenterScreenPoint.x - anchorPoint.x) * normalX +
      (countyCenterScreenPoint.y - anchorPoint.y) * normalY;

    return fallbackSide >= 0 ? 1 : -1;
  }

  function buildCenterCountyLabelCandidate(countyRecord, displayRect, viewCenter) {
    const centerScreenPoint = view.toScreen(countyRecord.labelPointGeometry);
    if (!isScreenPointInRect(centerScreenPoint, displayRect)) {
      return null;
    }

    return {
      countyName: countyRecord.countyName,
      x: centerScreenPoint.x,
      y: centerScreenPoint.y,
      angle: 0,
      mode: "center",
      score: -Math.hypot(centerScreenPoint.x - viewCenter.x, centerScreenPoint.y - viewCenter.y),
    };
  }

  function buildBoundaryCountyLabelCandidate(countyRecord, clipRect, displayRect, viewCenter) {
    const visibleScreenPaths = buildVisibleCountyScreenPaths(countyRecord, clipRect);
    let bestCandidate = null;

    visibleScreenPaths.forEach((screenPath) => {
      const totalVisibleLength = getPathLength(screenPath);
      if (totalVisibleLength < COUNTY_LABEL_MIN_VISIBLE_PATH_PX) {
        return;
      }

      const projectedPoint = projectPointOntoPath(screenPath, viewCenter);
      if (!projectedPoint) {
        return;
      }

      const tangentX = projectedPoint.tangentX;
      const tangentY = projectedPoint.tangentY;
      const tangentLength = projectedPoint.segmentLength;
      if (tangentLength < 8) {
        return;
      }

      const endpointMargin = Math.min(COUNTY_LABEL_SEGMENT_ENDPOINT_MARGIN_PX, tangentLength / 2);
      const anchorRatio =
        tangentLength > endpointMargin * 2
          ? Math.min(
              1 - endpointMargin / tangentLength,
              Math.max(endpointMargin / tangentLength, projectedPoint.ratio),
            )
          : 0.5;
      const anchorPoint = {
        x: projectedPoint.startPoint.x + tangentX * anchorRatio,
        y: projectedPoint.startPoint.y + tangentY * anchorRatio,
      };
      const normalX = -tangentY / tangentLength;
      const normalY = tangentX / tangentLength;
      const direction = getCountyBoundaryLabelDirection(
        countyRecord,
        anchorPoint,
        normalX,
        normalY,
      );
      const labelPoint = {
        x: anchorPoint.x + normalX * COUNTY_LABEL_OFFSET_PX * direction,
        y: anchorPoint.y + normalY * COUNTY_LABEL_OFFSET_PX * direction,
      };

      if (!isScreenPointInRect(labelPoint, displayRect)) {
        return;
      }

      const candidate = {
        countyName: countyRecord.countyName,
        x: labelPoint.x,
        y: labelPoint.y,
        angle: normalizeCountyLabelAngle((Math.atan2(tangentY, tangentX) * 180) / Math.PI),
        mode: "boundary",
        score: totalVisibleLength - projectedPoint.distance * 1.15,
      };

      if (!bestCandidate || candidate.score > bestCandidate.score) {
        bestCandidate = candidate;
      }
    });

    return bestCandidate;
  }

  function createCountyLabelElement(labelCandidate) {
    const labelElement = document.createElement("div");
    labelElement.className = `county-dynamic-label ${
      labelCandidate.mode === "boundary" ? "is-boundary" : "is-center"
    }`;
    labelElement.dataset.county = labelCandidate.countyName;
    labelElement.dataset.mode = labelCandidate.mode;
    labelElement.textContent = formatCountyDisplayLabel(labelCandidate.countyName);
    labelElement.style.left = `${labelCandidate.x.toFixed(1)}px`;
    labelElement.style.top = `${labelCandidate.y.toFixed(1)}px`;
    labelElement.style.transform = `translate(-50%, -50%) rotate(${labelCandidate.angle.toFixed(
      1,
    )}deg)`;
    return labelElement;
  }

  function refreshCountyLabelOverlay() {
    const overlay = ensureCountyLabelOverlay();
    if (!overlay) {
      return;
    }

    if (!countyLabelRecords.length || !view.extent || !view.width || !view.height) {
      overlay.replaceChildren();
      return;
    }

    const useCenterLabels = view.scale >= COUNTY_LABEL_SWITCH_SCALE;
    const clipRect = getExpandedScreenRect(COUNTY_LABEL_VIEW_PADDING);
    const displayRect = getInsetScreenRect(COUNTY_LABEL_EDGE_MARGIN);
    const viewCenter = {
      x: view.width / 2,
      y: view.height / 2,
    };
    const labelCandidates = countyLabelRecords
      .filter((countyRecord) => extentsIntersect(countyRecord.extent, view.extent))
      .map((countyRecord) =>
        useCenterLabels
          ? buildCenterCountyLabelCandidate(countyRecord, displayRect, viewCenter)
          : buildBoundaryCountyLabelCandidate(countyRecord, clipRect, displayRect, viewCenter) ??
              buildCenterCountyLabelCandidate(countyRecord, displayRect, viewCenter),
      )
      .filter(Boolean)
      .sort((firstLabel, secondLabel) => firstLabel.score - secondLabel.score);

    const labelFragment = document.createDocumentFragment();
    labelCandidates.forEach((labelCandidate) => {
      labelFragment.appendChild(createCountyLabelElement(labelCandidate));
    });

    overlay.replaceChildren(labelFragment);
  }

  async function showCountyBoundaryPopup(graphic, mapPoint) {
    view.popup.open({
      features: [graphic],
      location: mapPoint,
    });
  }

  async function initializeCountyBoundaries() {
    try {
      await hideCountyStyleLayersFromMap();

      const countyNames = getRelevantCountyNames();
      if (!countyNames.length) {
        console.warn("No FTW county names were available for the county boundary layer.");
        return;
      }

      const countyServiceLayer = new FeatureLayer({
        url: COUNTY_BOUNDARY_URL,
        popupEnabled: false,
      });

      await countyServiceLayer.load();

      const query = countyServiceLayer.createQuery();
      query.where = buildCountyWhereClause(countyNames);
      query.returnGeometry = true;
      query.outFields = ["OBJECTID", "CNTY_NM"];
      query.orderByFields = ["CNTY_NM ASC"];

      const result = await countyServiceLayer.queryFeatures(query);
      const boundaryGraphics = [];
      countyLabelRecords = [];

      result.features.forEach((feature, index) => {
        if (!feature.geometry) {
          return;
        }

        const countyName = String(feature.attributes?.CNTY_NM ?? "").trim();
        const objectId = Number(feature.attributes?.OBJECTID ?? index + 1);
        const labelPointGeometry = labelPointOperator.execute(feature.geometry);
        const boundaryGeometry = boundaryOperator.execute(feature.geometry);

        if (!boundaryGeometry || !labelPointGeometry) {
          return;
        }

        const attributes = createCountyLabelAttributes(countyName, objectId);

        boundaryGraphics.push(
          new Graphic({
            geometry: boundaryGeometry,
            attributes,
          }),
        );
        countyLabelRecords.push({
          countyName,
          objectId,
          extent: feature.geometry.extent,
          polygonGeometry: feature.geometry,
          labelPointGeometry,
          boundaryGeometry,
        });
      });

      if (!boundaryGraphics.length || !countyLabelRecords.length) {
        return;
      }

      const spatialReference =
        boundaryGraphics[0].geometry?.spatialReference || { wkid: 4326 };
      const visibleBoundaryGraphics = boundaryGraphics.map((graphic) =>
        typeof graphic.clone === "function" ? graphic.clone() : graphic,
      );
      const hitBoundaryGraphics = boundaryGraphics.map((graphic) =>
        typeof graphic.clone === "function" ? graphic.clone() : graphic,
      );

      countyBoundaryLayer = new FeatureLayer({
        title: "County Boundaries",
        listMode: "hide",
        popupTemplate: createCountyPopupTemplate(),
        source: visibleBoundaryGraphics,
        objectIdField: "OBJECTID",
        fields: [
          { name: "OBJECTID", alias: "OBJECTID", type: "oid" },
          { name: "CNTY_NM", alias: "County Name", type: "string" },
          { name: "COUNTY_LABEL", alias: "County Label", type: "string" },
        ],
        geometryType: "polyline",
        spatialReference,
        renderer: {
          type: "simple",
          symbol: {
            type: "simple-line",
            color: [194, 122, 41, 255],
            width: 3,
            cap: "round",
            join: "round",
          },
        },
        labelsVisible: false,
      });

      map.add(countyBoundaryLayer, 1);

      countyBoundaryHitLayer = new FeatureLayer({
        title: "County Boundary Hit Area",
        listMode: "hide",
        popupTemplate: createCountyPopupTemplate(),
        source: hitBoundaryGraphics,
        objectIdField: "OBJECTID",
        fields: [
          { name: "OBJECTID", alias: "OBJECTID", type: "oid" },
          { name: "CNTY_NM", alias: "County Name", type: "string" },
          { name: "COUNTY_LABEL", alias: "County Label", type: "string" },
        ],
        geometryType: "polyline",
        spatialReference,
        renderer: {
          type: "simple",
          symbol: {
            type: "simple-line",
            color: [194, 122, 41, 0],
            width: 36,
            cap: "round",
            join: "round",
          },
        },
        labelsVisible: false,
      });

      map.add(countyBoundaryHitLayer, 2);
      ensureCountyLabelOverlay();
      syncCountyLabelOverlayWithView();
    } catch (error) {
      console.warn("Unable to load county boundaries.", error);
    }
  }

  function normalizeWording(value) {
    return String(value ?? "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  // "IH 30 to 28th Street", or "" when the record is missing or carries no limits.
  function wordingOf(record) {
    if (!record || (!record.from && !record.to)) {
      return "";
    }

    return `${record.from || "?"} to ${record.to || "?"}`;
  }

  // What the row of a CSJ shows as its limits: DCIS first, the Project Tracker when DCIS has none.
  function csjLimitsLabel(csj) {
    const dcis = wordingOf(csj.dcis);

    if (dcis) {
      return dcis;
    }

    const tracker = wordingOf(csj.tracker);
    return tracker ? `${tracker} (Tracker)` : "";
  }

  function segmentMatchesText(segment, normalizedSearch) {
    const haystack = [
      segment.label,
      segment.segmentId,
      segment.highway,
      segment.county,
      segment.hsys,
      segment.limits,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return haystack.includes(normalizedSearch);
  }

  // A CSJ matches on its number (hyphens optional, four digits or more) or on either limits wording.
  function csjMatchesSearch(csj, normalizedSearch) {
    const digitsQuery = normalizedSearch.replace(/\D/g, "");

    if (digitsQuery.length >= 4 && csj.digits.includes(digitsQuery)) {
      return true;
    }

    return [csj.dashed, wordingOf(csj.dcis), wordingOf(csj.tracker)]
      .join(" ")
      .toLowerCase()
      .includes(normalizedSearch);
  }

  function getSegmentCsjs(segment) {
    return state.csjsBySegment.get(segment.segmentId) ?? [];
  }

  // The CSJ selected from the pane or a link, while its segment is still selected.
  function getSelectedCsj() {
    const csj = state.selectedCsj
      ? state.csjs.find((item) => item.digits === state.selectedCsj)
      : null;
    const segment = csj ? state.segments.find((item) => item.segmentId === csj.segmentId) : null;

    if (!csj || !segment || !state.selectedSegmentIds.has(segment.objectId)) {
      state.selectedCsj = null;
      return null;
    }

    return csj;
  }

  function getVisibleSegments() {
    const normalizedSearch = state.searchTerm.trim().toLowerCase();

    return state.segments.filter((segment) => {
      const matchesCategory =
        state.activeCategory === "All" || segment.hsys === state.activeCategory;

      if (!matchesCategory) {
        return false;
      }

      const csjs = getSegmentCsjs(segment);

      if (state.onlyDiffering && !csjs.some((csj) => csj.differs)) {
        return false;
      }

      if (!normalizedSearch) {
        return true;
      }

      return (
        segmentMatchesText(segment, normalizedSearch) ||
        csjs.some((csj) => csjMatchesSearch(csj, normalizedSearch))
      );
    });
  }

  function getCategorySummaries() {
    const counts = new globalThis.Map([["All", state.segments.length]]);

    state.segments.forEach((segment) => {
      counts.set(segment.hsys, (counts.get(segment.hsys) ?? 0) + 1);
    });

    const summaries = Array.from(counts.entries()).map(([code, count]) => ({
      code,
      count,
      label: code,
    }));

    return [summaries[0], ...summaries.slice(1).sort(sortByLabel)];
  }

  function applyCategoryFilter() {
    segmentsLayer.definitionExpression =
      state.activeCategory === "All" ? null : "HSYS = '" + state.activeCategory.replaceAll("'", "''") + "'";

    const allowedIds =
      state.activeCategory === "All"
        ? null
        : new Set(
            state.segments
              .filter((segment) => segment.hsys === state.activeCategory)
              .map((segment) => segment.objectId),
          );

    if (allowedIds) {
      state.selectedSegmentIds = new Set(
        Array.from(state.selectedSegmentIds).filter((objectId) => allowedIds.has(objectId)),
      );
    }
  }

  function renderCategories() {
    const summaries = getCategorySummaries();

    elements.categoryList.innerHTML = summaries
      .map(
        (summary) => `
          <button
            type="button"
            class="category-button ${summary.code === state.activeCategory ? "is-active" : ""}"
            data-category="${escapeHtml(summary.code)}"
          >
            <span class="category-code">${escapeHtml(summary.label)}</span>
            <span class="count-pill">${summary.count}</span>
          </button>
        `,
      )
      .join("");

    elements.categoryList.querySelectorAll("[data-category]").forEach((button) => {
      button.addEventListener("click", () => {
        state.activeCategory = button.dataset.category;
        applyCategoryFilter();
        render();
        syncSelectedGraphics();
      });
    });
  }

  function formatSegmentLength(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "";
    }

    // Segment lengths run from 0.14 to 33.68 miles, so a flat 1 decimal is 28% off on the
    // shortest one. Round at render only — the stored value is never modified.
    return `${value.toFixed(value >= 10 ? 1 : 2)} mi`;
  }

  function renderSegments() {
    const visibleSegments = getVisibleSegments();

    elements.visibleCount.textContent = String(visibleSegments.length);
    elements.selectedCount.textContent = String(state.selectedSegmentIds.size);
    elements.clearSelectionButton.disabled = state.selectedSegmentIds.size === 0;
    elements.zoomSelectedButton.disabled = state.selectedSegmentIds.size === 0;
    elements.differFilter.disabled = !state.limitsLoaded;
    elements.differFilter.setAttribute("aria-pressed", String(state.onlyDiffering));
    elements.differCount.textContent = state.limitsLoaded
      ? String(state.csjs.filter((csj) => csj.differs).length)
      : "...";

    if (!visibleSegments.length) {
      elements.segmentList.innerHTML =
        '<div class="empty-state">No segments match the current filter.</div>';
      return;
    }

    const normalizedSearch = state.searchTerm.trim().toLowerCase();
    const selectedCsj = getSelectedCsj();

    elements.segmentList.innerHTML = visibleSegments
      .map((segment) => {
        const isSelected = state.selectedSegmentIds.has(segment.objectId);
        const lengthLabel = formatSegmentLength(segment.lengthMiles);
        const csjs = getSegmentCsjs(segment);

        // A segment opens by itself when only its CSJs match the search, or while the filter for
        // differing limits is on. Then only the CSJs that matched are listed.
        let shownCsjs = csjs;
        let isAutoExpanded = false;

        if (state.onlyDiffering) {
          shownCsjs = csjs.filter((csj) => csj.differs);
          isAutoExpanded = true;
        } else if (normalizedSearch && !segmentMatchesText(segment, normalizedSearch)) {
          shownCsjs = csjs.filter((csj) => csjMatchesSearch(csj, normalizedSearch));
          isAutoExpanded = true;
        }

        const isExpanded = isAutoExpanded || state.expandedSegmentIds.has(segment.objectId);
        const differingCount = csjs.filter((csj) => csj.differs).length;
        const countLabel =
          shownCsjs.length === csjs.length
            ? `${csjs.length} CSJ${csjs.length === 1 ? "" : "s"}`
            : `${shownCsjs.length} of ${csjs.length} CSJs`;

        const csjToggle = csjs.length
          ? `
            <button
              type="button"
              class="csj-toggle"
              data-csj-toggle="${segment.objectId}"
              aria-expanded="${isExpanded}"
              ${isAutoExpanded ? "disabled" : ""}
            >
              <span class="csj-toggle-arrow" aria-hidden="true">&#9656;</span>${countLabel}${
                differingCount
                  ? ` <span class="csj-differ-note">&middot; ${differingCount} differ</span>`
                  : ""
              }
            </button>
          `
          : "";

        const csjList =
          csjs.length && isExpanded
            ? `
            <ul class="csj-list">
              ${shownCsjs
                .map((csj) => {
                  const limits = csjLimitsLabel(csj);
                  const trackerWording = wordingOf(csj.tracker);
                  const isMatch = normalizedSearch && csjMatchesSearch(csj, normalizedSearch);

                  return `
                    <li>
                      <button
                        type="button"
                        class="csj-row ${selectedCsj?.digits === csj.digits ? "is-selected" : ""} ${
                          isMatch ? "is-match" : ""
                        }"
                        data-csj="${csj.digits}"
                      >
                        <span class="csj-number">${escapeHtml(csj.dashed)}${
                          csj.differs ? '<span class="csj-flag">Tracker differs</span>' : ""
                        }</span>
                        ${limits ? `<span class="csj-limits">${escapeHtml(limits)}</span>` : ""}
                        ${
                          csj.differs
                            ? `<span class="csj-tracker">Tracker: ${escapeHtml(trackerWording)}</span>`
                            : ""
                        }
                      </button>
                    </li>
                  `;
                })
                .join("")}
            </ul>
          `
            : "";

        return `
          <div class="segment-group">
            <label class="segment-row ${isSelected ? "is-selected" : ""}" data-segment-id="${segment.objectId}">
              <input
                class="segment-toggle"
                type="checkbox"
                data-toggle-id="${segment.objectId}"
                ${isSelected ? "checked" : ""}
              />
              <span class="segment-text">
                <span class="segment-name">${escapeHtml(segment.label)}</span>
                ${
                  segment.limits
                    ? `<span class="segment-limits">${escapeHtml(segment.limits)}</span>`
                    : ""
                }
              </span>
              ${lengthLabel ? `<span class="segment-length">${lengthLabel}</span>` : ""}
            </label>
            ${csjToggle}
            ${csjList}
          </div>
        `;
      })
      .join("");

    elements.segmentList.querySelectorAll("[data-toggle-id]").forEach((checkbox) => {
      checkbox.addEventListener("change", async () => {
        const objectId = Number(checkbox.dataset.toggleId);

        state.selectedCsj = null;

        if (checkbox.checked) {
          state.selectedSegmentIds.add(objectId);
        } else {
          state.selectedSegmentIds.delete(objectId);
        }

        render();
        await syncSelectedGraphics();
        await zoomToSegments(Array.from(state.selectedSegmentIds));
      });
    });

    elements.segmentList.querySelectorAll("[data-csj-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const objectId = Number(button.dataset.csjToggle);

        if (state.expandedSegmentIds.has(objectId)) {
          state.expandedSegmentIds.delete(objectId);
        } else {
          state.expandedSegmentIds.add(objectId);
        }

        renderSegments();
      });
    });

    elements.segmentList.querySelectorAll("[data-csj]").forEach((button) => {
      button.addEventListener("click", () => {
        focusCsj(button.dataset.csj).catch((error) => console.error(error));
      });
    });
  }

  function render() {
    renderCategories();
    renderSegments();
  }

  async function querySegments(objectIds) {
    if (!objectIds.length) {
      return [];
    }

    const query = segmentsLayer.createQuery();
    query.objectIds = objectIds;
    query.returnGeometry = true;
    query.outFields = [
      "OBJECTID",
      "Readable_SegID",
      "Segment_ID",
      "Highway",
      "County",
      "HSYS",
      "Segment_Length_Mi",
      "Segment_Limits",
    ];

    const result = await segmentsLayer.queryFeatures(query);
    return result.features;
  }

  function buildZoomExtent(features) {
    const extents = features.map((feature) => feature.geometry?.extent).filter(Boolean);

    if (!extents.length) {
      return null;
    }

    const bounds = extents.reduce(
      (accumulator, extent) => ({
        xmin: Math.min(accumulator.xmin, extent.xmin),
        ymin: Math.min(accumulator.ymin, extent.ymin),
        xmax: Math.max(accumulator.xmax, extent.xmax),
        ymax: Math.max(accumulator.ymax, extent.ymax),
      }),
      {
        xmin: Number.POSITIVE_INFINITY,
        ymin: Number.POSITIVE_INFINITY,
        xmax: Number.NEGATIVE_INFINITY,
        ymax: Number.NEGATIVE_INFINITY,
      },
    );

    const width = Math.max(bounds.xmax - bounds.xmin, 1);
    const height = Math.max(bounds.ymax - bounds.ymin, 1);
    const isSingleSegment = features.length === 1;
    const horizontalPadding = Math.max(width * (isSingleSegment ? 0.28 : 0.18), isSingleSegment ? 1800 : 900);
    const verticalPadding = Math.max(height * (isSingleSegment ? 0.55 : 0.35), isSingleSegment ? 1800 : 900);

    // Long, shallow segment extents still fit too tightly unless we expand beyond raw bounds.
    return new Extent({
      xmin: bounds.xmin - horizontalPadding,
      ymin: bounds.ymin - verticalPadding,
      xmax: bounds.xmax + horizontalPadding,
      ymax: bounds.ymax + verticalPadding,
      spatialReference: extents[0].spatialReference,
    }).expand(isSingleSegment ? 1.2 : 1.1);
  }

  /** Drop tiny artifact paths that are less than 5% of the longest path. */
  function filterArtifactPaths(geometry) {
    if (!geometry || !geometry.paths || geometry.paths.length <= 1) {
      return geometry;
    }

    const paths = geometry.paths;

    function pathLength(path) {
      let len = 0;
      for (let i = 1; i < path.length; i++) {
        const dx = path[i][0] - path[i - 1][0];
        const dy = path[i][1] - path[i - 1][1];
        len += Math.sqrt(dx * dx + dy * dy);
      }
      return len;
    }

    // Find the longest path — that's the main segment
    const lengths = paths.map(pathLength);
    const maxLength = Math.max(...lengths);

    // Keep paths that are at least 5% of the longest path's length
    const kept = paths.filter((path, i) => lengths[i] >= maxLength * 0.05);

    if (kept.length === 0) {
      return geometry;
    }

    const normalizedPaths = kept.map((path) => path.map((point) => Array.from(point)));
    const geometryJson = typeof geometry.toJSON === "function"
      ? geometry.toJSON()
      : {
          spatialReference: geometry.spatialReference,
          hasM: geometry.hasM,
          hasZ: geometry.hasZ,
        };

    geometryJson.type = "polyline";
    geometryJson.paths = normalizedPaths;
    return new Polyline(geometryJson);
  }

  let selectedCsjSyncToken = 0;

  async function syncSelectedCsjGraphics() {
    const token = ++selectedCsjSyncToken;
    const segmentIds = state.segments
      .filter((segment) => state.selectedSegmentIds.has(segment.objectId) && segment.segmentId)
      .map((segment) => `'${segment.segmentId.replaceAll("'", "''")}'`);

    selectedCsjLayer.removeAll();

    if (!segmentIds.length) {
      return;
    }

    const selectedCsj = getSelectedCsj();
    const query = csjLayer.createQuery();
    query.where = selectedCsj
      ? `CSJ = '${selectedCsj.digits}'`
      : `Segment_ID IN (${segmentIds.join(",")})`;
    query.returnGeometry = true;
    query.outFields = ["OBJECTID", "CSJ", "CSJ_Dashed", "Segment_ID", "Segment_Label"];

    const result = await csjLayer.queryFeatures(query);

    // A newer selection started while this query ran, so its answer is out of date.
    if (token !== selectedCsjSyncToken) {
      return;
    }

    result.features.forEach((feature) => {
      const highlightedFeature = typeof feature.clone === "function" ? feature.clone() : feature;
      highlightedFeature.symbol = {
        type: "simple-line",
        color: [0, 90, 200, 255],
        width: 3,
        cap: "round",
        join: "round",
      };
      selectedCsjLayer.add(highlightedFeature);
    });
  }

  async function syncSelectedGraphics() {
    const objectIds = Array.from(state.selectedSegmentIds);

    syncSelectedCsjGraphics().catch((error) => console.error(error));
    selectedSegmentsLayer.removeAll();

    if (!objectIds.length) {
      return;
    }

    const features = await querySegments(objectIds);

    features.forEach((feature) => {
      const highlightedFeature = typeof feature.clone === "function" ? feature.clone() : feature;
      highlightedFeature.geometry = filterArtifactPaths(feature.geometry);
      highlightedFeature.symbol = {
        type: "simple-line",
        color: [158, 50, 82, 255],
        width: 5,
        cap: "round",
        join: "round",
      };
      selectedSegmentsLayer.add(highlightedFeature);
    });
  }

  async function zoomToSegments(objectIds) {
    const features = await querySegments(objectIds);

    if (!features.length) {
      return;
    }

    const isSingleSegment = features.length === 1;
    await view.goTo(buildZoomExtent(features) ?? features, {
      padding: {
        top: 140,
        right: 120,
        bottom: 140,
        left: 120,
      },
      maxScale: 140000,
    });

    await view.goTo(
      {
        center: view.center,
        scale: view.scale * (isSingleSegment ? 1.2 : 1.1),
      },
      {
        animate: false,
      },
    );

  }

  // ── Automation API ──────────────────────────────────────────────
  // The following window.__ functions are the public contract used by
  // Scripts/visual-review-screenshots.py (Playwright-based batch capture). The batch
  // script verifies these exist at runtime and will fail fast if any
  // are missing. If you rename, remove, or change the signature of
  // any of these functions, update Scripts/visual-review-screenshots.py to match.
  //
  // These functions are also used by the web app's own UI (segment
  // selection, zoom), so they must continue to work standalone in
  // the browser without Playwright.
  // ────────────────────────────────────────────────────────────────
  window.__segments_state = state;
  window.__render = render;
  window.__syncSelectedGraphics = syncSelectedGraphics;

  window.__waitForSegments = function () {
    return view.when().then(() => {
      return new Promise((resolve) => {
        const check = () => {
          if (state.segments && state.segments.length > 0 && !view.updating) {
            resolve(state.segments.length);
          } else {
            setTimeout(check, 500);
          }
        };
        check();
      });
    });
  };

  window.__selectAndZoomSegment = async function (segmentName) {
    const match = state.segments.find((segment) => segment.label === segmentName);
    if (!match) {
      return false;
    }
    state.selectedSegmentIds.clear();
    state.selectedSegmentIds.add(match.objectId);
    render();
    await syncSelectedGraphics();
    await zoomToSegments([match.objectId]);
    return true;
  };

  window.__waitForTiles = function (timeout) {
    timeout = timeout || 15000;
    return new Promise(function (resolve) {
      if (!view.updating) { resolve(true); return; }
      var settled = false;
      var handle = view.watch("updating", function (updating) {
        if (!updating && !settled) {
          settled = true;
          handle.remove();
          resolve(true);
        }
      });
      setTimeout(function () {
        if (!settled) {
          settled = true;
          handle.remove();
          resolve(false);
        }
      }, timeout);
    });
  };

  window.__captureView = async function (width, height) {
    await window.__waitForTiles(15000);
    var screenshot = await view.takeScreenshot({
      width: width || 1920,
      height: height || 1080,
      format: "png",
    });
    return screenshot.dataUrl;
  };

  window.__selectCorridorSegments = async function (segmentName) {
    // First try exact match
    const exact = state.segments.find((s) => s.label === segmentName);
    if (exact) {
      return window.__selectAndZoomSegment(segmentName);
    }

    // No exact match — select all sub-segments that start with this name
    const prefix = segmentName + " - ";
    const matches = state.segments.filter((s) => s.label.startsWith(prefix));
    if (matches.length === 0) {
      return false;
    }

    state.selectedSegmentIds.clear();
    matches.forEach((m) => state.selectedSegmentIds.add(m.objectId));
    render();
    await syncSelectedGraphics();
    return matches.length;
  };

  window.__queryRoadsNearPoint = async function (lon, lat, radiusMeters) {
    radiusMeters = radiusMeters || 50;
    const point = {
      type: "point",
      longitude: lon,
      latitude: lat,
      spatialReference: { wkid: 4326 },
    };
    const query = roadsQueryLayer.createQuery();
    query.geometry = point;
    query.distance = radiusMeters;
    query.units = "meters";
    query.spatialRelationship = "intersects";
    query.returnGeometry = false;
    query.outFields = [
      "RTE_NM", "RTE_PRFX", "RTE_NBR", "MAP_LBL",
      "RDBD_TYPE", "DES_DRCT", "COUNTY", "BEGIN_DFO", "END_DFO",
    ];
    query.orderByFields = ["RTE_NM ASC"];

    const result = await roadsQueryLayer.queryFeatures(query);
    const seen = new Set();
    const roads = [];
    result.features.forEach(function (f) {
      const a = f.attributes || {};
      const primaryName = a.MAP_LBL || a.RTE_NM;
      const key = [primaryName || "", a.RDBD_TYPE || "", a.DES_DRCT || ""].join("|");
      if (seen.has(key)) return;
      seen.add(key);
      roads.push({
        route_name: a.RTE_NM || null,
        route_prefix: a.RTE_PRFX || null,
        route_number: a.RTE_NBR || null,
        map_label: a.MAP_LBL || null,
        roadbed_type: a.RDBD_TYPE || null,
        direction: a.DES_DRCT || null,
        county: a.COUNTY || null,
        begin_dfo: a.BEGIN_DFO,
        end_dfo: a.END_DFO,
      });
    });
    return roads;
  };

  window.__navigateAndCapture = async function (_segmentName, lon, lat, closeZoom, contextZoom) {
    closeZoom = closeZoom || 17;
    contextZoom = contextZoom || 15;
    await view.goTo({ center: [lon, lat], zoom: closeZoom }, { animate: false });
    await window.__waitForTiles(15000);
    var closeImg = await view.takeScreenshot({ width: 1920, height: 1080, format: "png" });

    await view.goTo({ center: [lon, lat], zoom: contextZoom }, { animate: false });
    await window.__waitForTiles(15000);
    var contextImg = await view.takeScreenshot({ width: 1920, height: 1080, format: "png" });

    return { close: closeImg.dataUrl, context: contextImg.dataUrl };
  };

  function dedupeRoadResults(features) {
    const items = [];
    const seen = new Set();

    features.forEach((feature) => {
      const attributes = feature.attributes ?? {};
      const primaryName = attributes.MAP_LBL || attributes.RTE_NM;

      if (!primaryName) {
        return;
      }

      const key = [
        primaryName,
        attributes.RDBD_TYPE || "",
        attributes.DES_DRCT || "",
      ].join("|");

      if (seen.has(key)) {
        return;
      }

      seen.add(key);
      items.push({
        name: primaryName,
        routeName: attributes.RTE_NM || primaryName,
        routePrefix: attributes.RTE_PRFX || "",
        routeNumber: attributes.RTE_NBR || "",
        roadbedType: attributes.RDBD_TYPE || "Roadway",
        direction: attributes.DES_DRCT || "",
        county: attributes.COUNTY || "",
        beginDfo: attributes.BEGIN_DFO,
        endDfo: attributes.END_DFO,
      });
    });

    return items;
  }

  function formatDfo(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
      return "N/A";
    }

    return value.toFixed(3);
  }

  async function showRoadPopup(mapPoint) {
    const query = roadsQueryLayer.createQuery();
    query.geometry = mapPoint;
    query.distance = Math.max(3, Math.min(view.resolution * 5, 20));
    query.units = "meters";
    query.spatialRelationship = "intersects";
    query.returnGeometry = true;
    query.outFields = [
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
    ];
    query.orderByFields = ["RTE_NM ASC"];
    query.num = 1;

    const result = await roadsQueryLayer.queryFeatures(query);

    if (!result.features.length) {
      view.closePopup();
      return;
    }

    // Highlight the clicked road on the map
    const hitFeature = result.features[0];
    if (hitFeature.geometry) {
      const highlight = typeof hitFeature.clone === "function" ? hitFeature.clone() : hitFeature;
      highlight.symbol = {
        type: "simple-line",
        color: [0, 180, 220, 255],
        width: 5,
        cap: "round",
        join: "round",
      };
      roadHighlightLayer.add(highlight);
    }

    const roads = dedupeRoadResults(result.features);

    if (!roads.length) {
      view.closePopup();
      return;
    }

    const road = roads[0];
    const title = road.name;
    const content = `
      <div class="road-popup">
        <p><strong>${escapeHtml(road.routeName)}</strong></p>
        <ul>
          <li>Roadbed Type: ${escapeHtml(road.roadbedType)}</li>
          <li>Name/Number: ${escapeHtml(road.name)}</li>
          <li>Direction: ${escapeHtml(road.direction || "N/A")}</li>
          <li>Begin DFO: ${escapeHtml(formatDfo(road.beginDfo))}</li>
          <li>End DFO: ${escapeHtml(formatDfo(road.endDfo))}</li>
        </ul>
        ${
          road.routePrefix && road.routeNumber
            ? `<p><a href="${HIGHWAY_DESIGNATION_BASE_URL}?rtePrefix=${encodeURIComponent(
                road.routePrefix,
              )}&rteNumber=${encodeURIComponent(
                road.routeNumber,
              )}" target="_blank" rel="noreferrer">Open highway designation lookup</a></p>`
            : ""
        }
      </div>
    `;

    view.openPopup({
      title: escapeHtml(title),
      content,
      location: mapPoint,
    });
  }

  async function loadSegments() {
    const query = segmentsLayer.createQuery();
    query.where = "1=1";
    query.returnGeometry = false;
    query.outFields = [
      "OBJECTID",
      "Readable_SegID",
      "Segment_ID",
      "Highway",
      "County",
      "HSYS",
      "Segment_Length_Mi",
      "Segment_Limits",
    ];
    query.orderByFields = ["Readable_SegID ASC"];

    const result = await segmentsLayer.queryFeatures(query);

    state.segments = result.features
      .map((feature) => ({
        objectId: feature.attributes.OBJECTID,
        label: feature.attributes.Readable_SegID || feature.attributes.Segment_ID || "Unnamed segment",
        segmentId: feature.attributes.Segment_ID || "",
        highway: feature.attributes.Highway || "",
        county: feature.attributes.County || "",
        hsys: feature.attributes.HSYS || "Unknown",
        lengthMiles: feature.attributes.Segment_Length_Mi,
        limits: feature.attributes.Segment_Limits || "",
      }))
      .sort(sortByLabel);

    render();
  }

  async function queryTxdotRecords(url, where, outFields) {
    const response = await fetch(`${url}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ where, outFields, returnGeometry: "false", f: "json" }),
    });

    if (!response.ok) {
      throw new Error(`${url} answered ${response.status}`);
    }

    const json = await response.json();

    if (json.error) {
      throw new Error(json.error.message);
    }

    return (json.features ?? []).map((feature) => feature.attributes);
  }

  async function queryTxdotCsj(url, where, outFields) {
    const records = await queryTxdotRecords(url, where, outFields);
    return records[0] ?? null;
  }

  function formatLimitsPair(record) {
    if (!record) {
      return "No record";
    }

    const from = String(record.LIMITS_FROM ?? "").trim();
    const to = String(record.LIMITS_TO ?? "").trim();

    return from || to ? `${from || "?"} to ${to || "?"}` : "No limits listed";
  }

  // Shows what the two TxDOT layers say today about one CSJ, beside the limits of its segment, so
  // a difference in wording can be told apart from a difference in extent on the map.
  async function showCsjPopup(attributes, location) {
    const digits = String(attributes.CSJ ?? "").replace(/\D/g, "");
    const segment = state.segments.find((item) => item.segmentId === attributes.Segment_ID);

    const [dcis, tracker] = await Promise.allSettled([
      queryTxdotCsj(
        TXDOT_DCIS_URL,
        `CONTROL_SECT_JOB LIKE '%${digits}%'`,
        "CONTROL_SECT_JOB,LIMITS_FROM,LIMITS_TO",
      ),
      queryTxdotCsj(
        TXDOT_TRACKER_URL,
        `CONTROL_SECT_JOB = '${digits}'`,
        "CONTROL_SECT_JOB,LIMITS_FROM,LIMITS_TO,LAST_PROJ_UPDATE_DT",
      ),
    ]);

    const describe = (settled) =>
      settled.status === "fulfilled" ? formatLimitsPair(settled.value) : "Could not load";
    const trackerUpdated =
      tracker.status === "fulfilled" && tracker.value?.LAST_PROJ_UPDATE_DT
        ? new Date(tracker.value.LAST_PROJ_UPDATE_DT).toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
            timeZone: "UTC",
          })
        : "";

    const content = `
      <div class="road-popup">
        <p><strong>${escapeHtml(attributes.CSJ_Dashed)}</strong> on ${escapeHtml(
          attributes.Segment_Label || attributes.Segment_ID,
        )}</p>
        <ul>
          <li>TxDOT DCIS limits: ${escapeHtml(describe(dcis))}</li>
          <li>TxDOT Project Tracker limits: ${escapeHtml(describe(tracker))}${
            trackerUpdated ? ` (updated ${escapeHtml(trackerUpdated)})` : ""
          }</li>
          ${segment?.limits ? `<li>Segment limits: ${escapeHtml(segment.limits)}</li>` : ""}
        </ul>
      </div>
    `;

    view.openPopup({
      title: `CSJ ${escapeHtml(attributes.CSJ_Dashed)}`,
      content,
      location,
    });
  }

  async function selectSegmentOnMap(segment) {
    state.selectedCsj = null;
    state.selectedSegmentIds = new Set([segment.objectId]);
    state.searchTerm = segment.label;
    elements.searchInput.value = segment.label;
    render();
    await syncSelectedGraphics();
  }

  // Selects one CSJ, from its row in the pane or from a ?csj= link: its segment is selected and
  // opened in the list, the map zooms to the CSJ, and its popup opens. Returns false when no CSJ
  // matches.
  async function focusCsj(digits) {
    const csj = state.csjs.find((item) => item.digits === digits);

    if (!csj) {
      return false;
    }

    const query = csjLayer.createQuery();
    query.where = `CSJ = '${csj.digits}'`;
    query.returnGeometry = true;
    query.outFields = ["OBJECTID", "CSJ", "CSJ_Dashed", "Segment_ID", "Segment_Label"];

    const result = await csjLayer.queryFeatures(query);
    const feature = result.features[0];

    if (!feature?.geometry) {
      return false;
    }

    const segment = state.segments.find((item) => item.segmentId === csj.segmentId);

    state.selectedCsj = csj.digits;
    state.selectedSegmentIds = segment ? new Set([segment.objectId]) : new Set();

    if (segment) {
      state.expandedSegmentIds.add(segment.objectId);
    }

    render();
    elements.segmentList.querySelector(".csj-row.is-selected")?.scrollIntoView({ block: "nearest" });
    await syncSelectedGraphics();

    await view.goTo(feature.geometry.extent.clone().expand(1.4), {
      padding: {
        top: 140,
        right: 120,
        bottom: 140,
        left: 120,
      },
    });

    const path = feature.geometry.paths[0];
    const [x, y] = path[Math.floor(path.length / 2)];

    await showCsjPopup(feature.attributes, {
      type: "point",
      x,
      y,
      spatialReference: feature.geometry.spatialReference,
    });

    return true;
  }

  // ?csj=0014-16-289 (hyphens optional): the list narrows to that CSJ, then focusCsj does the rest.
  async function selectCsjFromUrl(requested) {
    const digits = requested.replace(/\D/g, "");
    const csj = digits.length === 9 ? state.csjs.find((item) => item.digits === digits) : null;

    if (!csj) {
      return false;
    }

    state.searchTerm = csj.dashed;
    elements.searchInput.value = csj.dashed;

    return focusCsj(csj.digits);
  }

  async function loadCsjs() {
    const query = csjLayer.createQuery();
    query.where = "1=1";
    query.returnGeometry = false;
    query.outFields = ["OBJECTID", "CSJ", "CSJ_Dashed", "Segment_ID", "Segment_Label"];
    query.orderByFields = ["CSJ_Dashed ASC"];

    const result = await csjLayer.queryFeatures(query);

    state.csjs = result.features.map((feature) => ({
      objectId: feature.attributes.OBJECTID,
      digits: String(feature.attributes.CSJ ?? "").replace(/\D/g, ""),
      dashed: feature.attributes.CSJ_Dashed || "",
      segmentId: feature.attributes.Segment_ID || "",
      segmentLabel: feature.attributes.Segment_Label || "",
      dcis: null,
      tracker: null,
      differs: false,
    }));

    state.csjsBySegment = new globalThis.Map();
    state.csjs.forEach((csj) => {
      const list = state.csjsBySegment.get(csj.segmentId) ?? [];
      list.push(csj);
      state.csjsBySegment.set(csj.segmentId, list);
    });

    render();

    // The limits wording comes after the list is on screen; a CSJ row shows only its number until then.
    loadCsjLimits().catch((error) => console.error(error));
  }

  // Reads what DCIS and the Project Tracker say for every CSJ in two requests, and marks the CSJs
  // the two word differently. Case, spacing and punctuation do not count as a difference.
  async function loadCsjLimits() {
    const inList = state.csjs.map((csj) => `'${csj.digits}'`).join(",");
    const [dcisResult, trackerResult] = await Promise.allSettled([
      queryTxdotRecords(
        TXDOT_DCIS_URL,
        `CONTROL_SECT_JOB IN (${inList})`,
        "CONTROL_SECT_JOB,LIMITS_FROM,LIMITS_TO",
      ),
      queryTxdotRecords(
        TXDOT_TRACKER_URL,
        `CONTROL_SECT_JOB IN (${inList})`,
        "CONTROL_SECT_JOB,LIMITS_FROM,LIMITS_TO,LAST_PROJ_UPDATE_DT",
      ),
    ]);

    const byCsj = (settled) =>
      new globalThis.Map(
        settled.status === "fulfilled"
          ? settled.value.map((record) => [String(record.CONTROL_SECT_JOB).trim(), record])
          : [],
      );
    const dcis = byCsj(dcisResult);
    const tracker = byCsj(trackerResult);

    // DCIS pads some control-section-job values with spaces, which IN does not match.
    const missing = state.csjs.filter((csj) => !dcis.has(csj.digits));

    if (dcisResult.status === "fulfilled" && missing.length) {
      try {
        const found = await queryTxdotRecords(
          TXDOT_DCIS_URL,
          missing.map((csj) => `CONTROL_SECT_JOB LIKE '%${csj.digits}%'`).join(" OR "),
          "CONTROL_SECT_JOB,LIMITS_FROM,LIMITS_TO",
        );
        found.forEach((record) => dcis.set(String(record.CONTROL_SECT_JOB).trim(), record));
      } catch (error) {
        console.error(error);
      }
    }

    const toWording = (record) =>
      record
        ? {
            from: String(record.LIMITS_FROM ?? "").trim(),
            to: String(record.LIMITS_TO ?? "").trim(),
            updated: record.LAST_PROJ_UPDATE_DT,
          }
        : null;

    state.csjs.forEach((csj) => {
      csj.dcis = toWording(dcis.get(csj.digits));
      csj.tracker = toWording(tracker.get(csj.digits));
      csj.differs =
        Boolean(wordingOf(csj.dcis) && wordingOf(csj.tracker)) &&
        (normalizeWording(csj.dcis.from) !== normalizeWording(csj.tracker.from) ||
          normalizeWording(csj.dcis.to) !== normalizeWording(csj.tracker.to));
    });

    state.limitsLoaded = true;
    renderSegments();
  }

  // Opens the app on one CSJ or one segment from the link: ?csj=0014-16-289, ?segment=IH%2035W%20-%20D
  // (the segment label) or ?segment=IH0035WD (its Segment_ID). A value that matches nothing leaves
  // the app as it opens without one.
  async function selectFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const requestedCsj = params.get("csj");

    if (requestedCsj && (await selectCsjFromUrl(requestedCsj))) {
      return;
    }

    const requested = params.get("segment");

    if (!requested) {
      return;
    }

    const wanted = requested.trim().toLowerCase();
    const match = state.segments.find(
      (segment) =>
        segment.label.toLowerCase() === wanted || segment.segmentId.toLowerCase() === wanted,
    );

    if (!match) {
      return;
    }

    await selectSegmentOnMap(match);
    await zoomToSegments([match.objectId]);
  }

  elements.searchInput.addEventListener("input", () => {
    state.searchTerm = elements.searchInput.value;
    renderSegments();
  });

  elements.differFilter.addEventListener("click", () => {
    state.onlyDiffering = !state.onlyDiffering;
    renderSegments();
  });

  elements.clearSelectionButton.addEventListener("click", async () => {
    state.selectedCsj = null;
    state.selectedSegmentIds.clear();
    render();
    await syncSelectedGraphics();
    view.closePopup();
  });

  elements.zoomSelectedButton.addEventListener("click", async () => {
    await zoomToSegments(Array.from(state.selectedSegmentIds));
  });

  view.on("click", async (event) => {
    view.closePopup();
    roadHighlightLayer.removeAll();

    const csjHit = await view.hitTest(event, { include: [csjLayer, selectedCsjLayer] });
    const csjGraphic = csjHit.results.find((result) => result.graphic?.attributes?.CSJ_Dashed)?.graphic;

    if (csjGraphic) {
      await showCsjPopup(csjGraphic.attributes, event.mapPoint);
      return;
    }

    const countyLayer = countyBoundaryHitLayer || countyBoundaryLayer;
    if (countyLayer) {
      const hitTestResult = await view.hitTest(event, { include: countyLayer });
      const countyHit = hitTestResult.results.find((result) => result.graphic?.layer === countyLayer);

      if (countyHit?.graphic) {
        await showCountyBoundaryPopup(countyHit.graphic, event.mapPoint);
        return;
      }
    }

    await showRoadPopup(event.mapPoint);
  });

  view.on("pointer-move", async (event) => {
    if (!countyBoundaryLayer) {
      view.container.style.cursor = "default";
      return;
    }

    const hoverToken = ++countyBoundaryHoverToken;
    const hitTestResult = await view.hitTest(event, {
      include: countyBoundaryHitLayer || countyBoundaryLayer,
    });

    if (hoverToken !== countyBoundaryHoverToken) {
      return;
    }

    view.container.style.cursor = hitTestResult.results.length ? "pointer" : "default";
  });

  view.watch("stationary", syncCountyLabelOverlayWithView);
  view.watch("rotation", syncCountyLabelOverlayWithView);
  view.watch("width", syncCountyLabelOverlayWithView);
  view.watch("height", syncCountyLabelOverlayWithView);

  Promise.all([segmentsLayer.load(), roadsQueryLayer.load(), view.when()])
    .then(loadSegments)
    .then(() => loadCsjs().catch((error) => console.error(error)))
    .then(initializeCountyBoundaries)
    .then(() => selectFromUrl().catch((error) => console.error(error)))
    .catch((error) => {
      console.error(error);
      elements.segmentList.innerHTML =
        '<div class="empty-state">The app could not load the ArcGIS services. Check the browser console for details.</div>';
    });
});
