# app/core/dataset_cache.py

import logging
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

# Global in-memory cache dictionary
_DATASET_CACHE = {
    "fwi": None,       
    "fopi": None,     
    "aifs": None,     
    "ndvi": None,    
    "last_updated": None,
    "signature": None,
}

def set_cached_indices(
    fwi_da: xr.DataArray,
    fopi_da: xr.DataArray,
    aifs_ds: xr.Dataset,
    ndvi_ds: xr.Dataset,
    signature=None,
):
    """Updates the globally cached datasets in RAM."""
    global _DATASET_CACHE
    _DATASET_CACHE["fwi"] = fwi_da
    _DATASET_CACHE["fopi"] = fopi_da
    _DATASET_CACHE["aifs"] = aifs_ds
    _DATASET_CACHE["ndvi"] = ndvi_ds
    _DATASET_CACHE["last_updated"] = pd.Timestamp.now()
    _DATASET_CACHE["signature"] = signature
    logger.info("Successfully updated global in-memory dataset cache.")

def get_cached_indices():
    return _DATASET_CACHE

    
