// static/js/modules/fireIndexLayers.js
import { getMapRight, showMapLoading, hideMapLoading } from './mapManager.js';
import { formatLegendTitle, formatLegendUnit } from './legendUtils.js';

let rightFireIndexOverlay = null;
let rightFireIndexLegendControl = null;
let fireIndexFetchController = null;

/**
 * Updates the right Leaflet map panel with FWI or FOPI forecast plots
 * @param {L.Map} mapRight - Leaflet map handle for the right container
 * @param {string} indexType - 'fwi' or 'fopi'
 * @param {number} dayNum - Integer day forecast step (0, 1, 2)
 */

export function updateRightFireIndexLayer(mapRight, indexType = 'fwi', dayNum = 0) {
  if (!mapRight) return;
  if (mapRight !== getMapRight()) {
    console.error('[FireIndexLayer] BLOCKED...');
    return;
  }

  if (fireIndexFetchController) {
    fireIndexFetchController.abort();
  }
  fireIndexFetchController = new AbortController();

  showMapLoading(mapRight, `Calculating ${indexType.toUpperCase()} (Day ${dayNum})...`, '#f43f5e');

  const url = `/api/fire-indices/plot?index=${encodeURIComponent(indexType)}&day=${dayNum}`;

  fetch(url, { signal: fireIndexFetchController.signal })
    .then((res) => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then((data) => {

      hideMapLoading(mapRight);

      if (data.status !== 'success' || !data.imageUrl || !data.bounds) {
        console.error('Error fetching Fire Index plot:', data.error || 'Invalid payload');
        return;
      }

      clearRightFireIndexLayer(mapRight);

      rightFireIndexOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
        opacity: 0.8,
        interactive: false,
        zIndex: 400,
        className: 'amp-raster-overlay'
      }).addTo(mapRight);

      if (data.legend && Array.isArray(data.legend) && data.legend.length > 0) {
        rightFireIndexLegendControl = createFireIndexLegendControl(data, 'bottomright');
        rightFireIndexLegendControl.addTo(mapRight);
      }
    })
    .catch((err) => {

      if (err.name !== 'AbortError') {
        hideMapLoading(mapRight);
        console.error('Failed to load Fire Index layer:', err);
      }

    });
}

export function clearRightFireIndexLayer(mapRight) {
  if (fireIndexFetchController) {
    fireIndexFetchController.abort();
    fireIndexFetchController = null;
  }

  if (!mapRight) return;

  if (rightFireIndexOverlay) {
    try { mapRight.removeLayer(rightFireIndexOverlay); } catch (e) {}
    rightFireIndexOverlay = null;
  }


  if (rightFireIndexLegendControl) {
    try { mapRight.removeControl(rightFireIndexLegendControl); } catch (e) {}
    rightFireIndexLegendControl = null;
  }
}


function createFireIndexLegendControl(data, position = 'bottomright') {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'fire-index-legend-box');

    const displayTitle = formatLegendTitle(data, 'Indices de risque de feu');
    const displayUnit = formatLegendUnit(data.unit);

    const rowsHtml = data.legend.map((item) => `
      <div class="map-legend-row">
        <span class="map-legend-swatch" style="background: ${item.color};"></span>
        <span>${item.value}</span>
      </div>
    `).join('');

    div.innerHTML = `
      <div class="map-legend-panel" style="--map-legend-accent: #f43f5e;">
        <div class="map-legend-title">${displayTitle}${displayUnit}</div>
        ${rowsHtml}
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);
    return div;
  };

  return legendControl;
}
