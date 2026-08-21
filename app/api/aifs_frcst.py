#app/api/aifs_frcst.py

import base64
import io
import logging
import os
import time
import icechunk
import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import geopandas as gpd
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from scipy.ndimage import median_filter
import xarray as xr
from flask import Blueprint, jsonify, request
from app.scripts.spatial_calc import get_geojson_from_shapefile

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

aifs_bp = Blueprint("aifs_forecast", __name__)

# Memory cache
AIFS_CACHE = {"last_fetched": 0, "dataset": None}
PLOT_CACHE = {}
FIELD_CACHE = {}
DAILY_CACHE = {"key": None, "dataset": None}
GEOMETRY_MASK_CACHE = None

DEBUG_MODE = os.environ.get("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")
CACHE_TTL = 21600  # 06 hours aloh

FORECAST_DIR = os.path.join("data", "forecast")
LOCAL_ZARR_PATH = os.path.join(FORECAST_DIR, "aifs_raw_latest.zarr")

MADAGASCAR_BBOX = {
    "lat_north": -10.0,
    "lat_south": -26.0,
    "lon_west": 43.0,
    "lon_east": 51.0,
}

LOCAL_UTC_OFFSET_HOURS = 3
MAX_LEAD_HOURS = 96
FORECAST_HORIZON_DAYS = 4
TARGET_GRID_RESOLUTION_DEG = 0.05


def clear_zarr_encodings(dataset):
    """Clear remote S3 chunk encodings so Zarr can write fresh local structures."""
    dataset.encoding.clear()
    for var in dataset.variables:
        dataset[var].encoding.clear()
    return dataset


def get_cached_land_mask(lats, lons, layer_key="districtMdg"):

    global GEOMETRY_MASK_CACHE

    if GEOMETRY_MASK_CACHE is not None:
        return GEOMETRY_MASK_CACHE

    logger.info("Building land mask from districtMdg shapefile...")
    try:
        geojson_data = get_geojson_from_shapefile(layer_key)
        gdf = gpd.GeoDataFrame.from_features(geojson_data["features"], crs="EPSG:4326")

        height = len(lats)
        width = len(lons)

        min_lon, max_lon = float(np.min(lons)), float(np.max(lons))
        min_lat, max_lat = float(np.min(lats)), float(np.max(lats))

        transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)
        geometries = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]

        mask = geometry_mask(
            geometries,
            out_shape=(height, width),
            transform=transform,
            invert=False,
        )

        GEOMETRY_MASK_CACHE = mask
        return mask
    except Exception as e:
        logger.error(f"Failed to generate land mask: {e}")
        return None


def regrid_and_mask_to_land(ds, layer_key="districtMdg", target_resolution=TARGET_GRID_RESOLUTION_DEG,
                             bbox=MADAGASCAR_BBOX):

    target_lats = np.arange(bbox["lat_north"], bbox["lat_south"] - target_resolution, -target_resolution)
    target_lons = np.arange(bbox["lon_west"], bbox["lon_east"] + target_resolution, target_resolution)

    regridded = ds.interp(latitude=target_lats, longitude=target_lons, method="linear")

    is_ocean = get_cached_land_mask(target_lats, target_lons, layer_key)
    if is_ocean is not None:
        is_ocean_da = xr.DataArray(
            is_ocean,
            coords={"latitude": target_lats, "longitude": target_lons},
            dims=("latitude", "longitude"),
        )
        regridded = regridded.where(~is_ocean_da)
    else:
        logger.warning("Land mask unavailable - saving regridded data WITHOUT shapefile masking.")

    return regridded

PRECIP_SPIKE_RATIO = 5.0
PRECIP_SPIKE_FLOOR_KG_M2_S = 5.0 / 3600.0


def despike_precip_rate(precip_da, neighborhood=3):

    def _despike_2d(arr2d):
        local_median = median_filter(arr2d, size=neighborhood, mode="nearest")
        threshold = np.maximum(local_median * PRECIP_SPIKE_RATIO, PRECIP_SPIKE_FLOOR_KG_M2_S)
        spike_mask = arr2d > threshold
        if np.any(spike_mask):
            logger.warning(
                f"[Despike] Clipped {int(spike_mask.sum())} isolated precipitation "
                "grid-cell spike(s) (value far above local neighborhood median, "
                "with no spatial coherence - typical of AI-model artifacts, "
                "especially at longer lead times)."
            )
        return np.where(spike_mask, local_median, arr2d)

    cleaned = xr.apply_ufunc(
        _despike_2d,
        precip_da,
        input_core_dims=[["latitude", "longitude"]],
        output_core_dims=[["latitude", "longitude"]],
        vectorize=True,
    )
    cleaned.attrs = precip_da.attrs
    return cleaned


def calculate_relative_humidity(t2m_c, d2m_c):

    e = 6.112 * np.exp((17.67 * d2m_c) / (d2m_c + 243.5))
    es = 6.112 * np.exp((17.67 * t2m_c) / (t2m_c + 243.5))
    rh = (e / es) * 100.0
    return np.clip(rh, 0.0, 100.0)


def download_and_save_aifs():

    t_start = time.time()
    logger.info("Connecting to s3://dynamical-ecmwf-aifs-single via Icechunk...")

    storage = icechunk.s3_storage(
        bucket="dynamical-ecmwf-aifs-single",
        prefix="ecmwf-aifs-single-forecast/v0.1.0.icechunk",
        region="us-west-2",
        anonymous=True,
    )
    repo = icechunk.Repository.open(storage=storage)
    session = repo.readonly_session(branch="main")

    ds = xr.open_zarr(session.store, consolidated=False)

    requested_vars = [
        "temperature_2m",
        "dew_point_temperature_2m",
        "precipitation_surface",
        "wind_u_10m",
        "wind_v_10m",
    ]
    available_vars = [v for v in requested_vars if v in ds.data_vars]
    ds_sub = ds[available_vars]

    latest_init = ds_sub.init_time.values[-1]
    init_hour = pd.Timestamp(latest_init).hour
    effective_max_lead = MAX_LEAD_HOURS + 24 if init_hour >=12 else MAX_LEAD_HOURS 
    max_lead = np.timedelta64(effective_max_lead, "h")

    #max_lead = np.timedelta64(MAX_LEAD_HOURS, "h")

    logger.info(
        f"Downloading {MAX_LEAD_HOURS}h AIFS forecast for run {latest_init} over Madagascar (bbox pre-filter)..."
    )

    regional_ds = ds_sub.sel(
        init_time=[latest_init],
        lead_time=ds_sub.lead_time <= max_lead,
        latitude=slice(MADAGASCAR_BBOX["lat_north"], MADAGASCAR_BBOX["lat_south"]),
        longitude=slice(MADAGASCAR_BBOX["lon_west"], MADAGASCAR_BBOX["lon_east"]),
    )

    t_download = time.time()
    loaded_ds = regional_ds.load()
    loaded_ds = clear_zarr_encodings(loaded_ds)
    logger.info(f"[Timing] Download+load: {time.time() - t_download:.1f}s")


    # 1. Temperature in degC (already degree_Celsius per the AIFS catalog).
    if "temperature_2m" in loaded_ds:
        loaded_ds["temp_2m_celsius"] = loaded_ds["temperature_2m"]
        loaded_ds["temp_2m_celsius"].attrs["units"] = "degC"

    # 2. Relative Humidity (%) - t2m/d2m are already Celsius.
    if "temperature_2m" in loaded_ds and "dew_point_temperature_2m" in loaded_ds:
        loaded_ds["relative_humidity_2m"] = calculate_relative_humidity(
            loaded_ds["temperature_2m"], loaded_ds["dew_point_temperature_2m"]
        )
        loaded_ds["relative_humidity_2m"].attrs["units"] = "%"

    # 3. Precipitation in mm (CUMULATIVE since init_time). precipitation_surface
    t_despike = time.time()
    if "precipitation_surface" in loaded_ds:
        despiked_rate = despike_precip_rate(loaded_ds["precipitation_surface"])

        lead_seconds = loaded_ds["lead_time"].values.astype("timedelta64[s]").astype(np.float64)
        step_duration_s = np.diff(lead_seconds, prepend=0.0)
        step_duration_da = xr.DataArray(
            step_duration_s, coords={"lead_time": loaded_ds["lead_time"]}, dims=["lead_time"]
        )

        precip_step_mm = despiked_rate * step_duration_da
        loaded_ds["precipitation_surface_mm"] = precip_step_mm.cumsum(dim="lead_time")
        loaded_ds["precipitation_surface_mm"].attrs["units"] = "mm"
        loaded_ds["precipitation_surface_mm"].attrs["description"] = (
            "Cumulative precipitation (mm) since forecast init_time, derived "
            "from the (despiked) average precipitation rate (kg m-2 s-1) "
            "reported per forecast step."
        )
    logger.info(f"[Timing] Derive vars + despike (native res): {time.time() - t_despike:.1f}s")

    # 4. Wind speed in m/s
    if "wind_u_10m" in loaded_ds and "wind_v_10m" in loaded_ds:
        loaded_ds["wind_speed_10m"] = np.sqrt(
            loaded_ds["wind_u_10m"] ** 2 + loaded_ds["wind_v_10m"] ** 2
        )
        loaded_ds["wind_speed_10m"].attrs["units"] = "m/s"

    # --- Regrid to ~0.05deg (5km) + mask everything outside the districtMdg
    # shapefile boundary to NaN. THIS becomes the saved, canonical dataset. ---
    t_regrid = time.time()
    logger.info(
        f"Regridding to {TARGET_GRID_RESOLUTION_DEG} deg (5km) and masking to "
        "the districtMdg shapefile boundary - this is the only grid saved "
        "and used downstream."
    )
    loaded_ds = regrid_and_mask_to_land(loaded_ds)
    logger.info(f"[Timing] Regrid + mask to 0.05deg: {time.time() - t_regrid:.1f}s")

    t_save = time.time()
    os.makedirs(FORECAST_DIR, exist_ok=True)
    loaded_ds.to_zarr(LOCAL_ZARR_PATH, mode="w")
    logger.info(f"[Timing] Save to zarr: {time.time() - t_save:.1f}s")
    logger.info(f"Successfully saved shapefile-masked, 5km forecast to '{LOCAL_ZARR_PATH}'")

    PLOT_CACHE.clear()
    FIELD_CACHE.clear()
    DAILY_CACHE["key"] = None
    DAILY_CACHE["dataset"] = None
    NOON_DAILY_CACHE["key"] = None
    NOON_DAILY_CACHE["dataset"] = None

    AIFS_CACHE["dataset"] = loaded_ds
    AIFS_CACHE["last_fetched"] = time.time()

    try:
        from app.scripts.update_fire_state import update_state_for_date

        state_path = update_state_for_date(source="aifs_shortlead")
        if state_path is not None:
            logger.info(f"Operational fire state refreshed after AIFS download: {state_path}")
    except Exception:
        logger.error(
            "Fresh AIFS forecast was saved, but operational fire-state "
            "refresh failed. FWI/FOPI will fall back according to "
            "fire_state_io.load_fire_initialization().",
            exc_info=True,
        )

    try:
        t_warm = time.time()
        get_daily_aifs_dataset()
        get_daily_noon_aifs_dataset()
        from app.api.fire_indices import compute_fire_indices
        compute_fire_indices(force_recompute=True)
        logger.info(f"[Timing] Pre-warm daily dataset + FWI/FOPI: {time.time() - t_warm:.1f}s")
    except Exception as e:
        logger.warning(f"Could not pre-warm FWI/FOPI after download (will compute lazily on first request): {e}")

    logger.info(f"[Timing] TOTAL download_and_save_aifs(): {time.time() - t_start:.1f}s")

    return loaded_ds


def get_aifs_dataset():
    current_time = time.time()

    if AIFS_CACHE["dataset"] is not None:
        if DEBUG_MODE or (current_time - AIFS_CACHE["last_fetched"] < CACHE_TTL):
            return AIFS_CACHE["dataset"]

    file_exists = os.path.exists(LOCAL_ZARR_PATH)

    if file_exists:
        file_age = current_time - os.path.getmtime(LOCAL_ZARR_PATH)

        if DEBUG_MODE or (file_age < CACHE_TTL):
            logger.info(f"Loading cached Zarr from '{LOCAL_ZARR_PATH}'")
            ds = xr.open_zarr(LOCAL_ZARR_PATH)
            AIFS_CACHE["dataset"] = ds
            AIFS_CACHE["last_fetched"] = current_time
            return ds

    logger.info("Triggering fresh AIFS forecast download...")
    ds = download_and_save_aifs()
    AIFS_CACHE["dataset"] = ds
    AIFS_CACHE["last_fetched"] = current_time
    return ds


def build_local_day_groups(lead_time_da, init_time_val, max_days=FORECAST_HORIZON_DAYS):

    init_ts = pd.Timestamp(init_time_val)
    valid_time_utc = init_ts + pd.to_timedelta(lead_time_da.values)
    local_time = pd.DatetimeIndex(valid_time_utc) + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    local_date = local_time.normalize()

    init_hour = init_ts.hour
    #unique_dates = local_date.unique().sort_values()[:max_days]
    unique_dates = local_date.unique().sort_values()
    if init_hour >= 12 and len(unique_dates) > 1:
        logger.info(
            f"[AIFS Time Logic] Run initialized at {init_hour:02d}:00 UTC. "
            "Omitting partial first day and shifting window to maintain full forecast length."
        )
        unique_dates = unique_dates[1:]

    unique_dates = unique_dates[:max_days]

    day_dates, day_step_idx = [], []
    for d in unique_dates:
        idx = np.where(local_date == d)[0]
        if len(idx) == 0:
            continue
        day_dates.append(d.to_datetime64())
        day_step_idx.append(idx)

    return day_dates, day_step_idx, local_time


def _select_local_noon_step_indices(lead_time_da, init_time_val, day_dates, day_step_idx,
                                     target_local_hour=12):

    init_ts = pd.Timestamp(init_time_val)
    valid_time_utc = init_ts + pd.to_timedelta(lead_time_da.values)
    local_time = pd.DatetimeIndex(valid_time_utc) + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)

    noon_step_idx = []
    for d, idx_group in zip(day_dates, day_step_idx):
        day_local_times = local_time[idx_group]
        target = pd.Timestamp(d) + pd.Timedelta(hours=target_local_hour)
        deltas = np.abs((day_local_times - target).total_seconds())
        best = idx_group[int(np.argmin(deltas))]
        noon_step_idx.append(int(best))
        chosen_local_time = local_time[best]
        offset_min = (chosen_local_time - target).total_seconds() / 60.0
        if abs(offset_min) > 90:
            logger.warning(
                f"[Noon Sampling] Closest available step to local noon on "
                f"{pd.Timestamp(d).date()} is {chosen_local_time.strftime('%H:%M')} "
                f"local ({offset_min:+.0f} min from noon) - forecast step "
                "cadence is coarser than desired for CFFDRS noon-observation "
                "fidelity. Consider a finer AIFS output cadence if/when "
                "available."
            )
    return noon_step_idx


def _reduce_daily_noon(da, noon_step_idx, dim="lead_time"):
    """Select the single local-noon-closest step for each local day -
    used for CFFDRS tas/hurs/sfcWind inputs (see
    _select_local_noon_step_indices)."""
    vals = [da.isel({dim: idx}) for idx in noon_step_idx]
    return xr.concat(vals, dim="time")


NOON_DAILY_CACHE = {"key": None, "dataset": None}


def get_daily_noon_aifs_dataset():

    ds = get_aifs_dataset()

    if "init_time" in ds.coords:
        init_time_val = np.atleast_1d(ds["init_time"].values)[0]
    else:
        init_time_val = pd.Timestamp.now().floor("D")

    cache_key = str(init_time_val)
    if NOON_DAILY_CACHE["key"] == cache_key and NOON_DAILY_CACHE["dataset"] is not None:
        return NOON_DAILY_CACHE["dataset"]

    if "lead_time" not in ds.dims:
        raise KeyError("Expected 'lead_time' dimension in AIFS dataset.")

    day_dates, day_step_idx, _ = build_local_day_groups(ds["lead_time"], init_time_val)
    if len(day_dates) == 0:
        raise RuntimeError("No forecast steps available to build the noon-sampled AIFS dataset.")

    noon_step_idx = _select_local_noon_step_indices(
        ds["lead_time"], init_time_val, day_dates, day_step_idx
    )

    tas = _drop_singleton_init_time(ds["temp_2m_celsius"])
    wind = _drop_singleton_init_time(ds["wind_speed_10m"])
    rh = _drop_singleton_init_time(ds["relative_humidity_2m"])
    pr_cumulative = _drop_singleton_init_time(ds["precipitation_surface_mm"])

    noon_tas = _reduce_daily_noon(tas, noon_step_idx).load()
    noon_wind = _reduce_daily_noon(wind, noon_step_idx).load()
    noon_rh = _reduce_daily_noon(rh, noon_step_idx).load()
    # Precipitation stays a full 24h accumulation (per spec) - reuse the
    # existing accumulation reducer, NOT noon sampling.
    daily_pr = _reduce_daily_precip_total(pr_cumulative, day_step_idx).load()

    time_coord = np.array(day_dates, dtype="datetime64[ns]")
    for da in (noon_tas, noon_wind, noon_rh, daily_pr):
        da.coords["time"] = ("time", time_coord)

    noon_tas.name = "temp_2m_celsius"
    noon_tas.attrs["units"] = "degC"
    noon_tas.attrs["description"] = "Local-noon (~12:00 UTC+3) temperature - CFFDRS input"
    noon_wind.name = "wind_speed_10m"
    noon_wind.attrs["units"] = "m/s"
    noon_wind.attrs["description"] = "Local-noon (~12:00 UTC+3) wind speed - CFFDRS input"
    noon_rh.name = "relative_humidity_2m"
    noon_rh.attrs["units"] = "%"
    noon_rh.attrs["description"] = "Local-noon (~12:00 UTC+3) relative humidity - CFFDRS input"
    daily_pr.name = "precipitation_surface_mm"
    daily_pr.attrs["units"] = "mm"
    daily_pr.attrs["description"] = "24-hour accumulated precipitation - CFFDRS input"

    noon_tas = noon_tas.drop_vars(["valid_time", "lead_time"], errors="ignore")
    daily_pr = daily_pr.drop_vars(["valid_time", "lead_time"], errors="ignore")

    daily_ds = xr.Dataset({
        "temp_2m_celsius": noon_tas,
        "wind_speed_10m": noon_wind,
        "relative_humidity_2m": noon_rh,
        "precipitation_surface_mm": daily_pr,
    })

    NOON_DAILY_CACHE["key"] = cache_key
    NOON_DAILY_CACHE["dataset"] = daily_ds
    return daily_ds


def _drop_singleton_init_time(da):
    if "init_time" in da.dims:
        da = da.squeeze("init_time", drop=True)
    return da


def _reduce_daily_max(da, day_step_idx, dim="lead_time"):

    vals = [da.isel({dim: idx}).max(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")


def _reduce_daily_min(da, day_step_idx, dim="lead_time"):

    vals = [da.isel({dim: idx}).min(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")


def _reduce_daily_mean(da, day_step_idx, dim="lead_time"):
    """Daily MEAN across all native-cadence steps within each local day -
    used for wind speed."""
    vals = [da.isel({dim: idx}).mean(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")

DAILY_PRECIP_SANITY_CAP_MM = 500.0


def _reduce_daily_precip_total(cumulative_mm_da, day_step_idx, dim="lead_time"):

    totals = []
    prev_end = None
    for idx in day_step_idx:
        end_val = cumulative_mm_da.isel({dim: int(idx[-1])}).drop_vars(dim, errors="ignore")
        start_val = xr.zeros_like(end_val) if prev_end is None else prev_end
        day_total = end_val - start_val
        totals.append(day_total)
        prev_end = end_val

    result = xr.concat(totals, dim="time")

    over_cap = result.values > DAILY_PRECIP_SANITY_CAP_MM
    if np.any(np.nan_to_num(over_cap.astype(float)) > 0):
        logger.warning(
            f"[Sanity Check] daily-rainfall grid cell(s) exceeded the "
            f"{DAILY_PRECIP_SANITY_CAP_MM}mm sanity cap after despiking - "
            "clipping them. This should be rare; if it happens often, investigate."
        )
        result = result.clip(max=DAILY_PRECIP_SANITY_CAP_MM)

    return result


def get_daily_aifs_dataset():

    ds = get_aifs_dataset()

    if "init_time" in ds.coords:
        init_time_val = np.atleast_1d(ds["init_time"].values)[0]
    else:
        init_time_val = pd.Timestamp.now().floor("D")

    cache_key = str(init_time_val)
    if DAILY_CACHE["key"] == cache_key and DAILY_CACHE["dataset"] is not None:
        return DAILY_CACHE["dataset"]

    if "lead_time" not in ds.dims:
        raise KeyError("Expected 'lead_time' dimension in AIFS dataset.")

    day_dates, day_step_idx, _ = build_local_day_groups(ds["lead_time"], init_time_val)
    if len(day_dates) == 0:
        raise RuntimeError("No forecast steps available to build daily AIFS dataset.")

    tas = _drop_singleton_init_time(ds["temp_2m_celsius"])
    wind = _drop_singleton_init_time(ds["wind_speed_10m"])
    rh = _drop_singleton_init_time(ds["relative_humidity_2m"])
    pr_cumulative = _drop_singleton_init_time(ds["precipitation_surface_mm"])

    daily_tas = _reduce_daily_max(tas, day_step_idx).load()
    daily_wind = _reduce_daily_mean(wind, day_step_idx).load()
    daily_rh = _reduce_daily_min(rh, day_step_idx).load()
    daily_pr = _reduce_daily_precip_total(pr_cumulative, day_step_idx).load()

    time_coord = np.array(day_dates, dtype="datetime64[ns]")
    for da in (daily_tas, daily_wind, daily_rh, daily_pr):
        da.coords["time"] = ("time", time_coord)

    daily_tas.name = "temp_2m_celsius"
    daily_tas.attrs["units"] = "degC"
    daily_tas.attrs["description"] = "Daily maximum temperature (proxy for noon-LST temperature)"
    daily_wind.name = "wind_speed_10m"
    daily_wind.attrs["units"] = "m/s"
    daily_rh.name = "relative_humidity_2m"
    daily_rh.attrs["units"] = "%"
    daily_rh.attrs["description"] = "Daily minimum relative humidity (proxy for noon-LST RH)"
    daily_pr.name = "precipitation_surface_mm"
    daily_pr.attrs["units"] = "mm"
    daily_pr.attrs["description"] = "Daily total precipitation (accumulated over the local calendar day)"

    daily_ds = xr.Dataset({
        "temp_2m_celsius": daily_tas,
        "wind_speed_10m": daily_wind,
        "relative_humidity_2m": daily_rh,
        "precipitation_surface_mm": daily_pr,
    })

    DAILY_CACHE["key"] = cache_key
    DAILY_CACHE["dataset"] = daily_ds
    return daily_ds


def get_daily_weather_field(var_name, day_num):

    cache_key = f"{var_name}_day{day_num}"
    if cache_key in FIELD_CACHE:
        return FIELD_CACHE[cache_key]

    daily_ds = get_daily_aifs_dataset()
    if var_name not in daily_ds:
        raise KeyError(f"'{var_name}' not found in daily AIFS dataset.")

    field = daily_ds[var_name].isel(time=day_num)

    # Sort latitude north-to-south
    if field.latitude[0] < field.latitude[-1]:
        field = field.reindex(latitude=field.latitude[::-1])

    FIELD_CACHE[cache_key] = field
    return field


@aifs_bp.route("/plot", methods=["GET"])
def get_forecast_plot():
    """Generates Base64 PNG overlay with ultra-fast responses via in-memory plot caching."""
    raw_var = request.args.get("variable", default="temp_2m_celsius")
    day_num = request.args.get("day", default=0, type=int)

    var_map = {
        "temp": "temp_2m_celsius",
        "Temp": "temp_2m_celsius",
        "temp_c": "temp_2m_celsius",
        "temp_2m_celsius": "temp_2m_celsius",
        "rr": "precipitation_surface_mm",
        "Rain": "precipitation_surface_mm",
        "rain": "precipitation_surface_mm",
        "precipitation_surface": "precipitation_surface_mm",
        "precipitation_surface_mm": "precipitation_surface_mm",
        "rh": "relative_humidity_2m",
        "RH": "relative_humidity_2m",
        "relative_humidity": "relative_humidity_2m",
        "relative_humidity_2m": "relative_humidity_2m",
        "wind": "wind_speed_10m",
        "Wind": "wind_speed_10m",
        "wind_speed_10m": "wind_speed_10m",
    }
    var_name = var_map.get(raw_var, raw_var)


    display_config = {
        "precipitation_surface_mm": ("Blues", "mm", "Précipitations totales journalières"),
        "temp_2m_celsius": ("Spectral_r", "°C", "Température maximale journalière"),
        "wind_speed_10m": ("viridis", "m/s", "Vitesse moyenne journalière du vent"),
        "relative_humidity_2m": ("YlGnBu", "%", "Humidité relative minimale journalière"),
    }

    cmap_name, unit, title_name = display_config.get(var_name, ("coolwarm", "", var_name))

    cache_key = f"{var_name}_day{day_num}"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        field = get_daily_weather_field(var_name, day_num)

        lats = field.latitude.values
        lons = field.longitude.values

        min_lat, max_lat = float(np.min(lats)), float(np.max(lats))
        min_lon, max_lon = float(np.min(lons)), float(np.max(lons))

        lat_res = float(np.abs(np.mean(np.diff(lats)))) if len(lats) > 1 else 0.0
        lon_res = float(np.abs(np.mean(np.diff(lons)))) if len(lons) > 1 else 0.0

        bounds = [
            [min_lat - lat_res / 2, min_lon - lon_res / 2],  # [South, West]
            [max_lat + lat_res / 2, max_lon + lon_res / 2],  # [North, East]
        ]

        data_vals = field.values
        vmin = float(np.nanmin(data_vals)) if not np.all(np.isnan(data_vals)) else 0.0
        vmax = float(np.nanmax(data_vals)) if not np.all(np.isnan(data_vals)) else 1.0

        if vmin == vmax:
            vmax = vmin + 1.0

        fig = plt.figure(figsize=(6, 6), frameon=False)
        ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
        ax.set_axis_off()
        fig.add_axes(ax)

        cmap = matplotlib.colormaps[cmap_name]
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

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
        tick_vals = np.linspace(vmin, vmax, 5)
        for val in tick_vals:
            rgba = cmap(norm(val))
            hex_color = mcolors.to_hex(rgba)
            legend_ticks.append({"value": round(float(val), 1), "color": hex_color})

        real_date = pd.Timestamp(field.time.values).strftime("%Y-%m-%d")

        response_payload = {
            "status": "success",
            "bounds": bounds,
            "imageUrl": data_url,
            "legend": legend_ticks,
            "unit": unit,
            "title": f"{title_name} ({real_date})",
            "date": real_date,
            "day_index": day_num,
        }

        PLOT_CACHE[cache_key] = response_payload
        return jsonify(response_payload)

    except Exception as e:
        logger.error(f"Failed to generate forecast plot: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500




def download_historical_day_daily_means(target_date):
    # Ato no midownload anle data teo aloha hanaovana calcul ny FWI latest FMMC, DC, DMC

    target_date = pd.Timestamp(target_date).normalize()
 
    storage = icechunk.s3_storage(
        bucket="dynamical-ecmwf-aifs-single",
        prefix="ecmwf-aifs-single-forecast/v0.1.0.icechunk",
        region="us-west-2",
        anonymous=True,
    )
    repo = icechunk.Repository.open(storage=storage)
    session = repo.readonly_session(branch="main")
    ds = xr.open_zarr(session.store, consolidated=False)
 
    requested_vars = [
        "temperature_2m",
        "dew_point_temperature_2m",
        "precipitation_surface",
        "wind_u_10m",
        "wind_v_10m",
    ]
    available_vars = [v for v in requested_vars if v in ds.data_vars]
    ds_sub = ds[available_vars]
 
    init_times = pd.to_datetime(ds_sub.init_time.values)
    same_day_runs = init_times[init_times.normalize() == target_date]
    if len(same_day_runs) == 0:
        raise ValueError(
            f"No AIFS init_time found in the archive for {target_date.date()} "
            "- the rolling archive likely does not retain data that far "
            "back. Reduce the spin-up window or use a reanalysis source "
            "(e.g. ERA5/CDS) for longer spin-ups."
        )
    chosen_init = same_day_runs.min()  # earliest run of that day (~00Z)
 
    window_end = np.timedelta64(24, "h")
    regional_ds = ds_sub.sel(
        init_time=[chosen_init],
        lead_time=ds_sub.lead_time <= window_end,
        latitude=slice(MADAGASCAR_BBOX["lat_north"], MADAGASCAR_BBOX["lat_south"]),
        longitude=slice(MADAGASCAR_BBOX["lon_west"], MADAGASCAR_BBOX["lon_east"]),
    ).load()
    regional_ds = clear_zarr_encodings(regional_ds)
 
    if "temperature_2m" in regional_ds:
        regional_ds["temp_2m_celsius"] = regional_ds["temperature_2m"]
 
    if "temperature_2m" in regional_ds and "dew_point_temperature_2m" in regional_ds:
        regional_ds["relative_humidity_2m"] = calculate_relative_humidity(
            regional_ds["temperature_2m"], regional_ds["dew_point_temperature_2m"]
        )
 
    if "wind_u_10m" in regional_ds and "wind_v_10m" in regional_ds:
        regional_ds["wind_speed_10m"] = np.sqrt(
            regional_ds["wind_u_10m"] ** 2 + regional_ds["wind_v_10m"] ** 2
        )
 
    if "precipitation_surface" in regional_ds:
        despiked_rate = despike_precip_rate(regional_ds["precipitation_surface"])
        lead_seconds = regional_ds["lead_time"].values.astype("timedelta64[s]").astype(np.float64)
        step_duration_s = np.diff(lead_seconds, prepend=0.0)
        step_duration_da = xr.DataArray(
            step_duration_s, coords={"lead_time": regional_ds["lead_time"]}, dims=["lead_time"]
        )
        regional_ds["precipitation_surface_mm"] = (
            despiked_rate * step_duration_da
        ).cumsum(dim="lead_time")
 
    regridded = regrid_and_mask_to_land(regional_ds)
 
    daily_tas = regridded["temp_2m_celsius"].max(dim="lead_time", skipna=True)
    daily_wind = regridded["wind_speed_10m"].mean(dim="lead_time", skipna=True)
    daily_rh = regridded["relative_humidity_2m"].min(dim="lead_time", skipna=True)
    daily_pr = regridded["precipitation_surface_mm"].isel(lead_time=-1)  # 24h total
 
    daily = xr.Dataset(
        {
            "temp_2m_celsius": daily_tas.squeeze(drop=True),
            "wind_speed_10m": daily_wind.squeeze(drop=True),
            "relative_humidity_2m": daily_rh.squeeze(drop=True),
            "precipitation_surface_mm": daily_pr.squeeze(drop=True),
        }
    )
    daily = daily.expand_dims(time=[target_date])
    daily["temp_2m_celsius"].attrs["units"] = "degC"
    daily["wind_speed_10m"].attrs["units"] = "m/s"
    daily["relative_humidity_2m"].attrs["units"] = "%"
    daily["precipitation_surface_mm"].attrs["units"] = "mm"
    return daily
