"""Health gap map literature and model sweep.

Pulls candidate leads for the global health gap map (a fork-local extension, separate from
the main map's sources/ pipeline):

  * Europe PMC (PubMed + preprints) for each function in queries.json
  * Hugging Face Hub for LMIC-language speech/translation models and medical models (5.1)

Every lead is checked against known_tools.json (the tools already in the gap map sheet) by a
name match on title + abstract, so known tools are marked rather than rediscovered.

Output is leads, not tool rows: a paper names a tool only sometimes, and a person (or an agent
pass) still assigns the tool and fills Tier 1 fields.

Standard library only:  python sweeps/health/sweep.py --since 2019 --out sweeps/health/out
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
HF = "https://huggingface.co/api/models"
UA = "health-gap-map-sweep/0.1"


def get_json(url: str, tries: int = 4) -> dict | list:
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def known_matcher(names: list[str]):
    # Match on the head of each name, before any parenthetical, at least 4 chars.
    heads = []
    for n in names:
        head = norm(re.split(r"[(/]", n)[0])
        if len(head) >= 4:
            heads.append((head, n))

    def match(text: str) -> list[str]:
        t = f" {norm(text)} "
        return sorted({n for h, n in heads if f" {h} " in t})

    return match


def sweep_epmc(cfg: dict, since: int, per_query: int, match) -> list[dict]:
    rows: dict[str, dict] = {}
    for code, fn in cfg["functions"].items():
        for q in fn["queries"]:
            query = q.format(chw=cfg["chw"], lmic=cfg["lmic"])
            full = f"ABSTRACT:({query}) AND PUB_YEAR:[{since} TO 2100]"
            params = urllib.parse.urlencode(
                {"query": full, "format": "json", "pageSize": per_query,
                 "resultType": "core"})
            data = get_json(f"{EPMC}?{params}")
            hits = data.get("resultList", {}).get("result", [])
            print(f"[epmc] {code}: {data.get('hitCount', 0)} hits, kept {len(hits)}")
            for h in hits:
                key = h.get("doi") or h.get("id")
                abstract = re.sub(r"<[^>]+>", "", h.get("abstractText", "") or "")
                text = f"{h.get('title', '')} {abstract}"
                known = match(text)
                row = rows.setdefault(key, {
                    "source": "europepmc",
                    "function_codes": set(),
                    "title": h.get("title", ""),
                    "year": h.get("pubYear", ""),
                    "venue": h.get("journalTitle", "") or h.get("bookOrReportDetails", {}).get("publisher", ""),
                    "url": f"https://doi.org/{h['doi']}" if h.get("doi") else
                           f"https://europepmc.org/article/{h.get('source')}/{h.get('id')}",
                    "cited_by": h.get("citedByCount", 0),
                    "known_tools_mentioned": "; ".join(known),
                    "lead_status": "known_tool" if known else "new_lead",
                    "abstract": abstract[:600],
                })
                row["function_codes"].add(code)
            time.sleep(1)
    for r in rows.values():
        r["function_codes"] = "; ".join(sorted(r["function_codes"]))
    return list(rows.values())


def sweep_hf(cfg: dict, match) -> list[dict]:
    hf = cfg["huggingface"]
    rows: dict[str, dict] = {}

    def add(m: dict, why: str):
        mid = m["id"]
        r = rows.setdefault(mid, {
            "source": "huggingface", "function_codes": "5.1", "title": mid,
            "year": (m.get("createdAt") or "")[:4], "venue": m.get("pipeline_tag", ""),
            "url": f"https://huggingface.co/{mid}", "cited_by": m.get("downloads", 0),
            "known_tools_mentioned": "; ".join(match(mid.replace("/", " ").replace("-", " "))),
            "lead_status": "", "abstract": "", "_why": set()})
        r["_why"].add(why)

    for pipe in hf["pipelines"]:
        for lang in hf["languages"]:
            params = urllib.parse.urlencode(
                {"pipeline_tag": pipe, "filter": lang, "sort": "downloads", "limit": 15})
            for m in get_json(f"{HF}?{params}"):
                if m.get("downloads", 0) >= 100:
                    add(m, f"{pipe}:{lang}")
            time.sleep(0.3)
        print(f"[hf] {pipe}: {len(rows)} models so far")
    for term in hf["medical_search"]:
        params = urllib.parse.urlencode(
            {"search": term, "pipeline_tag": "text-generation", "sort": "downloads", "limit": 50})
        for m in get_json(f"{HF}?{params}"):
            if m.get("downloads", 0) >= 500:
                add(m, f"medical:{term}")
    for r in rows.values():
        r["abstract"] = "matched: " + ", ".join(sorted(r.pop("_why")))
        r["lead_status"] = "known_tool" if r["known_tools_mentioned"] else "new_lead"
    return list(rows.values())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", type=int, default=2019)
    ap.add_argument("--per-query", type=int, default=50)
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--skip-hf", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((HERE / "queries.json").read_text())
    match = known_matcher(json.loads((HERE / "known_tools.json").read_text()))
    leads = sweep_epmc(cfg, args.since, args.per_query, match)
    if not args.skip_hf:
        leads += sweep_hf(cfg, match)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    path = args.out / f"leads_{stamp}.csv"
    cols = ["source", "function_codes", "lead_status", "title", "year", "venue", "url",
            "cited_by", "known_tools_mentioned", "abstract"]
    leads.sort(key=lambda r: (r["source"], r["function_codes"]))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(leads)
    new = sum(r["lead_status"] == "new_lead" for r in leads)
    print(f"wrote {len(leads)} leads ({new} new, {len(leads) - new} mention known tools) to {path}")


if __name__ == "__main__":
    main()
