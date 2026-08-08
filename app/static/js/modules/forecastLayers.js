// static/js/modules/forecastLayers.js

let leftForecastOverlay = null;
let leftForecastLegendControl = null;

let rightForecastOverlay = null;
let rightForecastLegendControl = null;

let leftForecastFetchController = null;
let rightForecastFetchController = null;

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

  mapLeft.eachLayer((layer) => {
    if (layer instanceof L.ImageOverlay) {
      mapLeft.removeLayer(layer);
    }
  });

  if (leftForecastLegendControl) {
    try { mapLeft.removeControl(leftForecastLegendControl); } catch (e) {}
    leftForecastLegendControl = null;
  }
}

export function clearRightForecastLayer(mapRight) {
  if (rightForecastFetchController) {
    rightForecastFetchController.abort();
    rightForecastFetchController = null;
  }

  if (!mapRight) return;

  if (rightForecastOverlay) {
    try { mapRight.removeLayer(rightForecastOverlay); } catch (e) {}
    rightForecastOverlay = null;
  }

  mapRight.eachLayer((layer) => {
    if (layer instanceof L.ImageOverlay) {
      mapRight.removeLayer(layer);
    }
  });

  if (rightForecastLegendControl) {
    try { mapRight.removeControl(rightForecastLegendControl); } catch (e) {}
    rightForecastLegendControl = null;
  }
}

export function updateLeftForecastLayer(mapLeft, parameter = 'temp', day = 0) {
  if (!mapLeft) return;

  if (leftForecastFetchController) {
    leftForecastFetchController.abort();
  }
  leftForecastFetchController = new AbortController();

  //const paramMap = { 'Temp': 'temp', 'Rain': 'rr', 'RH': 'rh', 'Wind': 'wind' };
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

  const url = `/api/forecast/plot?variable=${param}&day=${day}`;

  fetch(url, { signal: leftForecastFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`Forecast server status ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      import('./uiManager.js').then(uiModule => {
        if (uiModule.state.currentNav !== 'FOR') {
          clearLeftForecastLayer(mapLeft);
          return;
        }

        clearLeftForecastLayer(mapLeft);

        leftForecastOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
          opacity: 0.8,
          interactive: false,
          zIndex: 400
        });
        leftForecastOverlay.addTo(mapLeft);

        leftForecastLegendControl = createForecastLegendControl(data, 'bottomleft');
        leftForecastLegendControl.addTo(mapLeft);
      });
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        console.error("Left map forecast update error:", err);
      }
    });
}

export function updateRightForecastLayer(mapRight, parameter = 'temp', day = 0) {
  if (!mapRight) return;

  if (rightForecastFetchController) {
    rightForecastFetchController.abort();
  }
  rightForecastFetchController = new AbortController();

  const paramMap = { 'Temp': 'temp', 'Rain': 'rr', 'RH': 'rh', 'Wind': 'wind' };
  const param = paramMap[parameter] || parameter;

  const url = `/api/forecast/plot?variable=${param}&day=${day}`;

  fetch(url, { signal: rightForecastFetchController.signal })
    .then(res => {
      if (!res.ok) throw new Error(`Forecast server status ${res.status}`);
      return res.json();
    })
    .then(data => {
      if (!data.imageUrl || !data.bounds) return;

      import('./uiManager.js').then(uiModule => {
        if (uiModule.state.currentNav !== 'FOR') {
          clearRightForecastLayer(mapRight);
          return;
        }

        clearRightForecastLayer(mapRight);

        rightForecastOverlay = L.imageOverlay(data.imageUrl, data.bounds, {
          opacity: 0.8,
          interactive: false,
          zIndex: 400
        });
        rightForecastOverlay.addTo(mapRight);

        rightForecastLegendControl = createForecastLegendControl(data, 'bottomright');
        rightForecastLegendControl.addTo(mapRight);
      });
    })
    .catch(err => {
      if (err.name !== 'AbortError') {
        console.error("Right map forecast update error:", err);
      }
    });
}

function createForecastLegendControl(data, position) {
  const legendControl = L.control({ position: position });

  legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'forecast-legend-box');
    const colors = data.legend.map(item => item.color).join(', ');
    const gradientCss = `linear-gradient(to right, ${colors})`;

    div.innerHTML = `
      <div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(4px); padding: 8px 12px; border-radius: 6px; color: #f8fafc; font-family: sans-serif; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); min-width: 160px;">
        <div style="font-weight: 600; margin-bottom: 4px; color: #38bdf8;">${data.title} (${data.unit})</div>
        <div style="height: 10px; width: 100%; background: ${gradientCss}; border-radius: 2px; margin-bottom: 4px; border: 1px solid rgba(255,255,255,0.2);"></div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;">
          <span>${data.legend[0].value}</span>
          <span>${data.legend[Math.floor(data.legend.length / 2)].value}</span>
          <span>${data.legend[data.legend.length - 1].value}</span>
        </div>
      </div>
    `;

    L.DomEvent.disableClickPropagation(div);
    return div;
  };

  return legendControl;
}

