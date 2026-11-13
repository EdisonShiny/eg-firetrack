import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODIS_HEADER = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
                "confidence,version,bright_t31,frp,daynight,type")
VIIRS_HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
                "confidence,version,bright_ti5,frp,daynight,type")
VIIRS_NRT_HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
                    "confidence,version,bright_ti5,frp,daynight")


@pytest.fixture
def squares():
    """Two 1-degree test 'districts' side by side, standing in for GADM boundaries."""
    import geopandas as gpd
    from shapely.geometry import box

    return gpd.GeoDataFrame(
        {"country": ["Indonesia", "Malaysia"], "province": ["Central Kalimantan", "Sarawak"],
         "district": ["Kapuas", "Miri"], "gid": ["A", "B"]},
        geometry=[box(113.0, -3.0, 114.0, -2.0), box(114.0, -3.0, 115.0, -2.0)], crs="EPSG:4326")


def write(tmp_path, name, header, rows):
    p = tmp_path / name
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)


def frame(**cols):
    return pd.DataFrame(cols)
