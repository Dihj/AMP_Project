// static/js/main.js

import { navConfig } from './modules/config.js';
import { 
  initMapsOnce, 
  triggerResize, 
  setTileOpacity, 
  toggleFireLayer, 
  toggleBoundaryLayer, 
  updateRasterLayer ,
  clearRasterLayer
} from './modules/mapManager.js';
import { state, renderUI } from './modules/uiManager.js';

document.addEventListener("DOMContentLoaded", function () {

  // DOM Handles
  const navBtns = document.querySelectorAll('.nav-btn');
  const textDrawer = document.getElementById('text-drawer');
  const closeDrawerBtn = document.getElementById('close-drawer');
  const opacitySlider = document.getElementById('opacity-slider');
  const opacityVal = document.getElementById('opacity-val');
  const toggleFireBtn = document.getElementById('toggle-fire-btn');
  const timePillsContainer = document.getElementById('time-pills'); // Target parent container

  // 1. Navigation Button Click Listeners (MON, FOR, About)
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      navBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const targetNav = btn.dataset.nav;

      if (targetNav !== 'About') {
        state.currentNav = targetNav;
        state.selectedIcon = navConfig[state.currentNav].icons[0].name;
        state.selectedTime = navConfig[state.currentNav].timeData[0];
      } else {
        state.currentNav = 'About';
        clearRasterLayer();
      }

      renderUI();
      
      // Update spatial map raster for the selected tab/time
      if (state.currentNav !== 'About') {
        updateRasterLayer(state.selectedIcon, state.selectedTime);
      }
    });
  });

  // 2. Close Drawer Button Listener
  if (closeDrawerBtn) {
    closeDrawerBtn.addEventListener('click', () => {
      if (textDrawer) textDrawer.classList.add('hidden');
      triggerResize();
    });
  }

  // 3. Opacity Slider Listener
  if (opacitySlider) {
    opacitySlider.addEventListener('input', (e) => {
      const val = e.target.value;
      state.currentOpacity = val / 100;
      if (opacityVal) opacityVal.innerText = `${val}%`;
      setTileOpacity(state.currentOpacity);
    });
  }

  // 4. Toggle Fire Button Listener
  if (toggleFireBtn) {
    toggleFireBtn.addEventListener('click', () => {
      state.fireVisible = !state.fireVisible;
      if (state.fireVisible) {
        toggleFireBtn.classList.add('active-icon');
      } else {
        toggleFireBtn.classList.remove('active-icon');
      }
      toggleFireLayer(state.fireVisible);
    });
  }

  // 5. Boundary Layer Checkbox Listeners
  document.querySelectorAll('.layer-checkbox').forEach(chk => {
    chk.addEventListener('change', (e) => {
      const layerKey = e.target.dataset.layer;
      const isChecked = e.target.checked;
      toggleBoundaryLayer(layerKey, isChecked);
    });
  });

  // 6. Dynamic Time Pill Listener (Event Delegation)
  // Listen on the parent container because time pills are dynamically rendered by renderUI()
  if (timePillsContainer) {
    timePillsContainer.addEventListener('click', (e) => {
      const pill = e.target.closest('.time-pill');
      if (pill) {
        const selectedTime = pill.dataset.time || pill.innerText.trim();
        state.selectedTime = selectedTime;
        
        // Pass current active icon/parameter and selected time step to the raster update function
        const activeParam = state.selectedIcon || 'rr';
        updateRasterLayer(activeParam, selectedTime);
      }
    });
  }

  // ==========================================
  // BOOT SEQUENCE
  // ==========================================
  initMapsOnce(state.currentOpacity, state.fireVisible);
  renderUI();

  // Load initial spatial map colors on startup
  if (state.selectedIcon && state.selectedTime) {
    updateRasterLayer(state.selectedIcon, state.selectedTime);
  }
});

