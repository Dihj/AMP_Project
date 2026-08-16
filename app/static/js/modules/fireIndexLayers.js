// static/js/modules/fireIndexLayers.js
// import { getMapRight } from './mapManager.js';
import { getMapRight, showMapLoading, hideMapLoading } from './mapManager.js';

let rightFireIndexOverlay = null;
let rightFireIndexLegendControl = null;
let fireIndexFetchController = null;

/**
 * Updates the right Leaflet map panel with FWI or FOPI forecast plots
 * @param {L.Map} mapRight - Leaflet map handle for the right container
 * @param {string} indexType - 'fwi' or 'fopi'
 * @param {number} dayNum - Integer day forecast step (0, 1, 2)
 */

/**
export function updateRightFireIndexLayer(mapRight, indexType = 'fwi', dayNum = 0) {
  if (!mapRight) return;

  if (mapRight !== getMapRight()) {
    console.error(
      '[FireIndexLayer] BLOCKED: updateRightFireIndexLayer() was called with ' +
      'a map instance that is not the registered RIGHT map. FWI/FOPI must ' +
      'only render on the right map - refusing to render.'
    );
    return;
  }

  // Abort any ongoing request to prevent race conditions
  if (fireIndexFetchController) {
    fireIndexFetchController.abort();
  }
  fireIndexFetchController = new AbortController();

  const url = `/api/fire-indices/plot?index=${encodeURIComponent(indexType)}&day=${dayNum}`;

  fetch(url, { signal: fireIndexFetchController.signal })
    .then((res) => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then((data) => {
      if (data.status !== 'success' || !data.imageUrl || !data.bounds) {
        console.error('Error fetching Fire Index plot:', data.error || 'Invalid payload');
        return;
      }

      // Clear existing layer & legend
      clearRightFireIndexLayer(mapRight);

      // Add image overlay
      rightFireIndexOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
        opacity: 0.8,
        interactive: false,
        zIndex: 400
      }).addTo(mapRight);

      // Render & attach dynamic legend control if data.legend is returned by backend
      if (data.legend && Array.isArray(data.legend) && data.legend.length > 0) {
        rightFireIndexLegendControl = createFireIndexLegendControl(data, 'bottomright');
        rightFireIndexLegendControl.addTo(mapRight);
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        console.error('Failed to load Fire Index layer:', err);
      }
    });
}

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

  // 2. SHOW THE LOADER BEFORE FETCHING
  // Using a red/rose color to match the fire theme
  showMapLoading(mapRight, `Calculating ${indexType.toUpperCase()} (Day ${dayNum})...`, '#f43f5e');

  const url = `/api/fire-indices/plot?index=${encodeURIComponent(indexType)}&day=${dayNum}`;

  fetch(url, { signal: fireIndexFetchController.signal })
    .then((res) => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then((data) => {
      // 3. HIDE THE LOADER ON SUCCESS
      hideMapLoading(mapRight);

      if (data.status !== 'success' || !data.imageUrl || !data.bounds) {
        console.error('Error fetching Fire Index plot:', data.error || 'Invalid payload');
        return;
      }

      clearRightFireIndexLayer(mapRight);

      rightFireIndexOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
        opacity: 0.8,
        interactive: false,
        zIndex: 400
      }).addTo(mapRight);

      if (data.legend && Array.isArray(data.legend) && data.legend.length > 0) {
        rightFireIndexLegendControl = createFireIndexLegendControl(data, 'bottomright');
        rightFireIndexLegendControl.addTo(mapRight);
      }
    })
    .catch((err) => {
      // 4. HIDE THE LOADER ON ERROR (Unless it was aborted by clicking a new day)
      if (err.name !== 'AbortError') {
        hideMapLoading(mapRight);
        console.error('Failed to load Fire Index layer:', err);
      }

    });
}


/**
 * Clears the active Fire Index layer and legend from the right map panel
 */
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

    const displayTitle = data.title || 'Indices des risques du feux';
    const displayUnit = data.unit ? ` (${data.unit})` : '';

    const rowsHtml = data.legend.map((item) => `
      <div style="display: flex; align-items: center; gap: 6px; margin-top: 3px;">
        <span style="width: 14px; height: 14px; flex-shrink: 0; border-radius: 3px; background: ${item.color}; border: 1px solid rgba(255,255,255,0.25);"></span>
        <span style="font-size: 10px; color: #e2e8f0;">${item.value}</span>
      </div>
    `).join('');

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 160px;">
        <div style="font-weight: 600; margin-bottom: 2px; color: #f43f5e;">${displayTitle}${displayUnit}</div>
        ${rowsHtml}
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);
    return div;
  };

  return legendControl;
}
