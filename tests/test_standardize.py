from datetime import datetime

import pandas as pd
import pytest

from pipeline import ingest
from tests.conftest import MODIS_HEADER, VIIRS_HEADER, VIIRS_NRT_HEADER, write

NOW = datetime(2026, 11, 9, 12, 0)


def test_modis_archive_row(tmp_path):
    p = write(tmp_path, "fire_archive_M-C61_1.csv", MODIS_HEADER,
              ["-2.5,113.5,330.1,1.0,1.0,2019-09-15,535,Aqua,MODIS,85,6.1,300.2,45.3,D,0"])
    df = ingest.read_firms_file(p)
    r = df.iloc[0]
    assert (r.sensor, r.satellite, r.confidence, r.time_utc, r.source) == ("MODIS", "Aqua", "high", "05:35", "archive")
    assert r.brightness == pytest.approx(330.1) and r.frp == pytest.approx(45.3) and r.type == 0


def test_viirs_archive_row_uses_bright_ti4(tmp_path):
    p = write(tmp_path, "fire_archive_SV-C2_1.csv", VIIRS_HEADER,
              ["-2.5,113.5,345.0,0.4,0.4,2023-09-01,0512,N,VIIRS,n,2,290,12.5,D,0"])
    r = ingest.read_firms_file(p).iloc[0]
    assert (r.sensor, r.satellite, r.confidence, r.time_utc) == ("VIIRS", "S-NPP", "nominal", "05:12")
    assert r.brightness == pytest.approx(345.0)


def test_nrt_row_without_type_is_unknown(tmp_path):
    p = write(tmp_path, "fire_nrt_J1V-C2_1.csv", VIIRS_NRT_HEADER,
              ["-2.5,113.5,345.0,0.4,0.4,2026-11-08,620,N20,VIIRS,h,2.0NRT,290,9.1,D"])
    r = ingest.read_firms_file(p).iloc[0]
    assert r.source == "nrt" and r.type == -1 and r.satellite == "NOAA-20"


@pytest.mark.parametrize("code,name", [("N", "S-NPP"), ("N20", "NOAA-20"), ("1", "NOAA-20"),
                                       ("1.0", "NOAA-20"), ("N21", "NOAA-21"), ("T", "Terra"),
                                       ("A", "Aqua"), ("Terra", "Terra")])
def test_satellite_codes(code, name):
    assert ingest.satellite_name(pd.Series([code])).iloc[0] == name


def test_acq_time_padding_and_myt_across_midnight(tmp_path):
    p = write(tmp_path, "fire_archive_SV-C2_1.csv", VIIRS_HEADER,
              ["-2.5,113.5,345,0.4,0.4,2026-03-01,5,N,VIIRS,n,2,290,1,N,0",
               "-2.5,113.5,345,0.4,0.4,2026-03-01,1745,N,VIIRS,n,2,290,1,N,0"])
    df = ingest.standardize(ingest.read_firms_file(p), NOW)
    assert list(df.time_utc) == ["00:05", "17:45"]
    assert str(df.time_myt.iloc[0]) == "2026-03-01 08:05:00"
    assert df.date_myt.iloc[1] == "2026-03-02"          # 17:45 UTC = 01:45 MYT next day
    assert df.date.iloc[1] == "2026-03-01"


def test_zip_with_several_csvs(tmp_path):
    import zipfile

    z = tmp_path / "DL_FIRE_SV-C2_123.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("fire_archive_SV-C2_123.csv", VIIRS_HEADER + "\n-2.5,113.5,345,0.4,0.4,2026-01-01,0530,N,VIIRS,n,2,290,1,D,0\n")
        f.writestr("fire_nrt_SV-C2_123.csv", VIIRS_NRT_HEADER + "\n-2.6,113.6,345,0.4,0.4,2026-11-01,0530,N,VIIRS,n,2.0NRT,290,1,D\n")
    df = ingest.read_firms_file(z)
    assert sorted(df.source) == ["archive", "nrt"]
    assert ingest.find_firms_files(tmp_path) == [z]


# Real FIRMS archive download headers (DL_FIRE_*.zip, 2026): VIIRS brightness is in "brightness",
# and S-NPP files say instrument/satellite "SNPP".
REAL_HEADER = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
               "confidence,version,bright_t31,frp,daynight,type")


def test_real_snpp_archive_row_is_viirs(tmp_path):
    p = write(tmp_path, "fire_archive_SV-C2_841194.csv", REAL_HEADER,
              ["-4.03164,114.75741,328.23,0.42,0.38,2017-01-01,0539,SNPP,SNPP,n,2,296.92,3.34,D,0"])
    r = ingest.read_firms_file(p).iloc[0]
    assert (r.sensor, r.satellite, r.confidence, r.source) == ("VIIRS", "S-NPP", "nominal", "archive")
    assert r.brightness == pytest.approx(328.23)


def test_real_noaa20_nrt_row_is_viirs(tmp_path):
    header = REAL_HEADER.rsplit(",type", 1)[0]
    p = write(tmp_path, "fire_nrt_J1V-C2_841193.csv", header,
              ["-0.25094,110.88815,330.79,0.39,0.36,2026-08-01,0603,N20,VIIRS,h,2.0NRT,295.83,22.69,D"])
    r = ingest.read_firms_file(p).iloc[0]
    assert (r.sensor, r.satellite, r.confidence, r.source, r.type) == ("VIIRS", "NOAA-20", "high", "nrt", -1)
    assert r.brightness == pytest.approx(330.79)


def test_real_modis_archive_row_stays_modis(tmp_path):
    p = write(tmp_path, "fire_archive_M-C61_841192.csv", REAL_HEADER,
              ["4.3483,111.9722,305.4,3.1,1.7,2017-01-01,1737,Aqua,MODIS,30,6.03,287.4,24.4,N,0"])
    r = ingest.read_firms_file(p).iloc[0]
    assert (r.sensor, r.satellite, r.confidence) == ("MODIS", "Aqua", "nominal")
