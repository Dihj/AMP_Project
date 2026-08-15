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
import geopandas as gpd
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
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
PLOT_CACHE = {}  # Caches final JSON responses: key = f"{var_name}_{day_num}"
GEOMETRY_MASK_CACHE = None  # Caches spatial mask so geometry_mask runs only ONCE

# NOTE: was hardcoded to True, which permanently disabled cache refresh (CACHE_TTL
# became dead code) once a Zarr file existed on disk. Now driven by an env var so
# it can't accidentally ship "stuck" in debug mode.
DEBUG_MODE = os.environ.get("FIRE_APP_DEBUG", "false").strip().lower() in ("1", "true", "yes")
CACHE_TTL = 43200  # 12 hours

FORECAST_DIR = os.path.join("data", "forecast")
LOCAL_ZARR_PATH = os.path.join(FORECAST_DIR, "aifs_raw_latest.zarr")

MADAGASCAR_BBOX = {
    "lat_north": -10.0,
    "lat_south": -26.0,
    "lon_west": 43.0,
    "lon_east": 51.0,
}


def clear_zarr_encodings(dataset):
    """Clear remote S3 chunk encodings so Zarr can write fresh local structures."""
    dataset.encoding.clear()
    for var in dataset.variables:
        dataset[var].encoding.clear()
    return dataset


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


def get_cached_land_mask(fine_lats, fine_lons, layer_key="districtMdg"):
    """
    Generates and caches the boolean spatial land mask ONCE in memory.
    Subsequent calls re-use the cached mask array instantly (0ms overhead).
    """
    global GEOMETRY_MASK_CACHE

    if GEOMETRY_MASK_CACHE is not None:
        return GEOMETRY_MASK_CACHE

    logger.info("Building cached high-resolution land mask...")
    try:
        geojson_data = get_geojson_from_shapefile(layer_key)
        gdf = gpd.GeoDataFrame.from_features(geojson_data["features"], crs="EPSG:4326")

        height = len(fine_lats)
        width = len(fine_lons)

        min_lon, max_lon = float(np.min(fine_lons)), float(np.max(fine_lons))
        min_lat, max_lat = float(np.min(fine_lats)), float(np.max(fine_lats))

        transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)
        geometries = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]

        mask = geometry_mask(
            geometries,
            out_shape=(height, width),
            transform=transform,
            invert=False,  # False: Outside land geometry = True (Ocean)
        )

        GEOMETRY_MASK_CACHE = mask
        return mask
    except Exception as e:
        logger.error(f"Failed to generate land mask: {e}")
        return None


def clip_to_land_shapefile(da_field, layer_key="districtMdg", target_resolution=0.05):
    """
    Interpolates da_field to a fine grid and masks ocean pixels using pre-cached land mask.
    """
    try:
        min_lat, max_lat = float(da_field.latitude.min()), float(da_field.latitude.max())
        min_lon, max_lon = float(da_field.longitude.min()), float(da_field.longitude.max())

        # 1. High-resolution grid
        fine_lats = np.arange(max_lat, min_lat - target_resolution, -target_resolution)
        fine_lons = np.arange(min_lon, max_lon + target_resolution, target_resolution)

        # 2. Fast linear interpolation
        da_interp = da_field.interp(latitude=fine_lats, longitude=fine_lons, method="linear")

        # 3. Retrieve pre-built boolean mask
        mask = get_cached_land_mask(fine_lats, fine_lons, layer_key)

        if mask is not None:
            masked_values = np.where(mask, np.nan, da_interp.values)
            da_interp.values = masked_values

        return da_interp

    except Exception as e:
        logger.warning(f"Land clipping failed: {e}. Returning unclipped raster.")
        return da_field


def download_and_save_aifs():
    """Fetch 72h forecast from S3 Icechunk, compute parameters, and save locally."""
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
    max_lead = np.timedelta64(72, "h")

    logger.info(f"Downloading 72h AIFS forecast for run {latest_init} over Madagascar...")

    regional_ds = ds_sub.sel(
        init_time=[latest_init],
        lead_time=ds_sub.lead_time <= max_lead,
        latitude=slice(MADAGASCAR_BBOX["lat_north"], MADAGASCAR_BBOX["lat_south"]),
        longitude=slice(MADAGASCAR_BBOX["lon_west"], MADAGASCAR_BBOX["lon_east"]),
    )

    loaded_ds = regional_ds.load()
    loaded_ds = clear_zarr_encodings(loaded_ds)

    # 1. Temperature in degC
    # Per the AIFS data catalog, temperature_2m is ALREADY degree_Celsius -
    # no Kelvin conversion needed. (Previously this was assumed/guessed at
    # runtime via a ">200" heuristic in the FWI calc script - that heuristic
    # is now removed there too, since the units are confirmed at the source.)
    if "temperature_2m" in loaded_ds:
        loaded_ds["temp_2m_celsius"] = loaded_ds["temperature_2m"]
        loaded_ds["temp_2m_celsius"].attrs["units"] = "degC"

    # 2. Relative Humidity (%) - t2m/d2m are already Celsius, so no conversion
    # is required before calling calculate_relative_humidity().
    if "temperature_2m" in loaded_ds and "dew_point_temperature_2m" in loaded_ds:
        loaded_ds["relative_humidity_2m"] = calculate_relative_humidity(
            loaded_ds["temperature_2m"], loaded_ds["dew_point_temperature_2m"]
        )
        loaded_ds["relative_humidity_2m"].attrs["units"] = "%"

    # 3. Precipitation in mm (CUMULATIVE since init_time)
    # Per the AIFS data catalog, precipitation_surface is in kg m-2 s-1, described
    # as "average precipitation rate since the previous forecast step" - i.e. a
    # RATE (equivalent to mm/s), not an accumulated total, and NOT in meters.
    # The previous `* 1000.0` conversion was wrong on both counts.
    #
    # To get a correct, monotonically increasing cumulative mm field (which the
    # existing /plot "Total Rainfall" route relies on via max(lead_time) -
    # min(lead_time)), we convert each step's rate to the mm that fell during
    # that step's duration, then take a running cumulative sum.
    if "precipitation_surface" in loaded_ds:
        lead_seconds = loaded_ds["lead_time"].values.astype("timedelta64[s]").astype(np.float64)
        # Duration (s) covered by each step's "average rate since previous step".
        # First step's duration is assumed to run from init_time (t=0) to itself.
        step_duration_s = np.diff(lead_seconds, prepend=0.0)
        step_duration_da = xr.DataArray(
            step_duration_s, coords={"lead_time": loaded_ds["lead_time"]}, dims=["lead_time"]
        )

        precip_step_mm = loaded_ds["precipitation_surface"] * step_duration_da
        loaded_ds["precipitation_surface_mm"] = precip_step_mm.cumsum(dim="lead_time")
        loaded_ds["precipitation_surface_mm"].attrs["units"] = "mm"
        loaded_ds["precipitation_surface_mm"].attrs["description"] = (
            "Cumulative precipitation (mm) since forecast init_time, derived from "
            "the average precipitation rate (kg m-2 s-1) reported per forecast step."
        )

    # 4. Wind speed in m/s
    if "wind_u_10m" in loaded_ds and "wind_v_10m" in loaded_ds:
        loaded_ds["wind_speed_10m"] = np.sqrt(
            loaded_ds["wind_u_10m"] ** 2 + loaded_ds["wind_v_10m"] ** 2
        )
        loaded_ds["wind_speed_10m"].attrs["units"] = "m/s"

    os.makedirs(FORECAST_DIR, exist_ok=True)
    loaded_ds.to_zarr(LOCAL_ZARR_PATH, mode="w")
    logger.info(f"Successfully saved raw forecast to '{LOCAL_ZARR_PATH}'")

    # Invalidate rendered plot cache when new data arrives
    PLOT_CACHE.clear()

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


def get_day_slice(ds, day_num):
    start_h = day_num * 24
    end_h = (day_num + 1) * 24

    lead_hours = ds.lead_time.values.astype("timedelta64[h]").astype(int)
    mask = (lead_hours >= start_h) & (lead_hours <= end_h)
    return ds.isel(lead_time=mask)


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

    # -------------------------------------------------------------
    # OPTIMIZATION 1: Check In-Memory Plot Cache (Instant < 10ms response)
    # -------------------------------------------------------------
    cache_key = f"{var_name}_day{day_num}"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        ds = get_aifs_dataset()
        day_ds = get_day_slice(ds, day_num)

        # Config per variable
        if var_name == "precipitation_surface_mm":
            field = day_ds[var_name].max(dim="lead_time") - day_ds[var_name].min(dim="lead_time")
            cmap_name = "Blues"
            unit = "mm"
            title_name = "Total Rainfall"
        elif var_name == "temp_2m_celsius":
            field = day_ds[var_name].max(dim="lead_time")
            cmap_name = "Spectral_r"
            unit = "°C"
            title_name = "Max Temperature"
        elif var_name == "wind_speed_10m":
            field = day_ds[var_name].max(dim="lead_time")
            cmap_name = "viridis"
            unit = "m/s"
            title_name = "Max Wind Speed"
        elif var_name == "relative_humidity_2m":
            field = day_ds[var_name].min(dim="lead_time")
            cmap_name = "YlGnBu"
            unit = "%"
            title_name = "Min Relative Humidity"
        else:
            field = day_ds[var_name].mean(dim="lead_time")
            cmap_name = "coolwarm"
            unit = ""
            title_name = var_name

        if "init_time" in field.dims:
            field = field.squeeze("init_time")

        # Sort latitude north-to-south
        if field.latitude[0] < field.latitude[-1]:
            field = field.reindex(latitude=field.latitude[::-1])

        # -------------------------------------------------------------
        # OPTIMIZATION 2: Smooth & Mask using Cached Land Mask
        # -------------------------------------------------------------
        field = clip_to_land_shapefile(field, layer_key="districtMdg", target_resolution=0.05)

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

        # Render transparent PNG for Leaflet Overlay
        fig = plt.figure(figsize=(6, 6), frameon=False)  # Slightly reduced figure size for faster rendering
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
            interpolation="bilinear",  # Nearest is Faster rendering since array is already 0.05° interpolated, but maybe bilinear is better
        )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, transparent=True)  # Optimized 150 DPI
        buf.seek(0)
        plt.close(fig)

        # Base64 encoding
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{img_base64}"

        # Generate Legend Ticks
        legend_ticks = []
        tick_vals = np.linspace(vmin, vmax, 5)
        for val in tick_vals:
            rgba = cmap(norm(val))
            hex_color = mcolors.to_hex(rgba)
            legend_ticks.append({"value": round(float(val), 1), "color": hex_color})

        day_label = "Today" if day_num == 0 else "Tomorrow" if day_num == 1 else f"Day {day_num}"

        response_payload = {
            "status": "success",
            "bounds": bounds,
            "imageUrl": data_url,
            "legend": legend_ticks,
            "unit": unit,
            "title": f"{title_name} ({day_label})",
        }

        # Save result to memory cache
        PLOT_CACHE[cache_key] = response_payload

        return jsonify(response_payload)

    except Exception as e:
        logger.error(f"Failed to generate forecast plot: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500

    