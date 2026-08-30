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

// Global / Exported Theme Function (call this whenever you load/render Plotly charts)
export function updatePlotlyTheme(theme = localStorage.getItem("theme") || "dark") {
  const chartTarget = document.getElementById("chart-plotly-target");
  
  // Safely check if Plotly chart instance actually exists and is loaded
  if (!chartTarget || !window.Plotly || !chartTarget.classList.contains('js-plotly-plot')) {
    return;
  }

  const isLight = theme === "light";
  const updateLayout = {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: isLight ? "#0f172a" : "#f8fafc" },
    xaxis: { gridcolor: isLight ? "#cbd5e1" : "#334155" },
    yaxis: { gridcolor: isLight ? "#cbd5e1" : "#334155" }
  };

  try {
    Plotly.relayout(chartTarget, updateLayout);
  } catch (err) {
    console.warn("Plotly layout update deferred: chart not ready", err);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // 1. Draggable Setup
  makeElementDraggable('#chart-container', '.chart-modal-header');

  // 2. DOM Handles
  const navBtns = document.querySelectorAll('.nav-btn');
  const closeDrawerBtn = document.getElementById('close-drawer');
  const drawerToggleBtn = document.getElementById('drawer-toggle-btn');
  const opacitySlider = document.getElementById('opacity-slider');
  const opacityVal = document.getElementById('opacity-val');
  const toggleFireBtn = document.getElementById('toggle-fire-btn');
  const themeToggleBtn = document.getElementById("theme-toggle");
  const themeIcon = document.getElementById("theme-icon");

  // 3. Theme Toggle Setup
  const savedTheme = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  let currentTheme = savedTheme || (prefersDark ? "dark" : "light");

  function applyTheme(theme) {
    if (theme === "light") {
      document.documentElement.setAttribute("data-theme", "light");
      themeIcon?.classList.remove("fa-moon");
      themeIcon?.classList.add("fa-sun");
    } else {
      document.documentElement.removeAttribute("data-theme");
      themeIcon?.classList.remove("fa-sun");
      themeIcon?.classList.add("fa-moon");
    }
    localStorage.setItem("theme", theme);
    
    // Safely attempt Plotly theme update
    updatePlotlyTheme(theme);
  }

  // Apply saved/default theme on boot
  applyTheme(currentTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      currentTheme = currentTheme === "dark" ? "light" : "dark";
      applyTheme(currentTheme);
    });
  }

  // 4. Navigation Button Click Listeners (MON, FOR, About)
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

      renderUI();
    });
  });

  // 5. Close Drawer Button Listener
  if (closeDrawerBtn) {
    closeDrawerBtn.addEventListener('click', () => {
      state.drawerOpen = false;
      renderUI();
      triggerResize();
    });
  }

  if (drawerToggleBtn) {
    drawerToggleBtn.addEventListener('click', () => {
      state.drawerOpen = true;
      renderUI();
      triggerResize();
    });
  }

  // 6. Opacity Slider Listener
  if (opacitySlider) {
    opacitySlider.addEventListener('input', (e) => {
      const val = e.target.value;
      state.currentOpacity = val / 100;
      if (opacityVal) opacityVal.innerText = `${val}%`;
      setTileOpacity(state.currentOpacity);
    });
  }

  // 7. Toggle Fire Button Listener
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

  // 8. Boundary Layer Checkbox Listeners
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
