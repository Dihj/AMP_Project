# app/api/climate.py
import base64
import numpy as np
from flask import Blueprint, request, jsonify, current_app
from app.scripts.climate_calc import (
    generate_climate_png, 
    DATA_CACHE, 
    preload_climate_data
)

# Single Blueprint definition with prefix
climate_bp = Blueprint('climate', __name__, url_prefix='/api/climate')


@climate_bp.route('/raster', methods=['GET'])
def get_climate_raster():
    """Generates Base64 PNG image overlay and geographic bounds for Leaflet."""
    param = request.args.get('param', 'Rain')
    time_step = request.args.get('time', 'Jan')
    fixed_scale = request.args.get('fixed', 'false').lower() == 'true'

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
        print(f"[ERROR] Climate raster rendering failed: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@climate_bp.route('/timeseries', methods=['GET'])
def get_climate_timeseries():
    """Extracts 12-month time series for point click popup chart."""
    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid latitude or longitude'}), 400

    if not DATA_CACHE:
        preload_climate_data()

    if 'Rain' not in DATA_CACHE or 'Temp' not in DATA_CACHE or 'Fire' not in DATA_CACHE:
        return jsonify({'error': 'Climate datasets not loaded'}), 500

    # Nearest neighbor spatial lookup
    ref_lats = DATA_CACHE['Rain']['lats']
    ref_lons = DATA_CACHE['Rain']['lons']

    lat_idx = int(np.abs(ref_lats - lat).argmin())
    lon_idx = int(np.abs(ref_lons - lon).argmin())

    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Extract 12-month values
    rain_ts = DATA_CACHE['Rain']['data'][:, lat_idx, lon_idx]
    temp_ts = DATA_CACHE['Temp']['data'][:, lat_idx, lon_idx]
    fire_ts = DATA_CACHE['Fire']['data'][:, lat_idx, lon_idx]

    # Clean NaNs
    rain_vals = [round(float(x), 1) if not np.isnan(x) and x >= 0 else 0.0 for x in rain_ts]
    temp_vals = [round(float(x), 1) if not np.isnan(x) and x > -50 else None for x in temp_ts]
    fire_vals = [round(float(x), 2) if not np.isnan(x) and x >= 0 else 0.0 for x in fire_ts]

    return jsonify({
        'point': {'lat': round(float(ref_lats[lat_idx]), 4), 'lon': round(float(ref_lons[lon_idx]), 4)},
        'months': months,
        'rain': rain_vals,
        'temp': temp_vals,
        'fire': fire_vals
    })
