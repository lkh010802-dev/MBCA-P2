#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Migrate V1.2 14-field expected JSONL to V1.3 16-field policy.
Default adds target=null/scope=null; explicit overrides cover policy-changed legacy cases.
"""
import argparse, json
from pathlib import Path

OVERRIDES = {
    # V1.2 Blind100 #6 was previously treated as a future start location.
    # Backend FINAL removes the analogous "X에 갈 건데 추천" example from start_location
    # and V1.3 treats X as the requested activity target.
    ("blind100", 6): {
        "start_location_text": None,
        "target_location_text": "광화문",
        "target_location_scope": "area",
    },
}

def migrate_expected(expected, dataset, test_id):
    out = {}
    for key, value in expected.items():
        out[key] = value
        if key == "start_location_text":
            out["target_location_text"] = None
            out["target_location_scope"] = None
    out.update(OVERRIDES.get((dataset, test_id), {}))
    return out

def migrate_file(src, dst, dataset):
    rows=[]
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        row=json.loads(line)
        row["expected"] = migrate_expected(row["expected"], dataset, row["test_id"])
        rows.append(row)
    Path(dst).parent.mkdir(parents=True,exist_ok=True)
    Path(dst).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")

if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--dataset",required=True)
    a=ap.parse_args(); migrate_file(a.src,a.dst,a.dataset)
