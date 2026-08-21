
import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIRE_STATE_DIR = os.path.join(PROJECT_ROOT, "data", "fire_state")
LATEST_STATE_PATH = os.path.join(FIRE_STATE_DIR, "latest_fire_state.nc")

FFMC_CLIM_PATH = os.path.join(FIRE_STATE_DIR, "ffmc_climatology.nc")
DMC_CLIM_PATH = os.path.join(FIRE_STATE_DIR, "dmc_climatology.nc")
DC_CLIM_PATH = os.path.join(FIRE_STATE_DIR, "dc_climatology.nc")


EMERGENCY_FFMC = 85.0
EMERGENCY_DMC = 6.0
EMERGENCY_DC = 15.0

# NetCDF variable/attrs schema for latest_fire_state.nc
STATE_VARS = ("ffmc", "dmc", "dc")
EMERGENCY_DEFAULTS = {
    "ffmc": EMERGENCY_FFMC,
    "dmc": EMERGENCY_DMC,
    "dc": EMERGENCY_DC,
}


def _utc_today_naive():
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()



_NETCDF_ALLOWED_ATTR_TYPES = (str, bytes, int, float, np.integer, np.floating, np.ndarray, list, tuple)


def _sanitize_attrs(attrs):
    """Return (clean_attrs, dropped_keys) - drop any attr value that
    to_netcdf() cannot serialize."""
    clean, dropped = {}, []
    for k, v in attrs.items():
        if isinstance(v, _NETCDF_ALLOWED_ATTR_TYPES):
            clean[k] = v
        else:
            dropped.append(k)
    return clean, dropped


def _sanitize_dataset_for_netcdf(ds):

    ds = ds.copy()
    all_dropped = []

    clean, dropped = _sanitize_attrs(ds.attrs)
    ds.attrs = clean
    all_dropped.extend(f"(dataset).{k}" for k in dropped)

    for name in list(ds.variables):
        clean, dropped = _sanitize_attrs(ds[name].attrs)
        ds[name].attrs = clean
        all_dropped.extend(f"{name}.{k}" for k in dropped)

    if all_dropped:
        logger.warning(
            "[fire_state_io] Dropped non-netCDF-serializable attrs before "
            f"saving (typically upstream AIFS/icechunk provenance metadata "
            f"like dict-valued 'statistics_approximate'): {all_dropped}"
        )
    return ds


def _atomic_to_netcdf(ds, path):
    """Sanitize, then write via temp file + os.replace so a crash mid-write
    can never leave a corrupt/partial file for the next reader to load."""
    ds = _sanitize_dataset_for_netcdf(ds)
    tmp_path = path + ".tmp"
    ds.to_netcdf(tmp_path)
    os.replace(tmp_path, path)  # atomic on POSIX


# ---------------------------------------------------------------------------
# Component: save / load the continuous operational state
# ---------------------------------------------------------------------------

def save_operational_state(ffmc, dmc, dc, path=LATEST_STATE_PATH,
                            valid_date=None, source="unknown"):

    if valid_date is None:
        valid_date = pd.Timestamp.utcnow().normalize()
    valid_date = pd.Timestamp(valid_date)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    def _state_field(da):
        return da.reset_coords(drop=True).astype("float32")

    ds = xr.Dataset(
        data_vars={
            "ffmc": _state_field(ffmc),
            "dmc": _state_field(dmc),
            "dc": _state_field(dc),
        }
    )
    ds.attrs.update(
        {
            "title": "CFFDRS operational moisture-code state",
            "valid_date": valid_date.strftime("%Y-%m-%d"),
            "source": source,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "convention": (
                "State variables per Van Wagner (1987) / CFFDRS. "
                "ffmc = Fine Fuel Moisture Code, dmc = Duff Moisture Code, "
                "dc = Drought Code. This file always contains exactly one "
                "calendar day of state (the most recent update) - it is "
                "NOT a time series."
            ),
        }
    )
    ds["ffmc"].attrs.update(units="dimensionless", long_name="Fine Fuel Moisture Code")
    ds["dmc"].attrs.update(units="dimensionless", long_name="Duff Moisture Code")
    ds["dc"].attrs.update(units="dimensionless", long_name="Drought Code")

    _atomic_to_netcdf(ds, path)
    logger.info(
        f"Saved operational fire state to '{path}' "
        f"(valid_date={ds.attrs['valid_date']}, source={source})"
    )
    return path


def load_operational_state(path=LATEST_STATE_PATH):
    """
    Load the continuous operational state if it exists and looks valid.

    Returns
    -------
    dict with keys 'ffmc', 'dmc', 'dc' (xr.DataArray) and 'valid_date',
    'source' (metadata), or None if the file is missing/unreadable.
    """
    if not os.path.exists(path):
        logger.info(f"No operational fire state found at '{path}'.")
        return None

    try:
        with xr.open_dataset(path) as ds:
            missing = [v for v in STATE_VARS if v not in ds.data_vars]
            if missing:
                logger.warning(
                    f"Operational state file '{path}' is missing variable(s) "
                    f"{missing} - treating as unavailable."
                )
                return None

            state = {v: ds[v].load() for v in STATE_VARS}
            state["valid_date"] = ds.attrs.get("valid_date", None)
            state["source"] = ds.attrs.get("source", "unknown")

        if state["valid_date"] is not None:
            age_days = (
                _utc_today_naive()
                - pd.Timestamp(state["valid_date"]).tz_localize(None).normalize()
            ).days
            if age_days > 3:
                logger.warning(
                    f"Operational fire state at '{path}' is {age_days} day(s) "
                    "stale (last valid_date="
                    f"{state['valid_date']}). The daily update job "
                    "(scripts/update_fire_state.py) may not be running. "
                    "Proceeding to use it anyway, since it is still more "
                    "accurate than climatology."
                )
        return state

    except Exception as e:
        logger.error(f"Failed to read operational fire state '{path}': {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Component: climatology load / save
# ---------------------------------------------------------------------------

def save_climatology(ffmc_clim, dmc_clim, dc_clim, period_label="1981-2020"):

    os.makedirs(FIRE_STATE_DIR, exist_ok=True)

    specs = [
        (ffmc_clim, FFMC_CLIM_PATH, "ffmc_clim", "Fine Fuel Moisture Code climatology"),
        (dmc_clim, DMC_CLIM_PATH, "dmc_clim", "Duff Moisture Code climatology"),
        (dc_clim, DC_CLIM_PATH, "dc_clim", "Drought Code climatology"),
    ]
    for da, path, varname, long_name in specs:
        ds = da.astype("float32").rename(varname).to_dataset()
        ds.attrs.update(
            {
                "title": long_name + " (daily climatology)",
                "period": period_label,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "convention": (
                    "Computed by running xclim.indices.cffwis_indices() "
                    "sequentially through the full historical archive, "
                    "then grouping by time.dayofyear. This preserves the "
                    "recursive FFMC/DMC/DC definition WITHIN each year of "
                    "the archive; only the final climatological average "
                    "across years is a simple mean."
                ),
            }
        )
        _atomic_to_netcdf(ds, path)
        logger.info(f"Saved {long_name} to '{path}'.")


def load_climatological_initialization(target_grid, doy=None,
                                        ffmc_path=FFMC_CLIM_PATH,
                                        dmc_path=DMC_CLIM_PATH,
                                        dc_path=DC_CLIM_PATH):

    if not (os.path.exists(ffmc_path) and os.path.exists(dmc_path) and os.path.exists(dc_path)):
        logger.warning(
            "Fire-code climatology files not found "
            f"({ffmc_path}, {dmc_path}, {dc_path}) - climatological "
            "initialization unavailable."
        )
        return None

    if doy is None:
        doy = pd.Timestamp.utcnow().dayofyear

    lats = target_grid.latitude.values
    lons = target_grid.longitude.values

    try:
        out = {}
        for path, key in ((ffmc_path, "ffmc"), (dmc_path, "dmc"), (dc_path, "dc")):
            with xr.open_dataset(path) as clim_ds:
                varname = f"{key}_clim"
                available_doys = clim_ds["dayofyear"].values
                use_doy = doy if doy in available_doys else available_doys[-1]
                field = clim_ds[varname].sel(dayofyear=use_doy)
                interp = field.interp(
                    latitude=lats, longitude=lons, method="linear"
                )
                if bool(interp.isnull().any()):
                    nearest = field.interp(
                        latitude=lats,
                        longitude=lons,
                        method="nearest",
                        kwargs={"fill_value": "extrapolate"},
                    )
                    interp = interp.fillna(nearest).fillna(EMERGENCY_DEFAULTS[key])
                out[key] = interp.load()
        logger.info(f"Loaded climatological fire-code initialization for day-of-year={doy}.")
        return out
    except Exception as e:
        logger.error(f"Failed to load fire-code climatology: {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Component: unified priority-ordered initializer used by the forecast engine
# ---------------------------------------------------------------------------

def load_fire_initialization(target_grid, state_path=LATEST_STATE_PATH,
                              ffmc_clim_path=FFMC_CLIM_PATH,
                              dmc_clim_path=DMC_CLIM_PATH,
                              dc_clim_path=DC_CLIM_PATH):

    lats = target_grid.latitude.values
    lons = target_grid.longitude.values
    spatial_coords = {"latitude": lats, "longitude": lons}
    spatial_dims = ("latitude", "longitude")

    # --- Priority 1: continuous operational state ---
    state = load_operational_state(state_path)
    if state is not None:
        try:
            ffmc0 = state["ffmc"].interp(latitude=lats, longitude=lons, method="linear")
            dmc0 = state["dmc"].interp(latitude=lats, longitude=lons, method="linear")
            dc0 = state["dc"].interp(latitude=lats, longitude=lons, method="linear")

            if bool(ffmc0.isnull().any()) or bool(dmc0.isnull().any()) or bool(dc0.isnull().any()):
                logger.warning(
                    "Operational state did not fully cover the forecast "
                    "grid after interpolation - filling remaining gaps "
                    "from climatology (falling back further to emergency "
                    "defaults only where climatology is also unavailable)."
                )
                clim = load_climatological_initialization(
                    target_grid, ffmc_path=ffmc_clim_path,
                    dmc_path=dmc_clim_path, dc_path=dc_clim_path,
                )
                if clim is not None:
                    ffmc0 = ffmc0.fillna(clim["ffmc"])
                    dmc0 = dmc0.fillna(clim["dmc"])
                    dc0 = dc0.fillna(clim["dc"])
                ffmc0 = ffmc0.fillna(EMERGENCY_FFMC)
                dmc0 = dmc0.fillna(EMERGENCY_DMC)
                dc0 = dc0.fillna(EMERGENCY_DC)

            logger.info(
                "Initialized forecast fire codes from the continuous "
                f"operational state (valid_date={state.get('valid_date')}, "
                f"source={state.get('source')})."
            )
            return (
                ffmc0.assign_attrs(units="dimensionless"),
                dmc0.assign_attrs(units="dimensionless"),
                dc0.assign_attrs(units="dimensionless"),
                "operational_state",
            )
        except Exception as e:
            logger.error(
                f"Operational state was found but failed to interpolate "
                f"onto the forecast grid ({e}); falling back to "
                "climatology.", exc_info=True,
            )

    # --- Priority 2: climatology ---
    clim = load_climatological_initialization(
        target_grid, ffmc_path=ffmc_clim_path, dmc_path=dmc_clim_path, dc_path=dc_clim_path
    )
    if clim is not None:
        logger.info("Initialized forecast fire codes from climatology (no operational state available).")
        return (
            clim["ffmc"].assign_attrs(units="dimensionless"),
            clim["dmc"].assign_attrs(units="dimensionless"),
            clim["dc"].assign_attrs(units="dimensionless"),
            "climatology",
        )

    # --- Priority 3: emergency defaults ---
    logger.error(
        "Neither the operational fire state nor the climatology were "
        "available - initializing the forecast with EMERGENCY DEFAULT "
        f"constants (FFMC={EMERGENCY_FFMC}, DMC={EMERGENCY_DMC}, "
        f"DC={EMERGENCY_DC}). Forecast fire-danger output for this run "
        "should be treated as low-confidence until the operational "
        "pipeline is restored."
    )
    shape = (len(lats), len(lons))
    ffmc0 = xr.DataArray(np.full(shape, EMERGENCY_FFMC, dtype="float32"),
                          coords=spatial_coords, dims=spatial_dims,
                          attrs={"units": "dimensionless"})
    dmc0 = xr.DataArray(np.full(shape, EMERGENCY_DMC, dtype="float32"),
                         coords=spatial_coords, dims=spatial_dims,
                         attrs={"units": "dimensionless"})
    dc0 = xr.DataArray(np.full(shape, EMERGENCY_DC, dtype="float32"),
                        coords=spatial_coords, dims=spatial_dims,
                        attrs={"units": "dimensionless"})
    return ffmc0, dmc0, dc0, "emergency_default"
