(function () {
  "use strict";

  const config = window.SOLAR_MAP_CONFIG;
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const emptyCollection = { type: "FeatureCollection", features: [] };

  const DEFAULT_STATUS = "Click the map to find the nearest solar facilities.";
  const KM_PER_DEGREE = 111.32; // length of one degree of latitude
  // Rough bounds of the USPVDB coverage (US states + territories; the Aleutians cross 180°).
  const US_LAT = [17, 72];
  const US_LNG_WEST_OF = -64;
  const US_LNG_EAST_OF = 172;

  // Basemap: OpenStreetMap's public tile server, used per its tile usage policy
  // (https://operations.osmfoundation.org/policies/tiles/): standard HTTPS host, only tiles
  // in view are requested, browser HTTP caching is left intact, the page must not suppress
  // the Referer (see SECURE_REFERRER_POLICY in settings.py), and attribution is always
  // visible. This server is best-effort with no SLA — swap in a tile provider before any
  // real deployment or heavy use.
  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    // compact: false keeps attribution expanded; the policy forbids hiding it behind a toggle.
    attributionControl: { compact: false },
    center: [-98.5, 39.8], // continental US (used unless the browser shares a location)
    zoom: 3.5,
  });
  map.addControl(new maplibregl.NavigationControl(), "top-right");

  // Flatten arbitrarily nested GeoJSON coordinates into [lng, lat] pairs.
  function positions(coords) {
    return typeof coords[0] === "number" ? [coords] : coords.flatMap(positions);
  }

  function renderResults(features) {
    resultsEl.replaceChildren();
    features.forEach((feature, i) => {
      const p = feature.properties;
      const li = document.createElement("li");

      // textContent (not innerHTML): facility names come from external data.
      const name = document.createElement("div");
      name.className = "name";
      name.textContent = `${i + 1}. ${p.name}`;

      const km = p.distance_m / 1000;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent =
        `${p.state} · ${p.capacity_mw} MW · ${km.toFixed(1)} km (${(km * 0.621371).toFixed(1)} mi)`;

      li.append(name, meta);
      resultsEl.append(li);
    });
  }

  let latestRequest = 0;
  let userHasClicked = false;

  async function showNearest(lngLat) {
    userHasClicked = true;
    const requestId = ++latestRequest;
    statusEl.textContent = "Finding nearest facilities…";

    const params = new URLSearchParams({ lat: lngLat.lat, lon: lngLat.lng, n: config.nearestCount });
    let data;
    try {
      const response = await fetch(`${config.nearestUrl}?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = await response.json();
    } catch (err) {
      if (requestId === latestRequest) statusEl.textContent = `Could not load nearest facilities (${err.message}).`;
      return;
    }
    if (requestId !== latestRequest) return; // a newer click superseded this one

    const features = data.features;
    map.getSource("nearest").setData(data);
    // Markers use the denormalized centroid the API returns, so results stay visible at low zoom.
    map.getSource("nearest-points").setData({
      type: "FeatureCollection",
      features: features.map((f) => ({ type: "Feature", properties: {}, geometry: f.properties.centroid })),
    });
    map.getSource("query-point").setData({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: [lngLat.lng, lngLat.lat] },
    });

    renderResults(features);
    statusEl.textContent = features.length
      ? `${features.length} nearest to ${lngLat.lat.toFixed(4)}, ${lngLat.lng.toFixed(4)}`
      : "No facilities found.";

    if (features.length) {
      const bounds = new maplibregl.LngLatBounds([lngLat.lng, lngLat.lat], [lngLat.lng, lngLat.lat]);
      features.forEach((f) => positions(f.geometry.coordinates).forEach((pos) => bounds.extend(pos)));
      map.fitBounds(bounds, { padding: 60, maxZoom: 12 });
    }
  }

  // Bounding box of a circle of `radiusKm` around a point (a square 2 × radius across, so the
  // whole circle fits when the map fits this box).
  function radiusBounds(lng, lat, radiusKm) {
    const dLat = radiusKm / KM_PER_DEGREE;
    // A degree of longitude shrinks with latitude; clamp so we never divide by ~0 near the poles.
    const dLng = radiusKm / (KM_PER_DEGREE * Math.max(Math.cos((lat * Math.PI) / 180), 0.05));
    return [
      [lng - dLng, lat - dLat],
      [lng + dLng, lat + dLat],
    ];
  }

  function inUsCoverage(lng, lat) {
    return lat >= US_LAT[0] && lat <= US_LAT[1] && (lng <= US_LNG_WEST_OF || lng >= US_LNG_EAST_OF);
  }

  // If the browser shares its location, zoom to `userRadiusKm` around it. This happens entirely in
  // the browser (geolocation needs HTTPS or localhost); the position is not sent anywhere unless
  // the user clicks the map. Falls back to the whole-US view when unavailable, denied or outside
  // the dataset's coverage.
  function locateUser() {
    if (!("geolocation" in navigator)) return;
    statusEl.textContent = "Locating you…";

    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const { longitude: lng, latitude: lat } = coords;
        if (!inUsCoverage(lng, lat)) {
          statusEl.textContent = `You appear to be outside the US, which is all the data covers. ${DEFAULT_STATUS}`;
          return;
        }
        map.getSource("user-location").setData({
          type: "Feature",
          properties: {},
          geometry: { type: "Point", coordinates: [lng, lat] },
        });
        if (userHasClicked) return; // don't yank the view away from what they're already doing
        map.fitBounds(radiusBounds(lng, lat, config.userRadiusKm), { padding: 20, animate: false });
        statusEl.textContent = `Showing ${config.userRadiusKm} km around you. ${DEFAULT_STATUS}`;
      },
      (err) => {
        const reason = err.code === 1 ? "location permission denied" : "location unavailable";
        statusEl.textContent = `Showing the whole US (${reason}). ${DEFAULT_STATUS}`;
      },
      { timeout: 8000, maximumAge: 5 * 60 * 1000 },
    );
  }

  map.on("load", () => {
    // Facilities come as vector tiles. Absolute URL built by concatenation: MapLibre substitutes
    // the literal {z}/{x}/{y}, and `new URL()` would percent-encode the braces. Vector sources
    // default to 512 px tiles, so the tile zoom equals floor(map zoom) — which is why the server's
    // POLYGON_MIN_ZOOM lines up with the layer minzoom below.
    map.addSource("facilities", {
      type: "vector",
      tiles: [window.location.origin + config.tilesPath],
      maxzoom: config.tilesMaxZoom,
    });
    map.addSource("nearest", { type: "geojson", data: emptyCollection });
    map.addSource("nearest-points", { type: "geojson", data: emptyCollection });
    map.addSource("query-point", { type: "geojson", data: emptyCollection });
    map.addSource("user-location", { type: "geojson", data: emptyCollection });

    // Zoomed out: one dot per facility (panel arrays are smaller than a pixel).
    map.addLayer({
      id: "facilities-points",
      type: "circle",
      source: "facilities",
      "source-layer": "points",
      maxzoom: config.polygonMinZoom,
      paint: {
        "circle-radius": 3,
        "circle-color": "#f5a623",
        "circle-stroke-color": "#b36b00",
        "circle-stroke-width": 0.5,
      },
    });
    // Zoomed in: the real panel-array polygons.
    map.addLayer({
      id: "facilities-fill",
      type: "fill",
      source: "facilities",
      "source-layer": "polygons",
      minzoom: config.polygonMinZoom,
      paint: { "fill-color": "#f5a623", "fill-opacity": 0.5 },
    });
    map.addLayer({
      id: "facilities-outline",
      type: "line",
      source: "facilities",
      "source-layer": "polygons",
      minzoom: config.polygonMinZoom,
      paint: { "line-color": "#b36b00", "line-width": 1.5 },
    });
    map.addLayer({
      id: "nearest-fill",
      type: "fill",
      source: "nearest",
      paint: { "fill-color": "#d0021b", "fill-opacity": 0.6 },
    });
    map.addLayer({
      id: "nearest-outline",
      type: "line",
      source: "nearest",
      paint: { "line-color": "#7a0010", "line-width": 2 },
    });
    map.addLayer({
      id: "nearest-points",
      type: "circle",
      source: "nearest-points",
      paint: {
        "circle-radius": 8,
        "circle-color": "#d0021b",
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "query-point",
      type: "circle",
      source: "query-point",
      paint: {
        "circle-radius": 6,
        "circle-color": "#1565c0",
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "user-location",
      type: "circle",
      source: "user-location",
      paint: {
        "circle-radius": 7,
        "circle-color": "#2e7d32",
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
      },
    });

    map.on("click", (e) => showNearest(e.lngLat));
    map.getCanvas().style.cursor = "crosshair";
    locateUser();
  });
})();
