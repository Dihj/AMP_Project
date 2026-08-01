# app/scripts/spatial_calc.py
import os
import geopandas as gpd

def load_and_convert_shapefile(layer_name, data_dir):
    """
    Reads shapefile, reprojects to WGS84 for Leaflet, and returns GeoJSON dict.
    """
    shp_path = os.path.join(data_dir, 'shapefiles', f"{layer_name}.shp")
    
    if not os.path.exists(shp_path):
        raise FileNotFoundError(f"Shapefile {layer_name}.shp not found in {shp_path}")

    # Read and reproject
    gdf = gpd.read_file(shp_path)
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)
        
    return gdf.__geo_interface__


def calculate_fire_risk_in_protected_areas(nc_filename, data_dir):
    """
    Example custom calculation script comparing NetCDF fire data with Protected Area shapefiles.
    """
    # Your custom numpy/xarray/geopandas logic here...
    result = {"summary": "Calculation complete", "risk_index": 0.82}
    return result
