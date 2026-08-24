export function formatLegendTitle(data, fallbackTitle = 'Légende') {
  const rawTitle = String(data?.title || fallbackTitle).trim();

  const dateMatch = rawTitle.match(/\((\d{4}-\d{2}-\d{2})\)$/);
  const dateSuffix = dateMatch ? ` (${dateMatch[1]})` : '';
  const titleWithoutDate = dateMatch ? rawTitle.replace(/\s*\(\d{4}-\d{2}-\d{2}\)$/, '') : rawTitle;

  const climatologyMatch = titleWithoutDate.match(/^(Rain|Temp|Fire)\s+Climatology\s*\(([^)]+)\)$/i);
  if (climatologyMatch) {
    const labels = {
      rain: 'Climatologie des précipitations',
      temp: 'Climatologie de la température',
      fire: 'Climatologie des feux',
    };
    return `${labels[climatologyMatch[1].toLowerCase()]} (${climatologyMatch[2]})`;
  }

  const translations = {
    'Vegetation Index (MODIS 16-Day)': 'Indice de végétation (MODIS 16 jours)',
    FWI: 'Indice météo-feu (FWI)',
    FOPI: 'Indice de probabilité de feu (FOPI)',
  };

  return `${translations[titleWithoutDate] || titleWithoutDate}${dateSuffix}`;
}

export function formatLegendUnit(unit) {
  return unit ? ` (${unit})` : '';
}
