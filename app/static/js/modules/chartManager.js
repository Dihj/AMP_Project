// static/js/modules/chartManager.js

/**
 * Exports the complete chart modal as a high-resolution PNG using html2canvas
 */
function downloadChartAsPNG(titleText) {
  const modalElem = document.getElementById('chart-container');
  if (!modalElem) return;

  const downloadBtn = document.getElementById('download-chart-btn');
  const originalBtnContent = downloadBtn ? downloadBtn.innerHTML : '';

  if (downloadBtn) {
    downloadBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    downloadBtn.disabled = true;
  }

  if (typeof html2canvas === 'undefined') {
    alert('html2canvas library is missing. Ensure it is included in your base HTML script tags.');
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }
    return;
  }

  html2canvas(modalElem, {
    backgroundColor: '#0f172a', // Matches slate-900 background
    useCORS: true,
    scale: 2, // High resolution capture
    logging: false
  }).then(canvas => {
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }

    const link = document.createElement('a');
    const sanitizedTitle = (titleText || 'climatology_chart').replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const timeStamp = new Date().toISOString().slice(0, 10);

    link.download = `${sanitizedTitle}_${timeStamp}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }).catch(err => {
    console.error('[Export Error] Failed to capture chart as PNG:', err);
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }
  });
}

export function renderOmbrothermicFireChart(containerId, data, meta = {}) {
  const months = data.months;

  // 1. Determine title text for the HTML Modal Header
  let titleText = meta.name || data.name;
  if (!titleText) {
    if (data.point) {
      titleText = `Climatologie (${data.point.lat}°, ${data.point.lon}°)`;
    } else {
      titleText = 'Aperçu de la climatologie';
    }
  }

  // Update HTML header text
  const headerTitleEl = document.getElementById('chart-modal-title');
  if (headerTitleEl) {
    headerTitleEl.textContent = titleText;
  }

  // Attach PNG download event listener
  const downloadBtn = document.getElementById('download-chart-btn');
  if (downloadBtn) {
    downloadBtn.onclick = () => downloadChartAsPNG(titleText);
  }

  // 2. Traces
  const fireTrace = {
    x: months,
    y: data.fire,
    name: 'Feux',
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
    name: 'Precipitations (mm)',
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
    name: 'Temperature (°C)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#f97316', width: 2.5, shape: 'spline' },
    marker: { size: 5, color: '#f97316' },
    yaxis: 'y2'
  };

  // 3. Layout
  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { l: 40, r: 45, t: 15, b: 30 },
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
      title: { text: 'Precipitation (mm)', font: { color: '#38bdf8', size: 10 } },
      tickfont: { color: '#38bdf8', size: 10 },
      gridcolor: 'rgba(255, 255, 255, 0.05)',
      zeroline: false
    },
    yaxis2: {
      title: { text: 'Temperature (°C)', font: { color: '#f97316', size: 10 } },
      tickfont: { color: '#f97316', size: 10 },
      overlaying: 'y',
      side: 'right',
      zeroline: false
    },
    yaxis3: {
      title: { text: 'Feux/parcelle', font: { color: '#ef4444', size: 10 } },
      tickfont: { color: '#ef4444', size: 10 },
      overlaying: 'y',
      side: 'right',
      position: 0.95,
      showgrid: false,
      zeroline: false
    }, 
    hovermode: 'x unified'
  };

  const config = { responsive: true, displayModeBar: false };

  Plotly.newPlot('chart-plotly-target', [fireTrace, rainTrace, tempTrace], layout, config);
}

