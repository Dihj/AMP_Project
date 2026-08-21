
import base64
import io
import logging
import os

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba-cache")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import xarray as xr
import xclim
from flask import Blueprint, jsonify, request

from app.core.dataset_cache import get_cached_indices, set_cached_indices
from app.core.fire_state_io import load_fire_initialization

matplotlib.use("Agg")

from app.api.aifs_frcst import (
    get_aifs_dataset,
    get_daily_noon_aifs_dataset,
    FORECAST_HORIZON_DAYS,
)
from app.api.ndvi import get_ndvi_dataset

fire_indices_bp = Blueprint("fire_indices", __name__, url_prefix="/api/fire-indices")
logger = logging.getLogger(__name__)

PLOT_CACHE = {}
FIELD_CACHE = {}

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Southern_Africa_24h.csv"
MADAGASCAR_FIRMS_BOUNDS = {
    "lat_min": -25.7, "lat_max": -11.9, "lon_min": 43.1, "lon_max": 50.8,
}
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIRE_CLIM_PATH = os.path.join(BASE_DIR, "data", "netcdf", "climatology", "FIRE_climV2.nc")
FIRE_CLIM_FALLBACK_PATH = os.path.join(BASE_DIR, "data", "netcdf", "climatology", "FIRE_clim.nc")

FOPI_A = -3.5
FOPI_B1_FWI = 0.08
FOPI_B2_FUEL = 2.5
FOPI_B3_FIRE_CLIM = 2.0


# ---------------------------------------------------------------------------
# Optional active-fire enhancement layer (FOPI only - NOT used for FFMC/DMC/DC)
# ---------------------------------------------------------------------------

def get_active_fire_mask(target_grid):

    target_grid = _spatial_reference(target_grid)
    lats = target_grid.latitude.values
    lons = target_grid.longitude.values
    mask = np.zeros((len(lats), len(lons)), dtype=bool)

    try:
        resp = requests.get(FIRMS_URL, timeout=10)
        if resp.status_code == 200:
            df_firms = pd.read_csv(io.StringIO(resp.text))
            b = MADAGASCAR_FIRMS_BOUNDS
            mad_fires = df_firms[
                (df_firms["latitude"] >= b["lat_min"]) & (df_firms["latitude"] <= b["lat_max"]) &
                (df_firms["longitude"] >= b["lon_min"]) & (df_firms["longitude"] <= b["lon_max"])
            ]
            for _, fire in mad_fires.iterrows():
                lat_idx = int(np.abs(lats - fire["latitude"]).argmin())
                lon_idx = int(np.abs(lons - fire["longitude"]).argmin())
                mask[lat_idx, lon_idx] = True
        else:
            logger.warning(f"FIRMS request returned status {resp.status_code}; proceeding without active-fire enhancement.")
    except Exception as e:
        logger.warning(f"Could not fetch FIRMS data ({e}). Proceeding without active-fire enhancement for FOPI.")

    return xr.DataArray(mask, coords={"latitude": lats, "longitude": lons}, dims=("latitude", "longitude"))


def _spatial_reference(obj):
    """Return a 2-D spatial reference even when the input also has time."""
    if "time" in obj.dims:
        return obj.isel(time=0, drop=True)
    if "lead_time" in obj.dims:
        return obj.isel(lead_time=0, drop=True)
    return obj


def _latitude_for_cffwis(da):
    """xclim validates latitude units explicitly."""
    lat = da.latitude if "latitude" in da.coords else da.lat
    lat = lat.copy()
    lat.attrs.setdefault("units", "degrees_north")
    return lat



def _logistic(x):
    return 1.0 / (1.0 + np.exp(-x))


def _normalize_0_1(da):
    upper = float(da.quantile(0.95, skipna=True))
    if not np.isfinite(upper) or upper <= 0:
        upper = float(da.max(skipna=True))
    if not np.isfinite(upper) or upper <= 0:
        return xr.zeros_like(da)
    return (da / upper).clip(0.0, 1.0)


def load_monthly_fire_climatology_factor(fwi):

    clim_path = FIRE_CLIM_PATH if os.path.exists(FIRE_CLIM_PATH) else FIRE_CLIM_FALLBACK_PATH
    if not os.path.exists(clim_path):
        logger.warning(
            f"Fire climatology not found ({FIRE_CLIM_PATH} or "
            f"{FIRE_CLIM_FALLBACK_PATH}); FOPI fire-climatology term set to zero."
        )
        return xr.zeros_like(fwi)

    with xr.open_dataset(clim_path) as clim_ds:
        fire_density = clim_ds["fire_density"]
        if "lat" in fire_density.dims:
            fire_density = fire_density.rename({"lat": "latitude", "lon": "longitude"})

        monthly_norm = _normalize_0_1(fire_density)
        target_lats = fwi.latitude.values
        target_lons = fwi.longitude.values

        if "time" not in fwi.dims:
            month_idx = pd.Timestamp.now().month - 1
            clim = monthly_norm.isel(time=month_idx)
            return clim.interp(latitude=target_lats, longitude=target_lons, method="linear").fillna(0.0).load()

        clim_steps = []
        for t in pd.to_datetime(fwi.time.values):
            month_idx = pd.Timestamp(t).month - 1
            clim = monthly_norm.isel(time=month_idx)
            clim_interp = clim.interp(
                latitude=target_lats, longitude=target_lons, method="linear"
            ).fillna(0.0)
            clim_steps.append(clim_interp)

        out = xr.concat(clim_steps, dim=fwi.time)
        out = out.transpose(*fwi.dims)
        return out.load()


def calculate_fopi_improved(fwi, ndvi_ds, active_fire_mask=None):

    ndvi_key = "NDVI" if "NDVI" in ndvi_ds else list(ndvi_ds.data_vars)[0]
    logger.info(f"Using NDVI variable: {ndvi_key} with shape {ndvi_ds[ndvi_key].shape}")

    ndvi_da = ndvi_ds[ndvi_key]
    if "lat" in ndvi_da.dims:
        ndvi_da = ndvi_da.rename({"lat": "latitude", "lon": "longitude"})

    ndvi_interp = ndvi_da.interp(latitude=fwi.latitude, longitude=fwi.longitude, method="linear")
    nan_count = int(ndvi_interp.isnull().sum())
    total_count = ndvi_interp.size
    logger.info(f"NDVI grid NaN: {nan_count}/{total_count} pixel(s) filled with default 0.2")

    ndvi_clean = np.clip(ndvi_interp.fillna(0.2), 0.0, 1.0)

    # Fuel proxy: higher when vegetation is drier or sparse enough to burn.
    fuel_proxy = np.clip((0.85 - ndvi_clean) / 0.65, 0.0, 1.0)
    logger.info(
        f"FOPI fuel proxy range: min={float(fuel_proxy.min()):.3f}, "
        f"max={float(fuel_proxy.max()):.3f}, mean={float(fuel_proxy.mean()):.3f}"
    )

    fire_climatology = load_monthly_fire_climatology_factor(fwi)
    logger.info(
        f"FOPI fire climatology range: min={float(fire_climatology.min()):.3f}, "
        f"max={float(fire_climatology.max()):.3f}, mean={float(fire_climatology.mean()):.3f}"
    )

    fopi_raw = (
        FOPI_A
        + FOPI_B1_FWI * fwi
        + FOPI_B2_FUEL * fuel_proxy
        + FOPI_B3_FIRE_CLIM * fire_climatology
    )
    fopi = _logistic(fopi_raw).clip(0.0, 1.0)
    fopi.attrs.update(
        {
            "long_name": "Fire Occurrence Probability Index",
            "formula": "logistic(a + b1 * FWI + b2 * fuel_proxy + b3 * fire_climatology)",
            "a": FOPI_A,
            "b1_fwi": FOPI_B1_FWI,
            "b2_fuel_proxy": FOPI_B2_FUEL,
            "b3_fire_climatology": FOPI_B3_FIRE_CLIM,
            "fuel_proxy": "clip((0.85 - NDVI) / 0.65, 0, 1)",
            "fire_climatology": "Monthly MODIS active-fire climatology normalized by 95th percentile",
        }
    )
    return fopi


# ---------------------------------------------------------------------------
# Core forecast computation
# ---------------------------------------------------------------------------

def compute_fire_indices(force_recompute=False):

    cache = get_cached_indices()
    if not force_recompute and cache['fwi'] is not None and cache['fopi'] is not None:
        return cache['fwi'], cache['fopi'], cache['aifs'], cache['ndvi']

    logger.info(f"Computing FWI and FOPI (daily, day 0..{FORECAST_HORIZON_DAYS - 1}) ....")

    aifs_ds = get_aifs_dataset()
    ndvi_ds = get_ndvi_dataset()

    # Local-noon-sampled tas/hurs/wind + 24h-accumulated pr - see
    # app.api.aifs_frcst.get_daily_noon_aifs_dataset() for the CFFDRS
    # noon-sampling rationale.
    noon_ds = get_daily_noon_aifs_dataset()
    noon_tas = noon_ds["temp_2m_celsius"]
    noon_wind = noon_ds["wind_speed_10m"]
    noon_hurs = noon_ds["relative_humidity_2m"]
    noon_pr = noon_ds["precipitation_surface_mm"].copy()
    noon_pr.attrs["units"] = "mm/day"  # unit string xclim expects for precip

    if "latitude" not in noon_tas.coords and "lat" not in noon_tas.coords:
        raise KeyError("Latitude coordinate ('latitude' or 'lat') not found in dataset.")
    lat = _latitude_for_cffwis(noon_tas)

    # Seed the forecast chain from the continuous operational state
    # (priority order documented in app.core.fire_state_io).
    target_grid = _spatial_reference(noon_tas)
    ffmc0, dmc0, dc0, init_source = load_fire_initialization(target_grid)
    logger.info(f"Forecast fire-code initialization source: {init_source}")

    dc, dmc, ffmc, isi, bui, fwi = xclim.indices.cffwis_indices(
        tas=noon_tas, pr=noon_pr, sfcWind=noon_wind, hurs=noon_hurs,
        lat=lat, ffmc0=ffmc0, dmc0=dmc0, dc0=dc0,
    )

    fopi_ds = calculate_fopi_improved(fwi=fwi, ndvi_ds=ndvi_ds)

    fwi.attrs["fire_code_init_source"] = init_source
    fopi_ds.attrs["fire_code_init_source"] = init_source

    set_cached_indices(fwi, fopi_ds, aifs_ds, ndvi_ds)
    FIELD_CACHE.clear()

    return fwi, fopi_ds, aifs_ds, ndvi_ds


def get_fire_index_field(index_type, day_num):

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
    index_type = request.args.get("index", "fwi").lower()
    day = int(request.args.get("day", 0))

    cache_key = f"{index_type}_day_{day}"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        field = get_fire_index_field(index_type, day)

        lats = field.latitude.values
        lons = field.longitude.values

        lat_res = float(np.abs(np.mean(np.diff(lats)))) if len(lats) > 1 else 0.0
        lon_res = float(np.abs(np.mean(np.diff(lons)))) if len(lons) > 1 else 0.0

        bounds = [
            [float(np.min(lats)) - lat_res / 2, float(np.min(lons)) - lon_res / 2],
            [float(np.max(lats)) + lat_res / 2, float(np.max(lons)) + lon_res / 2],
        ]

        data_vals = field.values

        if index_type == "fwi":
            # Matches the FWI gauge scale used in forecastModalManager.js
            levels = [0, 11.2, 21.3, 38.0, 50.0, 70.0, 80.0]
            colors = [
                "#98FBB2",  # Low
                "#D2E351",  # Moderate
                "#E6A900",  # High
                "#D66610",  # Very High
                "#B4070C",  # Extreme
                "#320212",  # Extreme+
            ]
            labels = ["Faible", "Modéré", "Élevé", "Très Élevé", "Extrême", "Extrême+"]
            title = "FWI"
            unit = "FWI"
            cmap = mcolors.ListedColormap(colors)
            norm = mcolors.BoundaryNorm(levels, cmap.N)
        else:  # FOPI
            levels = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            colors = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]
            labels = [
                "Faible (<0.2)",
                "Modéré (0.2-0.4)",
                "Élevé (0.4-0.6)",
                "Très Élevé (0.6-0.8)",
                "Extrême (>0.8)",
            ]
            title = "FOPI"
            unit = "Probabilite"
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
            "fire_code_init_source": getattr(field, "attrs", {}).get("fire_code_init_source", "unknown"),
        }

        PLOT_CACHE[cache_key] = response_payload
        return jsonify(response_payload)

    except Exception as e:
        logger.error(
            f"Failed to calculate or render {index_type} plot: {e}",
            exc_info=True,
        )
        return jsonify({"status": "error", "error": str(e)}), 500
