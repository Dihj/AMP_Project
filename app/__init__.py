# app/__init__.py
import os
import traceback
import numpy as np
from flask import Flask, render_template, jsonify
from app.config import Config
from app.scripts.spatial_calc import get_geojson_from_shapefile
from app.scripts.climate_calc import DATA_CACHE, preload_climate_data
from app.api.aifs_frcst import get_aifs_dataset
from app.api.ndvi import get_ndvi_dataset  # <--- Import NDVI pre-fetcher

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.route('/')
    def index():
        return render_template('index.html')

    # Preload datasets into RAM
    with app.app_context():
        preload_climate_data()

        try:
            print("\n[INFO] Pre-fetching latest AIFS forecast data into memory ...")
            get_aifs_dataset()
        except Exception as e:
            print(f"\n[WARNING] Could not pre-fetch AIFS forecast at startup: {e}")

        # --- PRE-FETCH NDVI DATA ON STARTUP ---
        try:
            print("\n[INFO] Pre-fetching latest MODIS NDVI data into memory ...")
            get_ndvi_dataset()
        except Exception as e:
            print(f"\n[WARNING] Could not pre-fetch NDVI data at startup: {e}")

    # Import and register Flask Blueprints
    from app.api.spatial import spatial_bp
    from app.api.climate import climate_bp
    from app.api.firms import firms_bp
    from app.api.aifs_frcst import aifs_bp
    from app.api.ndvi import ndvi_bp
    from app.api.fire_indices import fire_indices_bp
    from app.api.forecast import forecast_bp
    
    app.register_blueprint(spatial_bp)
    app.register_blueprint(climate_bp)
    app.register_blueprint(firms_bp)
    app.register_blueprint(aifs_bp, url_prefix="/api/forecast")
    app.register_blueprint(fire_indices_bp)
    app.register_blueprint(forecast_bp)

    
    # Register NDVI with prefix so endpoint is GET /api/ndvi/plot
    app.register_blueprint(ndvi_bp, url_prefix="/api/ndvi")

    # Serve GeoJSON from /data/shapefile/
    @app.route('/api/shapefile/<layer_key>')
    def serve_shapefile(layer_key):
        try:
            data_dir = app.config.get('DATA_DIR', './data/')
            geojson = get_geojson_from_shapefile(layer_key, base_dir=data_dir)
            return jsonify(geojson)
        except Exception as e:
            print(f"\n[ERROR] Failed to load shapefile '{layer_key}':")
            traceback.print_exc()
            return jsonify({'error': str(e)}), 400

    return app

