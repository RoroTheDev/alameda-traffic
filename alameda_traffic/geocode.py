"""Street-name geocoder for CCRS crashes: intersection of PrimaryRoad x
SecondaryRoad on the Alameda County street centerlines, optionally shifted by
the reported offset (SecondaryDistance / SecondaryDirection) and snapped back
onto the primary street.

It is a deliberately simple, inspectable method — every result carries a
status so ambiguity is reported instead of guessed:

    ok              exactly one intersection location (all candidates within CLUSTER_M)
    ambiguous       the two streets meet in >1 distinct places (e.g. same name in two
                    neighbourhoods, or a street that crosses another twice)
    no_intersection both streets found but never meet (name/suffix mismatch, or the
                    streets are not connected in the centerline file)
    street_not_found  one street name has no match in the centerlines
    not_surface     highway/route/ramp/numeric names — out of scope

Accuracy is NOT assumed: audit/geocode_validation.py measures it against
crashes whose officer-reported coordinates we trust.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import Point
from shapely.ops import unary_union

log = logging.getLogger(__name__)

PROJ = 26910          # NAD83 / UTM zone 10N (meters)
TOL_M = 6.0           # centerline gap tolerance when intersecting two streets
CLUSTER_M = 150.0     # candidate intersections closer than this are the same place

DIRS = {"N", "S", "E", "W", "NB", "SB", "EB", "WB", "NE", "NW", "SE", "SW"}
SUFFIX_MAP = {
    "AV": "AV", "AVE": "AV", "AVENUE": "AV", "ST": "ST", "STREET": "ST", "BL": "BL", "BLVD": "BL",
    "RD": "RD", "ROAD": "RD", "DR": "DR", "DRIVE": "DR", "WY": "WY", "WAY": "WY", "CT": "CT",
    "COURT": "CT", "LN": "LN", "LANE": "LN", "PL": "PL", "PLACE": "PL", "TE": "TE", "TER": "TE",
    "CI": "CI", "CIR": "CI", "CM": "CM", "PW": "PW", "PKWY": "PW", "TR": "TR", "TRL": "TR",
    "LP": "LP", "LOOP": "LP", "HW": "HW", "HWY": "HW", "PA": "PA", "PK": "PK", "PZ": "PZ",
    "SQ": "SQ", "AL": "AL", "CTR": "CTR", "CV": "CV", "PT": "PT", "WK": "WK",
}
ROUTE_RE = re.compile(r"^(RT|SR|I|HWY|HW|FWY|US|ROUTE|STATE ROUTE)\b|^I-?\d|\bFWY\b|\bRAMP\b|^\d{2,3}$|"
                      r"\bOFF\b|\bON\b.*\bRAMP\b", re.I)
INCORPORATED_ALIAS = {"Oakland Intl Airport": "Oakland", "Uc Berkeley": "Berkeley", "CSU Hayward": "Hayward"}


def parse_street(raw) -> tuple[str, str | None] | None:
    """'W MACARTHUR BL' -> ('MACARTHUR', 'BL'); 'E 20TH' -> ('20TH', None); None if unusable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = re.sub(r"[.,'’]", "", raw.upper()).strip()
    s = re.sub(r"\s+", " ", s)
    if ROUTE_RE.search(s):
        return None
    toks = s.split()
    if len(toks) > 1 and toks[0] in DIRS:
        toks = toks[1:]
    if len(toks) > 1 and toks[-1] in DIRS and toks[-1] not in {"E", "W", "N", "S"}:
        toks = toks[:-1]  # trailing NB/SB/EB/WB
    suffix = None
    if len(toks) > 1 and toks[-1] in SUFFIX_MAP:
        suffix = SUFFIX_MAP[toks[-1]]
        toks = toks[:-1]
    return " ".join(toks), suffix


@dataclass
class Result:
    status: str
    x: float | None = None      # EPSG:26910
    y: float | None = None
    n_places: int = 0
    method: str | None = None


class Geocoder:
    def __init__(self, centerlines: gpd.GeoDataFrame):
        cl = centerlines.to_crs(PROJ)
        cl = cl[~cl["CLASS"].isin(["Ramp", "Interstate", "Freeway or Expressway"])].copy()
        names = cl["SFEANME"].fillna("").map(lambda s: re.sub(r"[.,'’]", "", s.upper()).strip())
        cl["_name"] = names.map(lambda s: re.sub(r"\s+", " ", s))
        cl["_suffix"] = cl["SFEATYP"].map(lambda s: SUFFIX_MAP.get(str(s).upper(), None))
        cl["_city"] = cl["CITYL"].fillna("")
        cl["_city_r"] = cl["CITYR"].fillna("")
        self.cl = cl
        self.by_name: dict[str, pd.DataFrame] = {k: g for k, g in cl.groupby("_name")}
        self._street_cache: dict = {}
        self._inter_cache: dict = {}

    # ---- street geometry -------------------------------------------------
    def _street(self, name: str, suffix: str | None, city: str | None):
        key = (name, suffix, city)
        if key in self._street_cache:
            return self._street_cache[key]
        g = self.by_name.get(name)
        geom = None
        if g is not None:
            if suffix:
                sel = g[g["_suffix"] == suffix]
                g = sel if len(sel) else None
            if g is not None and city:
                sel = g[(g["_city"] == city) | (g["_city_r"] == city)]
                g = sel if len(sel) else None
            if g is not None:
                geom = unary_union(list(g.geometry))
        self._street_cache[key] = geom
        return geom

    # ---- intersection ----------------------------------------------------
    def _places(self, a, b):
        key = (id(a), id(b))
        if key in self._inter_cache:
            return self._inter_cache[key]
        inter = a.buffer(TOL_M).intersection(b.buffer(TOL_M))
        pts = []
        if not inter.is_empty:
            parts = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
            pts = [p.centroid for p in parts if not p.is_empty]
        clusters: list[list[Point]] = []
        for p in pts:
            for c in clusters:
                if p.distance(c[0]) <= CLUSTER_M:
                    c.append(p)
                    break
            else:
                clusters.append([p])
        centers = [Point(sum(q.x for q in c) / len(c), sum(q.y for q in c) / len(c)) for c in clusters]
        self._inter_cache[key] = centers
        return centers

    def geocode(self, primary, secondary, city, dist=None, direction=None, unit=None) -> Result:
        pa, sb = parse_street(primary), parse_street(secondary)
        if pa is None or sb is None:
            return Result("not_surface")
        city = INCORPORATED_ALIAS.get(city, city)
        scope = city if city and city != "Unincorporated" else None
        a = self._street(pa[0], pa[1], scope)
        b = self._street(sb[0], sb[1], scope)
        if a is None or b is None:
            return Result("street_not_found")
        centers = self._places(a, b)
        if not centers:
            return Result("no_intersection")
        if len(centers) > 1:
            return Result("ambiguous", n_places=len(centers))
        p = centers[0]
        method = "intersection"
        d = _to_meters(dist, unit)
        vec = _DIR_VEC.get(str(direction).upper()) if direction else None
        if d and d > 0 and vec:
            shifted = Point(p.x + vec[0] * d, p.y + vec[1] * d)
            nearest = shapely.ops.nearest_points(a, shifted)[0]
            p = nearest if nearest.distance(shifted) <= 0.5 * d + 40 else shifted
            method = "intersection+offset"
        return Result("ok", p.x, p.y, 1, method)


_DIR_VEC = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0),
            "NE": (.7071, .7071), "NW": (-.7071, .7071), "SE": (.7071, -.7071), "SW": (-.7071, -.7071)}


def _to_meters(dist, unit) -> float | None:
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return None
    if math.isnan(d):
        return None
    u = str(unit).upper() if unit is not None else "F"
    return d * (1609.344 if u.startswith("M") else 0.3048)


def project(lat, lon):
    return gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(PROJ)


def unproject(x, y):
    s = gpd.GeoSeries(gpd.points_from_xy(x, y), crs=PROJ).to_crs(4326)
    return s.y.values, s.x.values
