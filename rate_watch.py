"""Rate Watch matcher for mortgagepatrick.com.

Runs after update_rates.py. Reads the Rate Watch signups (a Google Sheet tab published as CSV,
containing only id / loan type / target / status, no names or phone numbers), compares each
active watcher's target with today's Optimal Blue average for their loan type, and sends every
hit to a Zapier webhook. Zapier looks the person up by id, texts them through LoanOfficer.ai
and marks the row "hit" so they are only texted once.

Secrets (GitHub repo -> Settings -> Secrets and variables -> Actions):
  WATCHERS_CSV_URL  the "Publish to web" CSV link of the watch_public tab
  ZAPIER_HOOK_URL   the Catch Hook URL from Zap B
Optional:
  NEAR = how close counts as a hit, in percentage points (default 0.125 = one eighth)
"""
import csv, io, json, os, sys, urllib.request
from datetime import date

NEAR = float(os.environ.get("NEAR", "0.125"))
LOAN_KEYS = {"conventional": "conv30", "fha": "fha30", "va": "va30", "jumbo": "jumbo30", "not sure": "conv30", "": "conv30"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "rate-watch/1.0", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig")


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=30).read().decode()


def number(v):
    try:
        return float(str(v).replace("%", "").strip())
    except ValueError:
        return None


def main():
    csv_url, hook = os.environ.get("WATCHERS_CSV_URL", "").strip(), os.environ.get("ZAPIER_HOOK_URL", "").strip()
    if not csv_url or not hook:
        print("Rate Watch: WATCHERS_CSV_URL or ZAPIER_HOOK_URL secret is missing, nothing to do")
        return
    rates = json.load(open("rates.json"))
    types = (rates.get("obmmi") or {}).get("types") or {}
    if not types:
        sys.exit("Rate Watch: rates.json has no Optimal Blue numbers")

    rows = list(csv.DictReader(io.StringIO(get(csv_url))))
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]
    active = [r for r in rows if r.get("id") and r.get("status", "").lower() in ("active", "")]
    print(f"Rate Watch: {len(rows)} signups, {len(active)} active")

    hits = 0
    for r in active:
        key = LOAN_KEYS.get(r.get("loan_type", "").lower(), "conv30")
        market, target = types.get(key, {}).get("rate"), number(r.get("target_rate"))
        if market is None or target is None:
            continue
        if market <= target + NEAR:
            payload = {
                "id": r["id"], "loan_type": r.get("loan_type") or "Conventional", "loan_label": types[key]["label"],
                "target_rate": f"{target:.3f}".rstrip("0").rstrip("."), "market_rate": f"{market:.2f}",
                "market_date": types[key].get("date", date.today().isoformat()), "sent_on": date.today().isoformat(),
            }
            post(hook, payload)
            hits += 1
            print(f"Rate Watch: HIT id={r['id']} {payload['loan_label']} target {payload['target_rate']}% market {payload['market_rate']}%")
    print(f"Rate Watch: {hits} hit(s) sent to Zapier")


if __name__ == "__main__":
    main()
