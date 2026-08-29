// static/js/modules/mapManager.js

import { renderOmbrothermicFireChart } from './chartManager.js';
import { renderForecastSummaryModal } from './forecastModalManager.js';
import { updateLeftClimateLayer, clearLeftClimateLayer } from './climateLayers.js';

let mapLeft = null;
let mapRight = null;
let leftTileLayer = null;
let rightTileLayer = null;
let fireLayerRight = null;
let adminLinesLeft = null;
let adminLinesRight = null; 

const boundaryLayers = {
  districtMdg: { left: null, right: null },
  PA: { left: null, right: null }
};

const boundaryGeoData = {
  districtMdg: null,
  PA: null
};

export function getMapLeft() { return mapLeft; }
export function getMapRight() { return mapRight; }

function getCartoBasemapKey() {
  const meta = document.querySelector('meta[name="carto-basemap-key"]');
  return meta ? meta.content.trim() : '';
}

function getTileConfig() {
  const cartoKey = getCartoBasemapKey();
  if (cartoKey) {
    const suffix = `{r}.png?key=${encodeURIComponent(cartoKey)}`;
    return {
      dark: {
        url: `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}${suffix}`,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 20
      },
      light: {
        url: `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}${suffix}`,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 20
      }
    };
  }

  return {
    dark: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19
    },
    light: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19
    }
  };
}

function isLightMode() {
  return document.documentElement.classList.contains('light') || 
         document.body.classList.contains('light-mode') || 
         document.documentElement.getAttribute('data-theme') === 'light';
}

export function updateMapTheme() {
  if (!leftTileLayer || !rightTileLayer) return;

  const tileConfig = getTileConfig();
  const nextTiles = isLightMode() ? tileConfig.light : tileConfig.dark;

  leftTileLayer.setUrl(nextTiles.url);
  rightTileLayer.setUrl(nextTiles.url);
  leftTileLayer.options.attribution = nextTiles.attribution;
  rightTileLayer.options.attribution = nextTiles.attribution;
}

export function initMapsOnce(initialOpacity = 0.75, fireVisible = true) {
  const initialCenter = [-18.7, 46.8];
  const initialZoom = 6;

  const tileConfig = getTileConfig();
  const currentTiles = isLightMode() ? tileConfig.light : tileConfig.dark;

  mapLeft = L.map('map-left', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
  leftTileLayer = L.tileLayer(currentTiles.url, {
    maxZoom: currentTiles.maxZoom,
    attribution: currentTiles.attribution,
    opacity: initialOpacity
  }).addTo(mapLeft);

  mapRight = L.map('map-right', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
  rightTileLayer = L.tileLayer(currentTiles.url, {
    maxZoom: currentTiles.maxZoom,
    attribution: currentTiles.attribution,
    opacity: initialOpacity
  }).addTo(mapRight);
  L.control.zoom({ position: 'topright' }).addTo(mapRight);

  // 1. Pane for Climate Rasters (Sits BELOW admin lines)
  mapLeft.createPane('leftClimatePane');
  mapLeft.getPane('leftClimatePane').style.zIndex = 350;
  mapRight.createPane('rightClimatePane');
  mapRight.getPane('rightClimatePane').style.zIndex = 350;

  // 2. Pane for Administrative Overlay Lines & Labels (Sits ABOVE rasters)
  mapLeft.createPane('adminLinesPane');
  mapLeft.getPane('adminLinesPane').style.zIndex = 640;
  mapLeft.getPane('adminLinesPane').style.pointerEvents = 'none';
  
  mapRight.createPane('adminLinesPane'); 
  mapRight.getPane('adminLinesPane').style.zIndex = 640; 
  mapRight.getPane('adminLinesPane').style.pointerEvents = 'none';

  // Pane for active fires
  mapRight.createPane('firePane'); 
  mapRight.getPane('firePane').style.zIndex = 620; 

  // 3. Pane for Selected Interactive Vector Polygons (Sits ABOVE admin lines)
  mapLeft.createPane('topPolygonPane');
  mapLeft.getPane('topPolygonPane').style.zIndex = 650;

  mapRight.createPane('topPolygonPane');
  mapRight.getPane('topPolygonPane').style.zIndex = 650;

  // Load pure visual district boundary lines
  loadDistrictBoundaries();

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

export function setAdminLinesOpacity(opacity) {
  if (adminLinesLeft) adminLinesLeft.setOpacity(opacity);
  if (adminLinesRight) adminLinesRight.setOpacity(opacity);
}

export function toggleAdminLines(visible) {
  if (!mapLeft || !mapRight) return;
  if (visible) {
    if (adminLinesLeft && !mapLeft.hasLayer(adminLinesLeft)) adminLinesLeft.addTo(mapLeft);
    if (adminLinesRight && !mapRight.hasLayer(adminLinesRight)) adminLinesRight.addTo(mapRight);
  } else {
    if (adminLinesLeft && mapLeft.hasLayer(adminLinesLeft)) mapLeft.removeLayer(adminLinesLeft);
    if (adminLinesRight && mapRight.hasLayer(adminLinesRight)) mapRight.removeLayer(adminLinesRight);
  }
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
  if (!mapLeft || !mapRight) return;

  if (!isChecked) {
    if (boundaryLayers[selectedKey].left && mapLeft.hasLayer(boundaryLayers[selectedKey].left)) {
      mapLeft.removeLayer(boundaryLayers[selectedKey].left);
    }
    if (boundaryLayers[selectedKey].right && mapRight.hasLayer(boundaryLayers[selectedKey].right)) {
      mapRight.removeLayer(boundaryLayers[selectedKey].right);
    }
    return;
  }

  if (boundaryLayers[selectedKey].left && boundaryLayers[selectedKey].right) {
    boundaryLayers[selectedKey].left.addTo(mapLeft);
    boundaryLayers[selectedKey].right.addTo(mapRight);
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
        ? { color: '#10b981', weight: 1.5, fillColor: '#10b981', fillOpacity: 0.2 }
        : { color: '#38bdf8', weight: 1.2, fillColor: '#38bdf8', fillOpacity: 0.15 };

      const leftLayer = L.geoJSON(geoJsonData, { 
        style: layerStyle,
        pane: 'topPolygonPane',
        interactive: false
      });

      const rightLayer = L.geoJSON(geoJsonData, { 
        style: layerStyle,
        pane: 'topPolygonPane',
        interactive: false
      });

      boundaryLayers[selectedKey].left = leftLayer;
      boundaryLayers[selectedKey].right = rightLayer;

      leftLayer.addTo(mapLeft);
      rightLayer.addTo(mapRight);
    })
    .catch(err => console.error(`Error loading boundary ${selectedKey}:`, err));
}

function getFeatureName(props) {
  if (!props) return "Selected Area";
  return props.NAME_2 || props.NAME_1 || props.NAME_0 || props.nom || props.NAME || props.nam || props.site_name || props.ADM2_EN || "Selected Boundary";
}

export function setupMapClickEvents(mapLeft, mapRight) {
  if (!mapLeft || !mapRight) return;

  const chartDrawer = document.getElementById('chart-container');
  const closeBtn = document.getElementById('close-chart-btn');

  if (closeBtn && chartDrawer) {
    closeBtn.onclick = () => chartDrawer.classList.add('hidden');
  }

  const handleMapClick = (e) => {
    import('./uiManager.js').then((uiModule) => {
      const currentNav = uiModule.state.currentNav;
      if (currentNav !== 'MON' && currentNav !== 'FOR') return;

      const lat = parseFloat(e.latlng.lat.toFixed(4));
      const lon = parseFloat(e.latlng.lng.toFixed(4));

      const hitFeature = findIntersectedFeature(e.latlng);

      if (currentNav === 'MON') {
        // --- 1. CLIMATOLOGY (MON) -> SHOW COMBINED CHART DRAWER ---
        if (chartDrawer) chartDrawer.classList.remove('hidden');

        if (hitFeature) {
          fetch('/api/climate/timeseries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ geometry: hitFeature.geometry, name: hitFeature.name })
          })
            .then((res) => res.json())
            .then((data) => {
              if (data.error) return;
              renderOmbrothermicFireChart('chart-plotly-target', data, { name: data.name });
            })
            .catch((err) => console.error('Error fetching polygon climate timeseries:', err));
        } else {
          fetch(`/api/climate/timeseries?lat=${lat}&lon=${lon}`)
            .then((res) => res.json())
            .then((data) => {
              if (data.error) return;
              renderOmbrothermicFireChart('chart-plotly-target', data, { lat, lon, name: data.name });
            })
            .catch((err) => console.error('Error fetching point climate timeseries:', err));
        }

      } else if (currentNav === 'FOR') {
        // --- 2. FORECAST (FOR) -> SHOW WIDE MODAL TABLE ---
        const payload = hitFeature
          ? { geometry: hitFeature.geometry, name: hitFeature.name }
          : { lat: lat, lon: lon };

        fetch('/api/forecast/summary', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
          .then((res) => res.json())
          .then((data) => {
            if (data.status !== 'success') {
              console.error('Forecast summary error:', data.error);
              return;
            }
            renderForecastSummaryModal(data, {
              lat: lat,
              lon: lon,
              name: hitFeature ? hitFeature.name : data.name
            });
          })
          .catch((err) => console.error('Error fetching forecast summary:', err));
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
          fillOpacity: 0.8,
          pane: 'firePane'
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
 * Custom Ray-Casting Point-in-Polygon check
 */
function isPointInPolygon(latlng, feature) {
  if (!feature || !feature.geometry) return false;

  const lat = latlng.lat;
  const lng = latlng.lng;
  const geom = feature.geometry;

  let polygonRings = [];
  if (geom.type === 'Polygon') {
    polygonRings = [geom.coordinates];
  } else if (geom.type === 'MultiPolygon') {
    polygonRings = geom.coordinates;
  }

  for (const poly of polygonRings) {
    const outerRing = poly[0];
    let inside = false;

    for (let i = 0, j = outerRing.length - 1; i < outerRing.length; j = i++) {
      const xi = outerRing[i][0], yi = outerRing[i][1];
      const xj = outerRing[j][0], yj = outerRing[j][1];

      const intersect = ((yi > lat) !== (yj > lat)) &&
        (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);

      if (intersect) inside = !inside;
    }

    if (inside) return true;
  }

  return false;
}

/**
 * Checks if a point intersects active boundary features (District priority over PA).
 * Evaluates active state on both mapLeft and mapRight.
 */
function findIntersectedFeature(latlng) {
  const layerKeys = ['districtMdg', 'PA'];

  for (const key of layerKeys) {
    const geoData = boundaryGeoData[key];
    const leftActive = boundaryLayers[key].left && mapLeft.hasLayer(boundaryLayers[key].left);
    const rightActive = boundaryLayers[key].right && mapRight.hasLayer(boundaryLayers[key].right);

    // If boundary layer is active on EITHER left or right map
    if (geoData && (leftActive || rightActive)) {
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

function loadDistrictBoundaries() {
  fetch('/api/shapefile/districtMdg')
    .then(res => {
      if (!res.ok) throw new Error(`Shapefile API error: status ${res.status}`);
      return res.json();
    })
    .then(geojsonData => {
      const visualOnlyStyle = {
        color: '#ffffff',       // Crisp white district lines
        weight: 0.5,            
        opacity: 0.5,           
        fillOpacity: 0.0,       
        interactive: false      
      };

      const leftGeoJson = L.geoJSON(geojsonData, {
        pane: 'adminLinesPane',
        style: visualOnlyStyle,
        interactive: false      
      }).addTo(mapLeft);

      const rightGeoJson = L.geoJSON(geojsonData, {
        pane: 'adminLinesPane',
        style: visualOnlyStyle,
        interactive: false
      }).addTo(mapRight);

      if (leftGeoJson.getElement()) {
        leftGeoJson.getElement().style.pointerEvents = 'none';
      }
      if (rightGeoJson.getElement()) {
        rightGeoJson.getElement().style.pointerEvents = 'none';
      }
    })
    .catch(err => {
      console.error("Failed to load district shapefile boundaries:", err);
    });
}

// Automatic theme change observer (switches tiles when <html> or <body> theme classes change)
const themeObserver = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => {
    if (mutation.attributeName === 'class' || mutation.attributeName === 'data-theme') {
      updateMapTheme();
    }
  });
});

themeObserver.observe(document.documentElement, {
  attributes: true,
  attributeFilter: ['class', 'data-theme']
});


/**
 * Displays a loading overlay over the specified map.
 */
export function showMapLoading(map, message = "Calculating...", color = "#f43f5e") {
  if (!map) return;
  const container = map.getContainer();
  
  // If a loader is already present, just update the text and return
  const existingLoader = container.querySelector('.map-loading-overlay');
  if (existingLoader) {
    existingLoader.querySelector('.loading-text').innerText = message;
    return;
  }

  // Inject CSS for the spinner animation if it doesn't exist
  if (!document.getElementById('spinner-keyframes')) {
    const style = document.createElement('style');
    style.id = 'spinner-keyframes';
    style.innerHTML = '@keyframes leaflet-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }';
    document.head.appendChild(style);
  }

  const overlay = document.createElement('div');
  overlay.className = 'map-loading-overlay';
  
  // Apply inline styles for the blurred overlay
  Object.assign(overlay.style, {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(15, 23, 42, 0.65)',
    backdropFilter: 'blur(4px)',
    zIndex: 9999, // Sit above everything in Leaflet
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'opacity 0.2s ease-in-out'
  });

  overlay.innerHTML = `
    <div style="width: 36px; height: 36px; border: 4px solid rgba(255,255,255,0.2); border-top: 4px solid ${color}; border-radius: 50%; animation: leaflet-spin 1s linear infinite; margin-bottom: 12px;"></div>
    <div class="loading-text" style="color: #f8fafc; font-family: sans-serif; font-size: 13px; font-weight: 600; letter-spacing: 0.5px;">${message}</div>
  `;

  container.appendChild(overlay);
}

/**
 * Removes the loading overlay from the specified map.
 */
export function hideMapLoading(map) {
  if (!map) return;
  const container = map.getContainer();
  const overlay = container.querySelector('.map-loading-overlay');
  if (overlay) {
    container.removeChild(overlay);
  }
}
