// static/js/modules/forecastModalManager.js

let modalContainer = null;
let isDragging = false;
let currentX, currentY, initialX, initialY;
let xOffset = 0, yOffset = 0;

/**
 * Helper: Detects whether the page is currently in Light Mode
 */
function isLightMode() {
  return document.documentElement.classList.contains('light') || 
         document.body.classList.contains('light-mode') || 
         document.documentElement.getAttribute('data-theme') === 'light';
}

/**
 * Helper: Classifies FWI numerical values into text risk levels & colors.
 */
function getFWILevel(val) {
  if (val < 11.2) return { label: 'Faible', color: '#98FBB2' };
  if (val < 21.3) return { label: 'Modéré', color: '#D2E351' };
  if (val < 38.0) return { label: 'Élevé', color: '#E6A900' };
  if (val < 50.0) return { label: 'Très Élevé', color: '#D66610' };
  if (val < 70.0) return { label: 'Extrême', color: '#B4070C' };
  return { label: 'Extrême+', color: '#320212' };
}

/**
 * Helper: Classifies FOPI numerical values into text risk levels & colors
 */
function getFOPILevel(val) {
  const norm = val > 1.0 ? val / 100.0 : val;
  if (norm < 0.2) return { label: 'Faible', color: '#22c55e', val: norm };
  if (norm < 0.4) return { label: 'Modéré', color: '#eab308', val: norm };
  if (norm < 0.6) return { label: 'Élevé', color: '#f97316', val: norm };
  if (norm < 0.8) return { label: 'Très Élevé', color: '#ef4444', val: norm };
  return { label: 'Extrême', color: '#a855f7', val: norm };
}

/**
 * Renders Plotly.js Gauge Barometer with theme-adaptive colors
 */
/**
 * Renders Plotly.js Gauge Barometer with theme-adaptive colors
 */
function renderPlotlyGauges(fwiSeries, fopiSeries, selectedDay = 0) {
  const light = isLightMode();
  const gaugeContainer = document.getElementById('fwi-gauge-container');
  const gaugeWidth = Math.min(330, Math.max(260, Math.floor(gaugeContainer?.clientWidth || 330)));
  const gaugeHeight = window.matchMedia('(max-width: 700px)').matches ? 185 : 200;

  // Dynamic Theme Palette
  const textColor = light ? '#0f172a' : '#ffffff';
  const titleColor = light ? '#1e293b' : '#f8fafc';
  const tickColor = light ? '#64748b' : '#94a3b8';
  const gaugeBg = light ? 'rgba(241, 245, 249, 0.8)' : 'rgba(30, 41, 59, 0.5)';
  const gaugeBorder = light ? '#cbd5e1' : '#334155';

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
      text: `<b>Catégorie FWI : <span style="color:${fwiInfo.color};">${fwiInfo.label}</span></b>`, 
      font: { size: 14, color: titleColor },
      padding: { bottom: 12, top: 10 }
    },
    delta: { reference: prevFwi, increasing: { color: "#ef4444" }, decreasing: { color: "#22c55e" } },
    number: { font: { size: 22, color: textColor } },
    gauge: {
      axis: { range: [0, 80], tickwidth: 1, tickcolor: tickColor, dtick: 10 },
      bar: { color: fwiInfo.color, thickness: 0.35 },
      bgcolor: gaugeBg,
      bordercolor: gaugeBorder,
      steps: [
            // Opacité passée à 0.25 pour que la barre de niveau ressorte !
            { range: [0, 11.2], color: "rgba(152, 251, 178, 0.25)" },      // Low
            { range: [11.2, 21.3], color: "rgba(210, 227, 81, 0.25)" },    // Moderate
            { range: [21.3, 38.0], color: "rgba(230, 169, 0, 0.25)" },     // High
            { range: [38.0, 50.0], color: "rgba(214, 102, 16, 0.25)" },    // Very High
            { range: [50.0, 70.0], color: "rgba(180, 7, 12, 0.25)" },      // Extreme
            { range: [70.0, 80.0], color: "rgba(50, 2, 18, 0.25)" }        // Extreme+
      ]
    }
  }];

  const fopiData = [{
    type: "indicator",
    mode: "gauge+number+delta",
    value: fopiInfo.val,
    title: { 
      text: `<b>Catégorie FOPI : <span style="color:${fopiInfo.color};">${fopiInfo.label}</span></b>`, 
      font: { size: 14, color: titleColor },
      padding: { bottom: 12, top: 10 }
    },
    delta: { reference: prevFopi, valueformat: ".2f", increasing: { color: "#ef4444" }, decreasing: { color: "#22c55e" } },
    number: { valueformat: ".2f", font: { size: 22, color: textColor } },
    gauge: {
      axis: { range: [0, 1.0], tickwidth: 1, tickcolor: tickColor, dtick: 0.2 },
      bar: { color: fopiInfo.color, thickness: 0.35 },
      bgcolor: gaugeBg,
      bordercolor: gaugeBorder,
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
    width: gaugeWidth,
    height: gaugeHeight,
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
 * Downloads the modal element as a PNG image
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

  const origMaxHeight = modalElem.style.maxHeight;
  const origOverflow = modalElem.style.overflowY;
  modalElem.style.maxHeight = 'none';
  modalElem.style.overflowY = 'visible';

  if (typeof html2canvas === 'undefined') {
    alert('html2canvas library is missing.');
    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }
    return;
  }

  const canvasBgColor = isLightMode() ? '#ffffff' : '#0f172a';

  html2canvas(modalElem, {
    backgroundColor: canvasBgColor,
    useCORS: true,
    scale: 2,
    logging: false
  }).then(canvas => {
    modalElem.style.maxHeight = origMaxHeight;
    modalElem.style.overflowY = origOverflow;

    if (downloadBtn) {
      downloadBtn.innerHTML = originalBtnContent;
      downloadBtn.disabled = false;
    }

    const link = document.createElement('a');
    const sanitizedName = (locationName || 'summary').replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const timeStamp = new Date().toISOString().slice(0, 10);
    
    link.download = `resume_meteo_feu_${sanitizedName}_${timeStamp}.png`;
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
 * Generates automated alerts and operational advisories based on multi-level scenarios
 */
function generateAdvisories(data) {
  const alerts = [];
  const advisories = [];

  const fwi = data.fwi || [0, 0, 0];
  const fopi = data.fopi || [0, 0, 0];
  const fireInfo = data.fire_info || {};
  const ndviTrend = data.ndvi_trend || 0;
  
  const activeCount = fireInfo.active_count || 0;
  const minDist = fireInfo.min_distance_km;

  // 1. Proximité des feux (Active Fires)
  if (activeCount > 0 && minDist === 0) {
    alerts.push({
      type: 'danger',
      icon: 'fa-fire-flame-curved',
      title: 'CRITIQUE : Feu(x) actif(s) dans la zone sélectionnée',
      desc: `NASA FIRMS a détecté <b>${activeCount} point(s) chaud(s)</b> actif(s) à l'intérieur de ce périmètre. Action de confinement et mobilisation immédiate requises !`
    });
  } else if (minDist !== null && minDist <= 50.0) {
    alerts.push({
      type: 'warning',
      icon: 'fa-triangle-exclamation',
      title: 'ATTENTION : Feu actif à proximité (< 50 km)',
      desc: `Anomalie thermique détectée à environ <b>${minDist.toFixed(1)} km</b>. Risque de propagation et de transport de fumées.`
    });
  }

  // 2. Alertes sur la santé de la végétation (NDVI)
  if (ndviTrend < 0) {
    alerts.push({
      type: 'warning',
      icon: 'fa-leaf',
      title: 'STRESS VÉGÉTAL : Baisse du NDVI détectée',
      desc: `La tendance NDVI est négative (<b>${ndviTrend.toFixed(4)}</b>). La végétation s'assèche, augmentant la disponibilité du combustible. Anticipez une inflammabilité supérieure aux prévisions météorologiques pures.`
    });
    advisories.push('Végétation sèche : Restreindre de manière préventive l\'utilisation du feu, même si les conditions météo semblent clémentes.');
  }

  // Préparation des variables max
  const maxFwi = Math.max(...fwi);
  const fopiNorm = fopi.map(v => v > 1.0 ? v / 100.0 : v);
  const maxFopi = Math.max(...fopiNorm);

  // 3. NOUVEAU : Analyse des Tendances sur les prochains jours
  if (fwi.length >= 3 && fopiNorm.length >= 3) {
    // Tendance FWI (Hausse significative > 1.5 points)
    if (fwi[2] > fwi[0] && (fwi[2] - fwi[0] > 1.5)) {
      const isCritical = maxFwi >= 38.0; // Seuil "Élevé/Très Élevé"
      const vigilanceText = isCritical ? 'TRÈS VIGILANT' : 'vigilant';
      const alertType = isCritical ? 'danger' : 'warning';
      
      alerts.push({
        type: alertType,
        icon: 'fa-arrow-trend-up',
        title: 'TENDANCE FWI À LA HAUSSE',
        desc: `L'indice du feux météorologique (FWI) affiche une tendance à la hausse pour les prochains jours. Il faut être <b>${vigilanceText}</b> face à cette évolution (pic prévu à ${maxFwi.toFixed(1)}).`
      });
    }

    // Tendance FOPI (Hausse de probabilité > 5%)
    if (fopiNorm[2] > fopiNorm[0] && (fopiNorm[2] - fopiNorm[0] > 0.05)) {
      alerts.push({
        type: 'warning',
        icon: 'fa-chart-line',
        title: 'PROBABILITÉ (FOPI) CROISSANTE',
        desc: `La probabilité d'occurrence de feux (FOPI) augmentera au cours des prochains jours. Il est impératif de <b>faire les actions nécessaires</b> et de se préparer dès maintenant.`
      });
      advisories.push("Évolution FOPI : Inspecter et préparer de manière proactive le matériel d'intervention avant la hausse annoncée des risques.");
    }
  }

  // 4. Détermination du niveau de risque global sur 3 jours (Scénarios FWI/FOPI)
  let fwiRisk = 0;
  if (maxFwi >= 70.0) fwiRisk = 5;
  else if (maxFwi >= 50.0) fwiRisk = 4;
  else if (maxFwi >= 38.0) fwiRisk = 3;
  else if (maxFwi >= 21.3) fwiRisk = 2;
  else if (maxFwi >= 11.2) fwiRisk = 1;

  let fopiRisk = 0;
  if (maxFopi >= 0.8) fopiRisk = 4;
  else if (maxFopi >= 0.6) fopiRisk = 3;
  else if (maxFopi >= 0.4) fopiRisk = 2;
  else if (maxFopi >= 0.2) fopiRisk = 1;

  const riskLevel = Math.max(fwiRisk, fopiRisk);

  // 5. Génération des scénarios d'action selon le niveau de risque maximal
  if (riskLevel === 5) {
    alerts.push({
      type: 'danger', icon: 'fa-skull-crossbones',
      title: 'DANGER EXTRÊME+ : Situation Exceptionnelle',
      desc: `Les indices crèvent les plafonds (FWI: ${maxFwi.toFixed(1)}). Comportement de feu explosif et incontrôlable anticipé.`
    });
    advisories.push('Déclenchement immédiat des plans d\'urgence et de la cellule de crise régionale.');
    advisories.push('Évacuations préventives à anticiper pour toute zone habitée à proximité de massifs.');
    advisories.push('Interdiction stricte et totale de pénétration dans les espaces naturels.');
  } 
  else if (riskLevel === 4) {
    alerts.push({
      type: 'danger', icon: 'fa-radiation',
      title: 'RISQUE EXTRÊME : Danger Imminent',
      desc: `Conditions propices aux feux majeurs de cime (FWI: ${maxFwi.toFixed(1)}, FOPI: ${(maxFopi*100).toFixed(0)}%).`
    });
    advisories.push('Interdiction absolue de toute activité génératrice d\'étincelles (travaux, brûlages).');
    advisories.push('Déploiement maximal des patrouilles forestières et pré-positionnement des EPIs.');
    advisories.push('Mise en alerte de niveau maximum pour les services de secours de la zone.');
  } 
  else if (riskLevel === 3) {
    alerts.push({
      type: 'danger', icon: 'fa-exclamation',
      title: 'RISQUE TRÈS ÉLEVÉ : Alerte Renforcée',
      desc: `Tout départ de feu se propagera très rapidement et sera difficile à maîtriser.`
    });
    advisories.push('Suspension immédiate de tous les permis de brûlage agricole et forestier.');
    advisories.push('Mobilisation active des équipes de première intervention.');
    advisories.push('Diffusion de messages d\'alerte à la population via les médias locaux.');
  } 
  else if (riskLevel === 2) {
    alerts.push({
      type: 'warning', icon: 'fa-fire',
      title: 'RISQUE ÉLEVÉ : Action Préventive Requise',
      desc: `Même avec des valeurs modérées/élevées, la probabilité d'ignition soutient le développement des feux.`
    });
    advisories.push('Sensibilisation accrue des communautés locales sur les dangers du feu.');
    advisories.push('Limiter ou encadrer strictement les feux agricoles aux seules heures matinales sans vent.');
  } 
  else if (riskLevel === 1) {
    alerts.push({
      type: 'warning', icon: 'fa-triangle-exclamation',
      title: 'RISQUE MODÉRÉ : Vigilance Active',
      desc: `L'environnement commence à devenir réceptif aux étincelles.`
    });
    advisories.push('Rappeler les consignes de sécurité élémentaires aux exploitants agricoles.');
  } 
  else {
    if (ndviTrend >= 0 && fwi[2] <= fwi[0] && fopiNorm[2] <= fopiNorm[0]) { 
      advisories.push('Conditions météorologiques actuelles défavorables au développement de grands feux.');
      advisories.push('Maintenir les opérations de routine et la surveillance standard.');
    }
  }

  // Vérification de la synergie Vent / Température
  const maxTemp = Math.max(...data.temperature || [0,0,0]);
  const maxWind = Math.max(...data.wind || [0,0,0]);
  if (maxTemp > 33.0 && maxWind > 8.0) {
    advisories.push(`Alerte Microclimat : La combinaison de températures élevées (${maxTemp} °C) et de rafales (${maxWind} m/s) accélérera dramatiquement la vitesse du front de flamme.`);
  }

  return { alerts, advisories };
}



function makeDraggable(modal, handle) {
  handle.style.cursor = 'move';
  handle.addEventListener('mousedown', dragStart);
  document.addEventListener('mouseup', dragEnd);
  document.addEventListener('mousemove', drag);

  function dragStart(e) {
    if (window.matchMedia('(max-width: 700px)').matches) return;
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

  // CSS structure using CSS variables
  const style = document.createElement('style');
  style.textContent = `
    :root {
      --modal-bg: #0f172a;
      --modal-border: rgba(255, 255, 255, 0.15);
      --modal-text: #f8fafc;
      --modal-subtext: #94a3b8;
      --modal-card-bg: rgba(30, 41, 59, 0.7);
      --modal-card-border: rgba(255, 255, 255, 0.08);
      --modal-table-header: #1e293b;
      --modal-table-row: #e2e8f0;
      --modal-tab-bg: #1e293b;
    }

    html.light, body.light-mode, [data-theme="light"] {
      --modal-bg: #ffffff;
      --modal-border: #e2e8f0;
      --modal-text: #0f172a;
      --modal-subtext: #64748b;
      --modal-card-bg: #f8fafc;
      --modal-card-border: #e2e8f0;
      --modal-table-header: #f1f5f9;
      --modal-table-row: #334155;
      --modal-tab-bg: #f1f5f9;
    }

    .forecast-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 780px;
      max-width: 92vw;
      max-height: 85vh;
      overflow-y: auto;
      background: var(--modal-bg);
      border: 1px solid var(--modal-border);
      border-radius: 12px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
      z-index: 2000;
      color: var(--modal-text);
      font-family: system-ui, -apple-system, sans-serif;
      padding: 18px 22px;
      user-select: none;
    }
    .forecast-modal::-webkit-scrollbar { width: 6px; }
    .forecast-modal::-webkit-scrollbar-track { background: transparent; }
    .forecast-modal::-webkit-scrollbar-thumb { background: rgba(100, 116, 139, 0.5); border-radius: 4px; }
    .forecast-modal.hidden { display: none !important; }
    .forecast-modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--modal-border);
      padding-bottom: 10px;
      margin-bottom: 12px;
      cursor: move;
    }
    .forecast-modal-title { font-size: 15px; font-weight: 700; color: #0284c7; }
    .modal-actions { display: flex; align-items: center; gap: 8px; }
    .forecast-modal-btn-action {
      background: transparent;
      border: 1px solid var(--modal-border);
      color: var(--modal-subtext);
      font-size: 14px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      transition: all 0.2s;
    }
    .forecast-modal-btn-action:hover {
      color: #0284c7;
      border-color: #0284c7;
      background: rgba(56, 189, 248, 0.1);
    }
    .gauges-wrapper {
      display: flex;
      justify-content: space-around;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      background: var(--modal-card-bg);
      border: 1px solid var(--modal-card-border);
      border-radius: 10px;
      padding: 10px 0;
      margin-bottom: 14px;
    }
    #fwi-gauge-container,
    #fopi-gauge-container {
      width: 330px;
      max-width: 100%;
      min-height: 190px;
      flex: 1 1 320px;
    }
    .day-tabs { display: flex; gap: 8px; justify-content: center; margin-bottom: 10px; }
    .day-tab-btn {
      background: var(--modal-tab-bg);
      border: 1px solid var(--modal-border);
      color: var(--modal-subtext);
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
      background: var(--modal-card-bg);
      border: 1px solid var(--modal-card-border);
      border-radius: 8px;
      padding: 10px 12px;
    }
    .forecast-card-label { font-size: 11px; text-transform: uppercase; color: var(--modal-subtext); margin-bottom: 4px; }
    .forecast-card-value { font-size: 12px; font-weight: 600; }
    .forecast-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      text-align: center;
      background: var(--modal-card-bg);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--modal-card-border);
      margin-bottom: 16px;
    }
    .forecast-table-scroll {
      width: 100%;
      overflow-x: auto;
      margin-bottom: 16px;
    }
    .forecast-table-scroll .forecast-table {
      margin-bottom: 0;
    }
    .forecast-table th { background: var(--modal-table-header); color: var(--modal-text); padding: 8px 10px; font-weight: 600; }
    .forecast-table td { padding: 8px 10px; border-bottom: 1px solid var(--modal-card-border); color: var(--modal-table-row); }
    .forecast-table td:first-child { text-align: left; font-weight: 600; color: var(--modal-subtext); }
    .advisory-section {
      background: var(--modal-card-bg);
      border: 1px solid var(--modal-card-border);
      border-radius: 8px;
      padding: 12px 14px;
      margin-top: 10px;
    }
    .advisory-title { font-size: 13px; font-weight: 700; color: var(--modal-text); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
    .alert-box { border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; font-size: 12px; display: flex; gap: 10px; align-items: flex-start; }
    .alert-box.danger { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #ef4444; }
    .alert-box.warning { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #d97706; }
    .advisory-list { margin: 0; padding-left: 18px; font-size: 12px; color: var(--modal-subtext); }
    .advisory-list li { margin-bottom: 6px; }
    @media (max-width: 700px) {
      .forecast-modal {
        top: 8px;
        left: 8px;
        width: calc(100vw - 16px);
        max-width: none;
        max-height: calc(100vh - 16px);
        transform: none !important;
        padding: 12px;
        border-radius: 10px;
      }
      .forecast-modal-header {
        align-items: flex-start;
        gap: 10px;
        cursor: default;
      }
      .forecast-modal-title {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
        font-size: 13px;
        line-height: 1.25;
      }
      .forecast-modal-title span {
        white-space: normal;
      }
      .modal-actions {
        flex: 0 0 auto;
      }
      .day-tabs {
        justify-content: flex-start;
        overflow-x: auto;
        padding-bottom: 2px;
      }
      .day-tab-btn {
        flex: 0 0 auto;
        padding: 5px 10px;
        font-size: 11px;
      }
      .gauges-wrapper {
        flex-direction: column;
        align-items: stretch;
        padding: 8px;
      }
      #fwi-gauge-container,
      #fopi-gauge-container {
        width: 100%;
        flex-basis: auto;
      }
      .forecast-metrics-grid {
        grid-template-columns: 1fr;
      }
      .forecast-table {
        min-width: 560px;
      }
      .advisory-title {
        align-items: flex-start;
        font-size: 12px;
        line-height: 1.25;
      }
      .alert-box {
        font-size: 11px;
      }
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(modalContainer);

  return modalContainer;
}



export function renderForecastSummaryModal(data, meta = {}) {
  const modal = getOrCreateModal();
  const nameLabel = meta.name || (meta.lat && meta.lon ? `Point (${meta.lat}, ${meta.lon})` : 'Zone sélectionnée');
  const isPolygon = !!meta.name;

  // --- Gestion dynamique des dates ---
  // Tente de récupérer les dates depuis les données, sinon génère les dates du jour
  let label0, label1, label2;
  if (data.time && data.time.length >= 3) {
    label0 = data.time[0];
    label1 = data.time[1];
    label2 = data.time[2];
  } else if (data.dates && data.dates.length >= 3) {
    label0 = data.dates[0];
    label1 = data.dates[1];
    label2 = data.dates[2];
  } else {
    // Calcul de secours basé sur la date du clic du navigateur
    const today = new Date();
    const getFormatDate = (d) => d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    
    label0 = getFormatDate(today);
    
    const tmrw = new Date(today); tmrw.setDate(tmrw.getDate() + 1);
    label1 = getFormatDate(tmrw);
    
    const day2 = new Date(today); day2.setDate(day2.getDate() + 2);
    label2 = getFormatDate(day2);
  }

  // Date et heure exacte de l'établissement du bulletin
  const clickDate = new Date().toLocaleString('fr-FR', { 
    day: '2-digit', month: 'long', year: 'numeric', 
    hour: '2-digit', minute: '2-digit' 
  });

  // --- Indicateurs et Feux ---
  const ndviTrend = data.ndvi_trend || 0;
  const ndviColor = ndviTrend >= 0 ? '#22c55e' : '#ef4444';
  const ndviIcon = ndviTrend >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
  const ndviText = ndviTrend >= 0 ? `+${ndviTrend.toFixed(4)} (Stable/Verdoyant)` : `${ndviTrend.toFixed(4)} (Stress Végétal)`;

  let fireHtml = '';
  if (data.fire_info) {
    const { active_count, min_distance_km } = data.fire_info;
    if (active_count > 0 && min_distance_km === 0) {
      fireHtml = `<span style="color: #ef4444;"><i class="fa-solid fa-fire-flame-curved"></i> <b>${active_count} feu(x) actif(s)</b> dans le périmètre</span>`;
    } else if (min_distance_km !== null && min_distance_km !== undefined) {
      fireHtml = `<span style="color: #d97706;"><i class="fa-solid fa-fire"></i> <b>${active_count} feu(x)</b> à proximité. Le plus proche: <b>${min_distance_km.toFixed(1)} km</b></span>`;
    } else {
      fireHtml = `<span style="color: #22c55e;"><i class="fa-solid fa-shield-halved"></i> Aucun feu actif détecté (< 50 km)</span>`;
    }
  }

  // --- Données météo ---
  const temp = data.temperature || [0, 0, 0];
  const rawRain = data.rainfall || [0, 0, 0];
  const rawRh = data.rh || [0, 0, 0];
  const wind = data.wind || [0, 0, 0];
  const fwi = data.fwi || [0, 0, 0];
  const fopi = data.fopi || [0, 0, 0];

  const rain = rawRain.map(v => parseFloat((v ?? 0).toFixed(2)));
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

  // --- Injection HTML ---
  modal.innerHTML = `
    <div class="forecast-modal-header" id="forecast-modal-header">
      <div class="forecast-modal-title">
        <i class="fa-solid fa-grip-lines-vertical" style="color: #64748b; margin-right: 4px;"></i>
        <i class="fa-solid fa-gauge-high"></i> 
        <span>Indices Feux & Prévisions sur 3 Jours</span>
      </div>
      <div class="modal-actions">
        <button class="forecast-modal-btn-action" id="download-forecast-modal-btn" title="Télécharger le résumé (PNG)">
          <i class="fa-solid fa-download"></i>
        </button>
        <button class="forecast-modal-btn-action" id="close-forecast-modal-btn" title="Fermer">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
    </div>

    <div style="font-size: 12px; color: var(--modal-subtext); margin-bottom: 10px;">
      <i class="fa-solid fa-location-dot" style="color: #0284c7;"></i> <b>Emplacement :</b> ${nameLabel} ${isPolygon ? '(Moyenne de la zone)' : ''}
    </div>

    <!-- Onglets des jours (Dates exactes) -->
    <div class="day-tabs">
      <button class="day-tab-btn active" data-day="0">${label0}</button>
      <button class="day-tab-btn" data-day="1">${label1}</button>
      <button class="day-tab-btn" data-day="2">${label2}</button>
    </div>

    <!-- Plotly Gauge Barometers -->
    <div class="gauges-wrapper">
      <div id="fwi-gauge-container"></div>
      <div id="fopi-gauge-container"></div>
    </div>

    <!-- NDVI & Active Fire Cards -->
    <div class="forecast-metrics-grid">
      <div class="forecast-card">
        <div class="forecast-card-label">Tendance NDVI (Delta)</div>
        <div class="forecast-card-value" style="color: ${ndviColor};">
          <i class="fa-solid ${ndviIcon}"></i> ${ndviText}
        </div>
      </div>
      <div class="forecast-card">
        <div class="forecast-card-label">Statut Feux Actifs (FIRMS)</div>
        <div class="forecast-card-value">${fireHtml}</div>
      </div>
    </div>

    <!-- Tableau des Paramètres Météo (Dates exactes) -->
    <div class="forecast-table-scroll">
      <table class="forecast-table">
        <thead>
          <tr>
            <th>Paramètre Météo</th>
            <th>${label0}</th>
            <th>${label1}</th>
            <th>${label2}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><i class="fa-solid fa-temperature-high" style="color: #ef4444;"></i> Température</td>
            <td><b>${temp[0]} °C</b></td>
            <td><b>${temp[1]} °C</b></td>
            <td><b>${temp[2]} °C</b></td>
          </tr>
          <tr>
            <td><i class="fa-solid fa-cloud-showers-heavy" style="color: #0284c7;"></i> Précipitations</td>
            <td><b>${rain[0]} mm</b></td>
            <td><b>${rain[1]} mm</b></td>
            <td><b>${rain[2]} mm</b></td>
          </tr>
          <tr>
            <td><i class="fa-solid fa-droplet" style="color: #06b6d4;"></i> Humidité Relative</td>
            <td><b>${rh[0]} %</b></td>
            <td><b>${rh[1]} %</b></td>
            <td><b>${rh[2]} %</b></td>
          </tr>
          <tr>
            <td><i class="fa-solid fa-wind" style="color: #10b981;"></i> Vitesse du Vent</td>
            <td><b>${wind[0]} m/s</b></td>
            <td><b>${wind[1]} m/s</b></td>
            <td><b>${wind[2]} m/s</b></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Automated Advisories & Actionable Warnings -->
    <div class="advisory-section">
      <div class="advisory-title">
        <i class="fa-solid fa-bell-concierge" style="color: #d97706;"></i>
        <span>Évaluation Automatique des Risques & Actions Recommandées</span>
      </div>
      ${alertsHtml}
      ${advisoryItemsHtml ? `<ul class="advisory-list">${advisoryItemsHtml}</ul>` : ''}
    </div>

    <!-- Signature Officielle DGM / SRMB -->
    <div style="margin-top: 18px; text-align: right; font-size: 11px; color: var(--modal-subtext); border-top: 1px dashed var(--modal-border); padding-top: 10px;">
      <i>Bulletin établi le ${clickDate}</i><br>
      <strong style="color: var(--modal-text);">Bulletin Météorologique Spécial Feux - DGM / SRMB</strong>
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
