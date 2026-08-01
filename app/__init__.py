# app/__init__.py
import os
from flask import Flask, render_template, jsonify
from app.config import Config

# IMPORT YOUR CUSTOM PYTHON SCRIPTS HERE
from app.scripts.spatial_calc import load_and_convert_shapefile, calculate_fire_risk_in_protected_areas

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    data_dir = app.config['EXTERNAL_DATA_DIR']

    @app.route('/')
    def index():
        return render_template('index.html')

    # API Endpoint calling your script
    @app.route('/api/shapefile/<layer_name>')
    def get_shapefile(layer_name):
        try:
            # Call function from ./app/scripts/spatial_calc.py
            geojson_data = load_and_convert_shapefile(layer_name, data_dir)
            return jsonify(geojson_data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # API Endpoint calling a calculation script
    @app.route('/api/calc/fire-risk')
    def run_fire_calc():
        try:
            # Call calculation script
            result = calculate_fire_risk_in_protected_areas('fire_mon.nc', data_dir)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return app
