"""Previous HSS Truss Designs Database (JSON-backed)."""

import json
import os
from datetime import datetime

DEFAULT_DB_FILE = os.path.join(os.path.dirname(__file__), "designs_database.json")
DB_FILE = os.environ.get("HSS_TRUSS_DB_FILE", DEFAULT_DB_FILE)


def _load():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r") as f:
        return json.load(f).get("designs", [])


def _save(designs):
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with open(DB_FILE, "w") as f:
        json.dump({"designs": designs}, f, indent=2)


def save_design(span_ft, load_kpf, depth_ft, n_panels, top_chord, bottom_chord,
                web, total_weight_lbs, max_defl_in, defl_ratio, notes="",
                project_number="", spacing_ft=0.0):
    designs = _load()
    entry = {
        "id":               len(designs) + 1,
        "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "project_number":   project_number,
        "spacing_ft":       round(spacing_ft, 2),
        "span_ft":          round(span_ft, 2),
        "load_kpf":         round(load_kpf, 3),
        "depth_ft":         round(depth_ft, 2),
        "n_panels":         n_panels,
        "top_chord":        top_chord,
        "bottom_chord":     bottom_chord,
        "web":              web,
        "total_weight_lbs": round(total_weight_lbs, 0),
        "max_defl_in":      round(max_defl_in, 4),
        "defl_ratio":       round(defl_ratio, 0),
        "notes":            notes,
    }
    designs.append(entry)
    _save(designs)
    return entry


def load_all():
    return _load()


def delete_design(design_id):
    designs = _load()
    designs = [d for d in designs if d.get("id") != design_id]
    _save(designs)


def find_similar(span_ft, load_kpf, tol_span=0.10, tol_load=0.15):
    """Return designs within tol_span% of span and tol_load% of load."""
    designs = _load()
    matches = []
    for d in designs:
        ds = d["span_ft"]; dl = d["load_kpf"]
        if abs(ds - span_ft) / max(span_ft, 1) <= tol_span and            abs(dl - load_kpf) / max(load_kpf, 0.001) <= tol_load:
            matches.append(d)
    return matches


def add_manual_design(span_ft, load_kpf, depth_ft, n_panels,
                       top_chord, bottom_chord, web, notes=""):
    """Add a previously known design (manually entered, no analysis)."""
    designs = _load()
    entry = {
        "id":               len(designs) + 1,
        "date":             datetime.now().strftime("%Y-%m-%d %H:%M"),
        "span_ft":          round(span_ft, 2),
        "load_kpf":         round(load_kpf, 3),
        "depth_ft":         round(depth_ft, 2),
        "n_panels":         n_panels,
        "top_chord":        top_chord,
        "bottom_chord":     bottom_chord,
        "web":              web,
        "total_weight_lbs": 0,
        "max_defl_in":      0,
        "defl_ratio":       0,
        "notes":            notes + " [Manual entry]",
    }
    designs.append(entry)
    _save(designs)
    return entry
