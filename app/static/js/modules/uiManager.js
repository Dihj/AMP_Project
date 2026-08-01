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

  // Fetch Map Handles
  const mapLeft = getMapLeft();
  const mapRight = getMapRight();

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

  // 2. Handle MON / FOR Tabs
  if (sidebar) sidebar.classList.remove('hidden');
  if (textDrawer) textDrawer.classList.remove('hidden');
  if (appViewport) appViewport.classList.remove('hidden');
  if (aboutViewport) aboutViewport.classList.add('hidden');

  const config = navConfig[state.currentNav];

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
        // Switching icons changes left map layer (Temp or Rain)
        state.selectedIcon = item.name;
        if (textDrawer) textDrawer.classList.remove('hidden');
        renderUI();
      });

      iconBar.appendChild(iconBtn);
    });
  }

  // Render Month Selection Pills
  if (timeBarLabel) {
    timeBarLabel.innerText = config.timeType === 'months' ? 'Select Month:' : 'Select Day:';
  }

  if (timePills) {
    timePills.innerHTML = '';
    config.timeData.forEach(item => {
      const pillBtn = document.createElement('button');
      pillBtn.className = `pill-btn ${state.selectedTime === item ? 'active' : ''}`;
      pillBtn.innerText = item;

      pillBtn.addEventListener('click', () => {
        state.selectedTime = item;
        renderUI(); // Updates BOTH left and right maps for the new month
      });

      timePills.appendChild(pillBtn);
    });
  }

  // 3. Dual-Panel Side-by-Side Rendering Logic
  if (state.currentNav === 'MON') {
    // Determine left map parameter (defaults to Temp if Fire or unknown icon is clicked)
    const leftParam = (state.selectedIcon === 'Rain') ? 'Rain' : 'Temp';

    // Update Left Map (Climate: Temperature or Rainfall)
    updateLeftClimateLayer(mapLeft, leftParam, state.selectedTime, state.fixedScale);

    // Update Right Map (Wildfire Climatology - Always Active)
    updateRightClimateLayer(mapRight, 'Fire', state.selectedTime, state.fixedScale);
  } else {
    // Clear both maps when leaving MON mode
    clearLeftClimateLayer(mapLeft);
    clearRightClimateLayer(mapRight);
  }

  triggerResize();
}
