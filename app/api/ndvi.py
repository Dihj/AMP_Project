import base64
import io
import logging
import os
import time
from datetime import datetime, timedelta
import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import planetary_computer
from pystac_client import Client
import rioxarray
from rioxarray.merge import merge_arrays
import xarray as xr
from flask import Blueprint, jsonify, request

from app.scripts.spatial_calc import get_geojson_from_shapefile

matplotlib.use("Agg")
logger = logging.getLogger(__name__)

ndvi_bp = Blueprint("ndvi", __name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NDVI_DATA_DIR = os.path.join(BASE_DIR, "data", "NDVI")
LATEST_NDVI_PATH = os.path.join(NDVI_DATA_DIR, "latest_ndvi.nc")
PREVIOUS_NDVI_PATH = os.path.join(NDVI_DATA_DIR, "previous_ndvi.nc")

NDVI_CACHE = {"last_fetched": 0, "dataset": None}
PLOT_CACHE = {}
GEOMETRY_MASK_CACHE = None

DEBUG_MODE = False
CACHE_TTL = 86400 * 15

MADAGASCAR_BBOX = [43.1, -25.7, 50.8, -11.9] 
RASTER_EXPORT_DPI = 200
RASTER_EXPORT_MAX_PIXELS = 2600


def raster_figure_size(data_vals, max_pixels=RASTER_EXPORT_MAX_PIXELS, dpi=RASTER_EXPORT_DPI):
    height, width = np.squeeze(data_vals).shape[-2:]
    scale = min(max_pixels / max(height, width), 1.0)
    return (width * scale / dpi, height * scale / dpi)

import traceback  

def download_and_save_ndvi():

    os.makedirs(NDVI_DATA_DIR, exist_ok=True)
    logger.info(f"Downloading NDVI to repository directory: {NDVI_DATA_DIR}")

    try:
        catalog = Client.open(
            "https://planetarycomputer.microsoft.com/api/stac/v1",
            modifier=planetary_computer.sign_inplace,
        )

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=90)  # Expanded window to ensure complete coverage
        date_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"

        logger.info(f"Searching STAC API for MODIS items in range: {date_range}")
        search = catalog.search(
            collections=["modis-13Q1-061"],
            bbox=MADAGASCAR_BBOX,
            datetime=date_range,
        )

        items = search.item_collection()
        logger.info(f"Found {len(items)} raw STAC items.")

        if len(items) == 0:
            raise ValueError("No MODIS NDVI items found for Madagascar within the given date window.")

        grouped_items = {}
        for item in items:
            dt_str = item.properties.get("datetime")
            if not dt_str and hasattr(item, "datetime") and item.datetime is not None:
                dt_str = item.datetime.strftime("%Y-%m-%d")
            if not dt_str:
                dt_str = item.properties.get("start_datetime")
            if not dt_str:
                dt_str = str(item.id)

            period_key = str(dt_str)[:10]

            if period_key not in grouped_items:
                grouped_items[period_key] = []
            grouped_items[period_key].append(item)

        sorted_periods = sorted(grouped_items.keys(), reverse=True)
        logger.info(f"Available MODIS NDVI periods: {sorted_periods[:2]}")

        target_files = [(sorted_periods[0], LATEST_NDVI_PATH, "latest")]
        if len(sorted_periods) > 1:
            target_files.append((sorted_periods[1], PREVIOUS_NDVI_PATH, "previous"))

        for period_key, output_path, label in target_files:
            logger.info(f"Downloading {label} NDVI period ({period_key})...")
            period_items = grouped_items[period_key]
            ndvi_tiles = []

            for item in period_items:
                asset_key = "250m_16_days_NDVI" if "250m_16_days_NDVI" in item.assets else "NDVI"
                if asset_key in item.assets:
                    href = item.assets[asset_key].href
                    
                    tile_da = rioxarray.open_rasterio(href, masked=True).squeeze()
                    tile_da_4326 = tile_da.rio.reproject("EPSG:4326")
                    tile_da_clipped = tile_da_4326.rio.clip_box(*MADAGASCAR_BBOX, crs="EPSG:4326")
                    ndvi_tiles.append(tile_da_clipped)

            if not ndvi_tiles:
                logger.warning(f"No valid tiles retrieved for period {period_key}")
                continue

            merged_ndvi = merge_arrays(ndvi_tiles) * 0.0001
            
            if "x" in merged_ndvi.dims and "y" in merged_ndvi.dims:
                merged_ndvi = merged_ndvi.rename({"x": "longitude", "y": "latitude"})
                
            merged_ndvi.name = "NDVI"
            merged_ndvi = merged_ndvi.where((merged_ndvi >= -0.2) & (merged_ndvi <= 1.0))

            ndvi_ds = merged_ndvi.to_dataset()
            ndvi_ds.attrs["period_date"] = period_key
            ndvi_ds.to_netcdf(output_path)
            logger.info(f"Successfully saved NetCDF file: {output_path}")

        PLOT_CACHE.clear()
        return True

    except Exception as e:
        logger.error(f"CRITICAL ERROR in download_and_save_ndvi: {e}")
        import traceback
        traceback.print_exc()
        raise e
    
    

def get_ndvi_dataset():
    current_time = time.time()

    if NDVI_CACHE["dataset"] is not None:
        if DEBUG_MODE or (current_time - NDVI_CACHE["last_fetched"] < CACHE_TTL):
            return NDVI_CACHE["dataset"]

    if os.path.exists(LATEST_NDVI_PATH):
        file_age = current_time - os.path.getmtime(LATEST_NDVI_PATH)
        if DEBUG_MODE or (file_age < CACHE_TTL):
            logger.info(f"Loading local NetCDF from '{LATEST_NDVI_PATH}'")
            ds = xr.open_dataset(LATEST_NDVI_PATH)
            NDVI_CACHE["dataset"] = ds
            NDVI_CACHE["last_fetched"] = current_time
            return ds

    logger.info("Triggering fresh NDVI download pipeline...")
    download_and_save_ndvi()
    
    ds = xr.open_dataset(LATEST_NDVI_PATH)
    NDVI_CACHE["dataset"] = ds
    NDVI_CACHE["last_fetched"] = current_time
    return ds



@ndvi_bp.route("/plot", methods=["GET"])
def get_ndvi_plot():
    cache_key = "ndvi_latest_plot"
    if cache_key in PLOT_CACHE:
        return jsonify(PLOT_CACHE[cache_key])

    try:
        ds = get_ndvi_dataset()
        field = ds["NDVI"]

        if float(field.max()) > 1.5:
            field = field * 0.0001

        field = field.where((field >= -0.2) & (field <= 1.0))

        if field.latitude[0] < field.latitude[-1]:
            field = field.reindex(latitude=field.latitude[::-1])

        #field = clip_to_land_shapefile(field, layer_key="districtMdg", target_resolution=0.05)

        lats = field.latitude.values
        lons = field.longitude.values

        bounds = [
            [float(np.min(lats)), float(np.min(lons))],
            [float(np.max(lats)), float(np.max(lons))],
        ]

        data_vals = field.values

        vmin, vmax = -0.1, 0.8

        fig = plt.figure(figsize=raster_figure_size(data_vals), frameon=False)
        ax = plt.Axes(fig, [0.0, 0.0, 1.0, 1.0])
        ax.set_axis_off()
        fig.add_axes(ax)

        cmap = matplotlib.colormaps["YlGn"]
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        cmap.set_bad(color=(1, 1, 1, 0))

        ax.imshow(
            data_vals,
            cmap=cmap,
            norm=norm,
            origin="upper",
            aspect="auto",
            interpolation="nearest",
        )

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=RASTER_EXPORT_DPI, transparent=True)
        buf.seek(0)
        plt.close(fig)

        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{img_base64}"

        legend_ticks = []
        for val in np.linspace(vmin, vmax, 5):
            rgba = cmap(norm(val))
            legend_ticks.append({"value": round(float(val), 2), "color": mcolors.to_hex(rgba)})

        response_payload = {
            "status": "success",
            "bounds": bounds,
            "imageUrl": data_url,
            "legend": legend_ticks,
            "unit": "NDVI",
            "title": "Vegetation Index (MODIS 16-Day)",
        }

        PLOT_CACHE[cache_key] = response_payload
        return jsonify(response_payload)

    except Exception as e:
        logger.error(f"Failed to generate NDVI plot: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500
    
