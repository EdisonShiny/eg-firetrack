import pandas as pd

from pipeline import geo


def pts(*lonlat):
    return pd.DataFrame({"lon": [p[0] for p in lonlat], "lat": [p[1] for p in lonlat],
                         "id": range(len(lonlat))})


def test_point_inside_is_tagged(squares):
    out = geo.tag(pts((113.5, -2.5), (114.5, -2.5)), squares)
    assert list(out.district) == ["Kapuas", "Miri"]
    assert list(out.province) == ["Central Kalimantan", "Sarawak"]
    assert list(out.country) == ["Indonesia", "Malaysia"]


def test_point_just_outside_goes_to_nearest(squares):
    # ~500 m south of the Kapuas square (0.0045 deg latitude)
    out = geo.tag(pts((113.5, -3.0045)), squares)
    assert list(out.district) == ["Kapuas"]


def test_point_at_sea_is_dropped(squares):
    out = geo.tag(pts((113.5, -3.05), (113.5, -2.5)), squares)   # ~5.5 km out, then inside
    assert list(out.id) == [1]


def test_borneo_province_names():
    assert geo.province_for("IDN", "Kalimantan Tengah") == "Central Kalimantan"
    assert geo.province_for("IDN", "Kalimantan Utara") == "North Kalimantan"
    assert geo.province_for("IDN", "Sulawesi Barat") is None          # in the FIRMS box, not Borneo
    assert geo.province_for("MYS", "Labuan") == "Sabah"
    assert geo.province_for("MYS", "Johor") is None
    assert geo.province_for("BRN", "Belait") == "Brunei"
