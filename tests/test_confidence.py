import pandas as pd
import pytest

from pipeline import ingest


@pytest.mark.parametrize("value,level", [
    (0, "low"), (29, "low"), (30, "nominal"), (79, "nominal"), (80, "high"), (100, "high"),
])
def test_modis_confidence_bands(value, level):
    assert ingest.modis_confidence(pd.Series([value])).iloc[0] == level


@pytest.mark.parametrize("value,level", [
    ("l", "low"), ("n", "nominal"), ("h", "high"),
    ("low", "low"), ("nominal", "nominal"), ("high", "high"), (" H ", "high"),
])
def test_viirs_confidence_words(value, level):
    assert ingest.viirs_confidence(pd.Series([value])).iloc[0] == level


def test_unknown_confidence_is_missing():
    assert pd.isna(ingest.modis_confidence(pd.Series(["x"])).iloc[0])
    assert pd.isna(ingest.viirs_confidence(pd.Series(["?"])).iloc[0])
