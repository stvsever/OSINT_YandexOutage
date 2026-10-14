"""Export the study's actor set, the Yandex outage incident and the findings as a STIX 2.1 bundle,
with behaviours mapped to DISARM Red framework techniques (v1.6.1).

DISARM attack-patterns are copied verbatim from the official DISARM STIX bundle, so their STIX ids match
other DISARM-based tooling. Each mapping states its basis: a public attribution (EEAS, VIGINUM) or
behaviour observed in this study's data.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import stix2

from common import PROC

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stix" / "yandex_outage_io_disarm.json"
DISARM_URL = ("https://raw.githubusercontent.com/DISARMFoundation/DISARMframeworks/main/"
              "generated_files/DISARM_STIX/DISARM.json")
NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
REPO = "https://github.com/stvsever/OSINT_YandexOutage"
NS = uuid.UUID("6f3d2a1e-5b7c-4e2f-9a1d-0c8b7e6d5f40")  # namespace for deterministic STIX ids
sid = lambda typ, key: f"{typ}--{uuid.uuid5(NS, typ + ':' + key)}"

EEAS = stix2.ExternalReference(source_name="EEAS", description="4th EEAS report on foreign information manipulation and interference threats (2026)",
                               url="https://www.eeas.europa.eu/sites/default/files/2026/documents/EEAS%204th%20Threat%20Report_web%20version_1.pdf")
VIGINUM_PK = stix2.ExternalReference(source_name="VIGINUM", description="Portal Kombat: a structured and coordinated pro-Russian propaganda network (2024)",
                                     url="https://www.sgdsn.gouv.fr/files/files/20240212_NP_SGDSN_VIGINUM_PORTAL-KOMBAT-NETWORK_ENG_VF.pdf")
STUDY = stix2.ExternalReference(source_name="OSINT_YandexOutage", description="Yandex Cloud Outages as a Natural Experiment on Russian Influence Operations (report and data)", url=REPO)

# actor sets measured in the study: (key, name, aliases, description, references, DISARM techniques with basis)
ACTORS = [
    ("pravda", "Pravda network", ["Portal Kombat"],
     "Automated network of news portals in dozens of languages that republishes and machine-translates content from Russian state media and pro-Kremlin Telegram channels.",
     [VIGINUM_PK, EEAS],
     [("T0084", "attribution"), ("T0085.008", "attribution"), ("T0098.001", "attribution"), ("T0101", "attribution"),
      ("T0049.007", "attribution"), ("T0118", "observed"), ("T0152.004", "observed")]),
    ("afri", "African Initiative", [],
     "Outlet and Telegram channels presenting as a news agency for African audiences; named in the EEAS 4th FIMI threat report.",
     [EEAS], [("T0097.202", "attribution"), ("T0101", "attribution"), ("T0152.004", "observed"), ("T0151.007", "observed")]),
    ("rrn", "RRN (Reliable Recent News)", [],
     "Inauthentic news outlet associated with the Doppelganger operation; named in the EEAS 4th FIMI threat report.",
     [EEAS], [("T0098.001", "attribution"), ("T0097.202", "attribution"), ("T0152.004", "observed")]),
    ("rfbi", "R-FBI (Foundation to Battle Injustice)", ["Foundation to Battle Injustice"],
     "Organisation presenting as a human-rights foundation; named in the EEAS 4th FIMI threat report.",
     [EEAS], [("T0097.207", "attribution"), ("T0152.004", "observed")]),
    ("fio", "Foreign-audience pro-Kremlin channels", ["InfoDefense", "Strategic Culture", "Sputnik Africa", "DD Geopolitics"],
     "Telegram channels and outlets that relay Russian state narratives to foreign audiences in multiple languages.",
     [STUDY], [("T0101", "observed"), ("T0119.001", "observed"), ("T0151.007", "observed"), ("T0118", "observed")]),
    ("state", "Russian state media channels", ["TASS", "Zvezda", "Vesti", "Izvestia", "Channel One Kremlin pool", "War on Fakes"],
     "Overt state and state-aligned media channels on Telegram.",
     [STUDY], [("T0002", "observed"), ("T0151.007", "observed"), ("T0115", "observed"), ("T0068", "observed")]),
    ("milb", "Pro-Kremlin military bloggers", ["Rybar", "WarGonzo", "Readovka", "Two Majors", "Kotsnews"],
     "War-focused Telegram channels that amplify Russian military narratives.",
     [STUDY], [("T0151.007", "observed"), ("T0115", "observed"), ("T0118", "observed"), ("T0068", "observed")]),
]

FINDINGS = {
    "pravda": "Output fell to {r:.0f}% of expected for {h:.1f} h, starting {o:.0f} min after the Vladimir outage (onset-locked q = {q:.3f}); "
              "no comparable dip after Sasovo. Interpreted as a stall of the republishing pipeline, not a loss of capability.",
    "afri": "No credible drop and no time-locked dip after the strikes.",
    "rrn": "No credible drop and no time-locked dip after the strikes.",
    "rfbi": "Too few publications in the study period for separate inference.",
    "fio": "No credible drop; output rose relative to controls with coverage of the strikes.",
    "state": "No credible drop; non-war posts fell while war posts rose (topic substitution toward strike news).",
    "milb": "No credible drop after the strikes.",
}


def main():
    disarm = requests.get(DISARM_URL, timeout=120).json()["objects"]
    by_ext = {o["external_references"][0]["external_id"]: o for o in disarm if o["type"] == "attack-pattern"}
    keep_meta = [o for o in disarm if o["type"] in ("identity", "marking-definition")]
    tim = json.loads((PROC / "timing_results.json").read_text())["results"]["pravda.total"]["events"]["VLA"]

    author = stix2.Identity(id=sid("identity", "author"), name="OSINT_YandexOutage study", identity_class="organization", created=NOW, modified=NOW,
                            description="Independent open-source study of the October 2026 Yandex data-center strikes.")
    common = dict(created_by_ref=author.id, created=NOW, modified=NOW, object_marking_refs=[stix2.TLP_WHITE])
    incident = stix2.Incident(id=sid("incident", "yandex-strikes-2026-10"), name="Strikes on Yandex data centers and Yandex Cloud outage, 7 to 11 October 2026",
                              description="Drone strikes on Yandex data centers in Sasovo, Kaluga and Vladimir; measured Yandex Cloud reachability fell by about a third after Sasovo and by 78% in total after Vladimir.",
                              external_references=[STUDY], **common)
    campaign = stix2.Campaign(id=sid("campaign", "ru-io-2026"), name="Russian information operations on the war in Ukraine, observed 1 September to 13 October 2026",
                              description="Publication output of the actor sets below, measured in this study.", external_references=[STUDY], **common)
    objs, used_aps = [author, incident, campaign], set()
    for key, name, aliases, desc, refs, techs in ACTORS:
        iset = stix2.IntrusionSet(id=sid("intrusion-set", key), name=name, aliases=aliases or None, description=desc, external_references=refs, **common)
        objs.append(iset)
        objs.append(stix2.Relationship(id=sid("relationship", "attr:" + key), relationship_type="attributed-to", source_ref=campaign.id, target_ref=iset.id, **common))
        for t, basis in techs:
            ap = by_ext[t]
            used_aps.add(t)
            objs.append(stix2.Relationship(id=sid("relationship", f"uses:{key}:{t}"), relationship_type="uses", source_ref=iset.id, target_ref=ap["id"],
                                           description=("Based on public attribution: " + ", ".join(r.source_name for r in refs if r.source_name != "OSINT_YandexOutage"))
                                           if basis == "attribution" else "Observed in this study's publication data.", **common))
        text = FINDINGS[key].format(r=tim["dip_ratio"] * 100, h=tim["dip_hours"], o=tim["offset_min"], q=tim["q_locked"])
        objs.append(stix2.Note(id=sid("note", key), abstract=f"Effect of the Yandex outages on {name}", content=text, object_refs=[iset.id, incident.id], **common))
        if key == "pravda":
            objs.append(stix2.Relationship(id=sid("relationship", "incident:pravda"), relationship_type="related-to", source_ref=incident.id, target_ref=iset.id,
                                           description="Time-locked output stall after the Vladimir outage.", **common))
    aps = [by_ext[t] for t in sorted(used_aps)]
    report = stix2.Report(id=sid("report", "study"), name="Yandex Cloud Outages as a Natural Experiment on Russian Influence Operations",
                          description="Actor sets measured in the study, mapped to DISARM Red framework techniques (v1.6.1), with the effect of the October 2026 Yandex outages on each.",
                          published=NOW, report_types=["threat-actor", "campaign", "attack-pattern"],
                          object_refs=[o.id for o in objs] + [a["id"] for a in aps], external_references=[STUDY, EEAS, VIGINUM_PK], **common)
    bundle = stix2.Bundle(id=sid("bundle", "study"), objects=[*keep_meta, *aps, *objs, report, stix2.TLP_WHITE], allow_custom=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(bundle.serialize(pretty=True))
    stix2.parse(OUT.read_text(), allow_custom=True)  # round-trip validation
    print(f"{OUT.name}: {len(bundle.objects)} objects, {len(ACTORS)} actor sets, {len(aps)} DISARM techniques")


if __name__ == "__main__":
    main()
