// static/js/modules/config.js

export const navConfig = {
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
