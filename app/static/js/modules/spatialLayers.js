// static/js/modules/spatialLayers.js

const boundaryLayers = {
  districtMdg: null,
  PA: null
};

export function toggleBoundaryLayer(mapRight, selectedKey, isChecked) {
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
      const layerStyle = (selectedKey === 'PA')
        ? { color: '#22c55e', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.25 }
        : { color: '#38bdf8', weight: 1.2, fillColor: 'transparent' };

      const newLayer = L.geoJSON(geoJsonData, { style: layerStyle });
      boundaryLayers[selectedKey] = newLayer;
      newLayer.addTo(mapRight);
    })
    .catch(err => console.error(`Error loading boundary ${selectedKey}:`, err));
}