# app/core/dataset_cache.py

import logging
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

# Global in-memory cache dictionary
_DATASET_CACHE = {
    "fwi": None,       # DataArray or Dataset containing daily FWI
    "fopi": None,      # DataArray or Dataset containing daily FOPI
    "aifs": None,      # Weather forecast Dataset (tas, pr, sfcWind, hurs)
    "ndvi": None,      # NDVI Dataset
    "last_updated": None
}

def set_cached_indices(fwi_da: xr.DataArray, fopi_da: xr.DataArray, aifs_ds: xr.Dataset, ndvi_ds: xr.Dataset):
    """Updates the globally cached datasets in RAM."""
    global _DATASET_CACHE
    _DATASET_CACHE["fwi"] = fwi_da
    _DATASET_CACHE["fopi"] = fopi_da
    _DATASET_CACHE["aifs"] = aifs_ds
    _DATASET_CACHE["ndvi"] = ndvi_ds
    _DATASET_CACHE["last_updated"] = pd.Timestamp.now()
    logger.info("Successfully updated global in-memory dataset cache.")

def get_cached_indices():
    """Retrieves cached datasets."""
    return _DATASET_CACHE

    