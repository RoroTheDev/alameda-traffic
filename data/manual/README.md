# Manual downloads

Files here are git-ignored (except this README and `templates/`). Put
hand-downloaded files here, then rerun the matching script.

| File / folder | Source | Then run |
|---|---|---|
| `pubschls.txt` | CDE "Public Schools and Districts" (tab-delimited) — https://www.cde.ca.gov/ds/si/ds/pubschls.asp (CAPTCHA) | `python download.py schools` |
| `school_calendars.csv` | Copy `templates/school_calendars.csv`, fill from district calendars | `python download.py schools` |
| `tims/*.csv` | TIMS SWITRS Query & Map, Alameda County (Crashes, Parties, Victims) — https://tims.berkeley.edu | `python download.py tims` |

Everything else that needs a human (API keys, agency requests) is listed by
`python download.py manual`.
