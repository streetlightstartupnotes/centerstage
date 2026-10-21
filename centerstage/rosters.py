"""Source-backed candidate rosters; never a visual identity assignment."""
import re

CATALOGS = [{
    "id": "a2o-lite", "name": "A2O LITE", "verified_at": "2026-10-21",
    "source": "https://www.melon.com/artist/detail.htm?artistId=5217450",
    "names": ["YOUNG", "OA", "AYUNE", "AIJING", "HIMEKI", "RADA", "XILI", "VORA", "MERCI"],
}]


def candidate_roster(filename, group_id="auto"):
    for catalog in CATALOGS:
        if group_id == catalog["id"] or (group_id == "auto" and re.search(r"A2O[\s_-]*LITE", filename, re.I)):
            return catalog["name"], [{"name": name, "source": catalog["source"]} for name in catalog["names"]]
    return "", []
