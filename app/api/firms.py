# app/api/firms.py

import io
import time
import logging
import pandas as pd
import requests
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# Define Flask Blueprint
firms_bp = Blueprint('firms', __name__)

# Global in-memory cache
FIRE_CACHE = {
    "last_fetched": 0,
    "data": []
}

DEBUG_MODE = True  # Set to False for production
CACHE_TTL = 43200  # 12 hours (in seconds)

FIRMS_CSV_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Southern_Africa_24h.csv"

# Bounding box for Madagascar
MADAGASCAR_BBOX = {
    "lat_min": -25.7,
    "lat_max": -11.9,
    "lon_min": 43.1,
    "lon_max": 50.8
}

@firms_bp.route('/api/active-fires-24h', methods=['GET'])
def get_active_fires_24h():
    current_time = time.time()
    
    # 1. DEBUG MODE: Return cache if loaded once
    if DEBUG_MODE and FIRE_CACHE["data"]:
        return jsonify({"status": "success", "mode": "debug", "count": len(FIRE_CACHE["data"]), "fires": FIRE_CACHE["data"]})

    # 2. PRODUCTION MODE: Return cache if less than 12 hours old
    if not DEBUG_MODE and (current_time - FIRE_CACHE["last_fetched"] < CACHE_TTL) and FIRE_CACHE["data"]:
        return jsonify({"status": "success", "mode": "production_cached", "count": len(FIRE_CACHE["data"]), "fires": FIRE_CACHE["data"]})

    # 3. Fetch fresh CSV from NASA FIRMS
    try:
        logger.info("Fetching fresh 24h MODIS fire data from NASA FIRMS...")
        response = requests.get(FIRMS_CSV_URL, timeout=12)
        response.raise_for_status()

        # Parse CSV string directly into pandas
        df = pd.read_csv(io.StringIO(response.text))

        # Filter strictly for Madagascar domain
        mask = (
            (df['latitude'] >= MADAGASCAR_BBOX['lat_min']) &
            (df['latitude'] <= MADAGASCAR_BBOX['lat_max']) &
            (df['longitude'] >= MADAGASCAR_BBOX['lon_min']) &
            (df['longitude'] <= MADAGASCAR_BBOX['lon_max'])
        )
        filtered_df = df[mask]

        # Extract minimal payload
        fire_points = []
        for _, row in filtered_df.iterrows():
            fire_points.append({
                "lat": round(float(row['latitude']), 4),
                "lon": round(float(row['longitude']), 4),
                "brightness": float(row['brightness']),
                "confidence": str(row['confidence']),
                "acq_time": f"{row['acq_date']} {str(row['acq_time']).zfill(4)}"
            })

        # Update cache
        FIRE_CACHE["last_fetched"] = current_time
        FIRE_CACHE["data"] = fire_points

        return jsonify({"status": "success", "mode": "fresh_download", "count": len(fire_points), "fires": fire_points})

    except Exception as e:
        logger.error(f"Failed to fetch FIRMS fire data: {e}")
        if FIRE_CACHE["data"]:
            return jsonify({"status": "warning", "message": str(e), "fires": FIRE_CACHE["data"]})
        return jsonify({"error": f"Error processing FIRMS data: {str(e)}"}), 500

    