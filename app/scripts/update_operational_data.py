#!/usr/bin/env python

import logging
import os
import sys

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba-cache")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.api.aifs_frcst import download_and_save_aifs  # noqa: E402
from app.core.fire_state_io import load_operational_state  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("update_operational_data")


def main():
    logger.info("Starting scheduled operational data refresh.")
    download_and_save_aifs()

    state = load_operational_state()
    state_date = None if state is None else state.get("valid_date")
    logger.info(
        "Scheduled operational data refresh complete "
        f"(latest_fire_state.valid_date={state_date})."
    )


if __name__ == "__main__":
    main()
