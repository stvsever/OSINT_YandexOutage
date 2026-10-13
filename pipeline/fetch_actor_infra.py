"""Infrastructure of information-manipulation sets (IMS) named by the EEAS.

Domain sources: VIGINUM technical report on Storm-1516 (May 2025, appendix 6.2,
338 domains) and the EEAS 4th Report on FIMI Threats (March 2026) for African
Initiative, RRN/Media Brands, R-FBI and Portal Kombat. For each domain: public
DNS (A, NS, MX via 1.1.1.1, 8.8.8.8, 9.9.9.9), origin AS of the first address
(RIPE Stat), HTTP liveness, and Yandex dependency flags.
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import requests

from common import PROC, ROOT, get, save_json

YANDEX_ASNS = {"13238", "200350", "208722", "202611", "44534", "208795", "215109", "212066"}
RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
EXTRA = {"afrinz.ru": "African Initiative", "rrn.com.tr": "RRN / Media Brands (SDA)", "fondfbr.ru": "R-FBI",
         "news-pravda.com": "Portal Kombat"}


def dig(name, rtype):
    for r in RESOLVERS:
        try:
            out = subprocess.run(["dig", "+short", "+time=3", "+tries=1", f"@{r}", name, rtype],
                                 capture_output=True, text=True, timeout=12).stdout
        except subprocess.TimeoutExpired:
            continue
        res = [l.strip().rstrip(".") for l in out.splitlines() if l.strip() and not l.startswith(";")]
        if res:
            return res
    return []


def probe(dom):
    a = [x for x in dig(dom, "A") if x[0].isdigit()]
    ns = dig(dom, "NS")
    mx = [x.split()[-1] for x in dig(dom, "MX")]
    alive = None
    try:
        r = requests.get(f"https://{dom}/", timeout=12, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        alive = r.status_code
    except requests.RequestException:
        alive = None
    return dom, a, ns, mx, alive


def main():
    storm = json.loads((ROOT / "config" / "study.json").read_text())["actors"]["viginum_storm1516_domains"]["domains"]
    doms = {d: "Storm-1516 / CopyCop (VIGINUM)" for d in storm}
    doms.update(EXTRA)
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(probe, doms))
    out = []
    for dom, a, ns, mx, alive in res:
        asn, holder = None, ""
        if a:
            body = get("https://stat.ripe.net/data/network-info/data.json", {"resource": a[0]}, host_key="ripestat", min_interval=0.3)
            if body:
                asn = (json.loads(body)["data"].get("asns") or [None])[0]
            if asn:
                b2 = get("https://stat.ripe.net/data/as-overview/data.json", {"resource": f"AS{asn}"}, host_key="ripestat", min_interval=0.3)
                holder = json.loads(b2)["data"].get("holder", "") if b2 else ""
        out.append(dict(domain=dom, ims=doms[dom], resolves=bool(a), a=a[:3], asn=asn, holder=holder, ns=ns[:2], mx=mx[:2],
                        http=alive, yandex_hosting=asn in YANDEX_ASNS, yandex_mail=any("yandex" in m.lower() for m in mx),
                        yandex_dns=any("yandex" in n.lower() for n in ns)))
    save_json(out, PROC / "actor_infra.json")
    import collections
    print("domains", len(out), "resolving", sum(o["resolves"] for o in out), "http200", sum(o["http"] == 200 for o in out))
    print("yandex hosting", [o["domain"] for o in out if o["yandex_hosting"]])
    print("yandex mail", [o["domain"] for o in out if o["yandex_mail"]])
    print("yandex dns", [o["domain"] for o in out if o["yandex_dns"]])
    print(collections.Counter(o["holder"][:40] for o in out if o["resolves"]).most_common(15))


if __name__ == "__main__":
    main()
