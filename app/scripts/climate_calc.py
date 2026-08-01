# app/scripts/climate_calc.py
import os
import io
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize

# Color Maps
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

cmap_fire = plt.cm.YlOrRd

def generate_climate_png(parameter='Rain', time_step='Jan', fixed_scale=False, base_dir='./data'):
    file_map = {
        'Rain': ('netcdf/climatology/RR_clim.nc', 'rfe', cmap_precip, 'mm'),
        'Temp': ('netcdf/climatology/TMEAN_clim.nc', 'tmean', cmap_temp, '°C'),
        'Fire': ('netcdf/climatology/FIRE_clim.nc', 'fire_density', cmap_fire, 'fires/cell')
    }

    if parameter not in file_map:
        raise ValueError(f"No raster dataset configured for parameter: {parameter}")

    rel_path, var_name, colormap, unit = file_map[parameter]
    nc_path = os.path.join(base_dir, rel_path)

    if not os.path.exists(nc_path):
        raise FileNotFoundError(f"NetCDF file missing at: {nc_path}")

    month_list = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    month_idx = month_list.index(time_step) if time_step in month_list else 0

    # 1. Open NetCDF safely and load values immediately into memory
    with xr.open_dataset(nc_path, engine='netcdf4') as ds:
        vname = var_name if var_name in ds else list(ds.data_vars)[0]
        lats = ds['lat'].values
        lons = ds['lon'].values
        fill_val = ds[vname].attrs.get('_FillValue', -99.0)

        # Load into memory copy to avoid file-locking during multi-threaded requests
        data_all = ds[vname].values.copy()
        data_slice = data_all[month_idx, :, :].copy()

    # 2. Masking
    if parameter == 'Fire':
        masked_slice = np.ma.masked_less_equal(data_slice, 0.0)
        masked_all = np.ma.masked_less_equal(data_all, 0.0)
    else:
        masked_slice = np.ma.masked_invalid(np.ma.masked_equal(data_slice, fill_val))
        masked_all = np.ma.masked_invalid(np.ma.masked_equal(data_all, fill_val))

    # 3. Calculate Bounds safely (Handle months with no data or zero variance)
    target_mask = masked_all if fixed_scale else masked_slice

    if target_mask.count() > 0:
        vmin = float(np.nanmin(target_mask))
        vmax = float(np.nanmax(target_mask))
    else:
        vmin, vmax = 0.0, 1.0

    # Prevent crash if vmin == vmax (e.g. all pixels are 0)
    if vmin == vmax:
        vmax = vmin + 1.0

    norm = Normalize(vmin=vmin, vmax=vmax)

    # 4. Generate Color Legend Ticks
    num_steps = 5
    ticks = np.linspace(vmin, vmax, num_steps)
    legend_ticks = [
        {
            'value': round(float(t), 1),
            'color': matplotlib.colors.to_hex(colormap(norm(t)))
        }
        for t in ticks
    ]

    # 5. Render Transparent PNG
    bounds = [
        [float(np.min(lats)), float(np.min(lons))],
        [float(np.max(lats)), float(np.max(lons))]
    ]

    fig, ax = plt.subplots(figsize=(6, 8), dpi=100)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.axis('off')

    origin_loc = 'upper' if lats[0] > lats[-1] else 'lower'
    
    try:
        ax.imshow(
            masked_slice,
            cmap=colormap,
            norm=norm,
            origin=origin_loc,
            interpolation='nearest'
        )

        buf = io.BytesIO()
        plt.savefig(buf, format='png', transparent=True, bbox_inches='tight', pad_inches=0)
        buf.seek(0)
        return buf, bounds, legend_ticks, unit
    finally:
        # Guarantee figure cleanup even if an exception occurs
        plt.close(fig)
        