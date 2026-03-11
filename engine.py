"""
HSS Truss Analysis & CISC S16 / LSD Design Engine
Supports: Warren, Pratt, Howe truss types.
Analysis: Direct stiffness method (2D truss).
Design:   CISC S16-style LSD workflow using ASTM A500 Grade C HSS.
"""

import math
import numpy as np
from sections import SECTIONS, SECTIONS_BY_AREA, FY, FU, E as E_STEEL

PHI_T  = 0.90
PHI_C  = 0.90
K_CHORD = 0.65
K_WEB   = 0.75
KL_R_MAX = 200
LAMBDA_R  = 1.40 * math.sqrt(E_STEEL / FY)

TRUSS_TYPES = ["Warren w/ Verticals", "Pratt", "Howe"]


def recommended_depth(span_ft):
    d_in = round((span_ft / 12.0) * 12 / 6) * 6
    return max(24.0, d_in) / 12.0


def recommended_panels(span_ft):
    n = max(4, round(span_ft / 5.0))
    return n if n % 2 == 0 else n + 1


def build_geometry(span_ft, depth_ft, n_panels):
    n = n_panels
    a = span_ft / n
    d = depth_ft
    nodes = []
    for k in range(n + 1):
        nodes.append([k * a, 0.0])
    for k in range(n + 1):
        nodes.append([k * a, d])
    members = []
    for k in range(n):
        members.append({"i": k, "j": k + 1, "type": "BOTTOM_CHORD"})
    for k in range(n):
        members.append({"i": n + 1 + k, "j": n + 2 + k, "type": "TOP_CHORD"})
    for k in range(n + 1):
        members.append({"i": k, "j": n + 1 + k, "type": "VERTICAL"})
    for k in range(n):
        if k % 2 == 0:
            members.append({"i": n + 1 + k, "j": k + 1, "type": "DIAGONAL"})
        else:
            members.append({"i": k, "j": n + 2 + k, "type": "DIAGONAL"})
    return nodes, members


def support_nodes_for_type(truss_type, n_panels):
    return (0, n_panels)


def display_support_nodes_for_type(truss_type, n_panels):
    if truss_type == "Warren w/ Verticals":
        return (n_panels + 1, 2 * n_panels + 1)
    return (0, n_panels)


def build_geometry_pratt(span_ft, depth_ft, n_panels):
    """Pratt truss: verticals + diagonals sloping toward midspan (tension diagonals)."""
    n = n_panels
    a = span_ft / n
    d = depth_ft
    nodes = []
    for k in range(n + 1):
        nodes.append([k * a, 0.0])
    for k in range(n + 1):
        nodes.append([k * a, d])
    members = []
    for k in range(n):
        members.append({"i": k, "j": k + 1, "type": "BOTTOM_CHORD"})
    for k in range(n):
        members.append({"i": n + 1 + k, "j": n + 2 + k, "type": "TOP_CHORD"})
    for k in range(n + 1):
        members.append({"i": k, "j": n + 1 + k, "type": "VERTICAL"})
    # Pratt: diagonals slope from top panel point toward midspan on bottom chord
    for k in range(n):
        if k < n // 2:
            members.append({"i": n + 1 + k + 1, "j": k, "type": "DIAGONAL"})
        else:
            members.append({"i": n + 1 + k, "j": k + 1, "type": "DIAGONAL"})
    return nodes, members


def build_geometry_howe(span_ft, depth_ft, n_panels):
    """Howe truss: verticals + diagonals sloping away from midspan (compression diagonals)."""
    n = n_panels
    a = span_ft / n
    d = depth_ft
    nodes = []
    for k in range(n + 1):
        nodes.append([k * a, 0.0])
    for k in range(n + 1):
        nodes.append([k * a, d])
    members = []
    for k in range(n):
        members.append({"i": k, "j": k + 1, "type": "BOTTOM_CHORD"})
    for k in range(n):
        members.append({"i": n + 1 + k, "j": n + 2 + k, "type": "TOP_CHORD"})
    for k in range(n + 1):
        members.append({"i": k, "j": n + 1 + k, "type": "VERTICAL"})
    # Howe: diagonals slope from bottom panel point toward midspan on top chord
    for k in range(n):
        if k < n // 2:
            members.append({"i": k + 1, "j": n + 1 + k, "type": "DIAGONAL"})
        else:
            members.append({"i": k, "j": n + 2 + k, "type": "DIAGONAL"})
    return nodes, members


def build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels):
    """Dispatch to the correct geometry builder based on truss type string."""
    if truss_type == "Pratt":
        return build_geometry_pratt(span_ft, depth_ft, n_panels)
    elif truss_type == "Howe":
        return build_geometry_howe(span_ft, depth_ft, n_panels)
    else:  # "Warren w/ Verticals" or default
        return build_geometry(span_ft, depth_ft, n_panels)


def factored_load(dl_kpf, ll_kpf):
    """NBCC/CISC-style gravity combo: max of 1.25D+1.5L, 1.4D."""
    return max(1.25 * dl_kpf + 1.5 * ll_kpf, 1.4 * dl_kpf)


def member_length(nodes, mem):
    xi, yi = nodes[mem["i"]]
    xj, yj = nodes[mem["j"]]
    return math.sqrt((xj - xi) ** 2 + (yj - yi) ** 2)


def distribute_udl(nodes, n_panels, w_kpf):
    n = n_panels
    a = nodes[n][0] / n
    loads = {}
    for k in range(n + 1):
        nid = n + 1 + k
        P = w_kpf * a / 2.0 if (k == 0 or k == n) else w_kpf * a
        loads[nid] = [0.0, -P]
    return loads


def analyze(nodes, members, n_panels, loads, areas_in2=None, support_nodes=None):
    n_nodes = len(nodes)
    n_dof   = 2 * n_nodes
    if areas_in2 is None:
        areas_in2 = [1.0] * len(members)
    nxy = [[x * 12.0, y * 12.0] for x, y in nodes]
    import numpy as np
    K = np.zeros((n_dof, n_dof))
    for mem, A in zip(members, areas_in2):
        i, j = mem["i"], mem["j"]
        xi, yi = nxy[i]; xj, yj = nxy[j]
        dx, dy = xj - xi, yj - yi
        L  = math.sqrt(dx * dx + dy * dy)
        cx, cy = dx / L, dy / L
        k = A * E_STEEL / L
        dofs = [2*i, 2*i+1, 2*j, 2*j+1]
        km = k * np.array([
            [ cx*cx,  cx*cy, -cx*cx, -cx*cy],
            [ cx*cy,  cy*cy, -cx*cy, -cy*cy],
            [-cx*cx, -cx*cy,  cx*cx,  cx*cy],
            [-cx*cy, -cy*cy,  cx*cy,  cy*cy],
        ])
        for a_idx in range(4):
            for b_idx in range(4):
                K[dofs[a_idx], dofs[b_idx]] += km[a_idx, b_idx]
    F = np.zeros(n_dof)
    for nid, (fx, fy) in loads.items():
        F[2*nid] += fx; F[2*nid + 1] += fy
    n = n_panels
    left_support, right_support = support_nodes or (0, n)
    # Pin at left support, roller-y at right support
    fixed_dofs = [2 * left_support, 2 * left_support + 1, 2 * right_support + 1]
    free_dofs  = [d for d in range(n_dof) if d not in fixed_dofs]
    K_ff = K[np.ix_(free_dofs, free_dofs)]
    u_f  = np.linalg.solve(K_ff, F[free_dofs])
    u = np.zeros(n_dof)
    for idx, dof in enumerate(free_dofs):
        u[dof] = u_f[idx]
    forces_kips = []
    for mem, A in zip(members, areas_in2):
        i, j = mem["i"], mem["j"]
        xi, yi = nxy[i]; xj, yj = nxy[j]
        dx, dy = xj - xi, yj - yi
        L  = math.sqrt(dx * dx + dy * dy)
        cx, cy = dx / L, dy / L
        k = A * E_STEEL / L
        F_mem = k * (cx * (u[2*j] - u[2*i]) + cy * (u[2*j+1] - u[2*i+1]))
        forces_kips.append(F_mem)
        mem["force"] = F_mem
        mem["length_ft"] = L / 12.0
    R_vec = K @ u
    reactions_kips = {
        left_support: [R_vec[2 * left_support], R_vec[2 * left_support + 1]],
        right_support: [0.0, R_vec[2 * right_support + 1]],
    }
    disps_in = [[u[2*k], u[2*k+1]] for k in range(n_nodes)]
    return forces_kips, disps_in, reactions_kips


def compression_capacity(sec, KL_in):
    r = sec["r"]; A = sec["A"]
    KLr = KL_in / r
    if KLr > KL_R_MAX:
        return 0.0
    Fe  = math.pi**2 * E_STEEL / KLr**2
    limit = 4.71 * math.sqrt(E_STEEL / FY)
    Fcr = (0.658 ** (FY / Fe)) * FY if KLr <= limit else 0.877 * Fe
    return PHI_C * Fcr * A


def tension_capacity(sec):
    return PHI_T * FY * sec["A"]


def local_buckling_ratio(sec):
    bt = (sec["B"] - 3.0 * sec["t"]) / sec["t"]
    return bt, LAMBDA_R


def select_section(demand_kips, length_ft, role):
    if demand_kips == 0.0:
        return SECTIONS_BY_AREA[0]
    if role == "TENSION":
        for sec in SECTIONS_BY_AREA:
            if tension_capacity(sec) >= demand_kips:
                return sec
        return SECTIONS_BY_AREA[-1]
    K_fac = K_CHORD if role in ("TOP_CHORD", "BOTTOM_CHORD") else K_WEB
    KL_in = K_fac * length_ft * 12.0
    for sec in SECTIONS_BY_AREA:
        bt, limit = local_buckling_ratio(sec)
        if bt > limit:
            continue
        if compression_capacity(sec, KL_in) >= demand_kips:
            return sec
    return SECTIONS_BY_AREA[-1]


def design_members(members, nodes, n_panels, w_kpf,
                   override_sections=None, defl_limit=360, truss_type="Warren w/ Verticals"):
    """Design all members.  override_sections = {'TOP_CHORD': sec_dict, ...}."""
    override_sections = override_sections or {}
    support_nodes = support_nodes_for_type(truss_type, n_panels)
    display_support_nodes = display_support_nodes_for_type(truss_type, n_panels)
    loads = distribute_udl(nodes, n_panels, w_kpf)
    forces1, _, _ = analyze(nodes, members, n_panels, loads, support_nodes=support_nodes)
    for mem, F_mem in zip(members, forces1):
        mtype = mem["type"]
        demand = abs(F_mem)
        if mtype == "BOTTOM_CHORD":
            role = "TENSION"
        elif F_mem >= 0:
            role = "TENSION"
        else:
            role = mtype if mtype in ("TOP_CHORD", "DIAGONAL", "VERTICAL") else "COMPRESSION"
        # Apply override if provided
        if mtype in override_sections and override_sections[mtype]:
            mem["section"] = override_sections[mtype]
        else:
            mem["section"] = select_section(demand, mem["length_ft"], role)
        mem["role"] = role

    # Use one continuous section for each chord group.
    # This matches normal truss detailing and the desired continuous visualisation.
    for chord_type in ("TOP_CHORD", "BOTTOM_CHORD"):
        chord_members = [m for m in members if m["type"] == chord_type]
        if chord_members:
            governing_sec = max(chord_members, key=lambda m: m["section"]["A"])["section"]
            for m in chord_members:
                m["section"] = governing_sec

    # Use one common web section, except end webs which match the bottom chord.
    web_members = [m for m in members if m["type"] in ("DIAGONAL", "VERTICAL")]
    if web_members:
        span_ft = nodes[n_panels][0]
        panel_ft = span_ft / max(n_panels, 1)
        bottom_sec = next((m["section"] for m in members if m["type"] == "BOTTOM_CHORD"), None)
        end_webs = []
        interior_webs = []
        for m in web_members:
            xi, _ = nodes[m["i"]]
            xj, _ = nodes[m["j"]]
            midx = 0.5 * (xi + xj)
            if midx <= panel_ft * 0.75 or midx >= span_ft - panel_ft * 0.75:
                end_webs.append(m)
            else:
                interior_webs.append(m)
        governing_web = None
        if interior_webs:
            governing_web = max(interior_webs, key=lambda m: m["section"]["A"])["section"]
        elif web_members:
            governing_web = max(web_members, key=lambda m: m["section"]["A"])["section"]
        if governing_web is not None:
            for m in interior_webs:
                m["section"] = governing_web
        if bottom_sec is not None:
            for m in end_webs:
                m["section"] = bottom_sec

    actual_areas = [m["section"]["A"] for m in members]
    forces2, disps_in, reactions = analyze(nodes, members, n_panels, loads, actual_areas,
                                           support_nodes=support_nodes)
    n = n_panels
    for mem, F_mem in zip(members, forces2):
        mem["force"] = F_mem
        sec   = mem["section"]
        mtype = mem["type"]
        L_ft  = mem["length_ft"]
        if mtype == "BOTTOM_CHORD" or F_mem >= 0:
            phi_Pn = tension_capacity(sec)
            mem["role"] = "TENSION"
        else:
            K_fac  = K_CHORD if mtype in ("TOP_CHORD", "BOTTOM_CHORD") else K_WEB
            phi_Pn = compression_capacity(sec, K_fac * L_ft * 12.0)
            mem["role"] = "COMPRESSION"
        mem["capacity"] = phi_Pn
        mem["DCR"]      = abs(F_mem) / phi_Pn if phi_Pn > 0 else 999.0
        bt, lim         = local_buckling_ratio(sec)
        mem["bt"] = bt; mem["bt_limit"] = lim; mem["slender"] = bt > lim

    max_defl_in = max(abs(d[1]) for d in disps_in)
    span_in     = nodes[n][0] * 12.0
    defl_ratio  = span_in / max_defl_in if max_defl_in > 0 else 9999
    defl_ok     = defl_ratio >= defl_limit

    def governing(types):
        f = [m for m in members if m["type"] in types]
        return max(f, key=lambda m: m["section"]["A"])["section"] if f else None

    # Weight breakdown by member type
    weight_breakdown = {}
    for mtype in ("TOP_CHORD", "BOTTOM_CHORD", "DIAGONAL", "VERTICAL"):
        grp = [m for m in members if m["type"] == mtype]
        weight_breakdown[mtype] = sum(m["section"]["wt"] * m["length_ft"] for m in grp)

    summary = {
        "top_chord":        governing(["TOP_CHORD"]),
        "bottom_chord":     governing(["BOTTOM_CHORD"]),
        "web":              governing(["DIAGONAL", "VERTICAL"]),
        "total_weight_lbs": sum(m["section"]["wt"] * m["length_ft"] for m in members),
        "weight_breakdown": weight_breakdown,
        "max_defl_in":      max_defl_in,
        "defl_ratio":       defl_ratio,
        "defl_limit":       defl_limit,
        "defl_ok":          defl_ok,
        "reactions":        reactions,
        "support_nodes":    support_nodes,
        "display_support_nodes": display_support_nodes,
        "disps_in":         disps_in,
        "loads":            loads,
    }
    return members, summary
