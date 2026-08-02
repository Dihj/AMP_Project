// static/js/modules/mapManager.js

import { renderOmbrothermicFireChart } from './chartManager.js';
import { updateLeftClimateLayer, clearLeftClimateLayer } from './climateLayers.js';

let mapLeft = null;
let mapRight = null;
let leftTileLayer = null;
let rightTileLayer = null;
let fireLayerRight = null;

const boundaryLayers = {
  districtMdg: null,
  PA: null
};

// Store raw GeoJSON feature collections for spatial point-in-polygon queries
const boundaryGeoData = {
  districtMdg: null,
  PA: null
};

export function getMapLeft() { return mapLeft; }
export function getMapRight() { return mapRight; }

export function initMapsOnce(initialOpacity = 0.75, fireVisible = true) {
  const initialCenter = [-18.7, 46.8];
  const initialZoom = 6;
  const darkTileUrl = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
  const attrib = '&copy; CARTO';

  mapLeft = L.map('map-left', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
  leftTileLayer = L.tileLayer(darkTileUrl, { maxZoom: 18, attribution: attrib, opacity: initialOpacity }).addTo(mapLeft);

  mapRight = L.map('map-right', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
  rightTileLayer = L.tileLayer(darkTileUrl, { maxZoom: 18, attribution: attrib, opacity: initialOpacity }).addTo(mapRight);
  L.control.zoom({ position: 'topright' }).addTo(mapRight);

  fireLayerRight = L.layerGroup();
  if (fireVisible) fireLayerRight.addTo(mapRight);
  loadActiveFires24h();

  if (typeof mapLeft.sync === 'function') {
    mapLeft.sync(mapRight, { syncCursor: true });
    mapRight.sync(mapLeft, { syncCursor: true });
  }

  setupMapClickEvents(mapLeft, mapRight);
  updateRasterLayer('rr', 'Jan');
}

export function updateRasterLayer(parameter = 'Rain', timeStep = 'Jan', fixedScale = false) {
  if (!mapLeft) return;
  const paramMap = { 'rr': 'Rain', 'tmean': 'Temp', 'fire': 'Fire' };
  const param = paramMap[parameter] || parameter;
  updateLeftClimateLayer(mapLeft, param, timeStep, fixedScale);
}

export function clearRasterLayer() {
  if (mapLeft) clearLeftClimateLayer(mapLeft);
}

export function triggerResize() {
  setTimeout(() => {
    if (mapLeft) mapLeft.invalidateSize();
    if (mapRight) mapRight.invalidateSize();
  }, 50);
}

export function setTileOpacity(opacity) {
  if (leftTileLayer) leftTileLayer.setOpacity(opacity);
  if (rightTileLayer) rightTileLayer.setOpacity(opacity);
}

export function toggleFireLayer(visible) {
  if (!mapRight || !fireLayerRight) return;
  if (visible) mapRight.addLayer(fireLayerRight);
  else mapRight.removeLayer(fireLayerRight);
}

export function toggleBoundaryLayer(selectedKey, isChecked) {
  if (!mapRight) return;

  if (!isChecked) {
    if (boundaryLayers[selectedKey] && mapRight.hasLayer(boundaryLayers[selectedKey])) {
      mapRight.removeLayer(boundaryLayers[selectedKey]);
    }
    return;
  }

  if (boundaryLayers[selectedKey]) {
    boundaryLayers[selectedKey].addTo(mapRight);
    return;
  }

  fetch(`/api/shapefile/${selectedKey}`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      return res.json();
    })
    .then(geoJsonData => {
      boundaryGeoData[selectedKey] = geoJsonData;

      const layerStyle = (selectedKey === 'PA')
        ? { color: '#22c55e', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.25 }
        : { color: '#38bdf8', weight: 1.2, fillColor: 'transparent' };

      const newLayer = L.geoJSON(geoJsonData, { style: layerStyle });
      boundaryLayers[selectedKey] = newLayer;
      newLayer.addTo(mapRight);
    })
    .catch(err => console.error(`Error loading boundary ${selectedKey}:`, err));
}

/**
 * Extracts property name from shapefile feature properties safely
 */
function getFeatureName(props) {
  if (!props) return "Selected Area";
  return props.NAME_2 || props.NAME_1 || props.NAME_0 || props.nom || props.NAME || props.nam || props.site_name || props.ADM2_EN || "Selected Boundary";
}

/**
 * Utility function to check point in polygon using Leaflet geometry
 */
/*
function findIntersectedFeature(latlng) {
  // Priority order: District shapefile takes precedence over Protected Areas (PA)
  const layerKeys = ['districtMdg', 'PA'];

  for (const key of layerKeys) {
    const geoData = boundaryGeoData[key];
    const layer = boundaryLayers[key];

    if (geoData && mapRight && mapRight.hasLayer(layer)) {
      const point = [latlng.lng, latlng.lat];

      for (const feature of geoData.features) {
        // Wrap feature into temporary Leaflet GeoJSON layer to test containment
        const tempGeoLayer = L.geoJSON(feature);
        const results = leafletPip.gis ? leafletPip.pointInLayer(point, tempGeoLayer) : [];
        
        // Manual fallback check using Leaflet bounds if leafletPip isn't imported
        let isInside = false;
        tempGeoLayer.eachLayer(l => {
          if (l.getBounds && l.getBounds().contains(latlng)) {
            isInside = true;
          }
        });

        if (isInside) {
          return {
            key: key,
            name: getFeatureName(feature.properties),
            geometry: feature.geometry
          };
        }
      }
    }
  }

  return null;
}
*/

export function setupMapClickEvents(mapLeft, mapRight) {
  if (!mapLeft || !mapRight) return;

  const chartDrawer = document.getElementById('chart-container');
  const closeBtn = document.getElementById('close-chart-btn');

  if (closeBtn && chartDrawer) {
    closeBtn.onclick = () => chartDrawer.classList.add('hidden');
  }

  const handleMapClick = (e) => {
    import('./uiManager.js').then(uiModule => {
      if (uiModule.state.currentNav !== 'MON') return;

      const lat = e.latlng.lat.toFixed(4);
      const lon = e.latlng.lng.toFixed(4);

      if (chartDrawer) chartDrawer.classList.remove('hidden');

      // Check if click intersects an active boundary feature (District takes priority over PA)
      const hitFeature = findIntersectedFeature(e.latlng);

      if (hitFeature) {
        // Perform spatial extraction over polygon
        fetch('/api/climate/timeseries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            geometry: hitFeature.geometry,
            name: hitFeature.name
          })
        })
          .then(res => res.json())
          .then(data => {
            if (data.error) return;
            renderOmbrothermicFireChart('chart-plotly-target', data, { name: data.name });
          })
          .catch(err => console.error("Error fetching polygon timeseries:", err));

      } else {
        // Point extraction fallback
        fetch(`/api/climate/timeseries?lat=${lat}&lon=${lon}`)
          .then(res => res.json())
          .then(data => {
            if (data.error) return;
            renderOmbrothermicFireChart('chart-plotly-target', data, { lat, lon, name: data.name });
          })
          .catch(err => console.error("Error fetching point timeseries:", err));
      }
    });
  };

  mapLeft.on('click', handleMapClick);
  mapRight.on('click', handleMapClick);
}

export function loadActiveFires24h() {
  if (!fireLayerRight) return;

  fetch('/api/active-fires-24h')
    .then(res => res.json())
    .then(data => {
      if (!data.fires || !Array.isArray(data.fires)) return;

      fireLayerRight.clearLayers();

      data.fires.forEach(fire => {
        const marker = L.circleMarker([fire.lat, fire.lon], {
          radius: 5,
          fillColor: '#ef4444',
          color: '#f87171',
          weight: 1.5,
          opacity: 1,
          fillOpacity: 0.8
        });

        marker.bindPopup(`
          <div style="font-family: sans-serif; font-size: 11px;">
            <strong style="color: #ef4444;">Active Fire (MODIS 24h)</strong><br/>
            <b>Lat/Lon:</b> ${fire.lat}, ${fire.lon}<br/>
            <b>Date/Time:</b> ${fire.acq_time} UTC<br/>
            <b>Brightness:</b> ${fire.brightness} K<br/>
            <b>Confidence:</b> ${fire.confidence}
          </div>
        `);

        marker.addTo(fireLayerRight);
      });
    })
    .catch(err => console.error("Error loading active fires:", err));
}

/**
 * Custom Ray-Casting Point-in-Polygon check (Native JS, no external libraries needed)
 */
function isPointInPolygon(latlng, feature) {
  if (!feature || !feature.geometry) return false;

  const lat = latlng.lat;
  const lng = latlng.lng;
  const geom = feature.geometry;

  // Extract ring arrays for both Polygon and MultiPolygon
  let polygonRings = [];
  if (geom.type === 'Polygon') {
    polygonRings = [geom.coordinates];
  } else if (geom.type === 'MultiPolygon') {
    polygonRings = geom.coordinates;
  }

  for (const poly of polygonRings) {
    // Outer boundary ring is the first array in poly
    const outerRing = poly[0];
    let inside = false;

    for (let i = 0, j = outerRing.length - 1; i < outerRing.length; j = i++) {
      const xi = outerRing[i][0], yi = outerRing[i][1]; // lon, lat
      const xj = outerRing[j][0], yj = outerRing[j][1]; // lon, lat

      const intersect = ((yi > lat) !== (yj > lat)) &&
        (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);

      if (intersect) inside = !inside;
    }

    if (inside) return true;
  }

  return false;
}

/**
 * Finds the intersected boundary feature on map click
 * District layer takes priority over Protected Areas (PA)
 */
function findIntersectedFeature(latlng) {
  const layerKeys = ['districtMdg', 'PA'];

  for (const key of layerKeys) {
    const geoData = boundaryGeoData[key];
    const layer = boundaryLayers[key];

    // Check if the layer is active on the map
    if (geoData && mapRight && mapRight.hasLayer(layer)) {
      for (const feature of geoData.features) {
        if (isPointInPolygon(latlng, feature)) {
          return {
            key: key,
            name: getFeatureName(feature.properties),
            geometry: feature.geometry
          };
        }
      }
    }
  }

  return null;
}
