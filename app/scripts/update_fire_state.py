#!/usr/bin/env python

import argparse
import logging
import os
import sys

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba-cache")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

import numpy as np
import pandas as pd
import xarray as xr
import xclim

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.fire_state_io import (  # noqa: E402
    load_operational_state,
    save_operational_state,
    load_climatological_initialization,
    EMERGENCY_FFMC,
    EMERGENCY_DMC,
    EMERGENCY_DC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("update_fire_state")


def utc_now_naive():
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


# ---------------------------------------------------------------------------
# Primary weather source: AIFS short-lead output for YESTERDAY (default -
# no external feed required, and keeps the state one day behind the
# forecast's first step - see module docstring).
# ---------------------------------------------------------------------------

def load_aifs_shortlead_weather_for_yesterday():

    from app.api.aifs_frcst import download_historical_day_daily_means, LOCAL_UTC_OFFSET_HOURS

    yesterday = (
        utc_now_naive() + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    ).normalize() - pd.Timedelta(days=1)

    daily = download_historical_day_daily_means(yesterday)
    day = daily.isel(time=0)
    actual_date = pd.Timestamp(day.time.values)

    weather = xr.Dataset(
        {
            "tas": day["temp_2m_celsius"],
            "hurs": day["relative_humidity_2m"],
            "wind": day["wind_speed_10m"],
            "pr": day["precipitation_surface_mm"],
        }
    )
    return weather, actual_date


# ---------------------------------------------------------------------------
# Alternate/future weather sources - kept for when a real observed feed
# exists. Not used by default; select with --source.
# ---------------------------------------------------------------------------

def load_observed_weather(target_date, source, weather_path=None):

    date_str = target_date.strftime("%Y-%m-%d")

    if source == "era5land":
        path = weather_path or os.path.join(
            "data", "observed", "era5land", f"era5land_{date_str}.nc"
        )
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"ERA5-Land daily file not found: '{path}'. Expected "
                "variables: t2m_noon (degC), rh_noon (%), wind_noon (m/s), "
                "precip_24h (mm)."
            )
        with xr.open_dataset(path) as ds:
            out = xr.Dataset(
                {
                    "tas": ds["t2m_noon"],
                    "hurs": ds["rh_noon"],
                    "wind": ds["wind_noon"],
                    "pr": ds["precip_24h"],
                }
            ).load()
        return out

    elif source == "enacts":
        path = weather_path or os.path.join(
            "data", "observed", "enacts", f"enacts_{date_str}.nc"
        )
        if not os.path.exists(path):
            raise FileNotFoundError(f"ENACTS daily file not found: '{path}'.")
        with xr.open_dataset(path) as ds:
            out = xr.Dataset(
                {
                    "tas": ds["temp"],
                    "hurs": ds["rhum"],
                    "wind": ds["wspd"],
                    "pr": ds["rfe"],
                }
            ).load()
        return out

    elif source == "station":
        path = weather_path or os.path.join(
            "data", "observed", "station", f"station_{date_str}.csv"
        )
        if not os.path.exists(path):
            raise FileNotFoundError(f"Station analysis file not found: '{path}'.")
        raise NotImplementedError(
            "Station-based gridding (e.g. inverse-distance-weighting or "
            "kriging onto the operational grid) is site-specific and must "
            "be implemented against the Direction Generale de la "
            "Meteorologie network file format before this branch is used "
            "operationally."
        )

    else:
        raise ValueError(f"Unknown observed-weather source: '{source}'")


def get_reference_grid():

    from app.api.aifs_frcst import MADAGASCAR_BBOX, TARGET_GRID_RESOLUTION_DEG

    lats = np.arange(
        MADAGASCAR_BBOX["lat_north"], MADAGASCAR_BBOX["lat_south"] - TARGET_GRID_RESOLUTION_DEG,
        -TARGET_GRID_RESOLUTION_DEG,
    )
    lons = np.arange(
        MADAGASCAR_BBOX["lon_west"], MADAGASCAR_BBOX["lon_east"] + TARGET_GRID_RESOLUTION_DEG,
        TARGET_GRID_RESOLUTION_DEG,
    )
    return xr.Dataset(coords={"latitude": lats, "longitude": lons})


def latitude_for_cffwis(ds):
    """xclim validates latitude units explicitly."""
    lat = ds.latitude.copy()
    lat.attrs.setdefault("units", "degrees_north")
    return lat


def resolve_seed_state(target_date, ref_grid):

    state = load_operational_state()
    if state is not None:
        logger.info(f"Seeding today's update from previous state (valid_date={state.get('valid_date')}).")
        return (
            state["ffmc"].interp_like(ref_grid, method="linear"),
            state["dmc"].interp_like(ref_grid, method="linear"),
            state["dc"].interp_like(ref_grid, method="linear"),
        )

    logger.warning(
        "No previous operational state found - this looks like a cold "
        "start. Attempting climatological initialization for "
        f"day-of-year={target_date.dayofyear - 1} (yesterday)."
    )
    doy = 365 if target_date.dayofyear == 1 else target_date.dayofyear - 1
    clim = load_climatological_initialization(ref_grid, doy=doy)
    if clim is not None:
        return clim["ffmc"], clim["dmc"], clim["dc"]

    logger.error(
        "No previous state AND no climatology available - seeding with "
        f"emergency defaults (FFMC={EMERGENCY_FFMC}, DMC={EMERGENCY_DMC}, "
        f"DC={EMERGENCY_DC}). This should only happen on the very first "
        "run of the operational pipeline, before scripts/"
        "build_fire_climatology.py has ever been run."
    )
    shape = (ref_grid.sizes["latitude"], ref_grid.sizes["longitude"])
    coords = {"latitude": ref_grid.latitude, "longitude": ref_grid.longitude}
    dims = ("latitude", "longitude")
    return (
        xr.DataArray(np.full(shape, EMERGENCY_FFMC, dtype="float32"), coords=coords, dims=dims),
        xr.DataArray(np.full(shape, EMERGENCY_DMC, dtype="float32"), coords=coords, dims=dims),
        xr.DataArray(np.full(shape, EMERGENCY_DC, dtype="float32"), coords=coords, dims=dims),
    )


def update_state_for_date(target_date=None, source="aifs_shortlead", weather_path=None):

    if source == "aifs_shortlead":
        from app.api.aifs_frcst import LOCAL_UTC_OFFSET_HOURS

        # Cheap short-circuit: skip the archive fetch entirely if the
        # persisted state already covers the date we'd be advancing to.
        target_local = (
            utc_now_naive() + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
        ).normalize() - pd.Timedelta(days=1)
        existing = load_operational_state()
        if existing is not None and existing.get("valid_date") is not None:
            if pd.Timestamp(existing["valid_date"]).normalize() == target_local.normalize():
                logger.info(
                    f"Operational state is already up to date "
                    f"(valid_date={existing['valid_date']}) - skipping fetch."
                )
                return None

        weather, actual_date = load_aifs_shortlead_weather_for_yesterday()
        target_date = actual_date
        ref_grid = xr.Dataset(coords={"latitude": weather.latitude, "longitude": weather.longitude})
        logger.info(
            f"=== Operational fire-state update for {target_date.date()} "
            "(source=aifs_shortlead - AIFS short-lead output for yesterday "
            "used as observation proxy) ==="
        )
    else:
        if target_date is None:
            raise ValueError(f"--date is required when --source={source}.")
        logger.info(f"=== Operational fire-state update for {target_date.date()} (source={source}) ===")
        ref_grid = get_reference_grid()
        weather = load_observed_weather(target_date, source, weather_path)
        weather = weather.interp_like(ref_grid, method="linear")

    lat = latitude_for_cffwis(weather)
    ffmc0, dmc0, dc0 = resolve_seed_state(target_date, ref_grid)

    weather["pr"].attrs["units"] = "mm/day"

    # A single-day call: xclim.indices.cffwis_indices requires a 'time'
    # dimension, so we add a length-1 time axis for this one day.
    def _add_time(da):
        return da.expand_dims(time=[np.datetime64(pd.Timestamp(target_date).normalize())])

    tas = _add_time(weather["tas"])
    pr = _add_time(weather["pr"])
    hurs = _add_time(weather["hurs"])
    wind = _add_time(weather["wind"])

    dc, dmc, ffmc, isi, bui, fwi = xclim.indices.cffwis_indices(
        tas=tas, pr=pr, sfcWind=wind, hurs=hurs, lat=lat,
        ffmc0=ffmc0, dmc0=dmc0, dc0=dc0,
    )

    # Collapse the length-1 time dimension back out - the state file
    # always stores exactly the latest day (see fire_state_io docstring).
    ffmc_today = ffmc.isel(time=-1, drop=True)
    dmc_today = dmc.isel(time=-1, drop=True)
    dc_today = dc.isel(time=-1, drop=True)

    path = save_operational_state(
        ffmc_today, dmc_today, dc_today, valid_date=target_date, source=source
    )

    logger.info(
        "Update complete. Domain-mean today: "
        f"FFMC={float(ffmc_today.mean()):.1f}, "
        f"DMC={float(dmc_today.mean()):.1f}, "
        f"DC={float(dc_today.mean()):.1f}, "
        f"FWI={float(fwi.isel(time=-1).mean()):.1f}."
    )
    return path


def main():
    parser = argparse.ArgumentParser(description="Advance the operational CFFDRS fire-code state by one day.")
    parser.add_argument(
        "--date", type=str, default=None,
        help=(
            "Target date (YYYY-MM-DD), local Madagascar time. Ignored for "
            "--source aifs_shortlead (always advances to yesterday); for "
            "other sources it selects which file to load and defaults to "
            "today."
        ),
    )
    parser.add_argument(
        "--source", type=str, default="aifs_shortlead",
        choices=["aifs_shortlead", "era5land", "enacts", "station"],
        help="Weather source for this update. Defaults to AIFS short-lead output for yesterday (no external feed required).",
    )
    parser.add_argument(
        "--weather-path", type=str, default=None,
        help="Explicit path to the observed-weather file for this date (ignored for --source aifs_shortlead).",
    )
    args = parser.parse_args()

    if args.date is not None:
        target_date = pd.Timestamp(args.date)
    elif args.source == "aifs_shortlead":
        target_date = None  # resolved internally to yesterday
    else:
        target_date = (pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(hours=3)).normalize()

    try:
        update_state_for_date(target_date, args.source, args.weather_path)
    except Exception:
        logger.error(
            "Operational fire-state update FAILED "
            f"(source={args.source}) - the previous state file was left "
            "untouched, so the pipeline will carry it forward until the "
            "next successful run.", exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
