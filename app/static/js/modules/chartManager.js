// static/js/modules/chartManager.js

export function renderOmbrothermicFireChart(containerId, data, meta = {}) {
  const months = data.months;

  // 0. Determine dynamic title based on location type (Polygon vs Point)
  let titleText = meta.name || data.name;
  
  if (!titleText) {
    if (data.point) {
      titleText = `Climatology at (${data.point.lat}°,${data.point.lon}°)`;
    } else {
      titleText = 'Climatology';
    }
  } else if (!titleText.startsWith('Climatology')) {
    titleText = `Climatology: ${titleText}`;
  }

  // 1. Fire Density (Area Trace behind bars)
  const fireTrace = {
    x: months,
    y: data.fire,
    name: 'Fire Counts',
    type: 'scatter',
    mode: 'lines',
    fill: 'tozeroy',
    fillcolor: 'rgba(239, 68, 68, 0.15)',
    line: { color: '#ef4444', width: 1.5, shape: 'spline' },
    yaxis: 'y3'
  };

  // 2. Rainfall (Bar Trace)
  const rainTrace = {
    x: months,
    y: data.rain,
    name: 'Rainfall (mm)',
    type: 'bar',
    marker: {
      color: 'rgba(56, 189, 248, 0.75)',
      line: { color: '#0284c7', width: 1 }
    },
    yaxis: 'y1'
  };

  // 3. Temperature (Line Trace)
  const tempTrace = {
    x: months,
    y: data.temp,
    name: 'Temperature (°C)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#f97316', width: 3, shape: 'spline' },
    marker: { size: 6, color: '#f97316' },
    yaxis: 'y2'
  };

  const layout = {
    title: {
      text: titleText,
      font: { color: '#f8fafc', size: 13 }
    },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { l: 45, r: 50, t: 35, b: 35 },
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
    // Left Y-Axis: Rainfall
    yaxis: {
      title: { text: 'Rain (mm)', font: { color: '#38bdf8', size: 10 } },
      tickfont: { color: '#38bdf8', size: 10 },
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false
    },
    // Right Y-Axis 1: Temperature
    yaxis2: {
      title: { text: 'Temp (°C)', font: { color: '#f97316', size: 10 } },
      tickfont: { color: '#f97316', size: 10 },
      overlaying: 'y',
      side: 'right',
      zeroline: false
    },
    // Right Y-Axis 2: Fire Density (Overlay)
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

  Plotly.newPlot(containerId, [fireTrace, rainTrace, tempTrace], layout, config);
}

