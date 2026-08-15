# app/api/spatial.py
import traceback
from flask import Blueprint, jsonify, current_app
from app.scripts.spatial_calc import get_geojson_from_shapefile

spatial_bp = Blueprint('spatial', __name__, url_prefix='/api/shapefile')

@spatial_bp.route('/<layer_key>')
def serve_shapefile(layer_key):
    try:
        data_dir = current_app.config.get('DATA_DIR', './data/')
        geojson = get_geojson_from_shapefile(layer_key, base_dir=data_dir)
        return jsonify(geojson)
    except Exception as e:
        print(f"\n[ERROR] Shapefile '{layer_key}' failed:")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400

    