"""Borneo boundaries (GADM) and point tagging: country / province / district.

Run `python -m pipeline.geo` once with GADM files in data/raw/gadm to build the committed,
simplified data/processed/boundaries.geojson. Every later run tags points from that file,
so the daily GitHub Action does not need data/raw.
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config, paths

log = logging.getLogger(__name__)

METRIC_CRS = "EPSG:32650"  # UTM 50N, metres; fine for ~1 km distances across Borneo
COLUMNS = ["country", "province", "district", "gid"]


def province_for(iso: str, name_1: str) -> str | None:
    """Map a GADM level-1 name to one of the Borneo areas, or None if not in Borneo."""
    spec = config.data_cfg()["boundaries"]["countries"].get(iso)
    if not spec:
        return None
    provinces = spec["provinces"]
    if "*" in provinces:
        return provinces["*"]
    return provinces.get(name_1)


def build_boundaries(gadm_dir: Path = paths.RAW_GADM) -> gpd.GeoDataFrame:
    import pyogrio

    cfg = config.data_cfg()
    west, south, east, north = cfg["firms"]["bbox"]
    parts = []
    for iso, spec in cfg["boundaries"]["countries"].items():
        path = Path(gadm_dir) / f"gadm41_{iso}.gpkg"
        if not path.exists():
            raise FileNotFoundError(f"missing {path}")
        level = spec["district_level"]
        name_col, gid_col = f"NAME_{level}", f"GID_{level}"
        where = None
        names = [n for n in spec["provinces"] if n != "*"]
        if names:
            where = "NAME_1 IN (" + ",".join("'" + n.replace("'", "''") + "'" for n in names) + ")"
        gdf = pyogrio.read_dataframe(
            path, layer=f"ADM_ADM_{level}", where=where,
            columns=sorted({"NAME_1", name_col, gid_col}), bbox=(west, south, east, north),
        )
        gdf["country"] = spec["country"]
        gdf["province"] = [province_for(iso, n) for n in gdf["NAME_1"]]
        gdf["district"] = gdf[name_col]
        gdf["gid"] = gdf[gid_col]
        gdf = gdf[gdf["province"].notna()]
        parts.append(gdf[COLUMNS + ["geometry"]])
        log.info("%s: %d districts", iso, len(gdf))
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    out["geometry"] = out.geometry.make_valid()
    return out


def simplify_and_save(gdf: gpd.GeoDataFrame, path: Path = paths.BOUNDARIES) -> Path:
    tol = config.data_cfg()["boundaries"]["simplify_deg"]
    out = gdf.copy()
    out["geometry"] = out.geometry.simplify(tol, preserve_topology=True).make_valid()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    out.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=5)
    return path


def load_boundaries(path: Path = paths.BOUNDARIES) -> gpd.GeoDataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} is missing. Run `python -m pipeline.geo` with GADM files in data/raw/gadm.")
    return gpd.read_file(path)


def tag(df: pd.DataFrame, boundaries: gpd.GeoDataFrame) -> pd.DataFrame:
    """Add country/province/district to points (lat, lon); drop points not on Borneo land.

    Points inside a district polygon get it. Points just outside (simplified coast, gaps
    between simplified neighbours) get the nearest district within `nearest_max_km`.
    Everything else (sea, other islands) is dropped.
    """
    max_m = float(config.data_cfg()["boundaries"]["nearest_max_km"]) * 1000
    df = df.drop(columns=[c for c in ("country", "province", "district") if c in df.columns])
    if df.empty:
        return df.assign(country=pd.Series(dtype=str), province=pd.Series(dtype=str),
                         district=pd.Series(dtype=str))
    pts = gpd.GeoDataFrame(
        {"_i": range(len(df))},
        geometry=gpd.points_from_xy(df["lon"].astype(float), df["lat"].astype(float)),
        crs="EPSG:4326",
    )
    b = boundaries[["country", "province", "district", "geometry"]].to_crs("EPSG:4326")
    inside = gpd.sjoin(pts, b, how="left", predicate="within")
    inside = inside[~inside.index.duplicated(keep="first")]
    found = inside[inside["district"].notna()][["_i", "country", "province", "district"]]

    missing = pts[~pts["_i"].isin(found["_i"])]
    if len(missing):
        near = gpd.sjoin_nearest(
            missing.to_crs(METRIC_CRS), b.to_crs(METRIC_CRS), how="inner", max_distance=max_m)
        near = near[~near["_i"].duplicated(keep="first")][["_i", "country", "province", "district"]]
        found = pd.concat([found, near], ignore_index=True)

    found = found.set_index("_i").sort_index()
    out = df.reset_index(drop=True).iloc[found.index].copy()
    out[["country", "province", "district"]] = found[["country", "province", "district"]].to_numpy()
    return out.reset_index(drop=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    gdf = build_boundaries()
    path = simplify_and_save(gdf)
    size = path.stat().st_size / 1e6
    print(f"Wrote {path.relative_to(paths.ROOT)}: {len(gdf)} districts, {size:.1f} MB")
    print(gdf.groupby("province").size().to_string())


if __name__ == "__main__":
    main()
