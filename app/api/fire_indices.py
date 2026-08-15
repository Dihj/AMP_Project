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

# Madagascar (Indian/Antananarivo) is a fixed UTC+3 offset year-round (no DST).
LOCAL_UTC_OFFSET_HOURS = 3
# day 0 = today, day 1 = tomorrow, day 2 = day after tomorrow.
FORECAST_HORIZON_DAYS = 3


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
        # Opened as a context manager so the file handle is always released -
        # previously this leaked a handle (and a lazy dataset reference) on
        # every cache-miss recompute.
        with xr.open_dataset(clim_nc_path) as clim_ds:
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
    ndvi_da = ndvi_ds[ndvi_key]
    # Defensive rename, matching the same lat/lon normalization already applied
    # to the climatology dataset - NDVI sources sometimes use lat/lon instead
    # of latitude/longitude.
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


def _drop_singleton_init_time(da):
    if "init_time" in da.dims:
        da = da.squeeze("init_time", drop=True)
    return da


def _build_local_day_groups(lead_time_da, init_time_val, max_days=FORECAST_HORIZON_DAYS):
    """Group native-cadence forecast steps (lead_time) into local calendar days.

    The Canadian FWI System (xclim.indices.cffwis_indices) is a DAILY recursive
    model: it must be driven by one value per calendar day, not per raw forecast
    step. AIFS delivers sub-daily steps, so we bucket them here.

    Returns:
        day_dates:    list of np.datetime64 (local midnight), day0 ... dayN-1
        day_step_idx: list of integer index arrays into lead_time, one per day
        local_time:   pandas.DatetimeIndex of each step's local valid time
    """
    init_ts = pd.Timestamp(init_time_val)
    valid_time_utc = init_ts + pd.to_timedelta(lead_time_da.values)
    local_time = pd.DatetimeIndex(valid_time_utc) + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    local_date = local_time.normalize()

    unique_dates = local_date.unique().sort_values()[:max_days]

    day_dates, day_step_idx = [], []
    for d in unique_dates:
        idx = np.where(local_date == d)[0]
        if len(idx) == 0:
            continue
        day_dates.append(d.to_datetime64())
        day_step_idx.append(idx)

    return day_dates, day_step_idx, local_time


def _reduce_noon(da, day_step_idx, local_time, dim="lead_time"):
    """For each local day, pick the forecast step closest to local solar noon
    (12:00) - the standard reference time for CFFWI daily temperature/RH/wind."""
    picks = []
    for idx in day_step_idx:
        hours = np.array([local_time[i].hour + local_time[i].minute / 60.0 for i in idx])
        chosen = int(idx[int(np.argmin(np.abs(hours - 12.0)))])
        picks.append(da.isel({dim: chosen}).drop_vars(dim, errors="ignore"))
    return xr.concat(picks, dim="time")


def _reduce_daily_precip(cumulative_mm_da, day_step_idx, dim="lead_time"):
    """Daily total precip (mm) from a monotonically cumulative field: each day's
    total = cumulative value at day-end minus cumulative value at previous day's
    end (0 for day 0, i.e. accumulation is measured from forecast init_time)."""
    totals = []
    prev_end = None
    for idx in day_step_idx:
        end_val = cumulative_mm_da.isel({dim: int(idx[-1])}).drop_vars(dim, errors="ignore")
        start_val = xr.zeros_like(end_val) if prev_end is None else prev_end
        totals.append(end_val - start_val)
        prev_end = end_val
    return xr.concat(totals, dim="time")


def compute_fire_indices(force_recompute=False):
    cache = get_cached_indices()
    if not force_recompute and cache['fwi'] is not None and cache['fopi'] is not None:
        return cache['fwi'], cache['fopi'], cache['aifs'], cache['ndvi']

    logger.info('Computing FWI and FOPI (daily, day 0/1/2) ....')

    # 1. Fetch preloaded/cached datasets
    aifs_ds = get_aifs_dataset()
    ndvi_ds = get_ndvi_dataset()

    # 2. Extract native-cadence (per lead_time step) fields.
    # Per the AIFS data catalog: temperature_2m / dew_point_temperature_2m are
    # already degree_Celsius, wind components are m/s, and
    # precipitation_surface_mm (built in aifs_frcst.download_and_save_aifs) is a
    # cumulative mm total since init_time - no further unit guessing needed here.
    if "temp_2m_celsius" in aifs_ds:
        tas = aifs_ds["temp_2m_celsius"]
    elif "temperature_2m" in aifs_ds:
        tas = aifs_ds["temperature_2m"]
    else:
        raise KeyError("Temperature variable not found in AIFS dataset.")
    tas = _drop_singleton_init_time(tas)
    tas.attrs["units"] = "degC"
    tas_mean = float(tas.mean())
    if tas_mean > 60 or tas_mean < -60:
        logger.warning(
            f"Temperature mean ({tas_mean:.1f}) is out of a plausible Celsius "
            "range - verify AIFS variable units before trusting FWI output."
        )

    if "precipitation_surface_mm" in aifs_ds:
        pr_cumulative = aifs_ds["precipitation_surface_mm"]
    elif "tp" in aifs_ds:
        pr_cumulative = aifs_ds["tp"]
    elif "pr" in aifs_ds:
        pr_cumulative = aifs_ds["pr"]
    else:
        raise KeyError("Precipitation variable not found in AIFS dataset.")
    pr_cumulative = _drop_singleton_init_time(pr_cumulative)

    if "wind_speed_10m" in aifs_ds:
        sfcWind = aifs_ds["wind_speed_10m"]
    elif "wind_u_10m" in aifs_ds and "wind_v_10m" in aifs_ds:
        sfcWind = np.sqrt(aifs_ds["wind_u_10m"] ** 2 + aifs_ds["wind_v_10m"] ** 2)
    else:
        sfcWind = xr.ones_like(tas) * 2.0
    sfcWind = _drop_singleton_init_time(sfcWind)
    sfcWind.attrs["units"] = "m/s"

    if "relative_humidity_2m" in aifs_ds:
        hurs = aifs_ds["relative_humidity_2m"]
    elif "temperature_2m" in aifs_ds and "dew_point_temperature_2m" in aifs_ds:
        t2m = aifs_ds["temperature_2m"]  # degC
        d2m = aifs_ds["dew_point_temperature_2m"]  # degC
        hurs = 100 * (
            np.exp((17.625 * d2m) / (243.04 + d2m))
            / np.exp((17.625 * t2m) / (243.04 + t2m))
        )
    else:
        hurs = xr.ones_like(tas) * 50.0
    hurs = _drop_singleton_init_time(hurs)
    hurs = np.clip(hurs, 1.0, 100.0)
    hurs.attrs["units"] = "%"

    # 3. Bucket native-cadence steps into local calendar days 0/1/2.
    if "lead_time" not in aifs_ds.dims:
        raise KeyError("Expected 'lead_time' dimension in AIFS dataset.")
    lead_time_da = aifs_ds["lead_time"]

    if "init_time" in aifs_ds.coords:
        init_time_val = np.atleast_1d(aifs_ds["init_time"].values)[0]
    else:
        init_time_val = pd.Timestamp.now().floor("D")

    day_dates, day_step_idx, local_time = _build_local_day_groups(
        lead_time_da, init_time_val, max_days=FORECAST_HORIZON_DAYS
    )
    if len(day_dates) == 0:
        raise RuntimeError("No forecast steps available to build daily FWI/FOPI series.")

    # 4. Reduce each variable to one value per local calendar day.
    # NOTE: when aifs_ds comes from the cached-zarr path (xr.open_zarr without
    # .load()), it's dask-backed. Each per-day .isel() pick becomes its own
    # separate dask chunk, and concatenating them along the new "time"
    # dimension leaves "time" split across multiple chunks. xclim's
    # cffwis_indices runs a recursive day-to-day apply_ufunc with "time" as a
    # core dimension, which dask requires to be a SINGLE chunk - hence the
    # "consists of multiple chunks, but is also a core dimension" error.
    # These daily arrays are tiny (<=3 timesteps x spatial grid) at this
    # point, so materializing them eagerly is cheap and simplest.
    daily_tas = _reduce_noon(tas, day_step_idx, local_time).load()
    daily_wind = _reduce_noon(sfcWind, day_step_idx, local_time).load()
    daily_hurs = _reduce_noon(hurs, day_step_idx, local_time).load()
    daily_pr = _reduce_daily_precip(pr_cumulative, day_step_idx).load()

    time_coord = np.array(day_dates, dtype="datetime64[ns]")
    for da in (daily_tas, daily_wind, daily_hurs, daily_pr):
        da.coords["time"] = ("time", time_coord)

    daily_tas.attrs["units"] = "degC"
    daily_wind.attrs["units"] = "m/s"
    daily_hurs.attrs["units"] = "%"
    daily_pr.attrs["units"] = "mm/day"

    if "latitude" in daily_tas.coords:
        lat = daily_tas.latitude
    elif "lat" in daily_tas.coords:
        lat = daily_tas.lat
    else:
        raise KeyError("Latitude coordinate ('latitude' or 'lat') not found in dataset.")

    # 5. Generate dynamic seeds (ffmc0, dmc0, dc0), keyed off day 0 (today)
    ffmc0, dmc0, dc0, firms_mask_da = generate_dynamic_cffdrs_seeds(
        daily_tas, CLIM_NC_PATH
    )

    # 6. Compute CFFDRS FWI indices via xclim, recursively over day 0, 1, 2
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

    # 7. Compute FOPI
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

        # lats/lons are pixel CENTERS, but Leaflet's ImageOverlay bounds are
        # pixel EDGES. Using center min/max directly shifts the whole raster
        # by half a pixel relative to true geographic points (e.g. FIRMS
        # active-fire markers plotted from raw lat/lon) - this is the likely
        # cause of the FWI/FOPI raster looking offset from the fire dots.
        lat_res = float(np.abs(np.mean(np.diff(lats)))) if len(lats) > 1 else 0.0
        lon_res = float(np.abs(np.mean(np.diff(lons)))) if len(lons) > 1 else 0.0

        bounds = [
            [float(np.min(lats)) - lat_res / 2, float(np.min(lons)) - lon_res / 2],
            [float(np.max(lats)) + lat_res / 2, float(np.max(lons)) + lon_res / 2],
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
            interpolation="bilinear",
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

    