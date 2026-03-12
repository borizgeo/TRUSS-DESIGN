"""Load calculation and combination module for HSS Truss Designer.

Supports individual load types (Dead, Live, Roof Live, Snow, Wind, Seismic)
and standard load combinations per ASCE 7 (LRFD), ASCE 7 (ASD), and
NBCC / CISC (LSD).
"""

# ---------------------------------------------------------------------------
# Load combination definitions
# ---------------------------------------------------------------------------
# Each combo is a dict mapping load-type keys to their factor.
# Keys: D, L, Lr, S, W, E
# Sign convention: positive = downward gravity; Wind/Seismic factors can be
# negative (uplift) but users enter magnitude — the combo logic handles signs.
# ---------------------------------------------------------------------------

ASCE7_LRFD_COMBOS = [
    {'label': '1.4D',                       'factors': {'D': 1.4}},
    {'label': '1.2D + 1.6L + 0.5Lr',       'factors': {'D': 1.2, 'L': 1.6, 'Lr': 0.5}},
    {'label': '1.2D + 1.6L + 0.5S',        'factors': {'D': 1.2, 'L': 1.6, 'S': 0.5}},
    {'label': '1.2D + 1.6S + L',           'factors': {'D': 1.2, 'L': 1.0, 'S': 1.6}},
    {'label': '1.2D + 1.6S + 0.5W',        'factors': {'D': 1.2, 'S': 1.6, 'W': 0.5}},
    {'label': '1.2D + 1.6Lr + L',          'factors': {'D': 1.2, 'L': 1.0, 'Lr': 1.6}},
    {'label': '1.2D + 1.6Lr + 0.5W',       'factors': {'D': 1.2, 'Lr': 1.6, 'W': 0.5}},
    {'label': '1.2D + W + L + 0.5S',       'factors': {'D': 1.2, 'L': 1.0, 'W': 1.0, 'S': 0.5}},
    {'label': '1.2D + W + L + 0.5Lr',      'factors': {'D': 1.2, 'L': 1.0, 'W': 1.0, 'Lr': 0.5}},
    {'label': '1.2D + E + L + 0.2S',       'factors': {'D': 1.2, 'L': 1.0, 'E': 1.0, 'S': 0.2}},
    {'label': '0.9D + W',                  'factors': {'D': 0.9, 'W': 1.0}},
    {'label': '0.9D + E',                  'factors': {'D': 0.9, 'E': 1.0}},
]

ASCE7_ASD_COMBOS = [
    {'label': 'D',                          'factors': {'D': 1.0}},
    {'label': 'D + L',                      'factors': {'D': 1.0, 'L': 1.0}},
    {'label': 'D + Lr',                     'factors': {'D': 1.0, 'Lr': 1.0}},
    {'label': 'D + S',                      'factors': {'D': 1.0, 'S': 1.0}},
    {'label': 'D + 0.75L + 0.75Lr',        'factors': {'D': 1.0, 'L': 0.75, 'Lr': 0.75}},
    {'label': 'D + 0.75L + 0.75S',         'factors': {'D': 1.0, 'L': 0.75, 'S': 0.75}},
    {'label': 'D + 0.6W',                  'factors': {'D': 1.0, 'W': 0.6}},
    {'label': 'D + 0.75L + 0.75(0.6W) + 0.75S', 'factors': {'D': 1.0, 'L': 0.75, 'W': 0.45, 'S': 0.75}},
    {'label': 'D + 0.75L + 0.75(0.6W) + 0.75Lr', 'factors': {'D': 1.0, 'L': 0.75, 'W': 0.45, 'Lr': 0.75}},
    {'label': '0.6D + 0.6W',               'factors': {'D': 0.6, 'W': 0.6}},
    {'label': 'D + 0.7E',                  'factors': {'D': 1.0, 'E': 0.7}},
    {'label': 'D + 0.75L + 0.75(0.7E) + 0.75S', 'factors': {'D': 1.0, 'L': 0.75, 'E': 0.525, 'S': 0.75}},
    {'label': '0.6D + 0.7E',               'factors': {'D': 0.6, 'E': 0.7}},
]

NBCC_LSD_COMBOS = [
    {'label': '1.4D',                       'factors': {'D': 1.4}},
    {'label': '1.25D + 1.5L',              'factors': {'D': 1.25, 'L': 1.5}},
    {'label': '1.25D + 1.5S',              'factors': {'D': 1.25, 'S': 1.5}},
    {'label': '1.25D + 1.5L + 0.5S',       'factors': {'D': 1.25, 'L': 1.5, 'S': 0.5}},
    {'label': '1.25D + 1.5S + 0.5L',       'factors': {'D': 1.25, 'L': 0.5, 'S': 1.5}},
    {'label': '1.25D + 1.4W',              'factors': {'D': 1.25, 'W': 1.4}},
    {'label': '1.25D + 1.4W + 0.5L',       'factors': {'D': 1.25, 'W': 1.4, 'L': 0.5}},
    {'label': '1.25D + 1.4W + 0.5S',       'factors': {'D': 1.25, 'W': 1.4, 'S': 0.5}},
    {'label': '1.0D + 1.0E',               'factors': {'D': 1.0, 'E': 1.0}},
    {'label': '1.0D + 1.0E + 0.5L',        'factors': {'D': 1.0, 'E': 1.0, 'L': 0.5}},
    {'label': '1.0D + 1.0E + 0.25S',       'factors': {'D': 1.0, 'E': 1.0, 'S': 0.25}},
    {'label': '0.9D + 1.4W',               'factors': {'D': 0.9, 'W': 1.4}},
    {'label': '0.9D + 1.0E',               'factors': {'D': 0.9, 'E': 1.0}},
]

# Registry mapping user-facing name → combo list
COMBO_SETS = {
    'ASCE 7 LRFD': ASCE7_LRFD_COMBOS,
    'ASCE 7 ASD':  ASCE7_ASD_COMBOS,
    'NBCC / CISC LSD': NBCC_LSD_COMBOS,
}

COMBO_SET_NAMES = list(COMBO_SETS.keys())

# Load-type labels in display order
LOAD_TYPES = [
    ('D',  'Dead Load (kip/ft)'),
    ('L',  'Live Load (kip/ft)'),
    ('Lr', 'Roof Live Load (kip/ft)'),
    ('S',  'Snow Load (kip/ft)'),
    ('W',  'Wind Load (kip/ft)'),
    ('E',  'Seismic Load (kip/ft)'),
]


def compute_factored_load(loads, combo_set_name):
    """Return (governing wu_kpf, governing combo label, all combo results).

    Parameters
    ----------
    loads : dict
        Mapping of load-type key → service-level magnitude in kip/ft.
        Example: {'D': 0.90, 'L': 0.60, 'S': 0.30, 'W': 0.0, 'E': 0.0, 'Lr': 0.0}
    combo_set_name : str
        One of COMBO_SET_NAMES, e.g. 'ASCE 7 LRFD'.

    Returns
    -------
    wu_kpf : float
        The governing (maximum) factored load.
    governing_label : str
        Label of the governing combination.
    combo_results : list[dict]
        Each entry: {'label': str, 'wu': float}.
    """
    combos = COMBO_SETS[combo_set_name]
    results = []
    for combo in combos:
        wu = sum(factor * loads.get(key, 0.0)
                 for key, factor in combo['factors'].items())
        results.append({'label': combo['label'], 'wu': wu})

    # Governing = maximum factored load (gravity-dominated for truss design)
    governing = max(results, key=lambda r: r['wu'])
    return governing['wu'], governing['label'], results


def factored_load_legacy(dl_kpf, ll_kpf):
    """Original NBCC/CISC two-load shortcut kept for backward compatibility."""
    return max(1.25 * dl_kpf + 1.5 * ll_kpf, 1.4 * dl_kpf)
