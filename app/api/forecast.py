# app/api/forecast.py

import os
import time
import math
import pandas as pd
import numpy as np
import rioxarray
import xarray as xr
import shapely.geometry as sg
from shapely.geometry import Point, shape
from flask import Blueprint, request, jsonify
from app.api.fire_indices import compute_fire_indices

forecast_bp = Blueprint('forecast', __name__)

# NASA FIRMS 24h CSV URL for Southern Africa
FIRMS_CSV_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Southern_Africa_24h.csv"

# Global cache for FIRMS active fires to avoid downloading on every click
FIRMS_CACHE = {
    "last_fetched": 0,
    "df": None
}

def get_latest_firms_data(ttl_seconds=900):
    """
    Downloads and caches NASA FIRMS 24h active fire CSV for Southern Africa.
    Refreshes every 15 minutes (900s).
    """
    now = time.time()
    if FIRMS_CACHE["df"] is not None and (now - FIRMS_CACHE["last_fetched"] < ttl_seconds):
        return FIRMS_CACHE["df"]

    try:
        df = pd.read_csv(FIRMS_CSV_URL)
        # Standardize column names to lowercase
        df.columns = [c.lower() for c in df.columns]
        FIRMS_CACHE["df"] = df
        FIRMS_CACHE["last_fetched"] = now
        print(f"[FIRMS] Successfully cached {len(df)} active fire records from NASA FIRMS.")
        return df
    except Exception as e:
        print(f"[FIRMS] Error fetching FIRMS CSV: {e}")
        return FIRMS_CACHE["df"] if FIRMS_CACHE["df"] is not None else pd.DataFrame()


def haversine_distance_km(lat1, lon1, lat2, lon2):
    """
    Calculates the Great Circle distance between two points in km using the Haversine formula.
    """
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def compute_fire_proximity_firms(geometry_dict=None, lat=None, lon=None, max_radius_km=50.0):
    """
    Computes active fire count inside a polygon OR distance from clicked point to nearest FIRMS active fire.
    """
    df_fires = get_latest_firms_data()
    if df_fires.empty or ('latitude' not in df_fires.columns or 'longitude' not in df_fires.columns):
        return {"active_count": 0, "min_distance_km": None}

    # Extract latitudes and longitudes from FIRMS dataframe
    fire_lats = df_fires['latitude'].values
    fire_lons = df_fires['longitude'].values

    # 1. POLYGON / AREA SELECTION
    if geometry_dict:
        try:
            poly = shape(geometry_dict)
            
            # Count fires directly INSIDE or INTERSECTING polygon
            inside_count = 0
            min_km = float('inf')

            for flat, flon in zip(fire_lats, fire_lons):
                pt = Point(flon, flat)
                if poly.contains(pt) or poly.intersects(pt):
                    inside_count += 1
                else:
                    # Approximation for poly distance: center of poly to fire
                    centroid = poly.centroid
                    d_km = haversine_distance_km(centroid.y, centroid.x, flat, flon)
                    if d_km < min_km:
                        min_km = d_km

            if inside_count > 0:
                return {
                    "active_count": inside_count,
                    "min_distance_km": 0.0
                }

            if min_km != float('inf') and min_km <= max_radius_km:
                return {"active_count": 0, "min_distance_km": round(min_km, 2)}
            else:
                return {"active_count": 0, "min_distance_km": round(min_km, 2) if min_km != float('inf') else None}

        except Exception as e:
            print(f"[FIRMS] Error evaluating polygon fire intersection: {e}")
            return {"active_count": 0, "min_distance_km": None}

    # 2. CLICKED POINT SELECTION
    elif lat is not None and lon is not None:
        distances = [haversine_distance_km(lat, lon, flat, flon) for flat, flon in zip(fire_lats, fire_lons)]
        if not distances:
            return {"active_count": 0, "min_distance_km": None}

        min_km = min(distances)
        nearby_count = sum(1 for d in distances if d <= max_radius_km)

        return {
            "active_count": nearby_count if min_km <= max_radius_km else 0,
            "min_distance_km": round(min_km, 2)
        }

    return {"active_count": 0, "min_distance_km": None}


def compute_ndvi_trend_from_files(lat=None, lon=None, geometry_dict=None, ndvi_dir="./data/NDVI"):
    """
    Computes NDVI Delta (latest - previous) using ./data/NDVI/latest_ndvi.nc and previous_ndvi.nc
    """
    latest_path = os.path.join(ndvi_dir, "latest_ndvi.nc")
    previous_path = os.path.join(ndvi_dir, "previous_ndvi.nc")

    if not (os.path.exists(latest_path) and os.path.exists(previous_path)):
        print(f"[NDVI] NetCDF files missing in {ndvi_dir}")
        return 0.0

    try:
        ds_latest = rioxarray.open_rasterio(latest_path, masked=True)
        ds_prev = rioxarray.open_rasterio(previous_path, masked=True)

        # Set EPSG CRS if missing
        if not ds_latest.rio.crs: ds_latest = ds_latest.rio.write_crs("EPSG:4326")
        if not ds_prev.rio.crs: ds_prev = ds_prev.rio.write_crs("EPSG:4326")

        def extract_single_val(da):
            lat_key = next((k for k in ['latitude', 'lat', 'y'] if k in da.dims or k in da.coords), None)
            lon_key = next((k for k in ['longitude', 'lon', 'x'] if k in da.dims or k in da.coords), None)

            if geometry_dict:
                clipped = da.rio.clip([geometry_dict], crs="EPSG:4326", drop=True)
                spatial_dims = [d for d in [lat_key, lon_key] if d in clipped.dims]
                mean_val = clipped.mean(dim=spatial_dims, skipna=True).values if spatial_dims else clipped.mean(skipna=True).values
                return float(np.nan_to_num(mean_val, nan=0.0))
            elif lat is not None and lon is not None:
                val = da.sel({lat_key: lat, lon_key: lon}, method='nearest').values
                return float(np.nan_to_num(val, nan=0.0))
            return 0.0

        latest_val = extract_single_val(ds_latest)
        prev_val = extract_single_val(ds_prev)

        ds_latest.close()
        ds_prev.close()

        delta = latest_val - prev_val
        return round(float(delta), 4)

    except Exception as e:
        print(f"[NDVI] Delta calculation error: {e}")
        return 0.0


def extract_time_series(da, lat=None, lon=None, geometry_dict=None, num_days=3):
    """
    Extracts Day 0, Day 1, Day 2 values for a point or polygon area-average
    from a cached xarray DataArray or Dataset.
    """
    if da is None:
        return [0.0] * num_days

    lat_key = next((k for k in ['latitude', 'lat', 'y'] if k in da.dims or k in da.coords), None)
    lon_key = next((k for k in ['longitude', 'lon', 'x'] if k in da.dims or k in da.coords), None)

    try:
        if geometry_dict:
            if not da.rio.crs:
                da = da.rio.write_crs("EPSG:4326")

            clipped = da.rio.clip([geometry_dict], crs="EPSG:4326", drop=True)
            spatial_dims = [d for d in [lat_key, lon_key] if d in clipped.dims]
            means = clipped.mean(dim=spatial_dims, skipna=True).values if spatial_dims else clipped.mean(skipna=True).values
            
            vals = np.atleast_1d(np.nan_to_num(means, nan=0.0)).flatten()
            return [round(float(v), 4) for v in vals[:num_days]]

        elif lat is not None and lon is not None:
            point_vals = da.sel({lat_key: lat, lon_key: lon}, method='nearest').values
            vals = np.atleast_1d(np.nan_to_num(point_vals, nan=0.0)).flatten()
            return [round(float(v), 4) for v in vals[:num_days]]

    except Exception as e:
        print(f"Extraction error: {e}")
        return [0.0] * num_days

    return [0.0] * num_days


def get_da_by_keys(ds, possible_keys):
    """Helper to retrieve the first matching variable key from an xarray Dataset."""
    if ds is None:
        return None
    for k in possible_keys:
        if k in ds.data_vars or k in ds:
            return ds[k]
    return None


@forecast_bp.route('/api/forecast/summary', methods=['POST'])
def get_forecast_summary():
    data = request.get_json() or {}
    lat = data.get('lat')
    lon = data.get('lon')
    geometry_dict = data.get('geometry')
    location_name = data.get('name')

    if lat is not None: lat = float(lat)
    if lon is not None: lon = float(lon)

    # 1. Retrieve cached datasets from memory
    fwi_da, fopi_da, aifs_ds, _ = compute_fire_indices()

    # 2. Extract DataArrays matching variable names
    tas_da = get_da_by_keys(aifs_ds, ['temp_c', 'temperature_2m', '2t', 'tas'])
    pr_da = get_da_by_keys(aifs_ds, ['precipitation_surface', 'tp', 'pr', 'rr'])
    rh_da = get_da_by_keys(aifs_ds, ['relative_humidity', 'hurs', 'r', '2r', 'rh'])
    wind_da = get_da_by_keys(aifs_ds, ['wind_speed_10m', 'sfcWind', '10si', 'ws'])

    # 3. Extract Time Series
    temperature = extract_time_series(tas_da, lat, lon, geometry_dict)
    raw_rainfall = extract_time_series(pr_da, lat, lon, geometry_dict)
    raw_rh = extract_time_series(rh_da, lat, lon, geometry_dict)
    wind = extract_time_series(wind_da, lat, lon, geometry_dict)

    # Unit Adjustments:
    if max(raw_rainfall) < 1.0:
        rainfall = [round(r * 1000.0, 2) for r in raw_rainfall]
    else:
        rainfall = [round(r, 2) for r in raw_rainfall]

    if max(raw_rh) <= 1.0 and max(raw_rh) > 0.0:
        rh = [round(r * 100.0, 1) for r in raw_rh]
    else:
        rh = [round(r, 1) for r in raw_rh]

    # 4. Extract FWI & FOPI
    fwi_series = extract_time_series(fwi_da, lat, lon, geometry_dict)
    fopi_series = extract_time_series(fopi_da, lat, lon, geometry_dict)

    # 5. Compute NASA FIRMS active fire proximity & NDVI Delta from files
    fire_info = compute_fire_proximity_firms(geometry_dict, lat, lon)
    ndvi_trend = compute_ndvi_trend_from_files(lat, lon, geometry_dict)

    return jsonify({
        "status": "success",
        "name": location_name or (f"Point ({lat}, {lon})" if lat else "Selected Region"),
        "temperature": temperature,
        "rainfall": rainfall,    # in mm
        "rh": rh,                # in %
        "wind": wind,            # in m/s
        "fwi": [round(v, 1) for v in fwi_series],
        "fopi": [round(v, 2) for v in fopi_series],
        "fire_info": fire_info,
        "ndvi_trend": ndvi_trend
    })

