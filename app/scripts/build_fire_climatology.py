
import argparse
import glob
import logging
import os
import sys

import numpy as np
import pandas as pd
import xarray as xr
import xclim

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.fire_state_io import save_climatology, EMERGENCY_FFMC, EMERGENCY_DMC, EMERGENCY_DC  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_fire_climatology")


def load_archive(archive_path):

    if os.path.isdir(archive_path) or "*" in archive_path:
        pattern = os.path.join(archive_path, "*.nc") if os.path.isdir(archive_path) else archive_path
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No archive files matched '{pattern}'.")
        logger.info(f"Opening {len(files)} archive file(s) via open_mfdataset.")
        ds = xr.open_mfdataset(files, combine="by_coords")
    else:
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Archive file not found: '{archive_path}'.")
        ds = xr.open_dataset(archive_path)

    required = ["tas", "pr", "hurs", "wind"]
    missing = [v for v in required if v not in ds]
    if missing:
        raise KeyError(
            f"Historical archive '{archive_path}' is missing required "
            f"variable(s) {missing}. Expected: tas (degC), pr (mm), "
            "hurs (%), wind (m/s), all on (time, latitude, longitude)."
        )
    return ds


def run_sequential_cffdrs(ds, start_year, end_year):

    yearly_ffmc, yearly_dmc, yearly_dc = [], [], []

    ffmc_seed = xr.full_like(ds["tas"].isel(time=0), EMERGENCY_FFMC, dtype="float32")
    dmc_seed = xr.full_like(ds["tas"].isel(time=0), EMERGENCY_DMC, dtype="float32")
    dc_seed = xr.full_like(ds["tas"].isel(time=0), EMERGENCY_DC, dtype="float32")
    lat = ds["latitude"]

    for year in range(start_year, end_year + 1):
        year_ds = ds.sel(time=str(year))
        if year_ds.sizes.get("time", 0) == 0:
            logger.warning(f"No data for year {year} - skipping.")
            continue

        logger.info(f"Running CFFDRS recursion for {year} ({year_ds.sizes['time']} days)...")

        pr = year_ds["pr"].copy()
        pr.attrs["units"] = "mm/day"

        dc, dmc, ffmc, isi, bui, fwi = xclim.indices.cffwis_indices(
            tas=year_ds["tas"], pr=pr, sfcWind=year_ds["wind"], hurs=year_ds["hurs"],
            lat=lat, ffmc0=ffmc_seed, dmc0=dmc_seed, dc0=dc_seed,
        )

        yearly_ffmc.append(ffmc)
        yearly_dmc.append(dmc)
        yearly_dc.append(dc)

        # CFFDRS convention: each new fire season restarts from the
        # standard spring start-up constants rather than carrying the
        # previous year's late-season drought code forward, which is how
        # both the Canadian Forest Service and EFFIS build multi-decadal
        # climatologies.
        ffmc_seed = xr.full_like(ffmc_seed, EMERGENCY_FFMC)
        dmc_seed = xr.full_like(dmc_seed, EMERGENCY_DMC)
        dc_seed = xr.full_like(dc_seed, EMERGENCY_DC)

    all_ffmc = xr.concat(yearly_ffmc, dim="time")
    all_dmc = xr.concat(yearly_dmc, dim="time")
    all_dc = xr.concat(yearly_dc, dim="time")
    return all_ffmc, all_dmc, all_dc


def build_doy_climatology(all_ffmc, all_dmc, all_dc):
    """Groupby(time.dayofyear).mean() for each code - the final climatology step."""
    logger.info("Aggregating to day-of-year climatology (groupby time.dayofyear.mean)...")
    ffmc_clim = all_ffmc.groupby("time.dayofyear").mean(dim="time", skipna=True)
    dmc_clim = all_dmc.groupby("time.dayofyear").mean(dim="time", skipna=True)
    dc_clim = all_dc.groupby("time.dayofyear").mean(dim="time", skipna=True)
    return ffmc_clim, dmc_clim, dc_clim


def main():
    parser = argparse.ArgumentParser(description="Build day-of-year FFMC/DMC/DC climatology from a historical weather archive.")
    parser.add_argument("--archive", type=str, required=True, help="Path (or glob) to the historical daily weather archive.")
    parser.add_argument("--start-year", type=int, default=1981)
    parser.add_argument("--end-year", type=int, default=2020)
    args = parser.parse_args()

    try:
        ds = load_archive(args.archive)
        all_ffmc, all_dmc, all_dc = run_sequential_cffdrs(ds, args.start_year, args.end_year)
        ffmc_clim, dmc_clim, dc_clim = build_doy_climatology(all_ffmc, all_dmc, all_dc)
        save_climatology(
            ffmc_clim, dmc_clim, dc_clim,
            period_label=f"{args.start_year}-{args.end_year}",
        )
        logger.info("Fire-code climatology build complete.")
    except Exception:
        logger.error("Fire-code climatology build FAILED.", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
    