// static/js/modules/forecastModalManager.js

let modalContainer = null;
let isDragging = false;
let currentX;
let currentY;
let initialX;
let initialY;
let xOffset = 0;
let yOffset = 0;

/**
 * Attaches drag functionality to the modal header
 */
function makeDraggable(modal, handle) {
  handle.style.cursor = 'move';

  handle.addEventListener('mousedown', dragStart);
  document.addEventListener('mouseup', dragEnd);
  document.addEventListener('mousemove', drag);

  function dragStart(e) {
    // Prevent text selection while dragging
    if (e.target.closest('.forecast-modal-close')) return; // Allow close button click

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

      setTranslate(currentX, currentY, modal);
    }
  }

  function setTranslate(xPos, yPos, el) {
    el.style.transform = `translate(calc(-50% + ${xPos}px), calc(-50% + ${yPos}px))`;
  }
}

/**
 * Resets modal position back to center when re-opened
 */
function resetModalPosition(modal) {
  xOffset = 0;
  yOffset = 0;
  currentX = 0;
  currentY = 0;
  initialX = 0;
  initialY = 0;
  modal.style.transform = 'translate(-50%, -50%)';
}

/**
 * Initializes or retrieves the floating wide modal container
 */
function getOrCreateModal() {
  if (modalContainer) return modalContainer;

  modalContainer = document.createElement('div');
  modalContainer.id = 'forecast-summary-modal';
  modalContainer.className = 'forecast-modal hidden';

  // Inject Base Styles directly
  const style = document.createElement('style');
  style.textContent = `
    .forecast-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 740px;
      max-width: 92vw;
      max-height: 90vh;
      overflow-y: auto;
      background: #0f172a;
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
      z-index: 2000;
      color: #f8fafc;
      font-family: system-ui, -apple-system, sans-serif;
      padding: 20px;
      backdrop-filter: blur(8px);
      user-select: none;
    }
    .forecast-modal.hidden {
      display: none !important;
    }
    .forecast-modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      padding-bottom: 12px;
      margin-bottom: 16px;
      cursor: move; /* Drag cursor hint */
    }
    .forecast-modal-title {
      font-size: 16px;
      font-weight: 700;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .forecast-modal-close {
      background: transparent;
      border: none;
      color: #94a3b8;
      font-size: 18px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 4px;
      transition: color 0.2s, background 0.2s;
    }
    .forecast-modal-close:hover {
      color: #ffffff;
      background: rgba(255, 255, 255, 0.1);
    }
    .forecast-metrics-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 18px;
    }
    .forecast-card {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      padding: 12px 14px;
    }
    .forecast-card-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #94a3b8;
      margin-bottom: 4px;
    }
    .forecast-card-value {
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .forecast-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: center;
      background: rgba(30, 41, 59, 0.5);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .forecast-table th {
      background: #1e293b;
      color: #cbd5e1;
      padding: 10px 12px;
      font-weight: 600;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    .forecast-table td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      color: #e2e8f0;
    }
    .forecast-table tr:last-child td {
      border-bottom: none;
    }
    .forecast-table td:first-child {
      text-align: left;
      font-weight: 600;
      color: #94a3b8;
    }
    .param-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(modalContainer);

  return modalContainer;
}

/**
 * Renders the tabular forecast popup modal
 * @param {Object} data - Payload from /api/forecast/summary
 * @param {Object} meta - Spatial metadata (lat, lon, name)
 */
export function renderForecastSummaryModal(data, meta = {}) {
  const modal = getOrCreateModal();

  const nameLabel = meta.name || (meta.lat && meta.lon ? `Point (${meta.lat}, ${meta.lon})` : 'Selected Area');
  const isPolygon = !!meta.name;

  // 1. Calculate NDVI Trend
  const ndviTrend = data.ndvi_trend || 0;
  const ndviColor = ndviTrend >= 0 ? '#22c55e' : '#ef4444';
  const ndviIcon = ndviTrend >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
  const ndviText = ndviTrend >= 0 
    ? `+${ndviTrend.toFixed(4)} (Vegetation Improving/Stable)` 
    : `${ndviTrend.toFixed(4)} (Vegetation Stress)`;

  // 2. Active Fire Summary
  let fireHtml = '';
  if (data.fire_info) {
    const { active_count, min_distance_km } = data.fire_info;
    if (active_count > 0 && min_distance_km === 0) {
      fireHtml = `<span style="color: #ef4444;"><i class="fa-solid fa-fire-flame-curved"></i> <b>${active_count} active fire(s)</b> inside this area</span>`;
    } else if (min_distance_km !== null && min_distance_km !== undefined) {
      fireHtml = `<span style="color: #f59e0b;"><i class="fa-solid fa-fire"></i> <b>${active_count} active fire(s)</b> near area. Nearest: <b>${min_distance_km.toFixed(1)} km</b></span>`;
    } else {
      fireHtml = `<span style="color: #22c55e;"><i class="fa-solid fa-shield-halved"></i> No active fires detected within 50 km</span>`;
    }
  } else {
    fireHtml = `<span style="color: #94a3b8;"><i class="fa-solid fa-circle-info"></i> No active fire data available</span>`;
  }

  // 3. Prepare tabular arrays & safeguard unit conversions
  const temp = data.temperature || [0, 0, 0];
  const rawRain = data.rainfall || [0, 0, 0];
  const rawRh = data.rh || [0, 0, 0];
  const wind = data.wind || [0, 0, 0];
  const fwi = data.fwi || [0, 0, 0];
  const rawFopi = data.fopi || [0, 0, 0];

  const rain = rawRain.map(v => (v < 1.0 && v > 0.0 ? parseFloat((v * 1000).toFixed(2)) : parseFloat(v.toFixed(2))));
  const rh = rawRh.map(v => (v <= 1.0 && v > 0.0 ? parseFloat((v * 100).toFixed(1)) : parseFloat(v.toFixed(1))));
  const fopiPct = rawFopi.map(v => (v <= 1.0 ? (v * 100).toFixed(1) : parseFloat(v).toFixed(1)));

  modal.innerHTML = `
    <div class="forecast-modal-header" id="forecast-modal-header">
      <div class="forecast-modal-title">
        <i class="fa-solid fa-grip-lines-vertical" style="color: #64748b; margin-right: 4px;"></i>
        <i class="fa-solid fa-square-poll-vertical"></i> 
        <span>3-Day Forecast & Fire Risk Summary ${isPolygon ? '(Area Average)' : '(Grid Point)'}</span>
      </div>
      <button class="forecast-modal-close" id="close-forecast-modal-btn"><i class="fa-solid fa-xmark"></i></button>
    </div>

    <div style="font-size: 13px; color: #cbd5e1; margin-bottom: 14px;">
      <i class="fa-solid fa-location-dot" style="color: #38bdf8;"></i> <b>Location:</b> ${nameLabel}
    </div>

    <div class="forecast-metrics-grid">
      <div class="forecast-card">
        <div class="forecast-card-label">NDVI Trend (Δ Delta)</div>
        <div class="forecast-card-value" style="color: ${ndviColor};">
          <i class="fa-solid ${ndviIcon}"></i> ${ndviText}
        </div>
      </div>
      <div class="forecast-card">
        <div class="forecast-card-label">Active Fire Status</div>
        <div class="forecast-card-value">
          ${fireHtml}
        </div>
      </div>
    </div>

    <table class="forecast-table">
      <thead>
        <tr>
          <th>Parameter</th>
          <th>Day 0 (Today)</th>
          <th>Day 1 (Tomorrow)</th>
          <th>Day 2</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><span class="param-badge" style="color: #ef4444;"><i class="fa-solid fa-temperature-high"></i> Temperature</span></td>
          <td><b>${temp[0]} °C</b></td>
          <td><b>${temp[1]} °C</b></td>
          <td><b>${temp[2]} °C</b></td>
        </tr>
        <tr>
          <td><span class="param-badge" style="color: #38bdf8;"><i class="fa-solid fa-cloud-showers-heavy"></i> Rainfall</span></td>
          <td><b>${rain[0]} mm</b></td>
          <td><b>${rain[1]} mm</b></td>
          <td><b>${rain[2]} mm</b></td>
        </tr>
        <tr>
          <td><span class="param-badge" style="color: #06b6d4;"><i class="fa-solid fa-droplet"></i> Relative Humidity</span></td>
          <td><b>${rh[0]} %</b></td>
          <td><b>${rh[1]} %</b></td>
          <td><b>${rh[2]} %</b></td>
        </tr>
        <tr>
          <td><span class="param-badge" style="color: #10b981;"><i class="fa-solid fa-wind"></i> Wind Speed</span></td>
          <td><b>${wind[0]} m/s</b></td>
          <td><b>${wind[1]} m/s</b></td>
          <td><b>${wind[2]} m/s</b></td>
        </tr>
        <tr>
          <td><span class="param-badge" style="color: #f97316;"><i class="fa-solid fa-flame"></i> Fire Weather Index (FWI)</span></td>
          <td><b>${fwi[0]}</b></td>
          <td><b>${fwi[1]}</b></td>
          <td><b>${fwi[2]}</b></td>
        </tr>
        <tr>
          <td><span class="param-badge" style="color: #a855f7;"><i class="fa-solid fa-triangle-exclamation"></i> FOPI Risk</span></td>
          <td><b>${fopiPct[0]} %</b></td>
          <td><b>${fopiPct[1]} %</b></td>
          <td><b>${fopiPct[2]} %</b></td>
        </tr>
      </tbody>
    </table>
  `;

  resetModalPosition(modal);
  modal.classList.remove('hidden');

  // Enable dragging using the top header bar
  const headerHandle = document.getElementById('forecast-modal-header');
  makeDraggable(modal, headerHandle);

  // Attach close listener
  document.getElementById('close-forecast-modal-btn').onclick = () => {
    modal.classList.add('hidden');
  };
}

