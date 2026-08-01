# app/__init__.py
import os
from flask import Flask, render_template, jsonify
from app.config import Config
from app.scripts.spatial_calc import get_geojson_from_shapefile
import traceback
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.route('/')
    def index():
        return render_template('index.html')

    from app.api.spatial import spatial_bp
    from app.api.climate import climate_bp
    app.register_blueprint(spatial_bp)
    app.register_blueprint(climate_bp)

    # API Endpoint: Serve GeoJSON from /data/shapefile/
    @app.route('/api/shapefile/<layer_key>')
    def serve_shapefile(layer_key):
        try:
            data_dir = app.config.get('DATA_DIR', './data/')
            geojson = get_geojson_from_shapefile(layer_key, base_dir=data_dir)
            return jsonify(geojson)
        except Exception as e:
            print(f"\n[ERROR] Failed to load shapefie '{layer_key}':")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400

    return app
