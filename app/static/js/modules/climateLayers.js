// static/js/modules/climateLayers.js

let leftClimateOverlay = null;
let leftLegendControl = null;

let rightClimateOverlay = null;
let rightLegendControl = null;
let leftFetchController = null;
let rightFetchController = null;

export function clearLeftClimateLayer(mapLeft) {
  if (leftFetchController) {
    leftFetchController.abort();
    leftFetchController = null;
  }

  if (!mapLeft) return;

  if (leftClimateOverlay) {
    try { mapLeft.removeLayer(leftClimateOverlay); } catch(e){}
    leftClimateOverlay = null;
  }

  mapLeft.eachLayer((layer) => {
    if (layer instanceof L.ImageOverlay) {
      mapLeft.removeLayer(layer);
    }
  });

  if (leftLegendControl) {
    try { mapLeft.removeControl(leftLegendControl); } catch(e){}
    leftLegendControl = null;
  }
}

export function clearRightClimateLayer(mapRight) {
  if (rightFetchController) {
    rightFetchController.abort();
    rightFetchController = null;
  }

  if (!mapRight) return;

  if (rightClimateOverlay) {
    try { mapRight.removeLayer(rightClimateOverlay); } catch(e){}
    rightClimateOverlay = null;
  }

  mapRight.eachLayer((layer) => {
    if (layer instanceof L.ImageOverlay) {
      mapRight.removeLayer(layer);
    }
  });

  if (rightLegendControl) {
    try { mapRight.removeControl(rightLegendControl); } catch(e){}
    rightLegendControl = null;
  }
}

export function updateLeftClimateLayer(mapLeft, parameter, timeStep, fixedScale = false) {
  if (!mapLeft) return;

  if (leftFetchController) {
    leftFetchController.abort();
  }
  leftFetchController = new AbortController();

  const paramMap = { 'rr': 'Rain', 'tmean': 'Temp', 'fire': 'Fire' };
  const param = paramMap[parameter] || parameter;

  const url = `/api/climate/raster?param=${param}&time=${timeStep}&fixed=${fixedScale}`;

  fetch(url, { signal: leftFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      import('./uiManager.js').then(uiModule => {
        if (uiModule.state.currentNav !== 'MON') {
          clearLeftClimateLayer(mapLeft);
          return;
        }

        clearLeftClimateLayer(mapLeft);

        leftClimateOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
          opacity: 0.8,
          interactive: false,
          pane: 'leftClimatePane'
        });
        leftClimateOverlay.addTo(mapLeft);

        leftLegendControl = createLegendControl(data, fixedScale, 'bottomleft');
        leftLegendControl.addTo(mapLeft);
      });
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        console.error("Left map update error:", err);
      }
    });
}

export function updateRightClimateLayer(mapRight, parameter = 'Fire', timeStep, fixedScale = false) {
  if (!mapRight) return;

  if (rightFetchController) {
    rightFetchController.abort();
  }
  rightFetchController = new AbortController();

  const paramMap = { 'rr': 'Rain', 'tmean': 'Temp', 'fire': 'Fire' };
  const param = paramMap[parameter] || parameter;

  const url = `/api/climate/raster?param=${param}&time=${timeStep}&fixed=${fixedScale}`;

  fetch(url, { signal: rightFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      import('./uiManager.js').then(uiModule => {
        if (uiModule.state.currentNav !== 'MON') {
          clearRightClimateLayer(mapRight);
          return;
        }

        clearRightClimateLayer(mapRight);

        rightClimateOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
          opacity: 0.8,
          interactive: false
        });
        rightClimateOverlay.addTo(mapRight);

        rightLegendControl = createLegendControl(data, fixedScale, 'bottomright');
        rightLegendControl.addTo(mapRight);
      });
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        console.error("Right map update error:", err);
      }
    });
}

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