
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
from scipy.ndimage import gaussian_filter

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



def calculate_fopi_improved(fwi, ndvi_ds, active_fire_mask, k=0.12, fwi_50=18.0):

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

    # Curing factor: higher when vegetation is dry (low NDVI).
    curing_factor = np.clip((0.85 - ndvi_clean) / 0.65, 0.0, 1.0)
    logger.info(
        f"Curing factor range: min={float(curing_factor.min()):.3f}, "
        f"max={float(curing_factor.max()):.3f}, mean={float(curing_factor.mean()):.3f}"
    )

    # Scale hazard so moderate FWI with high curing maps effectively.
    hazard_score = fwi * (0.4 + 0.8 * curing_factor)

    fire_mask_values = active_fire_mask.values.astype(float)
    smoothed_fire_risk = gaussian_filter(fire_mask_values, sigma=5.0) # sigma: pixel fois ny dimensiuon radius, 5km = 1, 15km = 3, ...
    max_val = smoothed_fire_risk.max()
    if max_val > 0:
        smoothed_fire_risk = smoothed_fire_risk / max_val

    fire_boost_da = xr.DataArray(
        smoothed_fire_risk, coords=active_fire_mask.coords, dims=active_fire_mask.dims,
    )

    # Optional active-fire boost (additive, not part of FFMC/DMC/DC).
    boosted_hazard = hazard_score + (fire_boost_da * 6.0) # dia ity koa soloina 6.0 au lieu de 15.0

    # Logistic transformation - see module docstring for the "not a
    # calibrated probability" caveat.
    fopi = 1.0 / (1.0 + np.exp(-k * (boosted_hazard - fwi_50)))
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

    active_fire_mask = get_active_fire_mask(noon_tas)

    fopi_ds = calculate_fopi_improved(
        fwi=fwi, ndvi_ds=ndvi_ds, active_fire_mask=active_fire_mask,
        k=0.12, fwi_50=18.0,
    )

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
