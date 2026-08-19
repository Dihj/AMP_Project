// static/js/modules/forecastLayers.js
import { getMapLeft, getMapRight, showMapLoading, hideMapLoading } from './mapManager.js';

let leftForecastOverlay = null;
let leftForecastLegendControl = null;

let leftForecastFetchController = null;

export function clearLeftForecastLayer(mapLeft) {
  if (leftForecastFetchController) {
    leftForecastFetchController.abort();
    leftForecastFetchController = null;
  }

  if (!mapLeft) return;

  if (leftForecastOverlay) {
    try { mapLeft.removeLayer(leftForecastOverlay); } catch (e) {}
    leftForecastOverlay = null;
  }


  if (leftForecastLegendControl) {
    try { mapLeft.removeControl(leftForecastLegendControl); } catch (e) {}
    leftForecastLegendControl = null;
  }
}


export function clearRightForecastLayer(mapRight) {
  console.warn(
    '[ForecastLayer] clearRightForecastLayer() called, but the right map ' +
    'never hosts a weather overlay by design - this is a no-op. If you ' +
    'expected this to do something, the caller should be using ' +
    'fireIndexLayers.js instead.'
  );
}

export function updateLeftForecastLayer(mapLeft, parameter = 'temp', day = 0) {
  if (!mapLeft) return;

  if (mapLeft !== getMapLeft()) {
    console.error(
      '[ForecastLayer] BLOCKED: updateLeftForecastLayer() was called with a ' +
      'map instance that is not the registered LEFT map. Weather/NDVI must ' +
      'only render on the left map - refusing to render.'
    );
    return;
  }

  console.log('[ForecastLayer:LEFT] called with parameter=', parameter, 'day=', day);

  if (leftForecastFetchController) {
    leftForecastFetchController.abort();
  }
  leftForecastFetchController = new AbortController();

  let url = '';
  if (parameter === 'NDVI' || parameter === 'ndvi') {
    url = `/api/ndvi/plot`;
  } else {
    const paramMap = {
      'Temp': 'temp_c',
      'temp': 'temp_c',
      'Rain': 'precipitation_surface',
      'rr': 'precipitation_surface',
      'RH': 'relative_humidity',
      'rh': 'relative_humidity',
      'Wind': 'wind_speed_10m',
      'wind': 'wind_speed_10m'
    };
    const param = paramMap[parameter] || parameter;
    url = `/api/forecast/plot?variable=${param}&day=${day}`;
  }
  console.log('[ForecastLayer:LEFT] fetching URL:', url);

  showMapLoading(mapLeft, 'Loading...', '#38bdf8');


  fetch(url, { signal: leftForecastFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`Server status ${res.status}`);
      return res.json();
    })
    .then(data => {
      hideMapLoading(mapLeft);
      if (data.status && data.status !== 'success') {
        console.error(`[Forecast Layer] Backend error for ${url}:`, data.error || data);
        return;
      }
      if (!data.imageUrl || !data.bounds) {
        console.warn(`[Forecast Layer] Response missing imageUrl/bounds for ${url}:`, data);
        return;
      }
      console.log('[ForecastLayer:LEFT] SUCCESS for', url, '- bounds=', data.bounds, 'imageUrl length=', data.imageUrl.length, 'legend=', data.legend);

      import('./uiManager.js').then(uiModule => {
        console.log('[ForecastLayer:LEFT] currentNav=', uiModule.state.currentNav);
        if (uiModule.state.currentNav !== 'FOR') {
          console.log('[ForecastLayer:LEFT] SKIPPING render - currentNav is not FOR');
          clearLeftForecastLayer(mapLeft);
          return;
        }

        clearLeftForecastLayer(mapLeft);

        // Ensure left raster pane exists
        if (!mapLeft.getPane('leftClimatePane')) {
          mapLeft.createPane('leftClimatePane');
          mapLeft.getPane('leftClimatePane').style.zIndex = 350;
        }

        // Render overlay in background pane (z-index: 350)
        leftForecastOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
          opacity: 0.8,
          interactive: false,
          pane: 'leftClimatePane'
        });
        leftForecastOverlay.addTo(mapLeft);
        console.log('[ForecastLayer:LEFT] overlay added to map for', url);

        if (data.legend && Array.isArray(data.legend) && data.legend.length > 0) {
          leftForecastLegendControl = createForecastLegendControl(data, 'bottomleft');
          leftForecastLegendControl.addTo(mapLeft);
        }
      });
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        console.error("Left map forecast update error:", err);
      }
    });
}


export function updateRightForecastLayer(mapRight, parameter = 'temp', day = 0) {
  console.error(
    `[ForecastLayer] BLOCKED: updateRightForecastLayer(parameter=${parameter}, day=${day}) ` +
    'was called, but the right map is reserved exclusively for fire indices ' +
    '(FWI/FOPI). Weather/NDVI parameters belong on the LEFT map only - use ' +
    'updateLeftForecastLayer() there, and updateRightFireIndexLayer() from ' +
    'fireIndexLayers.js for the right map. Find and fix this call site.'
  );
}

function createForecastLegendControl(data, position) {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'forecast-legend-box');
    const colors = data.legend.map(item => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    const firstVal = data.legend[0].value;
    const midVal = data.legend[Math.floor(data.legend.length / 2)].value;
    const lastVal = data.legend[data.legend.length - 1].value;

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 160px;">
        <div style="font-weight: 600; margin-bottom: 4px; color: #38bdf8;">${data.title} (${data.unit})</div>
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
