(function () {
  "use strict";

  const config = window.SOLAR_MAP_CONFIG;
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const emptyCollection = { type: "FeatureCollection", features: [] };

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
    center: [-98.5, 39.8], // continental US
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

  async function showNearest(lngLat) {
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

  async function loadFacilities() {
    try {
      const response = await fetch(config.facilitiesUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      map.getSource("facilities").setData(data);
      statusEl.textContent = data.features.length
        ? `${data.features.length} facilities loaded. Click the map to find the nearest.`
        : "No facilities in the database yet — run load_uspvdb first.";
    } catch (err) {
      statusEl.textContent = `Could not load facilities (${err.message}).`;
    }
  }

  map.on("load", () => {
    map.addSource("facilities", { type: "geojson", data: emptyCollection });
    map.addSource("nearest", { type: "geojson", data: emptyCollection });
    map.addSource("nearest-points", { type: "geojson", data: emptyCollection });
    map.addSource("query-point", { type: "geojson", data: emptyCollection });

    map.addLayer({
      id: "facilities-fill",
      type: "fill",
      source: "facilities",
      paint: { "fill-color": "#f5a623", "fill-opacity": 0.5 },
    });
    // Panel arrays are tiny at country zoom; the outline keeps them visible as specks.
    map.addLayer({
      id: "facilities-outline",
      type: "line",
      source: "facilities",
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

    map.on("click", (e) => showNearest(e.lngLat));
    map.getCanvas().style.cursor = "crosshair";
    loadFacilities();
  });
})();
