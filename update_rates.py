"""Saves Freddie Mac's weekly mortgage rate averages (PMMS) to rates.json.

Tries several sources in order and uses the first one that works:
  1. The FRED API, if a free FRED_API_KEY secret has been added (most reliable)
  2. Freddie Mac's own PMMS history file
  3. FRED's public CSV download
"""
import csv, io, json, os, time, urllib.parse, urllib.request
from datetime import datetime

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def fetch(url, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER, "Accept": "*/*"})
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig")
        except Exception as err:
            last = err
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def number(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def iso(day):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(day.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def from_csv(text, col30, col15):
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.strip().lower() for h in rows[0]]
    i30, i15 = head.index(col30.lower()), head.index(col15.lower())
    weeks = []
    for r in rows[1:]:
        if len(r) > max(i30, i15):
            d, a, b = iso(r[0]), number(r[i30]), number(r[i15])
            if d and a is not None and b is not None:
                weeks.append((d, a, b))
    return sorted(weeks)


def fred_api():
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no FRED_API_KEY secret set")
    series = {}
    for sid in ("MORTGAGE30US", "MORTGAGE15US"):
        q = urllib.parse.urlencode({"series_id": sid, "api_key": key, "file_type": "json", "observation_start": "2015-01-01"})
        obs = json.loads(fetch("https://api.stlouisfed.org/fred/series/observations?" + q))["observations"]
        series[sid] = {o["date"]: number(o["value"]) for o in obs}
    a, b = series["MORTGAGE30US"], series["MORTGAGE15US"]
    return sorted((d, a[d], b[d]) for d in a if d in b and a[d] is not None and b[d] is not None)


def freddie_mac():
    return from_csv(fetch("https://www.freddiemac.com/pmms/docs/PMMS_history.csv"), "pmms30", "pmms15")


def fred_csv():
    return from_csv(fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US,MORTGAGE15US"), "MORTGAGE30US", "MORTGAGE15US")


def main():
    problems = []
    for name, source in (("FRED API", fred_api), ("Freddie Mac file", freddie_mac), ("FRED CSV", fred_csv)):
        try:
            weeks = source()
            if len(weeks) < 2:
                raise RuntimeError("returned too little data")
        except Exception as err:
            problems.append(f"{name}: {err}")
            print(f"Skipped {name}: {err}")
            continue
        latest, previous = weeks[-1], weeks[-2]
        data = {
            "source": "Freddie Mac Primary Mortgage Market Survey",
            "week": latest[0],
            "rate30": latest[1], "rate30_prev": previous[1],
            "rate15": latest[2], "rate15_prev": previous[2],
            "history": [[d, a, b] for d, a, b in weeks[-53:]],
        }
        with open("rates.json", "w") as f:
            json.dump(data, f, indent=1)
        print(f"Saved week of {latest[0]} from {name}: 30-year {latest[1]}%, 15-year {latest[2]}%")
        return
    raise SystemExit("Every source failed, so rates.json was left unchanged:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
