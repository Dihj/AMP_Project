// static/js/modules/fireIndexLayers.js

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

  // Remove stale Leaflet image overlays if any
  mapRight.eachLayer((layer) => {
    if (layer instanceof L.ImageOverlay) {
      mapRight.removeLayer(layer);
    }
  });

  if (rightFireIndexLegendControl) {
    try { mapRight.removeControl(rightFireIndexLegendControl); } catch (e) {}
    rightFireIndexLegendControl = null;
  }
}

/**
 * Creates a Leaflet map legend control for FWI / FOPI
 */
function createFireIndexLegendControl(data, position = 'bottomright') {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'fire-index-legend-box');
    const colors = data.legend.map((item) => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    const firstVal = data.legend[0].value;
    const midVal = data.legend[Math.floor(data.legend.length / 2)].value;
    const lastVal = data.legend[data.legend.length - 1].value;

    const displayTitle = data.title || 'Fire Risk Index';
    const displayUnit = data.unit ? ` (${data.unit})` : '';

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 160px;">
        <div style="font-weight: 600; margin-bottom: 4px; color: #f43f5e;">${displayTitle}${displayUnit}</div>
        <div style="height: 10px; width: 100%; background: ${gradientCss}; border-radius: 2px; margin-bottom: 4px; border: 1px solid rgba(255,255,255,0.2);"></div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;">
          <span>${firstVal}</span>
          <span>${midVal}</span>
          <span>${lastVal}</span>
        </div>
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);
    return div;
  };

  return legendControl;
}

