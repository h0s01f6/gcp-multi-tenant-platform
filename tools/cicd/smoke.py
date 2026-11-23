"""Stage 7 – post-deployment smoke test through the customer's public hostname (load balancer -> backend).

Usage:  python3 -m tools.cicd.smoke --tenant abc --product payroll --env prd [--attempts 10] [--dry-run]
The hostname comes from the N4 edge plan (build/edge.json), so the test exercises DNS, certificate, Cloud Armor,
the URL map / Gateway route and the backend. Success = HTTP 200 from /readyz (A-H-1) on N consecutive attempts.
Status: implemented; --dry-run locally tested; the real request needs the deployed platform (T-CI4).
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

PATH = "/readyz"


def hostname(tenant, product, env, edge="build/edge.json"):
    recs = json.loads(pathlib.Path(edge).read_text())["records"]
    hits = [r["hostname"] for r in recs if r.get("tenant") == tenant and f".{product}." in f".{r['hostname']}"
            and (r["hostname"].split(".")[0] == tenant if env == "prd" else r["hostname"].split(".")[0] == f"{tenant}-{env}")]
    if len(hits) != 1:
        raise SystemExit(f"expected one hostname for {tenant}/{product}/{env}, found {hits}")
    return hits[0]


def probe(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--env", required=True)
    ap.add_argument("--attempts", type=int, default=10)
    ap.add_argument("--consecutive", type=int, default=3)
    ap.add_argument("--edge", default="build/edge.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    url = f"https://{hostname(a.tenant, a.product, a.env, a.edge)}{PATH}"
    if a.dry_run:
        print(url)
        return 0
    ok = 0
    for i in range(a.attempts):
        code = probe(url)
        ok = ok + 1 if code == 200 else 0
        print(f"{url} -> {code}")
        if ok >= a.consecutive:
            return 0
        time.sleep(6)
    return 1


if __name__ == "__main__":
    sys.exit(main())
