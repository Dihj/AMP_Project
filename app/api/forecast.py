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
from app.api.aifs_frcst import get_daily_weather_field, FORECAST_HORIZON_DAYS
from app.api.fire_indices import get_fire_index_field

forecast_bp = Blueprint('forecast', __name__)

# NASA FIRMS 24h CSV URL for Southern Africa
FIRMS_CSV_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Southern_Africa_24h.csv"

FIRMS_CACHE = {
    "last_fetched": 0,
    "df": None
}

NUM_DAYS = FORECAST_HORIZON_DAYS

def get_latest_firms_data(ttl_seconds=900):

    now = time.time()
    if FIRMS_CACHE["df"] is not None and (now - FIRMS_CACHE["last_fetched"] < ttl_seconds):
        return FIRMS_CACHE["df"]

    try:
        df = pd.read_csv(FIRMS_CSV_URL)
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
    R = 6371.0
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

    fire_lats = df_fires['latitude'].values
    fire_lons = df_fires['longitude'].values

    if geometry_dict:
        try:
            poly = shape(geometry_dict)
            inside_count = 0
            min_km = float('inf')

            for flat, flon in zip(fire_lats, fire_lons):
                pt = Point(flon, flat)
                if poly.contains(pt) or poly.intersects(pt):
                    inside_count += 1
                else:
                    centroid = poly.centroid
                    d_km = haversine_distance_km(centroid.y, centroid.x, flat, flon)
                    if d_km < min_km:
                        min_km = d_km

            if inside_count > 0:
                return {"active_count": inside_count, "min_distance_km": 0.0}

            if min_km != float('inf') and min_km <= max_radius_km:
                return {"active_count": 0, "min_distance_km": round(min_km, 2)}
            else:
                return {"active_count": 0, "min_distance_km": round(min_km, 2) if min_km != float('inf') else None}

        except Exception as e:
            print(f"[FIRMS] Error evaluating polygon fire intersection: {e}")
            return {"active_count": 0, "min_distance_km": None}

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
        ds_latest = xr.open_dataset(latest_path)["NDVI"]
        ds_prev = xr.open_dataset(previous_path)["NDVI"]

        for da in (ds_latest, ds_prev):
            if da.rio.crs is None:
                da.rio.write_crs("EPSG:4326", inplace=True)
            da.rio.set_spatial_dims(x_dim="longitude", y_dim="latitude", inplace=True)

        def extract_single_val(da):
            lat_key = next((k for k in ['latitude', 'lat', 'y'] if k in da.dims or k in da.coords), None)
            lon_key = next((k for k in ['longitude', 'lon', 'x'] if k in da.dims or k in da.coords), None)

            if geometry_dict:
                clipped = da.rio.clip([geometry_dict], crs="EPSG:4326", drop=True)
                spatial_dims = [d for d in [lat_key, lon_key] if d in clipped.dims]
                reduced = clipped.mean(dim=spatial_dims, skipna=True) if spatial_dims else clipped.mean(skipna=True)
            elif lat is not None and lon is not None:
                reduced = da.sel({lat_key: lat, lon_key: lon}, method='nearest')
            else:
                return 0.0

            val = np.atleast_1d(np.nan_to_num(reduced.values, nan=0.0)).flatten()
            return float(val[0]) if val.size > 0 else 0.0

        latest_val = extract_single_val(ds_latest)
        prev_val = extract_single_val(ds_prev)

        ds_latest.close()
        ds_prev.close()

        delta = latest_val - prev_val
        return round(float(delta), 4)

    except Exception as e:
        print(f"[NDVI] Delta calculation error: {e}")
        return 0.0


def _extract_from_field(field, lat=None, lon=None, geometry_dict=None):
    """
    Extract a single scalar value from a field returned by
    get_daily_weather_field() or get_fire_index_field().
    """
    lat_key = next((k for k in ['latitude', 'lat', 'y'] if k in field.dims or k in field.coords), None)
    lon_key = next((k for k in ['longitude', 'lon', 'x'] if k in field.dims or k in field.coords), None)
    
    if lat_key is None or lon_key is None:
        return 0.0

    try:
        field_clean = field.copy()

        if hasattr(field_clean, "rio") and field_clean.rio.nodata is not None:
            field_clean = field_clean.where(field_clean != field_clean.rio.nodata)

        field_clean = field_clean.where((field_clean >= 0) & (field_clean < 2000.0))

        if geometry_dict:
            if field_clean.rio.crs is None:
                field_clean = field_clean.rio.write_crs("EPSG:4326")
            
            clipped = field_clean.rio.clip([geometry_dict], crs="EPSG:4326", drop=True)
            
            spatial_dims = [d for d in [lat_key, lon_key] if d in clipped.dims]
            if spatial_dims:
                reduced = clipped.mean(dim=spatial_dims, skipna=True)
            else:
                reduced = clipped.mean(skipna=True)
                
            val = reduced.values
        elif lat is not None and lon is not None:
            selected = field_clean.sel({lat_key: lat, lon_key: lon}, method="nearest")
            val = selected.values
        else:
            return 0.0

        val_flat = np.atleast_1d(val).flatten()
        if val_flat.size == 0 or np.isnan(val_flat[0]):
            return 0.0
            
        res = float(val_flat[0])
        return res if np.isfinite(res) else 0.0

    except Exception as e:
        print(f"[Forecast Summary] extraction error: {e}")
        return 0.0


def extract_series(field_fn, num_days=NUM_DAYS, lat=None, lon=None, geometry_dict=None):

    out = []
    for day in range(num_days):
        try:
            field = field_fn(day)
            val = _extract_from_field(field, lat, lon, geometry_dict)
        except Exception as e:
            print(f"[Forecast Summary] extraction error (day {day}): {e}")
            val = 0.0
        out.append(round(val, 4))
    return out


@forecast_bp.route('/api/forecast/summary', methods=['POST'])
def get_forecast_summary():
    data = request.get_json() or {}
    lat = data.get('lat')
    lon = data.get('lon')
    geometry_dict = data.get('geometry')
    location_name = data.get('name')

    if lat is not None: lat = float(lat)
    if lon is not None: lon = float(lon)

    temperature = extract_series(
        lambda d: get_daily_weather_field("temp_2m_celsius", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )
    rainfall = extract_series(
        lambda d: get_daily_weather_field("precipitation_surface_mm", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )
    rh = extract_series(
        lambda d: get_daily_weather_field("relative_humidity_2m", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )
    wind = extract_series(
        lambda d: get_daily_weather_field("wind_speed_10m", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )
    fwi_series = extract_series(
        lambda d: get_fire_index_field("fwi", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )
    fopi_series = extract_series(
        lambda d: get_fire_index_field("fopi", d), lat=lat, lon=lon, geometry_dict=geometry_dict,
    )

    rainfall = [round(v, 2) for v in rainfall]
    rh = [round(v, 1) for v in rh]
    temperature = [round(v, 1) for v in temperature]
    wind = [round(v, 1) for v in wind]
    fwi_formatted = [round(v, 1) for v in fwi_series]
    fopi_formatted = [round(v, 2) for v in fopi_series]

    fire_info = compute_fire_proximity_firms(geometry_dict, lat, lon)
    ndvi_trend = compute_ndvi_trend_from_files(lat, lon, geometry_dict)

    raw_data = []
    param_map = [
        ("Temperature (°C)", temperature),
        ("Precipitation (mm)", rainfall),
        ("Relative Humidity (%)", rh),
        ("Wind Speed (m/s)", wind),
        ("FWI", fwi_formatted),
        ("FOPI", fopi_formatted)
    ]

    for day_idx in range(NUM_DAYS):
        day_label = "Today" if day_idx == 0 else f"Day +{day_idx}"
        for param_name, series_data in param_map:
            raw_data.append({
                "time": day_label,
                "parameter": param_name,
                "value": series_data[day_idx]
            })

    return jsonify({
        "status": "success",
        "name": location_name or (f"Point ({lat}, {lon})" if lat else "Selected Region"),
        "temperature": temperature,
        "rainfall": rainfall,
        "rh": rh,
        "wind": wind,
        "fwi": fwi_formatted,
        "fopi": fopi_formatted,
        "fire_info": fire_info,
        "ndvi_trend": ndvi_trend,
        "raw_data": raw_data
    })
