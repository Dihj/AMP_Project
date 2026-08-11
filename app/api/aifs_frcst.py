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

# Import existing shapefile utility
from app.scripts.spatial_calc import get_geojson_from_shapefile

# Set non-GUI backend for server rendering
matplotlib.use("Agg")

logger = logging.getLogger(__name__)

aifs_bp = Blueprint("aifs_forecast", __name__)

# Global In-Memory Caches
AIFS_CACHE = {"last_fetched": 0, "dataset": None}
PLOT_CACHE = {}   # Caches final JSON responses: key = f"{var_name}_{day_num}"
FIELD_CACHE = {}  # Caches per-day DataArrays sliced out of the daily dataset
DAILY_CACHE = {"key": None, "dataset": None}  # Caches the canonical daily xr.Dataset (see get_daily_aifs_dataset)
GEOMETRY_MASK_CACHE = None  # Caches the boolean land mask so it's only built ONCE

DEBUG_MODE = os.environ.get("FIRE_APP_DEBUG", "false").strip().lower() in ("1", "true", "yes")
CACHE_TTL = 43200  # 12 hours

FORECAST_DIR = os.path.join("data", "forecast")
LOCAL_ZARR_PATH = os.path.join(FORECAST_DIR, "aifs_raw_latest.zarr")

# Rough rectangular pre-filter used only to keep the initial S3/Icechunk
# query small - the REAL boundary (districtMdg shapefile) is applied by
# regrid_and_mask_to_land() after download, on the FINAL 0.05deg grid.
MADAGASCAR_BBOX = {
    "lat_north": -10.0,
    "lat_south": -26.0,
    "lon_west": 43.0,
    "lon_east": 51.0,
}

# Madagascar / Nairobi (Africa/Nairobi, Indian/Antananarivo) is a FIXED
# UTC+3 offset year-round - no DST anywhere in that timezone family.
LOCAL_UTC_OFFSET_HOURS = 3

# 96h of lead time comfortably covers 4 local calendar days (day 0 = today,
# 1 = tomorrow, 2 = day after, 3 = the day after that), even accounting for
# the ~3h UTC/local offset eating into day 0's coverage at the start.
MAX_LEAD_HOURS = 96
FORECAST_HORIZON_DAYS = 4

# The ONLY grid saved to disk and used everywhere downstream - map, daily
# aggregation, FWI/FOPI, and point/polygon extraction all read this same
# ~0.05deg (~5km) shapefile-masked data.
TARGET_GRID_RESOLUTION_DEG = 0.05


def clear_zarr_encodings(dataset):
    """Clear remote S3 chunk encodings so Zarr can write fresh local structures."""
    dataset.encoding.clear()
    for var in dataset.variables:
        dataset[var].encoding.clear()
    return dataset


def get_cached_land_mask(lats, lons, layer_key="districtMdg"):
    """
    Builds (and caches) the boolean "is ocean / outside Madagascar" mask on
    the given lat/lon grid, from the districtMdg shapefile. True = outside
    the land boundary (should become NaN).
    """
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
            invert=False,  # False: Outside land geometry = True (Ocean / non-Madagascar)
        )

        GEOMETRY_MASK_CACHE = mask
        return mask
    except Exception as e:
        logger.error(f"Failed to generate land mask: {e}")
        return None


def regrid_and_mask_to_land(ds, layer_key="districtMdg", target_resolution=TARGET_GRID_RESOLUTION_DEG,
                             bbox=MADAGASCAR_BBOX):
    """
    THE single regrid+mask step for the whole app: bilinearly interpolates
    every variable in `ds` onto a fixed ~0.05deg (5km) grid over Madagascar,
    then sets every cell outside the districtMdg shapefile boundary to NaN.
    Masking on the fine grid (rather than AIFS's coarser native grid) gives
    a much cleaner coastline than rasterizing the shapefile onto a coarse
    grid would.

    Called ONCE per download, on the full per-lead_time-step dataset,
    before saving to disk - so the map, daily aggregation, FWI/FOPI, and
    point/polygon extraction all read the exact same already-regridded,
    already-masked data.

    NOTE: bilinear interpolation, not an area-conservative/flux-conserving
    remap. For precipitation specifically, a conservative regrid (e.g. via
    xesmf) would be more rigorous if exact area-integrated totals matter -
    flagging this as a known simplification, not treating it as exact.
    """
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
        regridded = regridded.where(~is_ocean_da)  # keep where NOT ocean; NaN elsewhere
    else:
        logger.warning("Land mask unavailable - saving regridded data WITHOUT shapefile masking.")

    return regridded


# A grid cell's per-step precip rate must exceed BOTH this multiple of its
# local neighborhood median AND this absolute floor to be treated as a
# despike candidate - the floor (~5mm/hr equivalent) keeps this from
# touching ordinary light/moderate rain variability; only isolated,
# extreme, non-spatially-coherent values get corrected.
PRECIP_SPIKE_RATIO = 5.0
PRECIP_SPIKE_FLOOR_KG_M2_S = 5.0 / 3600.0  # ~5 mm/hr, in kg m-2 s-1


def despike_precip_rate(precip_da, neighborhood=3):
    """
    AI-based weather models (AIFS included) occasionally emit an isolated,
    non-physical extreme value at a single grid cell/timestep for
    precipitation - especially at longer lead times - with no spatial
    coherence: unlike a genuine convective cell (which elevates a cluster of
    adjacent grid points together), the artifact's neighbors stay normal.

    Replaces any such isolated spike with its local neighborhood median. Run
    on the NATIVE-resolution rate (before regridding), which is the most
    precise place to catch it. Genuine widespread heavy rain is left
    untouched, because its neighbors are elevated too and the ratio check
    never triggers.
    """
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
    """Calculates Relative Humidity (%) using the August-Roche-Magnus formula.

    Inputs must be degrees Celsius. Per the AIFS data catalog, both
    temperature_2m and dew_point_temperature_2m are already reported in
    degree_Celsius, so no unit conversion is needed before calling this.
    """
    e = 6.112 * np.exp((17.67 * d2m_c) / (d2m_c + 243.5))
    es = 6.112 * np.exp((17.67 * t2m_c) / (t2m_c + 243.5))
    rh = (e / es) * 100.0
    return np.clip(rh, 0.0, 100.0)


def download_and_save_aifs():
    """
    Fetch a MAX_LEAD_HOURS forecast from S3 Icechunk (rectangular bbox
    pre-filter), compute derived per-step parameters at NATIVE resolution
    (unit fixes, despiking), then regrid + shapefile-mask the WHOLE dataset
    to the final ~0.05deg (5km) grid and save THAT to disk. Immediately
    pre-warms the daily dataset and FWI/FOPI caches too, so the FIRST user
    request after a refresh doesn't pay that computation cost.
    """
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
    max_lead = np.timedelta64(MAX_LEAD_HOURS, "h")

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

    # --- Derive per-step variables at NATIVE resolution ---

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
    # is kg m-2 s-1 ("average rate since previous forecast step", ~mm/s) - NOT
    # an accumulated total, and NOT in meters. Despike the RATE at native
    # resolution first (most precise place to catch an isolated bad value),
    # then convert to per-step mm and cumulatively sum.
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

    # A fresh forecast run invalidates EVERY downstream cache built from the
    # old one - rendered map cache, per-day field cache, and the canonical
    # daily-aggregated dataset. All three must be cleared together.
    PLOT_CACHE.clear()
    FIELD_CACHE.clear()
    DAILY_CACHE["key"] = None
    DAILY_CACHE["dataset"] = None

    # Pre-warm the daily dataset AND FWI/FOPI right now, rather than waiting
    # for the first user request to trigger (and pay for) that computation.
    # Deferred/local import to avoid a circular import (fire_indices.py
    # imports from this module at the top level).
    AIFS_CACHE["dataset"] = loaded_ds
    AIFS_CACHE["last_fetched"] = time.time()
    try:
        t_warm = time.time()
        get_daily_aifs_dataset()
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


# ---------------------------------------------------------------------------
# Local-calendar-day bucketing + daily aggregation.
#
# This is the SINGLE place native-cadence (sub-daily) AIFS steps get turned
# into "day 0 / day 1 / day 2 / day 3" data. app.api.fire_indices reuses
# these exact same functions/dataset to build FWI/FOPI's daily inputs, so
# there is only one definition of what a "day" is and how each variable is
# aggregated into it across the whole app.
#
# Temperature -> daily MAX, relative humidity -> daily MIN: this is the
# standard CFFWI daily-proxy convention (minimum RH typically coincides
# with maximum temperature near solar noon, so these two together
# approximate "noon LST" conditions when noon-specific sub-daily selection
# isn't used). Wind -> daily MEAN (no equivalent max/min convention for
# wind in the standard method). Precipitation -> daily TOTAL/accumulation.
# ---------------------------------------------------------------------------

def build_local_day_groups(lead_time_da, init_time_val, max_days=FORECAST_HORIZON_DAYS):
    """
    Groups native-cadence forecast steps (lead_time) into LOCAL (UTC+3)
    calendar days: day 0 = today, day 1 = tomorrow, etc.

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


def _drop_singleton_init_time(da):
    if "init_time" in da.dims:
        da = da.squeeze("init_time", drop=True)
    return da


def _reduce_daily_max(da, day_step_idx, dim="lead_time"):
    """Daily MAX across all native-cadence steps within each local day -
    used for temperature (standard proxy for noon-LST temperature)."""
    vals = [da.isel({dim: idx}).max(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")


def _reduce_daily_min(da, day_step_idx, dim="lead_time"):
    """Daily MIN across all native-cadence steps within each local day -
    used for relative humidity (standard proxy for noon-LST RH, since
    minimum daily RH typically coincides with maximum daily temperature)."""
    vals = [da.isel({dim: idx}).min(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")


def _reduce_daily_mean(da, day_step_idx, dim="lead_time"):
    """Daily MEAN across all native-cadence steps within each local day -
    used for wind speed."""
    vals = [da.isel({dim: idx}).mean(dim=dim, skipna=True) for idx in day_step_idx]
    return xr.concat(vals, dim="time")


# Absolute ceiling for a single day's total rainfall at one grid cell.
# Extremely generous on purpose (near world-record daily-rainfall
# territory) - this is a last-resort safety net, not a primary correction
# mechanism.
DAILY_PRECIP_SANITY_CAP_MM = 500.0


def _reduce_daily_precip_total(cumulative_mm_da, day_step_idx, dim="lead_time"):
    """Daily TOTAL precip (mm) from a monotonically cumulative field: each
    day's total = cumulative value at day-end minus cumulative value at the
    previous day's end (0 for day 0, i.e. accumulation is measured from
    forecast init_time)."""
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
    """
    Builds (and caches, keyed to the current forecast's init_time) the
    canonical DAILY forecast dataset: one value per LOCAL calendar day
    (day 0 = today ... day N-1) for:
      - temp_2m_celsius:        daily MAX (degC)
      - wind_speed_10m:         daily MEAN (m/s)
      - relative_humidity_2m:   daily MIN (%)
      - precipitation_surface_mm: daily TOTAL / accumulation (mm)

    on the already regridded (~0.05deg / 5km) and shapefile-masked grid from
    get_aifs_dataset(). This is the single source of truth: the map,
    point/polygon extraction, and FWI/FOPI all read this same dataset - no
    further interpolation or masking happens anywhere else.
    """
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

    # NOTE: arrays coming from the cached-zarr load path are dask-backed.
    # Concatenating several small per-day reductions leaves "time" split
    # across multiple chunks, which breaks any downstream apply_ufunc that
    # needs "time" as a single core-dimension chunk (e.g. xclim's recursive
    # daily FWI calculation). Materializing eagerly with .load() is cheap
    # here since these are daily-reduced arrays.
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
    """
    Returns the field for `var_name` / `day_num` from the canonical daily
    dataset (get_daily_aifs_dataset()) - already at ~0.05deg (5km) and
    shapefile-masked, since that happened once at download time. Used
    identically by the map (/plot) and by point/polygon extraction (see
    app.api.forecast).
    """
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
        "precipitation_surface_mm": ("Blues", "mm", "Daily Total Rainfall"),
        "temp_2m_celsius": ("Spectral_r", "°C", "Daily Max Temperature"),
        "wind_speed_10m": ("viridis", "m/s", "Daily Mean Wind Speed"),
        "relative_humidity_2m": ("YlGnBu", "%", "Daily Min Relative Humidity"),
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

        # lats/lons are pixel CENTERS, but Leaflet's ImageOverlay bounds are
        # pixel EDGES. Using center min/max directly shifts the whole raster
        # by half a pixel relative to true geographic points (e.g. FIRMS
        # active-fire markers plotted from raw lat/lon).
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

        # Real calendar date instead of a relative "Today/Tomorrow" label -
        # read directly off the field's own time coordinate.
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

        