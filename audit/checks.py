"""Follow-up checks on the coordinate audit (run: python -m audit.checks)."""
import warnings
import geopandas as gpd
import numpy as np
import pandas as pd
from audit.coordinates import PROCESSED, PROJ, classify_coords, load_crashes
from alameda_traffic.geocode import Geocoder

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)
county = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_county.geojson").to_crs(PROJ).geometry.iloc[0]
df = classify_coords(load_crashes(), county)
gc = Geocoder(gpd.read_file(PROCESSED / "county_gis" / "street_centerlines.geojson"))

# 1. Does applying the reported offset help? Same crashes, with vs without offset.
v = df[(df.coord_state == "valid") & (df.agency == "City/campus PD") & (df.IsFreeway.fillna("False") != "True")]
v = v[pd.to_numeric(v.SecondaryDistance, errors="coerce") > 0]
v = v.sample(min(6000, len(v)), random_state=0)
rows = []
for r in v.to_dict("records"):
    a = gc.geocode(r["PrimaryRoad"], r["SecondaryRoad"], r["City Name"])
    b = gc.geocode(r["PrimaryRoad"], r["SecondaryRoad"], r["City Name"], r["SecondaryDistance"],
                   r["SecondaryDirection"], r["SecondaryUnitOfMeasure"])
    if a.status == "ok" and b.status == "ok":
        rows.append((np.hypot(a.x - r["x"], a.y - r["y"]), np.hypot(b.x - r["x"], b.y - r["y"]),
                     r["SecondaryDirection"], r["SecondaryUnitOfMeasure"]))
e = pd.DataFrame(rows, columns=["no_offset_m", "with_offset_m", "dir", "unit"])
print(f"1. offset test on {len(e)} crashes that report an offset:")
print(e[["no_offset_m", "with_offset_m"]].describe(percentiles=[.5, .75, .9]).round(1).T)
print("   within 50 m  no-offset:", round((e.no_offset_m <= 50).mean(), 3), "| with-offset:", round((e.with_offset_m <= 50).mean(), 3))
print("   units:", df.SecondaryUnitOfMeasure.value_counts(dropna=False).to_dict())
print("   directions:", df.SecondaryDirection.value_counts(dropna=False).head(10).to_dict())

# 2. CHP 'outside county' points: where are they?
o = df[(df["NCIC Code"] == "9370") & (df.coord_state == "outside_county") & df.injury]
print(f"\n2. CHP Oakland (9370) injury crashes outside county polygon: {len(o)}")
print(o[["lat", "lon"]].describe().round(3).T)
print("   top primary roads:", o.PrimaryRoad.value_counts().head(8).to_dict())

# 3. Who ends up with no coordinate at all?
res = pd.read_parquet(PROCESSED / "audit" / "ccrs_crash_coordinates.parquet")
n = res[res.injury & (res.final_source == "none")]
print(f"\n3. injury crashes with no coordinate even after geocoding: {len(n)}")
print(n.groupby(["agency", "geo_status"], dropna=False).size().sort_values(ascending=False).head(10))
print(n["NCIC Code"].value_counts().head(8).to_dict())
