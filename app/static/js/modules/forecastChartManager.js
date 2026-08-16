// static/js/modules/forecastChartManager.js

/**
 * Renders the 3-day Forecast Summary, NDVI Trend, Active Fire Proximity, FWI, and FOPI
 * @param {string} containerId - Target HTML element ID (e.g. 'chart-plotly-target')
 * @param {Object} data - Forecast timeseries and spatial analysis payload
 * @param {Object} meta - Metadata containing lat/lon or location name
 */
export function renderForecastSummaryChart(containerId, data, meta = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // 1. Build Header & Info Card HTML
  const nameLabel = meta.name || (meta.lat && meta.lon ? `Coordonnées (${meta.lat}, ${meta.lon})` : 'Zone sélectionnée');
  
  // Calculate NDVI Trend Direction & Color
  const ndviTrend = data.ndvi_trend || 0;
  const ndviBadgeColor = ndviTrend >= 0 ? '#22c55e' : '#ef4444';
  const ndviIcon = ndviTrend >= 0 ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down';
  const ndviText = ndviTrend >= 0 ? `+${ndviTrend.toFixed(3)} (En amélioration / Stable)` : `${ndviTrend.toFixed(3)} (Stress végétal)`;

  // Fire Proximity / Containment Summary
  let fireSummaryHtml = '';
  let hasImmediateFireRisk = false;
  if (data.fire_info) {
    const { active_count, min_distance_km } = data.fire_info;
    if (active_count > 0 && min_distance_km === 0) {
      hasImmediateFireRisk = true;
      fireSummaryHtml = `<span style="color: #ef4444; font-weight: bold;"><i class="fa-solid fa-fire-flame-curved"></i> ${active_count} feu(x) actif(s) détecté(s) directement dans cette zone !</span>`;
    } else if (min_distance_km !== null && min_distance_km !== undefined) {
      if (min_distance_km < 10) hasImmediateFireRisk = true;
      fireSummaryHtml = `<span style="color: #f59e0b;"><i class="fa-solid fa-fire"></i> ${active_count} feu(x) actif(s) détecté(s). Le feu le plus proche est à ${min_distance_km.toFixed(1)} km.</span>`;
    } else {
      fireSummaryHtml = `<span style="color: #22c55e;"><i class="fa-solid fa-shield-halved"></i> Aucun feu actif dans un rayon de 50 km.</span>`;
    }
  }

  // Decision Support Summary / Scenarios (Aide à la décision & Scénarios de risque)
  const maxFwi = Math.max(...(data.fwi || [0]));
  const maxFopi = Math.max(...(data.fopi || [0]));
  
  // Determine Risk Levels based on actual scales
  let fwiRisk = 0;
  if (maxFwi >= 70.0) fwiRisk = 5;      // Extreme+
  else if (maxFwi >= 50.0) fwiRisk = 4; // Extreme
  else if (maxFwi >= 38.0) fwiRisk = 3; // Very High
  else if (maxFwi >= 21.3) fwiRisk = 2; // High
  else if (maxFwi >= 11.2) fwiRisk = 1; // Moderate

  let fopiRisk = 0;
  if (maxFopi >= 0.8) fopiRisk = 4;      // Extreme
  else if (maxFopi >= 0.6) fopiRisk = 3; // Very High
  else if (maxFopi >= 0.4) fopiRisk = 2; // High
  else if (maxFopi >= 0.2) fopiRisk = 1; // Moderate

  // Take the highest risk category between FWI and FOPI
  const riskLevel = Math.max(fwiRisk, fopiRisk);

  let decisionAlertColor = '#22c55e';
  let decisionTitle = '';
  let decisionDesc = '';

  switch (riskLevel) {
    case 5:
      decisionAlertColor = '#320212'; // Extreme+ FWI color
      decisionTitle = 'Risque Extrême+ : Situation Exceptionnelle';
      decisionDesc = 'Conditions météorologiques propices aux méga-feux. Danger majeur pour les infrastructures et écosystèmes. Activation des protocoles de crise de niveau maximum et évacuation préventive à envisager.';
      break;
    case 4:
      decisionAlertColor = '#d7191c'; // Extreme FOPI/FWI Red
      decisionTitle = 'Risque Extrême : Danger Imminent';
      decisionDesc = 'Propagation potentiellement explosive et incontrôlable. Déploiement maximal des ressources d\'alerte précoce, interdiction stricte de toute source d\'ignition et positionnement des équipes de secours.';
      break;
    case 3:
      decisionAlertColor = '#ea580c'; // Very High Orange/Red
      decisionTitle = 'Risque Très Élevé : Alerte Renforcée';
      decisionDesc = 'Conditions critiques. Tout départ de feu sera très difficile à maîtriser. Interdiction stricte des brûlages agricoles. Mobilisation immédiate des équipes de première intervention et des patrouilles forestières.';
      break;
    case 2:
      decisionAlertColor = '#f59e0b'; // High Amber/Yellow
      decisionTitle = 'Risque Élevé : Action Préventive';
      decisionDesc = 'Danger de feu important. Les conditions permettent une propagation rapide. Restriction recommandée des feux à ciel ouvert. Sensibilisation active des communautés locales et préparation des équipements d\'extinction.';
      break;
    case 1:
      decisionAlertColor = '#eab308'; // Moderate Yellow
      decisionTitle = 'Risque Modéré : Vigilance Requise';
      decisionDesc = 'Les conditions météorologiques soutiennent l\'allumage et la propagation initiale. Il faut agir : limiter les feux agricoles, surveiller les zones à risque et informer les autorités locales de toute activité suspecte.';
      break;
    default:
      decisionAlertColor = '#22c55e'; // Low Green
      decisionTitle = 'Risque Faible : Conditions Favorables';
      decisionDesc = 'Probabilité d\'ignition faible. Les opérations de routine et la surveillance standard sont suffisantes.';
      break;
  }

  // Modifiers: Append NDVI and Active Fire warnings directly to the decision description
  let modifiersHtml = '';
  
  if (ndviTrend < 0) {
    modifiersHtml += `<div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.1); color: #fca5a5;">
      <strong><i class="fa-solid fa-leaf"></i> Attention NDVI :</strong> La tendance négative indique un dessèchement récent de la végétation (combustible plus inflammable). Les mesures de précaution doivent être renforcées.
    </div>`;
  }

  if (hasImmediateFireRisk) {
    modifiersHtml += `<div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.1); color: #ef4444; font-weight: bold;">
      <strong><i class="fa-solid fa-bell"></i> ACTION IMMÉDIATE :</strong> Des feux sont déjà actifs à proximité immédiate. Une intervention directe ou une mise en sécurité est requise, indépendamment des prévisions météo.
    </div>`;
  }

  const decisionSupportHtml = `
    <div style="margin-top: 10px; padding: 10px 12px; background: rgba(15, 23, 42, 0.7); border-left: 4px solid ${decisionAlertColor}; border-radius: 4px; font-size: 11px;">
      <strong style="color: ${decisionAlertColor}; font-size: 12px;"><i class="fa-solid fa-triangle-exclamation"></i> ${decisionTitle}</strong>
      <div style="color: #cbd5e1; margin-top: 4px; line-height: 1.4;">${decisionDesc}</div>
      ${modifiersHtml}
    </div>
  `;

  // 2. Insert Summary Info Header
  const summaryHeader = `
    <div style="font-family: sans-serif; color: #f8fafc; padding: 10px 14px; background: #0f172a; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <h4 style="margin: 0; color: #38bdf8; font-size: 14px;"><i class="fa-solid fa-location-dot"></i> ${nameLabel} - Prévision à 3 Jours</h4>
        <span style="background: ${ndviBadgeColor}22; color: ${ndviBadgeColor}; padding: 3px 8px; border-radius: 12px; font-size: 11px; border: 1px solid ${ndviBadgeColor};">
          <i class="fa-solid ${ndviIcon}"></i> Indice NDVI Δ: ${ndviText}
        </span>
      </div>
      <div style="font-size: 12px; line-height: 1.4;">
        ${fireSummaryHtml}
        ${decisionSupportHtml}
      </div>
    </div>
    <div id="forecast-plotly-subtarget" style="height: 340px; width: 100%;"></div>
  `;

  container.innerHTML = summaryHeader;

  // 3. Prepare Time Series Data Arrays
  const days = ['Jour 0 (Aujourd\'hui)', 'Jour 1 (Demain)', 'Jour 2', 'Jour 3'];
  const temp = data.temperature || [0, 0, 0, 0];    // °C
  const rawRain = data.rainfall || [0, 0, 0, 0];    // mm
  const rh = data.rh || [0, 0, 0, 0];                // %
  const wind = data.wind || [0, 0, 0, 0];            // m/s
  const fwi = data.fwi || [0, 0, 0, 0];              // Index
  const fopi = data.fopi || [0, 0, 0, 0];            // Probability (0.0 - 1.0)

  // Cut days array to match the length of the data passed in (e.g., 3 vs 4 days)
  const plotDays = days.slice(0, temp.length);

  // Ensure rainfall is converted to mm if values are still in meters
  const rain = rawRain.map(v => (v < 1.0 && v > 0.0 ? parseFloat((v * 1000).toFixed(2)) : parseFloat(v.toFixed(2))));

  // Traces
  const traceRain = {
    x: plotDays,
    y: rain,
    name: 'Précipitations (mm)',
    type: 'bar',
    marker: { color: '#38bdf8', opacity: 0.6 },
    yaxis: 'y'
  };

  const traceTemp = {
    x: plotDays,
    y: temp,
    name: 'Temp (°C)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#ef4444', width: 2.5 },
    marker: { size: 6 },
    yaxis: 'y2'
  };

  const traceRH = {
    x: plotDays,
    y: rh,
    name: 'RH (%)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#06b6d4', dash: 'dot', width: 2 },
    marker: { size: 5 },
    yaxis: 'y'
  };

  const traceWind = {
    x: plotDays,
    y: wind,
    name: 'Vent (m/s)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#10b981', dash: 'dash', width: 2 },
    marker: { size: 5 },
    yaxis: 'y2'
  };

  const traceFWI = {
    x: plotDays,
    y: fwi,
    name: 'Indice FWI',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#f97316', width: 3 },
    marker: { size: 7, symbol: 'diamond' },
    yaxis: 'y2'
  };

  const traceFOPI = {
    x: plotDays,
    y: fopi.map(v => v * 100), // Scale 0-1 probability to 0-100%
    name: 'Risque FOPI (%)',
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: '#a855f7', width: 2.5, dash: 'dashdot' },
    marker: { size: 6, symbol: 'square' },
    yaxis: 'y'
  };

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { t: 10, r: 45, l: 45, b: 35 },
    showlegend: true,
    legend: { orientation: 'h', x: 0, y: 1.18, font: { color: '#94a3b8', size: 10 } },
    xaxis: { tickfont: { color: '#cbd5e1' }, gridcolor: '#334155' },
    yaxis: {
      title: 'Pluie (mm) / RH (%) / FOPI (%)',
      titlefont: { color: '#38bdf8', size: 10 },
      tickfont: { color: '#cbd5e1' },
      gridcolor: '#334155'
    },
    yaxis2: {
      title: 'Temp (°C) / Vent (m/s) / FWI',
      titlefont: { color: '#ef4444', size: 10 },
      tickfont: { color: '#cbd5e1' },
      overlaying: 'y',
      side: 'right',
      showgrid: false
    }
  };

  Plotly.newPlot(
    'forecast-plotly-subtarget',
    [traceRain, traceTemp, traceRH, traceWind, traceFWI, traceFOPI],
    layout,
    { responsive: true, displayModeBar: false }
  );
}
