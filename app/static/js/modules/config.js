// static/js/modules/config.js

export const navConfig = {
  'MON': {
    timeType: 'months',
    timeData: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    icons: [
      { name: 'Rain', iconClass: 'fa-cloud-showers-heavy' },
      { name: 'Temp', iconClass: 'fa-temperature-high' }
    ]
  },
  'FOR': {
    timeType: 'days',
    timeData: ['Day 0', 'Day 1', 'Day 2'],
    // Split into left and right screen parameters
    leftIcons: [
      { name: 'Rain', iconClass: 'fa-cloud-showers-heavy', key: 'rr' },
      { name: 'Temp', iconClass: 'fa-temperature-high', key: 'temp' },
      { name: 'Wind', iconClass: 'fa-wind', key: 'wind' },
      { name: 'RH', iconClass: 'fa-droplet', key: 'rh' },
      { name: 'NDVI', iconClass: 'fa-leaf', key: 'NDVI' }
    ],
    rightIcons: [
      { name: 'FWI', iconClass: 'fa-fire-flame-curved', key: 'fwi' },
      { name: 'FOPI', iconClass: 'fa-triangle-exclamation', key: 'fopi' }
    ]
  },
  'About': {
    timeType: 'none',
    timeData: [],
    icons: []
  }
};