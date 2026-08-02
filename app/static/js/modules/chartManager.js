// static/js/modules/chartManager.js

export function renderOmbrothermicFireChart(containerId, data, meta = {}) {
  const months = data.months;

  // 1. Determine title text for the HTML Modal Header
  let titleText = meta.name || data.name;
  if (!titleText) {
    if (data.point) {
      titleText = `Climatology (${data.point.lat}°, ${data.point.lon}°)`;
    } else {
      titleText = 'Climatology Overview';
    }
  }

  // Update HTML header text directly
  const headerTitleEl = document.getElementById('chart-modal-title');
  if (headerTitleEl) {
    headerTitleEl.textContent = titleText;
  }

  // 2. Traces
  const fireTrace = {
    x: months,
    y: data.fire,
    name: 'Fires',
    type: 'scatter',
    mode: 'lines',
    fill: 'tozeroy',
    fillcolor: 'rgba(239, 68, 68, 0.15)',
    line: { color: '#ef4444', width: 1.5, shape: 'spline' },
    yaxis: 'y3'
  };

  const rainTrace = {
    x: months,
    y: data.rain,
    name: 'Rain (mm)',
    type: 'bar',
    marker: {
      color: 'rgba(56, 189, 248, 0.75)',
      line: { color: '#0284c7', width: 1 }
    },
    yaxis: 'y1'
  };

  const tempTrace = {
    x: months,
    y: data.temp,
    name: 'Temp (°C)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#f97316', width: 2.5, shape: 'spline' },
    marker: { size: 5, color: '#f97316' },
    yaxis: 'y2'
  };

  // 3. Layout (Notice: title is omitted here to let HTML header manage it)
  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { l: 40, r: 45, t: 15, b: 30 }, // Tight margins so plot fills space
    legend: {
      orientation: 'h',
      x: 0,
      y: 1.15,
      font: { color: '#94a3b8', size: 10 }
    },
    xaxis: {
      tickfont: { color: '#cbd5e1', size: 10 },
      gridcolor: 'rgba(255, 255, 255, 0.05)'
    },
    yaxis: {
      title: { text: 'Rain (mm)', font: { color: '#38bdf8', size: 10 } },
      tickfont: { color: '#38bdf8', size: 10 },
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false
    },
    yaxis2: {
      title: { text: 'Temp (°C)', font: { color: '#f97316', size: 10 } },
      tickfont: { color: '#f97316', size: 10 },
      overlaying: 'y',
      side: 'right',
      zeroline: false
    },
    yaxis3: {
      title: { text: 'Fires/cell', font: { color: '#ef4444', size: 10 } },
      tickfont: { color: '#ef4444', size: 10 },
      overlaying: 'y',
      side: 'right',
      position: 0.95,
      showgrid: false,
      zeroline: false
    }
  };

  const config = { responsive: true, displayModeBar: false };

  Plotly.newPlot('chart-plotly-target', [fireTrace, rainTrace, tempTrace], layout, config);
}
