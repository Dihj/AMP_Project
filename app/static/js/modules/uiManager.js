// static/js/modules/uiManager.js

import { navConfig } from './config.js';
import { triggerResize, getMapLeft, getMapRight } from './mapManager.js';
import { 
  updateLeftClimateLayer, 
  clearLeftClimateLayer, 
  updateRightClimateLayer, 
  clearRightClimateLayer 
} from './climateLayers.js';

export const state = {
  currentNav: 'MON',
  selectedIcon: 'Temp', // Default left map layer ('Temp' or 'Rain')
  selectedTime: navConfig['MON'].timeData[0], // 'Jan'
  fireVisible: true,
  currentOpacity: 0.75,
  fixedScale: false
};

export function renderUI() {
  const sidebar = document.getElementById('sidebar');
  const iconBar = document.getElementById('icon-bar');
  const textDrawer = document.getElementById('text-drawer');
  const drawerTitle = document.getElementById('drawer-title');
  const appViewport = document.getElementById('app-viewport');
  const aboutViewport = document.getElementById('about-viewport');
  const timeBarLabel = document.getElementById('time-bar-label');
  const timePills = document.getElementById('time-pills');
  const chartDrawer = document.getElementById('chart-container');


  // Fetch Map Handles
  const mapLeft = getMapLeft();
  const mapRight = getMapRight();

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
    if (appViewport) appViewport.classList.add('hidden');
    if (aboutViewport) aboutViewport.classList.remove('hidden');

    clearLeftClimateLayer(mapLeft);
    clearRightClimateLayer(mapRight);
    return;
  }

  // 2. Handle MON / FOR Tabs UI setup
  if (sidebar) sidebar.classList.remove('hidden');
  if (textDrawer) textDrawer.classList.remove('hidden');
  if (appViewport) appViewport.classList.remove('hidden');
  if (aboutViewport) aboutViewport.classList.add('hidden');

  const config = navConfig[state.currentNav];

  // Validate that selectedTime belongs to the active tab configuration
  if (!config.timeData.includes(state.selectedTime)) {
    state.selectedTime = config.timeData[0];
  }

  // Validate selectedIcon for the active tab
  const validIconNames = config.icons.map(i => i.name);
  if (!validIconNames.includes(state.selectedIcon)) {
    state.selectedIcon = validIconNames[0];
  }

  if (drawerTitle) {
    drawerTitle.innerText = `${state.selectedIcon} Layer Controls`;
  }

  // Render Sidebar Icons (For Left Map switching)
  if (iconBar) {
    iconBar.innerHTML = '';
    config.icons.forEach(item => {
      const iconBtn = document.createElement('button');
      iconBtn.className = `icon-btn ${state.selectedIcon === item.name ? 'active' : ''}`;
      iconBtn.innerHTML = `<i class="fa-solid ${item.iconClass}"></i>`;
      iconBtn.title = item.name;

      iconBtn.addEventListener('click', () => {
        state.selectedIcon = item.name;
        if (textDrawer) textDrawer.classList.remove('hidden');
        renderUI();
      });

      iconBar.appendChild(iconBtn);
    });
  }

  // Render Time/Pill Selection Bar
  if (timeBarLabel) {
    timeBarLabel.innerText = config.timeType === 'months' ? 'Select Month:' : 'Select Period:';
  }

  if (timePills) {
    timePills.innerHTML = '';
    config.timeData.forEach(item => {
      const pillBtn = document.createElement('button');
      pillBtn.className = `pill-btn ${state.selectedTime === item ? 'active' : ''}`;
      pillBtn.innerText = item;

      pillBtn.addEventListener('click', () => {
        state.selectedTime = item;
        renderUI(); // Re-render maps with selected time step
      });

      timePills.appendChild(pillBtn);
    });
  }

  // 3. Dual-Panel Layer Rendering Logic
  // Clear existing layers first to avoid orphaned overlays
  clearLeftClimateLayer(mapLeft);
  clearRightClimateLayer(mapRight);

  if (state.currentNav === 'MON') {
    const leftParam = (state.selectedIcon === 'Rain') ? 'Rain' : 'Temp';
    
    // Render Left Map (Climate Raster) & Right Map (Wildfire Climatology)
    updateLeftClimateLayer(mapLeft, leftParam, state.selectedTime, state.fixedScale);
    updateRightClimateLayer(mapRight, 'Fire', state.selectedTime, state.fixedScale);

  } else if (state.currentNav === 'FOR') {
    // Forecast Mode Logic:
    // If FOR uses climate parameters (e.g., Rain/Temp forecasts)
    //const leftParam = (state.selectedIcon === 'Rain') ? 'Rain' : 'Temp';
    //updateLeftClimateLayer(mapLeft, leftParam, state.selectedTime, state.fixedScale);
    // If Right map in FOR also displays Fire forecast or a specialized layer:
    //updateRightClimateLayer(mapRight, 'Fire', state.selectedTime, state.fixedScale);
    clearLeftClimateLayer(mapLeft); 
    clearRightClimateLayer(mapRight);

  } 

  triggerResize();
}

/**
 * Enables mouse dragging on a floating panel via a target handle element
 * @param {HTMLElement|string} panelEl - The modal container element or selector
 * @param {HTMLElement|string} handleEl - The header element used to grab & drag
 */
export function makeElementDraggable(panelEl, handleEl) {
  const panel = typeof panelEl === 'string' ? document.querySelector(panelEl) : panelEl;
  const handle = typeof handleEl === 'string' ? document.querySelector(handleEl) : handleEl;

  if (!panel || !handle) return;

  let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;

  handle.onmousedown = dragMouseDown;

  function dragMouseDown(e) {
    // Ignore drag if user clicks the close button inside the header
    if (e.target.closest('#close-chart-btn')) return;

    e.preventDefault();
    
    // Get mouse initial position
    pos3 = e.clientX;
    pos4 = e.clientY;

    // Attach listeners to document so fast mouse movements don't detach
    document.onmouseup = closeDragElement;
    document.onmousemove = elementDrag;
  }

  function elementDrag(e) {
    e.preventDefault();

    // Calculate displacement
    pos1 = pos3 - e.clientX;
    pos2 = pos4 - e.clientY;
    pos3 = e.clientX;
    pos4 = e.clientY;

    // Switch positioning mode from fixed bottom/right to top/left on first drag
    const rect = panel.getBoundingClientRect();
    panel.style.bottom = 'auto';
    panel.style.right = 'auto';
    panel.style.top = (rect.top - pos2) + 'px';
    panel.style.left = (rect.left - pos1) + 'px';

    // Resize Plotly inside the container during or after drag
    if (window.Plotly) {
      Plotly.Plots.resize('chart-plotly-target');
    }
  }

  function closeDragElement() {
    // Stop moving when mouse button is released
    document.onmouseup = null;
    document.onmousemove = null;
  }
}
