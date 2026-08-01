// static/js/modules/climateLayers.js
let leftClimateOverlay = null;
let leftLegendControl = null;
let rightClimateOverlay = null;
let rightLegendControl = null;


// New export to clear the climate layer and legend from mapLeft
export function clearLeftClimateLayer(mapLeft) {
  if (!mapLeft) return;

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
    if (rightClimateOverlay && mapRight.hasLayer(rightClimateOverlay)) {
        mapRight.removeLayer(rightClimateOverlay); 
        rightClimateOverlay = null;
    }
    if (rightLegendControl) {
        mapRight.removeControl(rightLegendControl);
        rightLegendControl = null;
    }
}

export function updateLeftClimateLayer(mapLeft, parameter, timeStep, fixedScale = false) {
  if (!mapLeft) return;

  const url = `/api/climate/raster?param=${parameter}&time=${timeStep}&fixed=${fixedScale}`;

  fetch(url)
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

      renderMapLegend(mapLeft, data, fixedScale);
    })
    .catch(err => {
      console.error("Error loading climate layer on left map:", err);
      clearLeftClimateLayer(mapLeft);
    });
}

// --- RIGHT MAP --- 
export function updateRightClimateLayer(mapRight, parameter, timeStep, fixedScale = false) {
    if (!mapRight) return; 
    const url = '/api/climate/raster?param=${parameter}&time=${timeStep}&fixed=${fixed=${fixedScale}';
    fetch(url)
        .then(res => {
            if (!res.ok) throw new Error('HTTP error! status: ${res.status}');
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
            renderLegend(mapRight, data, fixedScale, 'bottomright', (ctrl) => {rightLegendControl = ctrl; });

        })
        .catch(err => {
            console.error('Error loading right map fire layer', err); 
            clearRightClimateLayer(mapRight);
        });
}
// --- REUSABLE LEGEND RENDERER ---

function renderLegend(mapInstance, data, fixedScale, position, setControlRef) {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'climate-legend-box');
    const colors = data.legend.map(item => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 170px;">
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

  legendControl.addTo(mapInstance);
  setControlRef(legendControl);
}

/*--
function renderMapLegend(mapLeft, data, fixedScale) {
  if (leftLegendControl) {
    mapLeft.removeControl(leftLegendControl);
  }

  leftLegendControl = L.control({ position: 'bottomleft' });

  leftLegendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'climate-legend-box');
    const colors = data.legend.map(item => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 170px;">
        <div style="font-weight: 600; margin-bottom: 4px; color: #38bdf8;">${data.title} (${data.unit})</div>
        <div style="height: 10px; width: 100%; background: ${gradientCss}; border-radius: 2px; margin-bottom: 4px; border: 1px solid rgba(255,255,255,0.2);"></div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8; margin-bottom: 6px;">
          <span>${data.legend[0].value}</span>
          <span>${data.legend[Math.floor(data.legend.length / 2)].value}</span>
          <span>${data.legend[data.legend.length - 1].value}</span>
        </div>
        <label style="display: flex; align-items: center; gap: 6px; font-size: 10px; color: #cbd5e1; cursor: pointer; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
          <input type="checkbox" id="map-legend-fixed-toggle" ${fixedScale ? 'checked' : ''} style="cursor: pointer;">
          <span>Fix annual min/max</span>
        </label>
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);

    div.querySelector('#map-legend-fixed-toggle').addEventListener('change', (e) => {
      import('./uiManager.js').then(module => {
        module.state.fixedScale = e.target.checked;
        module.renderUI();
      });
    });

    return div;
  };

  leftLegendControl.addTo(mapLeft);
  setControlRef(legendControl);

  
} --*/
