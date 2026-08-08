// static/js/modules/forecastModalManager.js

let modalContainer = null;
let isDragging = false;
let currentX, currentY, initialX, initialY;
let xOffset = 0, yOffset = 0;

/**
 * Helper: Classifies FWI numerical values into text risk levels & colors
 */
function getFWILevel(val) {
  if (val < 5.0) return { label: 'Low', color: '#22c55e' };
  if (val < 11.0) return { label: 'Moderate', color: '#eab308' };
  if (val < 19.0) return { label: 'High', color: '#f97316' };
  if (val < 30.0) return { label: 'Very High', color: '#ef4444' };
  if (val < 50.0) return { label: 'Extreme', color: '#a855f7' };
  return { label: 'Extreme+', color: '#ec4899' };
}

/**
 * Helper: Classifies FOPI numerical values into text risk levels & colors
 */
function getFOPILevel(val) {
  const norm = val > 1.0 ? val / 100.0 : val;
  if (norm < 0.2) return { label: 'Low', color: '#22c55e', val: norm };
  if (norm < 0.4) return { label: 'Moderate', color: '#eab308', val: norm };
  if (norm < 0.6) return { label: 'High', color: '#f97316', val: norm };
  if (norm < 0.8) return { label: 'Very High', color: '#ef4444', val: norm };
  return { label: 'Extreme', color: '#a855f7', val: norm };
}

/**
 * Renders Plotly.js Gauge Barometer with extra padding for labels & title
 */
function renderPlotlyGauges(fwiSeries, fopiSeries, selectedDay = 0) {
  const fwiVal = fwiSeries[selectedDay] || 0;
  const rawFopiVal = fopiSeries[selectedDay] || 0;
  
  const fwiInfo = getFWILevel(fwiVal);
  const fopiInfo = getFOPILevel(rawFopiVal);

  const prevFwi = selectedDay > 0 ? fwiSeries[selectedDay - 1] : fwiVal;
  const prevFopi = selectedDay > 0 ? getFOPILevel(fopiSeries[selectedDay - 1]).val : fopiInfo.val;

  const fwiData = [{
    type: "indicator",
    mode: "gauge+number+delta",
    value: fwiVal,
    title: { 
      text: `<b>FWI Category: <span style="color:${fwiInfo.color};">${fwiInfo.label}</span></b>`, 
      font: { size: 14, color: "#f8fafc" },
      padding: { bottom: 12, top: 10 }
    },
    delta: { reference: prevFwi, increasing: { color: "#ef4444" }, decreasing: { color: "#22c55e" } },
    number: { font: { size: 22, color: "#ffffff" } },
    gauge: {
      axis: { range: [0, 60], tickwidth: 1, tickcolor: "#94a3b8", dtick: 10 },
      bar: { color: fwiInfo.color, thickness: 0.35 },
      bgcolor: "rgba(30, 41, 59, 0.5)",
      bordercolor: "#334155",
      steps: [
        { range: [0, 5], color: "rgba(34, 197, 94, 0.25)" },
        { range: [5, 11], color: "rgba(234, 179, 8, 0.25)" },
        { range: [11, 19], color: "rgba(249, 115, 22, 0.25)" },
        { range: [19, 30], color: "rgba(239, 68, 68, 0.25)" },
        { range: [30, 50], color: "rgba(168, 85, 247, 0.25)" },
        { range: [50, 60], color: "rgba(236, 72, 153, 0.25)" }
      ]
    }
  }];

  const fopiData = [{
    type: "indicator",
    mode: "gauge+number+delta",
    value: fopiInfo.val,
    title: { 
      text: `<b>FOPI Category: <span style="color:${fopiInfo.color};">${fopiInfo.label}</span></b>`, 
      font: { size: 14, color: "#f8fafc" },
      padding: { bottom: 12, top: 10 }
    },
    delta: { reference: prevFopi, valueformat: ".2f", increasing: { color: "#ef4444" }, decreasing: { color: "#22c55e" } },
    number: { valueformat: ".2f", font: { size: 22, color: "#ffffff" } },
    gauge: {
      axis: { range: [0, 1.0], tickwidth: 1, tickcolor: "#94a3b8", dtick: 0.2 },
      bar: { color: fopiInfo.color, thickness: 0.35 },
      bgcolor: "rgba(30, 41, 59, 0.5)",
      bordercolor: "#334155",
      steps: [
        { range: [0, 0.2], color: "rgba(34, 197, 94, 0.25)" },
        { range: [0.2, 0.4], color: "rgba(234, 179, 8, 0.25)" },
        { range: [0.4, 0.6], color: "rgba(249, 115, 22, 0.25)" },
        { range: [0.6, 0.8], color: "rgba(239, 68, 68, 0.25)" },
        { range: [0.8, 1.0], color: "rgba(168, 85, 247, 0.25)" }
      ]
    }
  }];

  const layout = {
    width: 330,
    height: 200,
    margin: { t: 50, r: 30, l: 30, b: 20 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { family: "system-ui, sans-serif" }
  };

  const config = { responsive: true, displayModeBar: false };

  Plotly.newPlot('fwi-gauge-container', fwiData, layout, config);
  Plotly.newPlot('fopi-gauge-container', fopiData, layout, config);
}

/**
 * Downloads the modal element as a PNG image using html2canvas
 */
function downloadSummaryAsPNG(locationName) {
  const modalElem = document.getElementById('forecast-summary-modal');
  if (!modalElem) return;

  const downloadBtn = document.getElementById('download-forecast-modal-btn');
  const originalBtnContent = downloadBtn ? downloadBtn.innerHTML : '';

  if (downloadBtn) {
    downloadBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    downloadBtn.disabled = true;
  }

  // Temporarily adjust max-height so html2canvas captures full scrollable area
  const origMaxHeight = modalElem.style.maxHeight;
  const origOverflow = modalElem.style.overflowY;
  modalElem.style.maxHeight = 'none';
  modalElem.style.overflowY = 'visible';

  // Check if html2canvas is available
  if (typeof html2canvas === 'undefined') {
    alert('html2canvas library is missing. Please ensure it is loaded in your index.html template.');
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }
    return;
  }

  html2canvas(modalElem, {
    backgroundColor: '#0f172a',
    useCORS: true,
    scale: 2, // High resolution PNG capture
    logging: false
  }).then(canvas => {
    // Restore modal original dimensions
    modalElem.style.maxHeight = origMaxHeight;
    modalElem.style.overflowY = origOverflow;

    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }

    // Trigger PNG file download
    const link = document.createElement('a');
    const sanitizedName = (locationName || 'summary').replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const timeStamp = new Date().toISOString().slice(0, 10);
    
    link.download = `fire_weather_summary_${sanitizedName}_${timeStamp}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }).catch(err => {
    console.error('[Export Error] Failed to export PNG:', err);
    modalElem.style.maxHeight = origMaxHeight;
    modalElem.style.overflowY = origOverflow;
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }
  });
}

/**
 * Generates automated alerts and operational advisories based on fire indicators & weather
 */
function generateAdvisories(data) {
  const alerts = [];
  const advisories = [];

  const fwi = data.fwi || [0, 0, 0];
  const fopi = data.fopi || [0, 0, 0];
  const fireInfo = data.fire_info || {};
  const temp = data.temperature || [0, 0, 0];
  const wind = data.wind || [0, 0, 0];

  const activeCount = fireInfo.active_count || 0;
  const minDist = fireInfo.min_distance_km;

  if (activeCount > 0 && minDist === 0) {
    alerts.push({
      type: 'danger',
      icon: 'fa-fire-flame-curved',
      title: 'CRITICAL: Active Fire Detected Within Selected Boundary',
      desc: `NASA FIRMS detects <b>${activeCount} active hotspot(s)</b> currently inside this area. Immediate fire response and localized containment are strongly recommended.`
    });
  } else if (minDist !== null && minDist <= 50.0) {
    alerts.push({
      type: 'warning',
      icon: 'fa-triangle-exclamation',
      title: 'WARNING: Active Fire Proximity (< 50 km)',
      desc: `Detected active thermal anomaly approximately <b>${minDist.toFixed(1)} km</b> away. Risk of localized smoke transport and wildfire propagation if wind speed increases.`
    });
  }

  const fwiIncreasing = fwi[2] > fwi[0] + 3.0 || fwi[1] > fwi[0] + 2.0;
  const fopiNorm = fopi.map(v => v > 1.0 ? v / 100.0 : v);
  const fopiIncreasing = fopiNorm[2] > fopiNorm[0] + 0.1 || fopiNorm[1] > fopiNorm[0] + 0.08;

  if (fwiIncreasing || fopiIncreasing) {
    alerts.push({
      type: 'warning',
      icon: 'fa-arrow-trend-up',
      title: 'ESCALATING RISK: Increasing Fire Hazards Expected Over Next 48 Hours',
      desc: 'Model forecasts indicate an upward trend in Fire Weather Index / Probability over the 3-day forecast window. Prepare emergency response readiness for upcoming days.'
    });
  }

  const maxFwi = Math.max(...fwi);
  const maxFopi = Math.max(...fopiNorm);

  if (maxFwi >= 19.0 || maxFopi >= 0.6) {
    alerts.push({
      type: 'danger',
      icon: 'fa-radiation',
      title: 'HIGH IGNITION HAZARD: Severe Fire Weather Profile',
      desc: `Fire indices cross high risk thresholds (Max FWI: <b>${maxFwi.toFixed(1)}</b>, Max FOPI: <b>${(maxFopi * 100).toFixed(0)}%</b>). Atmospheric conditions favor rapid flame spread.`
    });
    advisories.push('Enforce strict restrictions on controlled agricultural burning and outdoor fires.');
    advisories.push('Deploy continuous satellite & lookout monitoring across vulnerable forest zones.');
  }

  if (Math.max(...temp) > 33.0 && Math.max(...wind) > 8.0) {
    advisories.push('Hot and windy microclimate conditions detected. Wind gusts exceed 8 m/s, accelerating flame front propagation velocity.');
  }

  if (advisories.length === 0 && alerts.length === 0) {
    advisories.push('Fire weather risk parameters are currently within baseline ranges. Maintain routine seasonal observations.');
  }

  return { alerts, advisories };
}

function makeDraggable(modal, handle) {
  handle.style.cursor = 'move';
  handle.addEventListener('mousedown', dragStart);
  document.addEventListener('mouseup', dragEnd);
  document.addEventListener('mousemove', drag);

  function dragStart(e) {
    if (e.target.closest('.forecast-modal-btn-action') || e.target.closest('.day-tab-btn')) return;
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    if (e.target === handle || handle.contains(e.target)) {
      isDragging = true;
    }
  }

  function dragEnd() {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
  }

  function drag(e) {
    if (isDragging) {
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      xOffset = currentX;
      yOffset = currentY;
      modal.style.transform = `translate(calc(-50% + ${currentX}px), calc(-50% + ${currentY}px))`;
    }
  }
}

function getOrCreateModal() {
  if (modalContainer) return modalContainer;

  modalContainer = document.createElement('div');
  modalContainer.id = 'forecast-summary-modal';
  modalContainer.className = 'forecast-modal hidden';

  const style = document.createElement('style');
  style.textContent = `
    .forecast-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 780px;
      max-width: 92vw;
      max-height: 85vh;
      overflow-y: auto;
      background: #0f172a;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.6);
      z-index: 2000;
      color: #f8fafc;
      font-family: system-ui, -apple-system, sans-serif;
      padding: 18px 22px;
      user-select: none;
    }
    .forecast-modal::-webkit-scrollbar { width: 6px; }
    .forecast-modal::-webkit-scrollbar-track { background: rgba(15, 23, 42, 0.6); border-radius: 4px; }
    .forecast-modal::-webkit-scrollbar-thumb { background: rgba(100, 116, 139, 0.5); border-radius: 4px; }
    .forecast-modal::-webkit-scrollbar-thumb:hover { background: #38bdf8; }
    .forecast-modal.hidden { display: none !important; }
    .forecast-modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      padding-bottom: 10px;
      margin-bottom: 12px;
      cursor: move;
    }
    .forecast-modal-title { font-size: 15px; font-weight: 700; color: #38bdf8; }
    .modal-actions { display: flex; align-items: center; gap: 8px; }
    .forecast-modal-btn-action {
      background: transparent;
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: #94a3b8;
      font-size: 14px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      transition: all 0.2s;
    }
    .forecast-modal-btn-action:hover {
      color: #38bdf8;
      border-color: #38bdf8;
      background: rgba(56, 189, 248, 0.1);
    }
    .gauges-wrapper {
      display: flex;
      justify-content: space-around;
      align-items: center;
      background: rgba(30, 41, 59, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      padding: 10px 0;
      margin-bottom: 14px;
    }
    .day-tabs { display: flex; gap: 8px; justify-content: center; margin-bottom: 10px; }
    .day-tab-btn {
      background: #1e293b;
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: #94a3b8;
      padding: 5px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      transition: all 0.2s;
    }
    .day-tab-btn.active { background: #0284c7; color: #ffffff; border-color: #38bdf8; }
    .forecast-metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
    .forecast-card {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .forecast-card-label { font-size: 11px; text-transform: uppercase; color: #94a3b8; margin-bottom: 4px; }
    .forecast-card-value { font-size: 12px; font-weight: 600; }
    .forecast-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      text-align: center;
      background: rgba(30, 41, 59, 0.5);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.08);
      margin-bottom: 16px;
    }
    .forecast-table th { background: #1e293b; color: #cbd5e1; padding: 8px 10px; font-weight: 600; }
    .forecast-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); color: #e2e8f0; }
    .forecast-table td:first-child { text-align: left; font-weight: 600; color: #94a3b8; }
    .advisory-section {
      background: rgba(30, 41, 59, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 12px 14px;
      margin-top: 10px;
    }
    .advisory-title { font-size: 13px; font-weight: 700; color: #f8fafc; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
    .alert-box { border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; font-size: 12px; display: flex; gap: 10px; align-items: flex-start; }
    .alert-box.danger { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #fca5a5; }
    .alert-box.warning { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #fcd34d; }
    .advisory-list { margin: 0; padding-left: 18px; font-size: 12px; color: #cbd5e1; }
    .advisory-list li { margin-bottom: 6px; }
  `;
  document.head.appendChild(style);
  document.body.appendChild(modalContainer);

  return modalContainer;
}

export function renderForecastSummaryModal(data, meta = {}) {
  const modal = getOrCreateModal();
  const nameLabel = meta.name || (meta.lat && meta.lon ? `Point (${meta.lat}, ${meta.lon})` : 'Selected Area');
  const isPolygon = !!meta.name;

  const ndviTrend = data.ndvi_trend || 0;
  const ndviColor = ndviTrend >= 0 ? '#22c55e' : '#ef4444';
  const ndviIcon = ndviTrend >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
  const ndviText = ndviTrend >= 0 ? `+${ndviTrend.toFixed(4)} (Stable/Green)` : `${ndviTrend.toFixed(4)} (Stress)`;

  let fireHtml = '';
  if (data.fire_info) {
    const { active_count, min_distance_km } = data.fire_info;
    if (active_count > 0 && min_distance_km === 0) {
      fireHtml = `<span style="color: #ef4444;"><i class="fa-solid fa-fire-flame-curved"></i> <b>${active_count} active fire(s)</b> inside boundary</span>`;
    } else if (min_distance_km !== null && min_distance_km !== undefined) {
      fireHtml = `<span style="color: #f59e0b;"><i class="fa-solid fa-fire"></i> <b>${active_count} fire(s)</b> nearby. Nearest: <b>${min_distance_km.toFixed(1)} km</b></span>`;
    } else {
      fireHtml = `<span style="color: #22c55e;"><i class="fa-solid fa-shield-halved"></i> No active fires detected (< 50 km)</span>`;
    }
  }

  const temp = data.temperature || [0, 0, 0];
  const rawRain = data.rainfall || [0, 0, 0];
  const rawRh = data.rh || [0, 0, 0];
  const wind = data.wind || [0, 0, 0];
  const fwi = data.fwi || [0, 0, 0];
  const fopi = data.fopi || [0, 0, 0];

  const rain = rawRain.map(v => (v < 1.0 && v > 0.0 ? parseFloat((v * 1000).toFixed(2)) : parseFloat(v.toFixed(2))));
  const rh = rawRh.map(v => (v <= 1.0 && v > 0.0 ? parseFloat((v * 100).toFixed(1)) : parseFloat(v.toFixed(1))));

  const { alerts, advisories } = generateAdvisories(data);

  let alertsHtml = '';
  alerts.forEach(a => {
    alertsHtml += `
      <div class="alert-box ${a.type}">
        <i class="fa-solid ${a.icon}" style="font-size: 16px; margin-top: 2px;"></i>
        <div>
          <b>${a.title}</b><br/>
          <span>${a.desc}</span>
        </div>
      </div>
    `;
  });

  let advisoryItemsHtml = '';
  advisories.forEach(adv => {
    advisoryItemsHtml += `<li>${adv}</li>`;
  });

  modal.innerHTML = `
    <div class="forecast-modal-header" id="forecast-modal-header">
      <div class="forecast-modal-title">
        <i class="fa-solid fa-grip-lines-vertical" style="color: #64748b; margin-right: 4px;"></i>
        <i class="fa-solid fa-gauge-high"></i> 
        <span>Fire Indices & 3-Day Weather Forecast</span>
      </div>
      <div class="modal-actions">
        <button class="forecast-modal-btn-action" id="download-forecast-modal-btn" title="Download Summary as PNG">
          <i class="fa-solid fa-download"></i>
        </button>
        <button class="forecast-modal-btn-action" id="close-forecast-modal-btn" title="Close">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
    </div>

    <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 10px;">
      <i class="fa-solid fa-location-dot" style="color: #38bdf8;"></i> <b>Location:</b> ${nameLabel} ${isPolygon ? '(Area Avg)' : ''}
    </div>

    <!-- Day Selector Tabs -->
    <div class="day-tabs">
      <button class="day-tab-btn active" data-day="0">Day 0 (Today)</button>
      <button class="day-tab-btn" data-day="1">Day 1 (Tomorrow)</button>
      <button class="day-tab-btn" data-day="2">Day 2</button>
    </div>

    <!-- Plotly Gauge Barometers -->
    <div class="gauges-wrapper">
      <div id="fwi-gauge-container"></div>
      <div id="fopi-gauge-container"></div>
    </div>

    <!-- NDVI & Active Fire Cards -->
    <div class="forecast-metrics-grid">
      <div class="forecast-card">
        <div class="forecast-card-label">NDVI Delta Trend</div>
        <div class="forecast-card-value" style="color: ${ndviColor};">
          <i class="fa-solid ${ndviIcon}"></i> ${ndviText}
        </div>
      </div>
      <div class="forecast-card">
        <div class="forecast-card-label">Active Fire Status</div>
        <div class="forecast-card-value">${fireHtml}</div>
      </div>
    </div>

    <!-- Weather Parameters Table -->
    <table class="forecast-table">
      <thead>
        <tr>
          <th>Weather Parameter</th>
          <th>Day 0 (Today)</th>
          <th>Day 1 (Tomorrow)</th>
          <th>Day 2</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><i class="fa-solid fa-temperature-high" style="color: #ef4444;"></i> Temperature</td>
          <td><b>${temp[0]} °C</b></td>
          <td><b>${temp[1]} °C</b></td>
          <td><b>${temp[2]} °C</b></td>
        </tr>
        <tr>
          <td><i class="fa-solid fa-cloud-showers-heavy" style="color: #38bdf8;"></i> Rainfall</td>
          <td><b>${rain[0]} mm</b></td>
          <td><b>${rain[1]} mm</b></td>
          <td><b>${rain[2]} mm</b></td>
        </tr>
        <tr>
          <td><i class="fa-solid fa-droplet" style="color: #06b6d4;"></i> Relative Humidity</td>
          <td><b>${rh[0]} %</b></td>
          <td><b>${rh[1]} %</b></td>
          <td><b>${rh[2]} %</b></td>
        </tr>
        <tr>
          <td><i class="fa-solid fa-wind" style="color: #10b981;"></i> Wind Speed</td>
          <td><b>${wind[0]} m/s</b></td>
          <td><b>${wind[1]} m/s</b></td>
          <td><b>${wind[2]} m/s</b></td>
        </tr>
      </tbody>
    </table>

    <!-- Automated Advisories & Actionable Warnings -->
    <div class="advisory-section">
      <div class="advisory-title">
        <i class="fa-solid fa-bell-concierge" style="color: #f59e0b;"></i>
        <span>Automated Risk Assessment & Actionable Advisories</span>
      </div>
      ${alertsHtml}
      ${advisoryItemsHtml ? `<ul class="advisory-list">${advisoryItemsHtml}</ul>` : ''}
    </div>
  `;

  modal.classList.remove('hidden');

  // Initial Gauge Render (Day 0)
  renderPlotlyGauges(fwi, fopi, 0);

  // Tab switching logic
  const tabBtns = modal.querySelectorAll('.day-tab-btn');
  tabBtns.forEach(btn => {
    btn.onclick = (e) => {
      tabBtns.forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      const dayIndex = parseInt(e.target.getAttribute('data-day'), 10);
      renderPlotlyGauges(fwi, fopi, dayIndex);
    };
  });

  // Attach Download PNG event listener
  document.getElementById('download-forecast-modal-btn').onclick = () => {
    downloadSummaryAsPNG(nameLabel);
  };

  // Enable dragging & close handler
  makeDraggable(modal, document.getElementById('forecast-modal-header'));
  document.getElementById('close-forecast-modal-btn').onclick = () => modal.classList.add('hidden');
}

