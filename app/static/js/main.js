// static/js/main.js

import { navConfig } from './modules/config.js';
import { 
  initMapsOnce, 
  triggerResize, 
  setTileOpacity, 
  toggleFireLayer, 
  toggleBoundaryLayer, 
  clearRasterLayer
} from './modules/mapManager.js';
import { state, renderUI, makeElementDraggable } from './modules/uiManager.js';

document.addEventListener('DOMContentLoaded', () => {
    makeElementDraggable('#chart-container', '.chart-modal-header');
});

document.addEventListener("DOMContentLoaded", function () {

  // DOM Handles
  const navBtns = document.querySelectorAll('.nav-btn');
  const textDrawer = document.getElementById('text-drawer');
  const closeDrawerBtn = document.getElementById('close-drawer');
  const opacitySlider = document.getElementById('opacity-slider');
  const opacityVal = document.getElementById('opacity-val');
  const toggleFireBtn = document.getElementById('toggle-fire-btn');

  // 1. Navigation Button Click Listeners (MON, FOR, About)
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      navBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const targetNav = btn.dataset.nav;

      if (targetNav !== 'About') {
        state.currentNav = targetNav;

        // Reset selected time for target tab
        state.selectedTime = navConfig[state.currentNav].timeData[0];

        // Safely set icon state based on available structure
        if (state.currentNav === 'MON') {
          state.selectedIcon = navConfig['MON'].icons[0].name;
        } else if (state.currentNav === 'FOR') {
          state.leftForecastIcon = navConfig['FOR'].leftIcons[0].name;
          state.rightForecastIcon = navConfig['FOR'].rightIcons[0].name;
        }
      } else {
        state.currentNav = 'About';
        clearRasterLayer();
      }

      // renderUI() handles fetching and rendering layer maps for all modes
      renderUI();
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

  // ==========================================
  // BOOT SEQUENCE
  // ==========================================
  initMapsOnce(state.currentOpacity, state.fireVisible);
  renderUI();
});
