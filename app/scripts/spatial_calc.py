# app/scripts/spatial_calc.py
import os
import geopandas as gpd
from shapely.validation import make_valid

def get_geojson_from_shapefile(layer_key, base_dir='./data'):
    """
    Reads shapefiles located in /data/shapefile/ and returns a GeoJSON dict.
    layer_key mapping:
      - 'PA' -> /data/shapefile/PA.shp
      - 'district' -> /data/shapefile/district.shp
    """
    # Map layer keys to your exact file names
    filename_map = {
        'PA': 'PA.shp',
        'districtMdg': 'districtMdg.shp'
    }

    if layer_key not in filename_map:
        raise ValueError(f"Unknown layer key: {layer_key}")

    shp_path = os.path.join(base_dir, 'shapefile', filename_map[layer_key])

    if not os.path.exists(shp_path):
        raise FileNotFoundError(f"Shapefile not found at: {shp_path}")

    # Read shapefile
    gdf = gpd.read_file(shp_path)
    gdf['geometry'] = gdf['geometry'].apply(lambda geom: make_valid(geom) if geom is not None else None)
    try:
        if gdf.crs is None: 
            gdf = gdf.set_crs(epsg=4326)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
    except Exception as e: 
        print(f'[{layer_key}] Warinig during CRS transfromation: {e}')
        gsf = gdf.set_crs(epsg=4326, allow_override=True)

    return gdf.__geo_interface__

