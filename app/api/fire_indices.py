import base64
import io
import logging
import os
import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import xarray as xr
import xclim
from flask import Blueprint, jsonify, request
from scipy.ndimage import gaussian_filter
from app.core.dataset_cache import get_cached_indices, set_cached_indices

matplotlib.use("Agg")

from app.api.aifs_frcst import clip_to_land_shapefile, get_aifs_dataset
from app.api.ndvi import get_ndvi_dataset

fire_indices_bp = Blueprint("fire_indices", __name__, url_prefix="/api/fire-indices")
logger = logging.getLogger(__name__)

PLOT_CACHE = {}
CLIM_NC_PATH = "data/netcdf/climatology/FIRE_climV2.nc"


def generate_dynamic_cffdrs_seeds(target_grid, clim_nc_path):
    """Generates spatially dynamic initial seed arrays (ffmc0, dmc0, dc0) for xclim

    using 24h active FIRMS fire detections and long-term fire climatology.
    """
    lats = target_grid.latitude.values
    lons = target_grid.longitude.values

    spatial_coords = {"latitude": lats, "longitude": lons}
    spatial_dims = ("latitude", "longitude")

    if "time" in target_grid.coords and target_grid.time.size > 0:
        time_val = target_grid.time.values.flatten()[0]
    elif "valid_time" in target_grid.coords:
        time_val = target_grid.valid_time.values.flatten()[0]
    elif "lead_time" in target_grid.coords:
        time_val = target_grid.lead_time.values.flatten()[0]
    else:
        time_val = pd.Timestamp.now()

    forecast_month_idx = pd.to_datetime(time_val).month - 1

    clim_risk_factor = np.zeros((len(lats), len(lons)))

    if os.path.exists(clim_nc_path):
        clim_ds = xr.open_dataset(clim_nc_path)
        monthly_clim = clim_ds["fire_density"].isel(time=forecast_month_idx)

        if "lat" in monthly_clim.dims:
            monthly_clim = monthly_clim.rename(
                {"lat": "latitude", "lon": "longitude"}
            )

        clim_interp = monthly_clim.interp(
            latitude=lats, longitude=lons, method="nearest"
        ).fillna(0.0)

        max_clim_val = (
            float(monthly_clim.max()) if float(monthly_clim.max()) > 0 else 1.0
        )

        raw_vals = np.squeeze(clim_interp.values)
        clim_risk_factor = np.clip(raw_vals / max_clim_val, 0.0, 1.0)

    firms_url = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Southern_Africa_24h.csv"
    active_fire_mask = np.zeros((len(lats), len(lons)), dtype=bool)

    try:
        resp = requests.get(firms_url, timeout=10)
        if resp.status_code == 200:
            df_firms = pd.read_csv(io.StringIO(resp.text))
            mad_fires = df_firms[
                (df_firms["latitude"] >= -25.7)
                & (df_firms["latitude"] <= -11.9)
                & (df_firms["longitude"] >= 43.1)
                & (df_firms["longitude"] <= 50.8)
            ]

            for _, fire in mad_fires.iterrows():
                lat_idx = (np.abs(lats - fire["latitude"])).argmin()
                lon_idx = (np.abs(lons - fire["longitude"])).argmin()
                active_fire_mask[lat_idx, lon_idx] = True
    except Exception as e:
        logger.warning(
            f"Could not fetch FIRMS data ({e}). Proceeding without active fire mask."
        )

    ffmc_base = 85.0
    dmc_base = 20.0 + (clim_risk_factor * 40.0)
    dc_base = 150.0 + (clim_risk_factor * 250.0)

    ffmc_arr = np.where(active_fire_mask, 92.0, ffmc_base)
    dmc_arr = np.where(active_fire_mask, np.maximum(dmc_base, 70.0), dmc_base)
    dc_arr = np.where(active_fire_mask, np.maximum(dc_base, 450.0), dc_base)

    ffmc_arr = np.squeeze(ffmc_arr)
    dmc_arr = np.squeeze(dmc_arr)
    dc_arr = np.squeeze(dc_arr)
    active_fire_mask = np.squeeze(active_fire_mask)

    ffmc0 = xr.DataArray(
        ffmc_arr,
        coords=spatial_coords,
        dims=spatial_dims,
        attrs={"units": "dimensionless"},
    )
    dmc0 = xr.DataArray(
        dmc_arr,
        coords=spatial_coords,
        dims=spatial_dims,
        attrs={"units": "dimensionless"},
    )
    dc0 = xr.DataArray(
        dc_arr,
        coords=spatial_coords,
        dims=spatial_dims,
        attrs={"units": "dimensionless"},
    )
    firms_mask_da = xr.DataArray(
        active_fire_mask, coords=spatial_coords, dims=spatial_dims
    )

    return ffmc0, dmc0, dc0, firms_mask_da


def calculate_fopi_improved(
    fwi, ndvi_ds, active_fire_mask, k=0.12, fwi_50=18.0
):
    """Calculates smoothed, calibrated FOPI index."""
    ndvi_key = "NDVI" if "NDVI" in ndvi_ds else list(ndvi_ds.data_vars)[0]
    ndvi_interp = ndvi_ds[ndvi_key].interp(
        latitude=fwi.latitude, longitude=fwi.longitude, method="nearest"
    ).fillna(0.2)
    ndvi_clean = np.clip(ndvi_interp, 0.0, 1.0)

    curing_factor = np.clip((0.85 - ndvi_clean) / 0.65, 0.0, 1.0)
    hazard_score = fwi * (0.3 + 0.7 * curing_factor)

    fire_mask_values = active_fire_mask.values.astype(float)
    smoothed_fire_risk = gaussian_filter(fire_mask_values, sigma=1.0)
    max_val = smoothed_fire_risk.max()
    if max_val > 0:
        smoothed_fire_risk = smoothed_fire_risk / max_val

    fire_boost_da = xr.DataArray(
        smoothed_fire_risk,
        coords=active_fire_mask.coords,
        dims=active_fire_mask.dims,
    )
    boosted_hazard = hazard_score + (fire_boost_da * 12.0)

    fopi = 1.0 / (1.0 + np.exp(-k * (boosted_hazard - fwi_50)))
    return fopi

def compute_fire_indices(force_recompute=False):
    ## INitialization ngamba
    cache = get_cached_indices()
    if not force_recompute and cache['fwi'] is not None and cache['fopi'] is not None :
        return cache['fwi'], cache['fopi'], cache['aifs'], cache['ndvi']

    logger.info('Computing FWI and FOPI ....')

    # 1. Fetch preloaded/cached datasets
    aifs_ds = get_aifs_dataset()
    ndvi_ds = get_ndvi_dataset()

    # 2. Extract required meteorological variables using exact Zarr variable names
    # Temperature (Check for Celsius first, otherwise convert Kelvin from temperature_2m)
    if "temp_c" in aifs_ds:
        tas = aifs_ds["temp_c"]
    elif "temperature_2m" in aifs_ds:
        tas = aifs_ds["temperature_2m"] - 273.15 if aifs_ds["temperature_2m"].mean() > 200 else aifs_ds["temperature_2m"]
    elif "2t" in aifs_ds:
        tas = aifs_ds["2t"] - 273.15 if aifs_ds["2t"].mean() > 200 else aifs_ds["2t"]
    elif "tas" in aifs_ds:
        tas = aifs_ds["tas"] - 273.15 if aifs_ds["tas"].mean() > 200 else aifs_ds["tas"]
    else:
        raise KeyError("Temperature variable not found in AIFS dataset.")
    tas.attrs["units"] = "degC"

    # Precipitation
    if "precipitation_surface" in aifs_ds:
        pr = aifs_ds["precipitation_surface"]
    elif "tp" in aifs_ds:
        pr = aifs_ds["tp"]
    elif "pr" in aifs_ds:
        pr = aifs_ds["pr"]
    else:
        raise KeyError("Precipitation variable not found in AIFS dataset.")
    pr.attrs["units"] = "mm/day"

    # Surface Wind Speed
    if "wind_speed_10m" in aifs_ds:
        sfcWind = aifs_ds["wind_speed_10m"]
    elif "wind_u_10m" in aifs_ds and "wind_v_10m" in aifs_ds:
        sfcWind = np.sqrt(aifs_ds["wind_u_10m"] ** 2 + aifs_ds["wind_v_10m"] ** 2)
    elif "10u" in aifs_ds and "10v" in aifs_ds:
        sfcWind = np.sqrt(aifs_ds["10u"] ** 2 + aifs_ds["10v"] ** 2)
    else:
        sfcWind = xr.ones_like(tas) * 2.0
    sfcWind.attrs["units"] = "m/s"

    # Relative Humidity
    if "relative_humidity" in aifs_ds:
        hurs = aifs_ds["relative_humidity"]
    elif "hurs" in aifs_ds:
        hurs = aifs_ds["hurs"]
    elif "dew_point_temperature_2m" in aifs_ds:
        d2m = aifs_ds["dew_point_temperature_2m"] - 273.15 if aifs_ds["dew_point_temperature_2m"].mean() > 200 else aifs_ds["dew_point_temperature_2m"]
        hurs = 100 * (np.exp((17.625 * d2m) / (243.04 + d2m)) / np.exp((17.625 * tas) / (243.04 + tas)))
    else:
        hurs = xr.ones_like(tas) * 50.0
    hurs = np.clip(hurs, 1.0, 100.0)
    hurs.attrs["units"] = "%"

    # 3. Format time dimensions for xclim compatibility
    input_arrays = [tas, pr, sfcWind, hurs]
    prepared_arrays = []

    for da in input_arrays:
        if "lead_time" in da.dims and "time" not in da.dims:
            da = da.rename({"lead_time": "time"})

        if "time" in da.dims:
            if not np.issubdtype(da.time.dtype, np.datetime64):
                if "valid_time" in da.coords:
                    vtime = da.valid_time
                    if vtime.ndim > 1:
                        vtime_1d = vtime.isel({d: 0 for d in vtime.dims if d != "time"})
                        da = da.assign_coords(time=vtime_1d.values)
                    else:
                        da = da.assign_coords(time=vtime.values)
                else:
                    start_date = pd.Timestamp.now().floor("D")
                    time_steps = pd.date_range(
                        start=start_date, periods=da.sizes["time"], freq="6h"
                    )
                    da = da.assign_coords(time=("time", time_steps))

        prepared_arrays.append(da)

    tas, pr, sfcWind, hurs = prepared_arrays

    # --- DEFINE lat BEFORE USING IT ---
    if "latitude" in tas.coords:
        lat = tas.latitude
    elif "lat" in tas.coords:
        lat = tas.lat
    else:
        raise KeyError("Latitude coordinate ('latitude' or 'lat') not found in dataset.")

    # 4. Generate dynamic seeds (ffmc0, dmc0, dc0)
    ffmc0, dmc0, dc0, firms_mask_da = generate_dynamic_cffdrs_seeds(
        tas, CLIM_NC_PATH
    )

    # 5. Compute CFFDRS FWI indices via xclim
    dc, dmc, ffmc, isi, bui, fwi = xclim.indices.cffwis_indices(
        tas=tas,
        pr=pr,
        sfcWind=sfcWind,
        hurs=hurs,
        lat=lat,
        ffmc0=ffmc0,
        dmc0=dmc0,
        dc0=dc0,
    )

    # 6. Compute FOPI
    fopi_ds = calculate_fopi_improved(
        fwi=fwi,
        ndvi_ds=ndvi_ds,
        active_fire_mask=firms_mask_da,
        k=0.12,
        fwi_50=18.0,
    )

    set_cached_indices(fwi, fopi_ds, aifs_ds, ndvi_ds)

    return fwi, fopi_ds, aifs_ds, ndvi_ds


@fire_indices_bp.route("/plot", methods=["GET"])
def get_fire_index_plot():
    index_type = request.args.get("index", "fwi").lower()  # 'fwi' or 'fopi'
    day = int(request.args.get("day", 0))

    cache_key = f"{index_type}_day_{day}"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        fwi_ds, fopi_ds, _, _ = compute_fire_indices()

        # Handle time dimension indexing safely
        target_ds = fwi_ds if index_type == "fwi" else fopi_ds
        time_dim = "time" if "time" in target_ds.dims else "lead_time"
        field = target_ds.isel({time_dim: day})

        # Clip field to Madagascar land boundaries
        field = clip_to_land_shapefile(
            field, layer_key="districtMdg", target_resolution=0.05
        )

        lats = field.latitude.values
        lons = field.longitude.values
        bounds = [
            [float(np.min(lats)), float(np.min(lons))],
            [float(np.max(lats)), float(np.max(lons))],
        ]

        data_vals = field.values

        # Styling depending on index
        if index_type == "fwi":
            levels = [0, 5, 11, 19, 30, 50, 100]
            colors = [
                "#2b83ba",
                "#abdda4",
                "#ffffbf",
                "#fdae61",
                "#d7191c",
                "#800020",
            ]
            labels = ["Low", "Mod", "High", "Very High", "Extreme", "Extreme+"]
            title = "Fire Weather Index (FWI)"
            unit = "FWI"
            cmap = mcolors.ListedColormap(colors)
            norm = mcolors.BoundaryNorm(levels, cmap.N)
        else:  # FOPI
            levels = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            colors = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]
            labels = [
                "Low (<0.2)",
                "Mod (0.2-0.4)",
                "High (0.4-0.6)",
                "Very High (0.6-0.8)",
                "Extreme (>0.8)",
            ]
            title = "Fire Occurrence Probability Index (FOPI)"
            unit = "Probability"
            cmap = mcolors.ListedColormap(colors)
            norm = mcolors.BoundaryNorm(levels, cmap.N)

        cmap.set_bad(color=(1, 1, 1, 0))

        # Render transparent PNG raster
        fig = plt.figure(figsize=(6, 6), frameon=False)
        ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
        ax.set_axis_off()
        fig.add_axes(ax)

        if hasattr(data_vals, 'squeeze'):
            data_vals = data_vals.squeeze()

        ax.imshow(
            data_vals,
            cmap=cmap,
            norm=norm,
            origin="upper",
            aspect="auto",
            interpolation="nearest",
        )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, transparent=True)
        buf.seek(0)
        plt.close(fig)

        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{img_base64}"

        # Build legend ticks
        legend_ticks = []
        for i in range(len(colors)):
            val_repr = (
                (levels[i] + levels[i + 1]) / 2
                if i < len(levels) - 1
                else levels[i]
            )
            rgba = cmap(norm(val_repr))
            legend_ticks.append(
                {"value": labels[i], "color": mcolors.to_hex(rgba)}
            )

        response_payload = {
            "status": "success",
            "bounds": bounds,
            "imageUrl": data_url,
            "legend": legend_ticks,
            "unit": unit,
            "title": f"Day {day} {title}",
        }

        PLOT_CACHE[cache_key] = response_payload
        return jsonify(response_payload)

    except Exception as e:
        logger.error(
            f"Failed to calculate or render {index_type} plot: {e}",
            exc_info=True,
        )
        return jsonify({"status": "error", "error": str(e)}), 500

