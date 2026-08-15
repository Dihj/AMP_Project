# app/analysis/climate_processor.py

def calculate_rainfall_anomaly(current_val, baseline_avg):
    """Calculates rainfall anomaly relative to a baseline."""
    if baseline_avg == 0:
        return 0
    return round(current_val - baseline_avg, 2)

def process_station_data(station_id):
    """Placeholder for reading NetCDF / GeoTIFF / CSV data for a station."""
    # Your backend spatial or climate logic here
    result = {
        "station_id": station_id,
        "current_rainfall_mm": 45.2,
        "anomaly": calculate_rainfall_anomaly(45.2, 30.0)
    }
    return result
