"""Fetches Freddie Mac's weekly mortgage rate averages (PMMS) from FRED and saves rates.json."""
import csv, io, json, urllib.request

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US,MORTGAGE15US"


def number(value):
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def main():
    request = urllib.request.Request(URL, headers={"User-Agent": "patricktaba-rates-updater"})
    text = urllib.request.urlopen(request, timeout=60).read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))[1:]
    weeks = [(r[0], number(r[1]), number(r[2])) for r in rows if len(r) >= 3]
    weeks = [w for w in weeks if w[1] is not None and w[2] is not None]
    if len(weeks) < 2:
        raise SystemExit("Not enough data came back, so rates.json was left unchanged.")
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
    print(f"Saved week of {latest[0]}: 30-year {latest[1]}%, 15-year {latest[2]}%")


if __name__ == "__main__":
    main()
