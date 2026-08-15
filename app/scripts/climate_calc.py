# app/scripts/climate_calc.py
import os
import io
import threading
import numpy as np
import xarray as xr
from PIL import Image
from matplotlib.colors import LinearSegmentedColormap, Normalize
import matplotlib

# Thread lock to prevent C-library execution conflicts
NETCDF_LOCK = threading.Lock()

# 1. DEFINE GLOBAL DATA CACHE (This fixes your ImportError)
DATA_CACHE = {}

# Define Colormaps
coulPREC_colors = [
    "#CB9362", "#DABE90", "#D2D179", "#91D47D", "#5CC247",
    "#49A136", "#287733", "#2A7E61", "#309181", "#327295",
    "#5B86C8", "#9D8CD9", "#CC79D2", "#C24799", "#7E2A73"
]
cmap_precip = LinearSegmentedColormap.from_list("coulPREC", coulPREC_colors)

temp_colors = [
    "#313695", "#4575b4", "#74add1", "#abd9e9", "#e0f3f8", 
    "#ffffbf", "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026"
]
cmap_temp = LinearSegmentedColormap.from_list("cmap_temp", temp_colors)

fire_colors = ["#ffffcc", "#ff2a00", "#800026"]
cmap_fire = LinearSegmentedColormap.from_list("cmap_fire", fire_colors)

# 2. PRELOAD FUNCTION FOR RAM CACHING
def preload_climate_data(base_dir='./data'):
    """Preloads NetCDF datasets into memory once at startup."""
    file_map = {
        'Rain': ('netcdf/climatology/RR_clim.nc', 'rfe'),
        'Temp': ('netcdf/climatology/TMEAN_clim.nc', 'tmean'),
        'Fire': ('netcdf/climatology/FIRE_climV2.nc', 'fire_density')
    }
    
    with NETCDF_LOCK:
        for param, (rel_path, var_name) in file_map.items():
            nc_path = os.path.join(base_dir, rel_path)
            if os.path.exists(nc_path):
                try:
                    with xr.open_dataset(nc_path, engine='netcdf4') as ds:
                        vname = var_name if var_name in ds else list(ds.data_vars)[0]
                        DATA_CACHE[param] = {
                            'lats': ds['lat'].values.copy(),
                            'lons': ds['lon'].values.copy(),
                            'data': np.array(ds[vname].values, dtype=np.float32)
                        }
                        print(f"[Climate Calc] Preloaded {param} successfully.")
                except Exception as e:
                    print(f"[Climate Calc] Error preloading {param}: {e}")

# 3. RASTER PNG GENERATOR
def generate_climate_png(parameter='Rain', time_step='Jan', fixed_scale=False, base_dir='./data'):
    colormaps = {
        'Rain': (cmap_precip, 'mm'),
        'Temp': (cmap_temp, '°C'),
        'Fire': (cmap_fire, 'fires/cell')
    }

    if parameter not in colormaps:
        raise ValueError(f"Unknown parameter: {parameter}")

    colormap, unit = colormaps[parameter]

    # Preload into cache if not loaded yet
    if parameter not in DATA_CACHE:
        preload_climate_data(base_dir)

    if parameter not in DATA_CACHE:
        raise FileNotFoundError(f"Data for {parameter} not available in cache.")

    cached = DATA_CACHE[parameter]
    lats = cached['lats']
    lons = cached['lons']
    data_all = cached['data']

    month_list = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    month_idx = month_list.index(time_step) if time_step in month_list else 0

    data_slice = data_all[month_idx, :, :]

    # Masking logic
    if parameter == 'Fire':
        mask_slice = (data_slice <= 0) | np.isnan(data_slice)
        mask_all = (data_all <= 0) | np.isnan(data_all)
    else:
        mask_slice = (data_slice < -90) | np.isnan(data_slice)
        mask_all = (data_all < -90) | np.isnan(data_all)

    target_data = data_all[~mask_all] if fixed_scale else data_slice[~mask_slice]

    if len(target_data) > 0:
        vmin = float(np.min(target_data))
        vmax = float(np.max(target_data))
    else:
        vmin, vmax = 0.0, 1.0

    if vmin == vmax:
        vmax = vmin + 1.0

    norm = Normalize(vmin=vmin, vmax=vmax)

    # Convert array directly to RGBA
    norm_data = norm(data_slice)
    rgba_image = colormap(norm_data)
    rgba_uint8 = (rgba_image * 255).astype(np.uint8)
    rgba_uint8[mask_slice, 3] = 0

    if lats[0] < lats[-1]:
        rgba_uint8 = np.flipud(rgba_uint8)

    img = Image.fromarray(rgba_uint8, mode='RGBA')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    num_steps = 5
    ticks = np.linspace(vmin, vmax, num_steps)
    legend_ticks = [
        {
            'value': round(float(t), 1),
            'color': matplotlib.colors.to_hex(colormap(norm(t)))
        }
        for t in ticks
    ]

    bounds = [
        [float(np.min(lats)), float(np.min(lons))],
        [float(np.max(lats)), float(np.max(lons))]
    ]

    return buf, bounds, legend_ticks, unit

