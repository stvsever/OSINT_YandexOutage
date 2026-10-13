"""Infrastructure dependency map of information-operation web assets.

For every domain we resolve A, AAAA, CNAME, MX and NS records (public DNS via
dig), map each address to its origin AS with RIPE Stat network-info, and flag
dependencies on Yandex: hosting in a Yandex AS (AS13238, AS200350 and related),
mail exchangers at Yandex (Yandex 360 for Business), or Yandex authoritative
DNS. Resolution date: run date (13 Oct 2026); historical DNS is not public.
"""
from __future__ import annotations

import json
import subprocess

import pandas as pd

from common import PROC, get, save_json

YANDEX_ASNS = {"13238", "200350", "208722", "202611", "44534", "208795", "215109", "212066"}

DOMAINS = {
    # Russian state media and IO-linked web assets
    "rt.com": "state_foreign", "russian.rt.com": "state_foreign", "de.rt.com": "state_foreign",
    "francais.rt.com": "state_foreign", "actualidad.rt.com": "state_foreign", "arabic.rt.com": "state_foreign",
    "sputnikglobe.com": "state_foreign", "sputniknews.lat": "state_foreign", "sputnik.by": "state_foreign",
    "sputniknews.cn": "state_foreign", "ria.ru": "state_domestic", "tass.ru": "state_domestic",
    "tass.com": "state_foreign", "rg.ru": "state_domestic", "iz.ru": "state_domestic", "1tv.ru": "state_domestic",
    "smotrim.ru": "state_domestic", "vesti.ru": "state_domestic", "ren.tv": "state_domestic",
    "lenta.ru": "loyal_domestic", "kp.ru": "loyal_domestic", "aif.ru": "loyal_domestic", "mk.ru": "loyal_domestic",
    "vz.ru": "loyal_domestic", "ukraina.ru": "io_web", "tsargrad.tv": "io_web", "readovka.news": "io_web",
    "rybar.ru": "io_web", "news-front.su": "io_web", "southfront.press": "io_web",
    "strategic-culture.su": "io_web", "katehon.com": "io_web", "geopolitika.ru": "io_web", "topcor.ru": "io_web",
    "eadaily.com": "io_web", "regnum.ru": "io_web", "news-pravda.com": "io_automated",
    "deutsch.news-pravda.com": "io_automated", "francais.news-pravda.com": "io_automated",
    "usa.news-pravda.com": "io_automated", "pravda-en.com": "io_automated",
    # Controls
    "meduza.io": "control_independent", "novayagazeta.eu": "control_independent",
    "istories.media": "control_independent", "theins.ru": "control_independent", "zona.media": "control_independent",
    "rbc.ru": "control_business", "interfax.ru": "control_business", "kommersant.ru": "control_business",
    # Positive controls (Yandex itself)
    "ya.ru": "positive_control", "yandex.ru": "positive_control", "kinopoisk.ru": "positive_control",
}


RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]  # the local ISP resolver filters sanctioned media


def dig(name: str, rtype: str) -> list[str]:
    for r in RESOLVERS:
        try:
            out = subprocess.run(["dig", "+short", "+time=4", "+tries=2", f"@{r}", name, rtype],
                                 capture_output=True, text=True, timeout=20).stdout
        except subprocess.TimeoutExpired:
            continue
        res = [l.strip().rstrip(".") for l in out.splitlines() if l.strip() and not l.startswith(";")]
        if res:
            return res
    return []


def asn_of(ip: str):
    body = get("https://stat.ripe.net/data/network-info/data.json", {"resource": ip},
               host_key="ripestat", min_interval=0.4)
    if not body:
        return None, None
    d = json.loads(body)["data"]
    return (d.get("asns") or [None])[0], d.get("prefix")


_holder: dict[str, str] = {}


def holder(asn: str) -> str:
    if asn in _holder:
        return _holder[asn]
    body = get("https://stat.ripe.net/data/as-overview/data.json", {"resource": f"AS{asn}"},
               host_key="ripestat", min_interval=0.4)
    h = json.loads(body)["data"].get("holder", "") if body else ""
    _holder[asn] = h
    return h


def main():
    rows = []
    for dom, role in DOMAINS.items():
        a = [x for x in dig(dom, "A") if x[0].isdigit()]
        cname = [x for x in dig(dom, "CNAME")]
        mx = [x.split()[-1] for x in dig(dom, "MX")]
        ns = dig(dom, "NS")
        if not mx and dom.count(".") > 1:
            mx = [x.split()[-1] for x in dig(".".join(dom.split(".")[-2:]), "MX")]
        if not ns and dom.count(".") > 1:
            ns = dig(".".join(dom.split(".")[-2:]), "NS")
        hosts = []
        for ip in a[:4]:
            asn, pfx = asn_of(ip)
            hosts.append({"ip": ip, "asn": asn, "prefix": pfx, "holder": holder(asn) if asn else ""})
        y_host = any(h["asn"] in YANDEX_ASNS for h in hosts)
        y_mail = any("yandex" in m.lower() for m in mx)
        y_dns = any("yandex" in n.lower() for n in ns)
        rows.append({"domain": dom, "role": role, "a": a, "cname": cname, "mx": mx, "ns": ns, "hosts": hosts,
                     "yandex_hosting": y_host, "yandex_mail": y_mail, "yandex_dns": y_dns,
                     "asn_holders": sorted({h["holder"] for h in hosts if h["holder"]})})
        print(f"{dom:28s} {role:20s} host={'Y' if y_host else '-'} mail={'Y' if y_mail else '-'} dns={'Y' if y_dns else '-'} "
              f"{', '.join(sorted({h['holder'][:30] for h in hosts}))} | mx={mx[:2]} ns={ns[:2]}")
    save_json(rows, PROC / "infra_map.json")
    pd.DataFrame(rows).drop(columns=["hosts"]).to_csv(PROC / "infra_map.csv", index=False)


if __name__ == "__main__":
    main()
