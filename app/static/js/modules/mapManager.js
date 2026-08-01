// static/js/modules/mapManager.js

let mapLeft = null;
let mapRight = null;
let leftTileLayer = null;
let rightTileLayer = null;
let fireLayerRight = null;

// Add this at the bottom of static/js/modules/mapManager.js

export function getMapLeft() {
  return mapLeft;
}
export function getMapRight() {
    return mapRight;
}

const boundaryLayers = {
  districtMdg: null,
  PA: null
};

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

  // Fire Layer setup
  fireLayerRight = L.layerGroup();
  const mockFirePoints = [[-18.5, 46.5], [-18.9, 47.1], [-19.2, 46.2], [-17.8, 48.1]];
  mockFirePoints.forEach(coords => {
    L.circleMarker(coords, {
      radius: 8, fillColor: '#ef4444', color: '#f87171', weight: 2, opacity: 1, fillOpacity: 0.8
    }).addTo(fireLayerRight);
  });

  if (fireVisible) fireLayerRight.addTo(mapRight);

  // Sync dual maps
  if (typeof mapLeft.sync === 'function') {
    mapLeft.sync(mapRight, { syncCursor: true });
    mapRight.sync(mapLeft, { syncCursor: true });
  }
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
  if (visible) {
    mapRight.addLayer(fireLayerRight);
  } else {
    mapRight.removeLayer(fireLayerRight);
  }
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

  console.log("Fetching boundary layer:", selectedKey);

  fetch(`/api/shapefile/${selectedKey}`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      return res.json();
    })
    .then(geoJsonData => {
      const layerStyle = (selectedKey === 'PA')
        ? { color: '#22c55e', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.25 }
        : { color: '#38bdf8', weight: 1.2, fillColor: 'transparent' };

      const newLayer = L.geoJSON(geoJsonData, { style: layerStyle });

      boundaryLayers[selectedKey] = newLayer;
      newLayer.addTo(mapRight);
    })
    .catch(err => console.error(`Error loading boundary ${selectedKey}:`, err));
}
