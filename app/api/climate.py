# app/api/climate.py
import base64
import numpy as np
from flask import Blueprint, request, jsonify, current_app
from shapely.geometry import shape, Point
from app.scripts.climate_calc import (
    generate_climate_png, 
    DATA_CACHE, 
    preload_climate_data
)

climate_bp = Blueprint('climate', __name__, url_prefix='/api/climate')


@climate_bp.route('/raster', methods=['GET'])
def get_climate_raster():
    """Generates Base64 PNG image overlay and geographic bounds for Leaflet."""
    raw_param = request.args.get('param', 'Rain')
    time_step = request.args.get('time', 'Jan')
    fixed_scale = request.args.get('fixed', 'false').lower() == 'true'

    param_map = {
        'rr': 'Rain',
        'rain': 'Rain',
        'Rain': 'Rain',
        'tmean': 'Temp',
        'temp': 'Temp',
        'Temp': 'Temp',
        'fire': 'Fire',
        'Fire': 'Fire'
    }
    param = param_map.get(raw_param, raw_param)

    try:
        data_dir = current_app.config.get('DATA_DIR', './data/')
        image_buf, bounds, legend_ticks, unit = generate_climate_png(
            parameter=param, 
            time_step=time_step, 
            fixed_scale=fixed_scale,
            base_dir=data_dir
        )

        img_base64 = base64.b64encode(image_buf.getvalue()).decode('utf-8')
        data_url = f"data:image/png;base64,{img_base64}"
        scale_mode = "Fixed (Annual)" if fixed_scale else "Dynamic (Monthly)"

        return jsonify({
            'status': 'success',
            'bounds': bounds,
            'imageUrl': data_url,
            'legend': legend_ticks,
            'unit': unit,
            'title': f"{param} Climatology ({time_step})",
            'scaleMode': scale_mode
        })
    except Exception as e:
        print(f"[ERROR] Climate raster rendering failed for param='{param}': {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@climate_bp.route('/timeseries', methods=['POST', 'GET'])
def get_climate_timeseries():
    """Extracts 12-month time series for point click popup or polygon spatial aggregation."""
    if not DATA_CACHE:
        preload_climate_data()

    if 'Rain' not in DATA_CACHE or 'Temp' not in DATA_CACHE or 'Fire' not in DATA_CACHE:
        return jsonify({'error': 'Climate datasets not loaded'}), 500

    ref_lats = DATA_CACHE['Rain']['lats']
    ref_lons = DATA_CACHE['Rain']['lons']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    req_data = request.get_json(silent=True) or {}
    geometry = req_data.get('geometry')
    location_name = req_data.get('name')

    if geometry:
        try:
            poly = shape(geometry)
            poly_bounds = poly.bounds

            lat_mask = (ref_lats >= poly_bounds[1]) & (ref_lats <= poly_bounds[3])
            lon_mask = (ref_lons >= poly_bounds[0]) & (ref_lons <= poly_bounds[2])

            lat_indices = np.where(lat_mask)[0]
            lon_indices = np.where(lon_mask)[0]

            if len(lat_indices) == 0 or len(lon_indices) == 0:
                centroid = poly.centroid
                lat_indices = np.array([int(np.abs(ref_lats - centroid.y).argmin())])
                lon_indices = np.array([int(np.abs(ref_lons - centroid.x).argmin())])

            matching_cells = []
            for i in lat_indices:
                for j in lon_indices:
                    pt = Point(ref_lons[j], ref_lats[i])
                    if poly.contains(pt) or poly.intersects(pt):
                        matching_cells.append((i, j))

            if len(matching_cells) == 0:
                centroid = poly.centroid
                best_lat_idx = int(np.abs(ref_lats - centroid.y).argmin())
                best_lon_idx = int(np.abs(ref_lons - centroid.x).argmin())
                matching_cells = [(best_lat_idx, best_lon_idx)]

            selected_lats = [c[0] for c in matching_cells]
            selected_lons = [c[1] for c in matching_cells]

            rain_data = DATA_CACHE['Rain']['data']
            temp_data = DATA_CACHE['Temp']['data']
            fire_data = DATA_CACHE['Fire']['data']

            rain_vals = []
            temp_vals = []
            fire_vals = []

            for m in range(12):
                m_rain = rain_data[m, selected_lats, selected_lons]
                m_temp = temp_data[m, selected_lats, selected_lons]
                m_fire = fire_data[m, selected_lats, selected_lons]

                valid_rain = m_rain[(~np.isnan(m_rain)) & (m_rain >= 0)]
                valid_temp = m_temp[(~np.isnan(m_temp)) & (m_temp > -50) & (m_temp < 60)]
                valid_fire = m_fire[(~np.isnan(m_fire)) & (m_fire >= 0)]

                r_mean = float(np.mean(valid_rain)) if len(valid_rain) > 0 else 0.0
                t_mean = float(np.mean(valid_temp)) if len(valid_temp) > 0 else None
                f_sum = float(np.sum(valid_fire)) if len(valid_fire) > 0 else 0.0

                rain_vals.append(round(r_mean, 1))
                temp_vals.append(round(t_mean, 1) if t_mean is not None else None)
                fire_vals.append(round(f_sum, 1))

            return jsonify({
                'name': location_name or "Selected Area",
                'is_polygon': True,
                'months': months,
                'rain': rain_vals,
                'temp': temp_vals,
                'fire': fire_vals
            })

        except Exception as e:
            print(f"[ERROR] Polygon timeseries extraction failed: {e}")
            return jsonify({'error': str(e)}), 500

    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid coordinates or payload'}), 400

    lat_idx = int(np.abs(ref_lats - lat).argmin())
    lon_idx = int(np.abs(ref_lons - lon).argmin())

    rain_ts = DATA_CACHE['Rain']['data'][:, lat_idx, lon_idx]
    temp_ts = DATA_CACHE['Temp']['data'][:, lat_idx, lon_idx]
    fire_ts = DATA_CACHE['Fire']['data'][:, lat_idx, lon_idx]

    rain_vals = [round(float(x), 1) if not np.isnan(x) and x >= 0 else 0.0 for x in rain_ts]
    temp_vals = [round(float(x), 1) if not np.isnan(x) and x > -50 and x < 60 else None for x in temp_ts]
    fire_vals = [round(float(x), 2) if not np.isnan(x) and x >= 0 else 0.0 for x in fire_ts]

    return jsonify({
        'name': f"Point ({round(ref_lats[lat_idx], 4)}, {round(ref_lons[lon_idx], 4)})",
        'point': {'lat': round(float(ref_lats[lat_idx]), 4), 'lon': round(float(ref_lons[lon_idx]), 4)},
        'is_polygon': False,
        'months': months,
        'rain': rain_vals,
        'temp': temp_vals,
        'fire': fire_vals
    })