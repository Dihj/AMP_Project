// static/js/modules/uiManager.js

import { navConfig } from './config.js';
import { triggerResize, getMapLeft, getMapRight } from './mapManager.js';
import { 
  updateLeftClimateLayer, 
  clearLeftClimateLayer, 
  updateRightClimateLayer, 
  clearRightClimateLayer 
} from './climateLayers.js';
import {
  updateLeftForecastLayer,
  clearLeftForecastLayer
} from './forecastLayers.js';
import { updateRightFireIndexLayer, clearRightFireIndexLayer } from './fireIndexLayers.js';

export const state = {
  currentNav: 'MON',
  selectedIcon: 'Temp',        // For MON mode
  leftForecastIcon: 'Temp',     // For FOR mode (Left Map: Rain, Temp, Wind, RH, NDVI)
  rightForecastIcon: 'FWI',     // For FOR mode (Right Map: FWI, FOPI)
  selectedTime: navConfig['MON'].timeData[0],
  fireVisible: true,
  currentOpacity: 0.75,
  fixedScale: false,
  drawerOpen: true
};

/**
 * Helper to convert time pill labels ("Day 0", "Day 1", etc.) into an integer day index (0, 1, 2)
 */
function getForecastDayNumber(timeValue) {
  if (typeof timeValue === 'number') return timeValue;
  if (typeof timeValue === 'string') {
    const match = timeValue.match(/\d+/);
    if (match) return parseInt(match[0], 10);
  }
  return 0;
}

export function renderUI() {
  const sidebar = document.getElementById('sidebar');
  const iconBar = document.getElementById('icon-bar');
  const textDrawer = document.getElementById('text-drawer');
  const drawerToggleBtn = document.getElementById('drawer-toggle-btn');
  const drawerTitle = document.getElementById('drawer-title');
  const appViewport = document.getElementById('app-viewport');
  const aboutViewport = document.getElementById('about-viewport');
  const timeBarLabel = document.getElementById('time-bar-label');
  const timePills = document.getElementById('time-pills');
  const chartDrawer = document.getElementById('chart-container');

  const mapLeft = getMapLeft();
  const mapRight = getMapRight();

  // Clear chart if leaving MON mode
  if (state.currentNav !== 'MON' && chartDrawer) {
    chartDrawer.classList.add('hidden'); 
    const chartTarget = document.getElementById('chart-plotly-target'); 
    if (chartTarget && window.Plotly) {
      window.Plotly.purge(chartTarget);
    }
  }

  // 1. Handle About Tab
  if (state.currentNav === 'About') {
    if (sidebar) sidebar.classList.add('hidden');
    if (textDrawer) textDrawer.classList.add('hidden');
    if (drawerToggleBtn) drawerToggleBtn.classList.add('hidden');
    if (appViewport) appViewport.classList.add('hidden');
    if (aboutViewport) aboutViewport.classList.remove('hidden');

    clearLeftClimateLayer(mapLeft);
    clearRightClimateLayer(mapRight);
    clearLeftForecastLayer(mapLeft);
    clearRightFireIndexLayer(mapRight);
    return;
  }

  // 2. Handle MON / FOR Tabs UI setup
  if (sidebar) sidebar.classList.remove('hidden');
  if (textDrawer) textDrawer.classList.toggle('hidden', !state.drawerOpen);
  if (drawerToggleBtn) drawerToggleBtn.classList.toggle('hidden', state.drawerOpen);
  if (appViewport) appViewport.classList.remove('hidden');
  if (aboutViewport) aboutViewport.classList.add('hidden');

  const config = navConfig[state.currentNav];

  // Validate selected time
  if (!config.timeData.includes(state.selectedTime)) {
    state.selectedTime = config.timeData[0];
  }

  if (drawerTitle) {
    const activeLabel = state.currentNav === 'MON' 
      ? state.selectedIcon 
      : `${state.leftForecastIcon} / ${state.rightForecastIcon}`;
    drawerTitle.innerText = `Contrôle des couches - ${activeLabel}`;
  }

  // Render Sidebar Icons dynamically depending on tab structure
  if (iconBar) {
    iconBar.innerHTML = '';

    if (state.currentNav === 'MON') {
      config.icons.forEach(item => {
        const iconBtn = document.createElement('button');
        iconBtn.className = `icon-btn ${state.selectedIcon === item.name ? 'active' : ''}`;
        iconBtn.innerHTML = `<i class="fa-solid ${item.iconClass}"></i>`;
        iconBtn.title = item.name;

        iconBtn.addEventListener('click', () => {
          state.selectedIcon = item.name;
          state.drawerOpen = true;
          renderUI();
        });

        iconBar.appendChild(iconBtn);
      });

    } else if (state.currentNav === 'FOR') {
      // Group 1: Left Map Weather & NDVI
      const leftLabel = document.createElement('div');
      leftLabel.className = 'sidebar-section-title';
      leftLabel.innerText = 'CARTE DU GAUCHE';
      iconBar.appendChild(leftLabel);

      config.leftIcons.forEach(item => {
        const iconBtn = document.createElement('button');
        iconBtn.className = `icon-btn ${state.leftForecastIcon === item.name ? 'active' : ''}`;
        iconBtn.innerHTML = `<i class="fa-solid ${item.iconClass}"></i>`;
        iconBtn.title = `Carte du gauche: ${item.name}`;

        iconBtn.addEventListener('click', () => {
          state.leftForecastIcon = item.name;
          state.drawerOpen = true;
          renderUI();
        });

        iconBar.appendChild(iconBtn);
      });

      // Divider
      const hr = document.createElement('hr');
      hr.className = 'sidebar-divider';
      iconBar.appendChild(hr);

      // Group 2: Right Map Fire Risk Indices
      const rightLabel = document.createElement('div');
      rightLabel.className = 'sidebar-section-title';
      rightLabel.innerText = 'CARTE DU DROITE';
      iconBar.appendChild(rightLabel);

      config.rightIcons.forEach(item => {
        const iconBtn = document.createElement('button');
        iconBtn.className = `icon-btn ${state.rightForecastIcon === item.name ? 'active' : ''}`;
        iconBtn.innerHTML = `<i class="fa-solid ${item.iconClass}"></i>`;
        iconBtn.title = `Carte du droite: ${item.name}`;

        iconBtn.addEventListener('click', () => {
          state.rightForecastIcon = item.name;
          state.drawerOpen = true;
          renderUI();
        });

        iconBar.appendChild(iconBtn);
      });
    }
  }

  // Render Time/Pill Selection Bar
  if (timeBarLabel) {
    timeBarLabel.innerText = config.timeType === 'months' ? 'Selection Mois:' : 'Selection Jours:';
  }

  if (timePills) {
    timePills.innerHTML = '';
    config.timeData.forEach(item => {
      const pillBtn = document.createElement('button');
      pillBtn.className = `pill-btn ${state.selectedTime === item ? 'active' : ''}`;
      pillBtn.innerText = item;

      pillBtn.addEventListener('click', () => {
        state.selectedTime = item;
        renderUI();
      });

      timePills.appendChild(pillBtn);
    });
  }

  // 3. Dual-Panel Layer Rendering Logic
  if (state.currentNav === 'MON') {
    // Clear forecast layers when in MON mode
    clearLeftForecastLayer(mapLeft);
    clearRightFireIndexLayer(mapRight);

    const leftParam = (state.selectedIcon === 'Rain') ? 'Rain' : 'Temp';
    updateLeftClimateLayer(mapLeft, leftParam, state.selectedTime, state.fixedScale);
    updateRightClimateLayer(mapRight, 'Fire', state.selectedTime, state.fixedScale);

  } else if (state.currentNav === 'FOR') {
    // Clear climate layers when in FOR mode
    clearLeftClimateLayer(mapLeft);
    clearRightClimateLayer(mapRight);

    const dayNum = getForecastDayNumber(state.selectedTime);

    // --- LEFT MAP (Weather Forecast / NDVI) ---
    // Pass 'NDVI' directly to updateLeftForecastLayer so it handles both overlay and legend
    if (state.leftForecastIcon === 'NDVI') {
      updateLeftForecastLayer(mapLeft, 'NDVI', dayNum);
    } else {
      const paramKeyMap = { 'Temp': 'temp', 'Rain': 'rr', 'Wind': 'wind', 'RH': 'rh' };
      const fcstKey = paramKeyMap[state.leftForecastIcon] || 'temp';
      updateLeftForecastLayer(mapLeft, fcstKey, dayNum);
    }

    // --- RIGHT MAP (Fire Risk Index: FWI / FOPI) ---
    const fireKey = state.rightForecastIcon.toLowerCase(); // 'fwi' or 'fopi'
    updateRightFireIndexLayer(mapRight, fireKey, dayNum);
  }

  triggerResize();
}

/**
 * Enables mouse dragging on a floating panel via a target handle element
 */
export function makeElementDraggable(panelEl, handleEl) {
  const panel = typeof panelEl === 'string' ? document.querySelector(panelEl) : panelEl;
  const handle = typeof handleEl === 'string' ? document.querySelector(handleEl) : handleEl;

  if (!panel || !handle) return;

  let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;

  handle.onmousedown = dragMouseDown;

  function dragMouseDown(e) {
    if (e.target.closest('#close-chart-btn')) return;

    e.preventDefault();
    pos3 = e.clientX;
    pos4 = e.clientY;

    document.onmouseup = closeDragElement;
    document.onmousemove = elementDrag;
  }

  function elementDrag(e) {
    e.preventDefault();

    pos1 = pos3 - e.clientX;
    pos2 = pos4 - e.clientY;
    pos3 = e.clientX;
    pos4 = e.clientY;

    const rect = panel.getBoundingClientRect();
    panel.style.bottom = 'auto';
    panel.style.right = 'auto';
    panel.style.top = (rect.top - pos2) + 'px';
    panel.style.left = (rect.left - pos1) + 'px';

    if (window.Plotly) {
      Plotly.Plots.resize('chart-plotly-target');
    }
  }

  function closeDragElement() {
    document.onmouseup = null;
    document.onmousemove = null;
  }
}
