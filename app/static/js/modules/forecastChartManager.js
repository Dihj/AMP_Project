// static/js/modules/forecastChartManager.js

/**
 * Renders the 3-day Forecast Summary, NDVI Trend, Active Fire Proximity, FWI, and FOPI
 * @param {string} containerId - Target HTML element ID (e.g. 'chart-plotly-target')
 * @param {Object} data - Forecast timeseries and spatial analysis payload
 * @param {Object} meta - Metadata containing lat/lon or location name
 */
export function renderForecastSummaryChart(containerId, data, meta = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // 1. Build Header & Info Card HTML
  const nameLabel = meta.name || (meta.lat && meta.lon ? `Point (${meta.lat}, ${meta.lon})` : 'Selected Area');
  
  // Calculate NDVI Trend Direction & Color
  const ndviTrend = data.ndvi_trend || 0;
  const ndviBadgeColor = ndviTrend >= 0 ? '#22c55e' : '#ef4444';
  const ndviIcon = ndviTrend >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
  const ndviText = ndviTrend >= 0 ? `+${ndviTrend.toFixed(3)} (Improving/Stable)` : `${ndviTrend.toFixed(3)} (Vegetation Stress)`;

  // Fire Proximity / Containment Summary
  let fireSummaryHtml = '';
  if (data.fire_info) {
    const { active_count, min_distance_km } = data.fire_info;
    if (active_count > 0 && min_distance_km === 0) {
      fireSummaryHtml = `<span style="color: #ef4444; font-weight: bold;"><i class="fa-solid fa-fire-flame-curved"></i> ${active_count} active fire(s) detected directly inside this area!</span>`;
    } else if (min_distance_km !== null && min_distance_km !== undefined) {
      fireSummaryHtml = `<span style="color: #f59e0b;"><i class="fa-solid fa-fire"></i> ${active_count} active fire(s) detected. Nearest fire is ${min_distance_km.toFixed(1)} km away.</span>`;
    } else {
      fireSummaryHtml = `<span style="color: #22c55e;"><i class="fa-solid fa-shield-halved"></i> No active fires within 50 km.</span>`;
    }
  }

  // 2. Insert Summary Info Header
  const summaryHeader = `
    <div style="font-family: sans-serif; color: #f8fafc; padding: 10px 14px; background: #0f172a; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <h4 style="margin: 0; color: #38bdf8; font-size: 14px;"><i class="fa-solid fa-location-dot"></i> ${nameLabel} - 3-Day Forecast</h4>
        <span style="background: ${ndviBadgeColor}22; color: ${ndviBadgeColor}; padding: 2px 8px; border-radius: 12px; font-size: 11px; border: 1px solid ${ndviBadgeColor};">
          <i class="fa-solid ${ndviIcon}"></i> NDVI Δ: ${ndviText}
        </span>
      </div>
      <div style="font-size: 12px; line-height: 1.4;">
        ${fireSummaryHtml}
      </div>
    </div>
    <div id="forecast-plotly-subtarget" style="height: 320px; width: 100%;"></div>
  `;

  container.innerHTML = summaryHeader;

  // 3. Prepare Time Series Data Arrays
  const days = ['Day 0 (Today)', 'Day 1 (Tomorrow)', 'Day 2'];
  const temp = data.temperature || [0, 0, 0];    // °C
  const rawRain = data.rainfall || [0, 0, 0];    // mm
  const rh = data.rh || [0, 0, 0];                // %
  const wind = data.wind || [0, 0, 0];            // m/s
  const fwi = data.fwi || [0, 0, 0];              // Index
  const fopi = data.fopi || [0, 0, 0];            // Probability (0.0 - 1.0)

  // Ensure rainfall is converted to mm if values are still in meters
  const rain = rawRain.map(v => (v < 1.0 && v > 0.0 ? parseFloat((v * 1000).toFixed(2)) : parseFloat(v.toFixed(2))));

  // Traces
  const traceRain = {
    x: days,
    y: rain,
    name: 'Rainfall (mm)',
    type: 'bar',
    marker: { color: '#38bdf8', opacity: 0.6 },
    yaxis: 'y'
  };

  const traceTemp = {
    x: days,
    y: temp,
    name: 'Temp (°C)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#ef4444', width: 2.5 },
    marker: { size: 6 },
    yaxis: 'y2'
  };

  const traceRH = {
    x: days,
    y: rh,
    name: 'RH (%)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#06b6d4', dash: 'dot', width: 2 },
    marker: { size: 5 },
    yaxis: 'y'
  };

  const traceWind = {
    x: days,
    y: wind,
    name: 'Wind (m/s)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#10b981', dash: 'dash', width: 2 },
    marker: { size: 5 },
    yaxis: 'y2'
  };

  const traceFWI = {
    x: days,
    y: fwi,
    name: 'FWI Index',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#f97316', width: 3 },
    marker: { size: 7, symbol: 'diamond' },
    yaxis: 'y2'
  };

  const traceFOPI = {
    x: days,
    y: fopi.map(v => v * 100), // Scale 0-1 probability to 0-100%
    name: 'FOPI Risk (%)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#a855f7', width: 2.5, dash: 'dashdot' },
    marker: { size: 6, symbol: 'square' },
    yaxis: 'y'
  };

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { t: 10, r: 45, l: 45, b: 35 },
    showlegend: true,
    legend: { orientation: 'h', x: 0, y: 1.18, font: { color: '#94a3b8', size: 10 } },
    xaxis: { tickfont: { color: '#cbd5e1' }, gridcolor: '#334155' },
    yaxis: {
      title: 'Rain (mm) / RH (%) / FOPI (%)',
      titlefont: { color: '#38bdf8', size: 10 },
      tickfont: { color: '#cbd5e1' },
      gridcolor: '#334155'
    },
    yaxis2: {
      title: 'Temp (°C) / Wind (m/s) / FWI',
      titlefont: { color: '#ef4444', size: 10 },
      tickfont: { color: '#cbd5e1' },
      overlaying: 'y',
      side: 'right',
      showgrid: false
    }
  };

  Plotly.newPlot(
    'forecast-plotly-subtarget',
    [traceRain, traceTemp, traceRH, traceWind, traceFWI, traceFOPI],
    layout,
    { responsive: true, displayModeBar: false }
  );
}
