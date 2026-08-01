document.addEventListener("DOMContentLoaded", function () {

  // Configuration Matrix
  const navConfig = {
    MON: {
      icons: [
        { name: 'Temp', iconClass: 'fa-temperature-high' },
        { name: 'Rain', iconClass: 'fa-cloud-showers-heavy' },
        { name: 'Fire', iconClass: 'fa-fire' }
      ],
      timeType: 'months',
      timeData: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    },
    FOR: {
      icons: [
        { name: 'Temp', iconClass: 'fa-temperature-high' },
        { name: 'Rain', iconClass: 'fa-cloud-showers-heavy' },
        { name: 'Fire', iconClass: 'fa-fire' },
        { name: 'Wind', iconClass: 'fa-wind' },
        { name: 'NDVI', iconClass: 'fa-leaf' }
      ],
      timeType: 'days',
      timeData: ['Day 0', 'Day 1', 'Day 2']
    }
  };

  // State Management (Default to MON + Temp + Jan)
  let currentNav = 'MON';
  let selectedIcon = navConfig['MON'].icons[0].name; // 'Temp'
  let selectedTime = navConfig['MON'].timeData[0];   // 'Jan'
  let fireVisible = true;
  let currentOpacity = 0.75;

  // DOM Handles
  const navBtns = document.querySelectorAll('.nav-btn');
  const sidebar = document.getElementById('sidebar');
  const iconBar = document.getElementById('icon-bar');
  const textDrawer = document.getElementById('text-drawer');
  const drawerTitle = document.getElementById('drawer-title');
  const closeDrawerBtn = document.getElementById('close-drawer');
  const appViewport = document.getElementById('app-viewport');
  const aboutViewport = document.getElementById('about-viewport');
  const timeBarLabel = document.getElementById('time-bar-label');
  const timePills = document.getElementById('time-pills');
  const opacitySlider = document.getElementById('opacity-slider');
  const opacityVal = document.getElementById('opacity-val');
  const toggleFireBtn = document.getElementById('toggle-fire-btn');

  // Leaflet Singletons
  let mapLeft = null;
  let mapRight = null;
  let leftTileLayer = null;
  let rightTileLayer = null;
  let fireLayerRight = null;

  // ==========================================
  // INITIALIZE MAPS ONCE
  // ==========================================
  function initMapsOnce() {
    const initialCenter = [-18.7, 46.8];
    const initialZoom = 6;
    const darkTileUrl = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    const attrib = '&copy; CARTO';

    mapLeft = L.map('map-left', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
    leftTileLayer = L.tileLayer(darkTileUrl, { maxZoom: 18, attribution: attrib, opacity: currentOpacity }).addTo(mapLeft);

    mapRight = L.map('map-right', { zoomControl: false, attributionControl: false }).setView(initialCenter, initialZoom);
    rightTileLayer = L.tileLayer(darkTileUrl, { maxZoom: 18, attribution: attrib, opacity: currentOpacity }).addTo(mapRight);
    L.control.zoom({ position: 'topright' }).addTo(mapRight);

    // Fire Layer setup
    fireLayerRight = L.layerGroup();
    const mockFirePoints = [[-18.5, 46.5], [-18.9, 47.1], [-19.2, 46.2], [-17.8, 48.1]];
    mockFirePoints.forEach(coords => {
      L.circleMarker(coords, {
        radius: 8, fillColor: '#ef4444', color: '#f87171', weight: 2, opacity: 1, fillOpacity: 0.8
      }).addTo(fireLayerRight);
    });

    if (fireVisible) fireLayerRight.addTo(mapRight);

    // Sync dual maps
    if (typeof mapLeft.sync === 'function') {
      mapLeft.sync(mapRight, { syncCursor: true });
      mapRight.sync(mapLeft, { syncCursor: true });
    }
  }

  function triggerResize() {
    setTimeout(() => {
      if (mapLeft) mapLeft.invalidateSize();
      if (mapRight) mapRight.invalidateSize();
    }, 50);
  }

  // ==========================================
  // RENDER UI STATE
  // ==========================================
  function renderUI() {
    // 1. Handle About Tab
    if (currentNav === 'About') {
      sidebar.classList.add('hidden');
      textDrawer.classList.add('hidden'); // Hide parameter drawer on About page
      appViewport.classList.add('hidden');
      aboutViewport.classList.remove('hidden');
      return;
    }

    // 2. Handle MON / FOR Tabs
    sidebar.classList.remove('hidden');
    textDrawer.classList.remove('hidden'); // SHOW parameter drawer initially
    appViewport.classList.remove('hidden');
    aboutViewport.classList.add('hidden');

    const config = navConfig[currentNav];

    // Update Drawer Title to match active icon
    if (drawerTitle) {
      drawerTitle.innerText = `${selectedIcon} Layer Controls`;
    }

    // Render Sidebar Icons
    iconBar.innerHTML = '';
    config.icons.forEach(item => {
      const iconBtn = document.createElement('button');
      iconBtn.className = `icon-btn ${selectedIcon === item.name ? 'active' : ''}`;
      iconBtn.innerHTML = `<i class="fa-solid ${item.iconClass}"></i>`;
      iconBtn.title = item.name;

      iconBtn.addEventListener('click', () => {
        selectedIcon = item.name;
        textDrawer.classList.remove('hidden'); // Ensure drawer stays open when clicking icons
        renderUI();
      });

      iconBar.appendChild(iconBtn);
    });

    // Render Time Bar (Months or Days)
    timeBarLabel.innerText = config.timeType === 'months' ? 'Select Month:' : 'Select Day:';
    timePills.innerHTML = '';

    config.timeData.forEach(item => {
      const pillBtn = document.createElement('button');
      pillBtn.className = `pill-btn ${selectedTime === item ? 'active' : ''}`;
      pillBtn.innerText = item;

      pillBtn.addEventListener('click', () => {
        selectedTime = item;
        renderUI();
      });

      timePills.appendChild(pillBtn);
    });

    // Force Leaflet recalculation after display un-hides
    triggerResize();
  }

  // ==========================================
  // EVENT LISTENERS
  // ==========================================
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      navBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const targetNav = btn.dataset.nav;

      if (targetNav !== 'About') {
        currentNav = targetNav;
        // Reset defaults for selected mode (MON or FOR)
        selectedIcon = navConfig[currentNav].icons[0].name;
        selectedTime = navConfig[currentNav].timeData[0];
      } else {
        currentNav = 'About';
      }

      renderUI();
    });
  });

  closeDrawerBtn.addEventListener('click', () => {
    textDrawer.classList.add('hidden');
    triggerResize();
  });

  opacitySlider.addEventListener('input', (e) => {
    const val = e.target.value;
    currentOpacity = val / 100;
    opacityVal.innerText = `${val}%`;
    if (leftTileLayer) leftTileLayer.setOpacity(currentOpacity);
    if (rightTileLayer) rightTileLayer.setOpacity(currentOpacity);
  });

  toggleFireBtn.addEventListener('click', () => {
    fireVisible = !fireVisible;
    if (fireVisible) {
      toggleFireBtn.classList.add('active-icon');
      if (mapRight && fireLayerRight) mapRight.addLayer(fireLayerRight);
    } else {
      toggleFireBtn.classList.remove('active-icon');
      if (mapRight && fireLayerRight) mapRight.removeLayer(fireLayerRight);
    }
  });

  // ==========================================
  // BOOT SEQUENCE
  // ==========================================
  initMapsOnce(); // 1. Maps mounted in DOM
  renderUI();     // 2. Render UI with open drawer & default options
});
