"""Saves mortgage rate averages to rates.json for mortgagepatrick.com.

Two sets of numbers, each kept from the last good run if its source is down:
  * Freddie Mac's weekly averages (PMMS): 30-year and 15-year fixed
  * Optimal Blue's daily averages of actual locked rates (OBMMI), by loan type:
    30-year conventional, 15-year conventional, 30-year FHA, 30-year VA and 30-year jumbo

Both come from FRED (Federal Reserve Bank of St. Louis). If a free FRED_API_KEY secret
has been added it's used first; otherwise the public FRED downloads are used.
"""
import csv, io, json, os, time, urllib.parse, urllib.request
from datetime import datetime, date, timedelta

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Optimal Blue Mortgage Market Indices on FRED: (key used by the website, FRED series, label)
OBMMI = [
    ("conv30", "OBMMIC30YF", "30-year conventional"),
    ("conv15", "OBMMIC15YF", "15-year conventional"),
    ("fha30", "OBMMIFHA30YF", "30-year FHA"),
    ("va30", "OBMMIVA30YF", "30-year VA"),
    ("jumbo30", "OBMMIJUMBO30YF", "30-year jumbo"),
]


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


# ---------- Freddie Mac weekly averages (unchanged) ----------

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


def freddie_weekly():
    problems = []
    for name, source in (("FRED API", fred_api), ("Freddie Mac file", freddie_mac), ("FRED CSV", fred_csv)):
        try:
            weeks = source()
            if len(weeks) < 2:
                raise RuntimeError("returned too little data")
        except Exception as err:
            problems.append(f"{name}: {err}")
            print(f"Freddie Mac: skipped {name}: {err}")
            continue
        latest, previous = weeks[-1], weeks[-2]
        print(f"Freddie Mac: week of {latest[0]} from {name}: 30-year {latest[1]}%, 15-year {latest[2]}%")
        return {
            "source": "Freddie Mac Primary Mortgage Market Survey",
            "week": latest[0],
            "rate30": latest[1], "rate30_prev": previous[1],
            "rate15": latest[2], "rate15_prev": previous[2],
            "history": [[d, a, b] for d, a, b in weeks[-53:]],
        }, problems
    return None, problems


# ---------- Optimal Blue daily averages by loan type ----------

def daily_values(sid):
    """Daily observations [(date, rate)] for one FRED series, oldest first."""
    start = (date.today() - timedelta(days=400)).isoformat()
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        try:
            q = urllib.parse.urlencode({"series_id": sid, "api_key": key, "file_type": "json", "observation_start": start})
            obs = json.loads(fetch("https://api.stlouisfed.org/fred/series/observations?" + q))["observations"]
            vals = [(o["date"], number(o["value"])) for o in obs]
            vals = [(d, v) for d, v in vals if v is not None]
            if vals:
                return sorted(vals)
        except Exception as err:
            print(f"Optimal Blue: FRED API failed for {sid}, trying the public download: {err}")
    rows = list(csv.reader(io.StringIO(fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?" + urllib.parse.urlencode({"id": sid, "cosd": start})))))
    vals = [(iso(r[0]), number(r[1])) for r in rows[1:] if len(r) > 1]
    return sorted((d, v) for d, v in vals if d and v is not None)


def weekly(vals):
    """The last daily value of each week, so the chart has one point per week."""
    by_week = {}
    for d, v in vals:
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        by_week[(y, w)] = (d, v)
    return [list(by_week[k]) for k in sorted(by_week)]


def optimal_blue():
    types = {}
    for key, sid, label in OBMMI:
        try:
            vals = daily_values(sid)
            if len(vals) < 10:
                raise RuntimeError("returned too little data")
            last_day, rate = vals[-1]
            week_ago = datetime.strptime(last_day, "%Y-%m-%d").date() - timedelta(days=7)
            prev = next((v for d, v in reversed(vals) if datetime.strptime(d, "%Y-%m-%d").date() <= week_ago), None)
            types[key] = {"label": label, "series": sid, "date": last_day, "rate": rate, "prev": prev,
                          "history": weekly(vals)[-53:]}
            print(f"Optimal Blue: {label} {rate}% on {last_day}")
        except Exception as err:
            print(f"Optimal Blue: skipped {sid}: {err}")
    return types


def main():
    try:
        with open("rates.json") as f:
            old = json.load(f)
    except Exception:
        old = {}
    data = dict(old)

    freddie, problems = freddie_weekly()
    if freddie:
        data.update(freddie)
    else:
        print("Freddie Mac: every source failed, keeping the last saved Freddie Mac numbers")

    fresh = optimal_blue()
    kept = (old.get("obmmi") or {}).get("types") or {}
    types = {k: fresh.get(k) or kept.get(k) for k, _, _ in OBMMI if fresh.get(k) or kept.get(k)}
    if types:
        data["obmmi"] = {
            "source": "Optimal Blue Mortgage Market Indices (OBMMI), via FRED",
            "copyright": "Copyright Optimal Blue, LLC",
            "link": "https://www2.optimalblue.com/obmmi",
            "date": max(t["date"] for t in types.values()),
            "types": types,
        }

    if not freddie and not fresh:
        raise SystemExit("Every source failed, so rates.json was left unchanged:\n  " + "\n  ".join(problems))
    with open("rates.json", "w") as f:
        json.dump(data, f, indent=1)
    print("Saved rates.json")


if __name__ == "__main__":
    main()
