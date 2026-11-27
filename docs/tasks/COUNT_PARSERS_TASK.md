# Task: parse the 2016–2022 Alameda CTC bike/ped count workbooks

> **Status (2026-11-26): done in-house.** Implemented in `analysis/counts.py`; results and checks are recorded in
> `docs/OSF_REGISTRATION.md` under "Post-tag changes". This brief is kept as the checklist the work followed.

**Why this matters.** Preregistered hypothesis H1 asks whether pedestrian crashes rise more slowly than the number of
people walking, using a panel of count years (2016, 2017, 2018, 2020, 2022, 2024). Only 2024 is parsed so far
(`analysis/counts.py`). H1 is run **once** (`analysis/partb_b1.py`), so the parsed counts have to be right before that
run. This task is the last thing blocking H1.

**What you deliver.** One file per year, `data/processed/analysis/counts_<year>.parquet`, for 2016, 2017, 2018, 2020 and
2022, in the same format as the 2024 file. Plus a short check report (template at the bottom). Code goes in as a pull
request on GitHub; Rohan reviews it before anything is merged.

---

## Ground rules (please read)

1. **Do not open or use any crash data**, and **do not run `analysis/partb_b1.py`** (with or without flags). Your work
   must be "blind" to the outcome, which is what keeps H1 honest. Everything below uses only the count workbooks and
   the street map.
2. **Do not change the 2024 results.** After your changes, parsing 2024 must give exactly the same numbers as before.
3. **Data never goes into git.** Everything under `data/` is ignored by git on purpose. Only code and the check
   report are committed.
4. If something is ambiguous (a weird file, a duplicate site), **write it down in the check report** rather than
   guessing silently. Unexpected cases are normal; hiding them is the only real mistake.

---

## Setup (about 30 minutes)

```bash
git clone https://github.com/RoroTheDev/alameda-traffic.git
cd alameda-traffic
python -m venv .venv                # Python 3.12
.venv\Scripts\activate              # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python download.py county_gis       # street centerlines, needed by the geocoder
```

Then download the five count zips from the Alameda CTC Bicycle & Pedestrian Count Program page
(https://www.alamedactc.org/programs-projects/bicycle-and-pedestrian/bicycle-pedestrian-count-program/) and unzip
each into its own folder:

| Year | File on that page | Unzip into | Workbooks |
|---|---|---|---|
| 2016 | `2016_AlamedaCTC_ManualBikePedCounts.zip` | `data/manual/alamedactc_public/raw2016/` | 76 |
| 2017 | `Alameda-CTC-2017-Bicycle-and-Ped-Counts.zip` | `.../raw2017/` | 75 |
| 2018 | `2018_Ped-Bike_Counts.zip` | `.../raw2018/` | 149 |
| 2020 | `2020_Ped-Bike_Counts.zip` | `.../raw2020/` | 150 |
| 2022 | `2022_Ped-Bike_Counts.zip` | `.../raw2022/` | 151 |

Also download the published summaries you will check against: `2018_Count_Summary.pdf`, `2020_Count_Summary.pdf`,
`2022_Count_Summary.pdf` and `2024_Count_Summary.pdf` (same page). There is no summary PDF for 2016 or 2017; see the
checks section.

---

## How the workbooks are laid out

Every workbook is one intersection. Each has a sheet for the 4–6 pm count (that is the only period we use, because
it is the one counted at every site in every year). Inside the sheet:

- rows 3–9: metadata (`DATE:`, `PERIOD`, `INTERSECTION: N/S <street>`, `E/W <street>`, `CITY:`)
- then four blocks, one per leg (`NORTH LEG`, `SOUTH LEG`, `EAST LEG`, `WEST LEG`), each with eight 15-minute rows
  (`400-415` … `545-600`) followed by hourly-total rows that must **not** be added in
- bicycles = the three movement columns (e.g. `SBRT`, `SBTH`, `SBLT`); pedestrians = the `TOTAL COUNT` column under
  `PEDS`

A correct parse of a normal site has **32 fifteen-minute rows** (4 legs × 8) and **4 legs**.

`analysis/counts.py` already does all of this for 2024: `meta()` reads the metadata, `tally()` sums the 15-minute rows,
`clean()`/`geocode_row()` turn the street names into a map position. Read it first; you will mostly be generalising it.

### What differs by year (checked on the first workbook of each year — verify on more)

| | 2016, 2017, 2018 | 2020, 2022 | 2024 (already done) |
|---|---|---|---|
| 4–6 pm sheet name | `400-600` | `400-600` | `400-600 (Non-Electric)` + `400-600 (Electric)` |
| Column groups | BICYCLES, PEDS | BICYCLES, SCOOTERS, PEDS | NON-ELECTRIC BIKES, NON-ELECTRIC SCOOTERS, PEDS |
| E-bikes counted separately? | no | no | yes (Electric sheet) |
| Location number in file name | yes (`... Loc 4.xlsx`), **except 2017** | yes | yes |

Things that will bite:

- **The pedestrian column moves.** Without scooter columns (2016–2018) the `PEDS / TOTAL COUNT` column is much further
  left than in 2020+. The 2024 code hard-codes the column index (`13`). Please **find the column from the header row
  instead** (the cell reading `TOTAL COUNT` in the `15-min Counts` row) so it cannot silently read the wrong column.
- **2020 has an extra `Bike - Total` column** at the end of the first data row. Make sure it is not added to anything.
- **2017 file names have no `Loc N`** (`ALAMEDA 01-SCH_PM.xlsx`, `ALAMEDA 02-PM.xlsx`), so the current regex finds no
  id and skips every file. Use the file name (city + number) as the id, e.g. `loc_id = "ALAMEDA 01"`. The id is only
  used for ordering; sites are matched across years by map position, not by id.
- **2018 has revised files** (`Alameda Loc 107 (Revised).xlsx`). If a location has both an original and a `(Revised)`
  file, use the revised one and list each such case in the report.
- **E-bikes before 2024:** they were not counted separately, so set `ebike = 0` and `escooter = 0` for 2016–2022, and
  note it in the report. (Any e-bikes are presumably inside the bicycle count.)
- Street-name spelling varies by year (`REDWOOD RD` vs `REDWOOD ROAD`, `CASTRO VALLEY` as a city). `clean()` and
  `geocode_row()` may need a few more fixes; that is expected.

---

## What to build

Suggested shape (you may do it differently if it is cleaner):

1. Add a `--year` option to `analysis/counts.py` (default 2024) so that `RAW` becomes `raw<year>/` and the output is
   `counts_<year>.parquet`.
2. Put the year-specific differences in one small settings dict per year (sheet names, how to get the location id,
   whether there is an Electric sheet), and find column positions from the header rows.
3. Keep the output columns identical to 2024: `loc_id, ns, ew, city, date, ped, bike, ebike, scooter, escooter, rows,
   legs, file, geo_status, x, y`. `analysis/partb_b1.py` relies on `loc_id, x, y, geo_status, ped, bike, ebike`.
4. Run it for each year:

```bash
python -m analysis.counts --year 2024     # must reproduce the existing 2024 numbers exactly
python -m analysis.counts --year 2016
python -m analysis.counts --year 2017
python -m analysis.counts --year 2018
python -m analysis.counts --year 2020
python -m analysis.counts --year 2022
```

---

## Checks (none of these look at crashes)

For **each** year, record in the report:

1. **Files vs sites.** Workbooks found, sites parsed, files skipped (with the reason for each skip).
2. **Shape.** How many sites have 32 rows and 4 legs; list every site that does not (some intersections really have
   3 legs; say which).
3. **Totals vs the published summary** (2018, 2020, 2022, 2024): compare your county-wide 4–6 pm totals of pedestrians
   and bicyclists, and at least 10 individual sites, against the summary PDF. Write down any difference and what you
   think caused it.
4. **Hand check** (all years, required for 2016 and 2017 since there is no summary PDF): open 5 random workbooks in
   Excel, add up the pedestrians and bicycles by hand, and confirm your parser matches.
5. **Geocoding.** How many sites were placed (`geo_status == "ok"`), and the list of the ones that were not. For 2024 it
   was 121 of 148 (82%). Fix street-name cleaning where you can; list the rest.
6. **2024 regression.** Confirm 2024 still gives 148 parsed and 121 geocoded, with unchanged totals.

### Report template (save as `docs/tasks/COUNT_PARSERS_REPORT.md`)

```
| Year | Workbooks | Parsed | Skipped | 32 rows & 4 legs | Geocoded | Ped total | Bike total | Matches summary? |
|------|-----------|--------|---------|------------------|----------|-----------|------------|------------------|
| 2016 |           |        |         |                  |          |           |            | n/a (hand check) |
...
Revised files used (2018): ...
Sites not geocoded, per year: ...
Anything odd: ...
```

---

## When you are done

Open a pull request with the code change and the report. Rohan reviews it and re-runs the 2024 regression check. After
merge, the parser commit hashes get recorded in `docs/OSF_REGISTRATION.md` (the registration allows parser fixes after
the code freeze, as long as they are listed), and only then is H1 run, once.

Questions are welcome at any point; it is much better to ask than to guess.
