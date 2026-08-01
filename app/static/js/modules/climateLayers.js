// static/js/modules/climateLayers.js

let leftClimateOverlay = null;
let leftLegendControl = null;
let leftFetchController = null; // Controller for Left Map

let rightClimateOverlay = null;
let rightLegendControl = null;
let rightFetchController = null; // Controller for Right Map

// --- CLEAR FUNCTIONS ---

export function clearLeftClimateLayer(mapLeft) {
  if (!mapLeft) return;
  if (leftFetchController) leftFetchController.abort();

  if (leftClimateOverlay && mapLeft.hasLayer(leftClimateOverlay)) {
    mapLeft.removeLayer(leftClimateOverlay);
    leftClimateOverlay = null;
  }
  if (leftLegendControl) {
    mapLeft.removeControl(leftLegendControl);
    leftLegendControl = null;
  }
}

export function clearRightClimateLayer(mapRight) {
  if (!mapRight) return;
  if (rightFetchController) rightFetchController.abort();

  if (rightClimateOverlay && mapRight.hasLayer(rightClimateOverlay)) {
    mapRight.removeLayer(rightClimateOverlay);
    rightClimateOverlay = null;
  }
  if (rightLegendControl) {
    mapRight.removeControl(rightLegendControl);
    rightLegendControl = null;
  }
}

// --- LEFT MAP (Temperature / Rainfall) ---

export function updateLeftClimateLayer(mapLeft, parameter, timeStep, fixedScale = false) {
  if (!mapLeft) return;

  // Abort previous in-flight fetch request
  if (leftFetchController) {
    leftFetchController.abort();
  }
  leftFetchController = new AbortController();

  const url = `/api/climate/raster?param=${parameter}&time=${timeStep}&fixed=${fixedScale}`;

  fetch(url, { signal: leftFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      if (leftClimateOverlay && mapLeft.hasLayer(leftClimateOverlay)) {
        mapLeft.removeLayer(leftClimateOverlay);
      }

      leftClimateOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
        opacity: 0.8,
        interactive: false
      });
      leftClimateOverlay.addTo(mapLeft);

      if (leftLegendControl) {
        mapLeft.removeControl(leftLegendControl);
        leftLegendControl = null;
      }

      leftLegendControl = createLegendControl(data, fixedScale, 'bottomleft');
      leftLegendControl.addTo(mapLeft);
    })
    .catch(err => {
      if (err.name === 'AbortError') return; // Ignore intentionally aborted requests
      console.error("Error updating left map climate layer:", err);
      clearLeftClimateLayer(mapLeft);
    });
}

// --- RIGHT MAP (Active Fire Climatology) ---

export function updateRightClimateLayer(mapRight, parameter = 'Fire', timeStep, fixedScale = false) {
  if (!mapRight) return;

  // Abort previous in-flight fetch request
  if (rightFetchController) {
    rightFetchController.abort();
  }
  rightFetchController = new AbortController();

  const url = `/api/climate/raster?param=${parameter}&time=${timeStep}&fixed=${fixedScale}`;

  fetch(url, { signal: rightFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      if (rightClimateOverlay && mapRight.hasLayer(rightClimateOverlay)) {
        mapRight.removeLayer(rightClimateOverlay);
      }

      rightClimateOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
        opacity: 0.8,
        interactive: false
      });
      rightClimateOverlay.addTo(mapRight);

      if (rightLegendControl) {
        mapRight.removeControl(rightLegendControl);
        rightLegendControl = null;
      }

      rightLegendControl = createLegendControl(data, fixedScale, 'bottomright');
      rightLegendControl.addTo(mapRight);
    })
    .catch(err => {
      if (err.name === 'AbortError') return; // Ignore intentionally aborted requests
      console.error("Error updating right map fire layer:", err);
      clearRightClimateLayer(mapRight);
    });
}

// --- LEGEND CONTROL BUILDER ---

function createLegendControl(data, fixedScale, position) {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'climate-legend-box');
    const colors = data.legend.map(item => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 160px;">
        <div style="font-weight: 600; margin-bottom: 4px; color: #38bdf8;">${data.title} (${data.unit})</div>
        <div style="height: 10px; width: 100%; background: ${gradientCss}; border-radius: 2px; margin-bottom: 4px; border: 1px solid rgba(255,255,255,0.2);"></div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8; margin-bottom: 6px;">
          <span>${data.legend[0].value}</span>
          <span>${data.legend[Math.floor(data.legend.length / 2)].value}</span>
          <span>${data.legend[data.legend.length - 1].value}</span>
        </div>
        <label style="display: flex; align-items: center; gap: 6px; font-size: 10px; color: #cbd5e1; cursor: pointer; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
          <input type="checkbox" class="map-legend-fixed-toggle" ${fixedScale ? 'checked' : ''} style="cursor: pointer;">
          <span>Fix annual min/max</span>
        </label>
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);

    div.querySelector('.map-legend-fixed-toggle').addEventListener('change', (e) => {
      import('./uiManager.js').then(module => {
        module.state.fixedScale = e.target.checked;
        module.renderUI();
      });
    });

    return div;
  };

  return legendControl;
}
