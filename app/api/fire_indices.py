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

from app.api.aifs_frcst import (
    get_aifs_dataset,
    get_daily_aifs_dataset,
    FORECAST_HORIZON_DAYS,
)
from app.api.ndvi import get_ndvi_dataset

fire_indices_bp = Blueprint("fire_indices", __name__, url_prefix="/api/fire-indices")
logger = logging.getLogger(__name__)

PLOT_CACHE = {}
FIELD_CACHE = {}  # Caches per-day FWI/FOPI DataArrays
CLIM_NC_PATH = "data/netcdf/climatology/FIRE_climV2.nc"


def generate_dynamic_cffdrs_seeds(target_grid, clim_nc_path):
    """
    Generates spatially dynamic initial seed arrays (ffmc0, dmc0, dc0) for
    xclim, using 24h active FIRMS fire detections AND the long-term
    MONTHLY fire climatology stored in FIRE_climV2.nc.

    `target_grid` is already the ~0.05deg (5km), shapefile-masked daily
    temperature field, so seeds and the FIRMS point-to-cell snapping below
    are built directly at display resolution.

    The climatology month is read directly off `target_grid`'s own real
    calendar-date time coordinate (day 0's date), so the seed always
    reflects the correct calendar month regardless of when the forecast
    happens to run.
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
        # Opened as a context manager so the file handle is always released.
        with xr.open_dataset(clim_nc_path) as clim_ds:
            # FIRE_climV2.nc's "fire_density" variable is indexed by month
            # (12 monthly climatological layers) - select the layer matching
            # this forecast's calendar month.
            monthly_clim = clim_ds["fire_density"].isel(time=forecast_month_idx)

            if "lat" in monthly_clim.dims:
                monthly_clim = monthly_clim.rename(
                    {"lat": "latitude", "lon": "longitude"}
                )

            clim_interp = monthly_clim.interp(
                latitude=lats, longitude=lons, method="linear"
            ).fillna(0.0)

            max_clim_val = (
                float(monthly_clim.max()) if float(monthly_clim.max()) > 0 else 1.0
            )

            raw_vals = np.squeeze(clim_interp.values)
            clim_risk_factor = np.clip(raw_vals / max_clim_val, 0.0, 1.0)
    else:
        logger.warning(
            f"Fire climatology file '{clim_nc_path}' not found - seeding "
            "with zero climatological risk factor (seeds will rely on FIRMS "
            "active-fire detections only)."
        )

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

'''
def calculate_fopi_improved(
    fwi, ndvi_ds, active_fire_mask, k=0.12, fwi_50=18.0
):
    """Calculates smoothed, calibrated FOPI index."""
    ndvi_key = "NDVI" if "NDVI" in ndvi_ds else list(ndvi_ds.data_vars)[0]
    ndvi_da = ndvi_ds[ndvi_key]
    if "lat" in ndvi_da.dims:
        ndvi_da = ndvi_da.rename({"lat": "latitude", "lon": "longitude"})

    ndvi_interp = ndvi_da.interp(
        latitude=fwi.latitude, longitude=fwi.longitude, method="linear"
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
'''
def calculate_fopi_improved(
    fwi, ndvi_ds, active_fire_mask, k=0.15, fwi_50=15.0
):
    """Calculates smoothed, calibrated FOPI index."""
    ndvi_key = "NDVI" if "NDVI" in ndvi_ds else list(ndvi_ds.data_vars)[0]
    ndvi_da = ndvi_ds[ndvi_key]
    if "lat" in ndvi_da.dims:
        ndvi_da = ndvi_da.rename({"lat": "latitude", "lon": "longitude"})

    ndvi_interp = ndvi_da.interp(
        latitude=fwi.latitude, longitude=fwi.longitude, method="linear"
    ).fillna(0.2)
    ndvi_clean = np.clip(ndvi_interp, 0.0, 1.0)

    # Curing factor: Higher when vegetation is dry (low NDVI)
    curing_factor = np.clip((0.85 - ndvi_clean) / 0.65, 0.0, 1.0)
    
    # Scale hazard so moderate FWI with high curing maps effectively
    hazard_score = fwi * (0.4 + 0.8 * curing_factor)

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
    
    # Add active fire boost
    boosted_hazard = hazard_score + (fire_boost_da * 15.0)

    # Logistic transformation with adjusted midpoint
    fopi = 1.0 / (1.0 + np.exp(-k * (boosted_hazard - fwi_50)))
    return fopi




def compute_fire_indices(force_recompute=False):
    cache = get_cached_indices()
    if not force_recompute and cache['fwi'] is not None and cache['fopi'] is not None:
        return cache['fwi'], cache['fopi'], cache['aifs'], cache['ndvi']

    logger.info(f'Computing FWI and FOPI (daily, day 0..{FORECAST_HORIZON_DAYS - 1}) ....')

    aifs_ds = get_aifs_dataset()
    ndvi_ds = get_ndvi_dataset()

    # Pull the SAME canonical daily dataset (daily MAX temp, daily MIN RH,
    # daily mean wind, daily total precip; local calendar days; already
    # ~0.05deg/5km and shapefile-masked) that the weather map and the
    # extraction endpoint use - see get_daily_aifs_dataset() in
    # aifs_frcst.py.
    #
    # Daily max temperature + daily min relative humidity is the standard
    # CFFWI daily-input proxy for "noon LST" conditions (minimum RH
    # typically coincides with maximum temperature near solar noon) - this
    # is the officially documented approach for driving the Canadian Fire
    # Weather Index System from datasets where a specific noon-LST
    # sub-daily selection isn't used directly.
    daily_ds = get_daily_aifs_dataset()
    daily_tas = daily_ds["temp_2m_celsius"]        # daily MAX
    daily_wind = daily_ds["wind_speed_10m"]        # daily MEAN
    daily_hurs = daily_ds["relative_humidity_2m"]  # daily MIN
    daily_pr = daily_ds["precipitation_surface_mm"].copy()  # daily TOTAL
    daily_pr.attrs["units"] = "mm/day"  # unit string xclim expects for precip

    if "latitude" in daily_tas.coords:
        lat = daily_tas.latitude
    elif "lat" in daily_tas.coords:
        lat = daily_tas.lat
    else:
        raise KeyError("Latitude coordinate ('latitude' or 'lat') not found in dataset.")

    # Generate dynamic seeds (ffmc0, dmc0, dc0) using FIRMS + the monthly
    # fire climatology, keyed off day 0 (today)'s calendar month.
    ffmc0, dmc0, dc0, firms_mask_da = generate_dynamic_cffdrs_seeds(
        daily_tas, CLIM_NC_PATH
    )

    # Compute CFFDRS FWI indices via xclim, recursively over day 0..N-1.
    # xclim automatically applies the correct month-dependent day-length
    # factors for DC/DMC internally, using `lat` and the real calendar
    # dates on daily_tas/daily_pr/etc.'s "time" coordinate - no separate
    # action needed beyond passing real dates, which get_daily_aifs_dataset()
    # already does.
    dc, dmc, ffmc, isi, bui, fwi = xclim.indices.cffwis_indices(
        tas=daily_tas,
        pr=daily_pr,
        sfcWind=daily_wind,
        hurs=daily_hurs,
        lat=lat,
        ffmc0=ffmc0,
        dmc0=dmc0,
        dc0=dc0,
    )

    # Compute FOPI
    fopi_ds = calculate_fopi_improved(
        fwi=fwi,
        ndvi_ds=ndvi_ds,
        active_fire_mask=firms_mask_da,
        k=0.12,
        fwi_50=18.0,
    )

    set_cached_indices(fwi, fopi_ds, aifs_ds, ndvi_ds)
    FIELD_CACHE.clear()

    return fwi, fopi_ds, aifs_ds, ndvi_ds


def get_fire_index_field(index_type, day_num):
    """
    Returns the FWI/FOPI field for `index_type` / `day_num` - already at
    the ~0.05deg (5km), shapefile-masked resolution inherited from the
    daily AIFS dataset. Used identically by the map (/plot) and by
    point/polygon extraction (see app.api.forecast).
    """
    cache_key = f"{index_type}_day{day_num}"
    if cache_key in FIELD_CACHE:
        return FIELD_CACHE[cache_key]

    fwi_ds, fopi_ds, _, _ = compute_fire_indices()
    target_ds = fwi_ds if index_type == "fwi" else fopi_ds
    time_dim = "time" if "time" in target_ds.dims else "lead_time"
    field = target_ds.isel({time_dim: day_num})

    FIELD_CACHE[cache_key] = field
    return field


@fire_indices_bp.route("/plot", methods=["GET"])
def get_fire_index_plot():
    index_type = request.args.get("index", "fwi").lower()  # 'fwi' or 'fopi'
    day = int(request.args.get("day", 0))

    cache_key = f"{index_type}_day_{day}"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        field = get_fire_index_field(index_type, day)

        lats = field.latitude.values
        lons = field.longitude.values

        # lats/lons are pixel CENTERS, but Leaflet's ImageOverlay bounds are
        # pixel EDGES. Using center min/max directly shifts the whole raster
        # by half a pixel relative to true geographic points (e.g. FIRMS
        # active-fire markers plotted from raw lat/lon).
        lat_res = float(np.abs(np.mean(np.diff(lats)))) if len(lats) > 1 else 0.0
        lon_res = float(np.abs(np.mean(np.diff(lons)))) if len(lons) > 1 else 0.0

        bounds = [
            [float(np.min(lats)) - lat_res / 2, float(np.min(lons)) - lon_res / 2],
            [float(np.max(lats)) + lat_res / 2, float(np.max(lons)) + lon_res / 2],
        ]

        data_vals = field.values

        # Styling depending on index
        if index_type == "fwi":
            # Matches the FWI gauge scale used in forecastModalManager.js -
            # keep these two in sync if either changes.
            levels = [0, 11.2, 21.3, 38.0, 50.0, 70.0, 80.0]
            colors = [
                "#98FBB2",  # Low
                "#D2E351",  # Moderate
                "#E6A900",  # High
                "#D66610",  # Very High
                "#B4070C",  # Extreme
                "#320212",  # Extreme+
            ]
            labels = ["Low", "Moderate", "High", "Very High", "Extreme", "Extreme+"]
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
            interpolation="bilinear",
        )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, transparent=True)
        buf.seek(0)
        plt.close(fig)

        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{img_base64}"

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

        # Real calendar date instead of a relative "Day N" label.
        real_date = pd.Timestamp(field.time.values).strftime("%Y-%m-%d")

        response_payload = {
            "status": "success",
            "bounds": bounds,
            "imageUrl": data_url,
            "legend": legend_ticks,
            "unit": unit,
            "title": f"{title} ({real_date})",
            "date": real_date,
            "day_index": day,
        }

        PLOT_CACHE[cache_key] = response_payload
        return jsonify(response_payload)

    except Exception as e:
        logger.error(
            f"Failed to calculate or render {index_type} plot: {e}",
            exc_info=True,
        )
        return jsonify({"status": "error", "error": str(e)}), 500

    