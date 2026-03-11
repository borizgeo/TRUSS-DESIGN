"""
HSS Truss Designer  -  Main Application  (v2.0)
================================================
Features:
  • Warren / Pratt / Howe truss types
    • LSD: separate Dead + Live load inputs  (1.25D + 1.5L governing)
  • Deflection limit selector  (L/180 → L/600)
  • Section override per member group  (TC / BC / Diagonal / Vertical)
  • Optimize (minimum weight) button
  • Export member schedule to CSV
  • Full-text Design Report tab  (with copy & save)
  • Steel cost estimate  ($1.25/lb installed default)
  • Weight breakdown by member type
CISC S16-style HSS design workflow, ASTM A500 Grade-C sections.
Run:  py -3 main.py
"""

import sys, os, copy, math, csv, io
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from sections import SECTIONS, SECTIONS_BY_AREA
from engine import (
    build_geometry_for_type, TRUSS_TYPES,
    recommended_depth, recommended_panels,
    distribute_udl, design_members, member_length,
    tension_capacity, compression_capacity, local_buckling_ratio,
    factored_load, K_CHORD, K_WEB,
)
import database as db

# ── colour palette ─────────────────────────────────────────────────────────
CLR_BG      = '#1a1f2e'
CLR_PANEL   = '#222840'
CLR_PANEL2  = '#1e2438'
CLR_ACCENT  = '#4a9eff'
CLR_ACCENT2 = '#2979d0'
CLR_TEXT    = '#dce6f0'
CLR_MUTED   = '#7a8baa'
CLR_ENTRY   = '#2a3250'
CLR_BTN     = '#2e3a5a'
CLR_BTN2    = '#384668'
CLR_SEP     = '#2e3a5a'
CLR_GREEN   = '#3ddc84'
CLR_YELLOW  = '#ffd740'
CLR_RED     = '#ff5252'
CLR_ORANGE  = '#ff9800'
CLR_TEAL    = '#26c6da'
CLR_PURPLE  = '#ce93d8'

STEEL_COST_PER_LB = 1.25   # $/lb installed estimate
RUN_LOG_FILE = os.path.join(os.path.dirname(__file__), 'run.log')


def _launcher_log(message):
    try:
        with open(RUN_LOG_FILE, 'a', encoding='utf-8') as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def _display_panels_from_internal(n_panels, truss_type='Warren w/ Verticals'):
    """Convert internal geometry count to the user-facing panel count."""
    n_panels = int(n_panels)
    if truss_type == 'Warren w/ Verticals':
        return max(2, n_panels // 2)
    return max(4, n_panels)


def _internal_panels_from_display(display_panels, truss_type='Warren w/ Verticals'):
    """Convert user-facing panel count to the internal geometry count."""
    display_panels = int(display_panels)
    if truss_type == 'Warren w/ Verticals':
        return max(4, display_panels * 2)
    return max(4, display_panels)



# ═══════════════════════════════════════════════════════════════════════════
#  DRAWING HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _blend_hex(c1, c2, t):
    t = max(0.0, min(1.0, t))
    c1 = c1.lstrip('#'); c2 = c2.lstrip('#')
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return '#%02x%02x%02x' % (r, g, b)


def _force_shade(force, role, max_force):
    mag = abs(force)
    ratio = 0.0 if max_force <= 1e-9 else min(1.0, mag / max_force)
    if role == 'TENSION':
        return _blend_hex('#dce9ff', '#2f6fff', 0.25 + 0.75 * ratio)
    return _blend_hex('#ffe0d6', '#d9481f', 0.25 + 0.75 * ratio)

def _member_rect(ax, xi, yi, xj, yj, B_ft, fc, ec='#000000', lw=0.6, alpha=1.0, zo=30):
    dx, dy = xj - xi, yj - yi
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-9:
        return
    hx, hy = -dy / L * B_ft / 2, dx / L * B_ft / 2
    pts = [(xi + hx, yi + hy), (xi - hx, yi - hy),
           (xj - hx, yj - hy), (xj + hx, yj + hy)]
    # Draw only the outer outline (no filled face)
    ax.add_patch(plt.Polygon(pts, closed=True, fc='none', ec=ec, lw=lw, alpha=alpha, zorder=zo))


def _member_inset_rect(ax, xi, yi, xj, yj, outer_B_ft, inset_ft, fc, alpha=1.0, zo=3):
    # Inset rendering removed for outline-only mode (no-op)
    return


def _member_hidden_edge(ax, xi, yi, xj, yj, outer_B_ft, inset_ft,
                        color='#ffffff', lw=0.6, zo=40,
                        face_y_i=None, face_y_j=None, alpha=0.95):
    dx, dy = xj - xi, yj - yi
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-9:
        return
    nx, ny = -dy / L, dx / L
    off = max(outer_B_ft * 0.5 - inset_ft, outer_B_ft * 0.10)

    def _intersect_y(a, b, yface):
        x1, y1 = a; x2, y2 = b
        if abs(y2 - y1) < 1e-12:
            return (x1, yface)
        t = (yface - y1) / (y2 - y1)
        return (x1 + t * (x2 - x1), yface)

    for sign in (1.0, -1.0):
        p1 = (xi + sign * nx * off, yi + sign * ny * off)
        p2 = (xj + sign * nx * off, yj + sign * ny * off)

        if face_y_i is not None:
            p1 = _intersect_y(p1, p2, face_y_i)
        if face_y_j is not None:
            p2 = _intersect_y(p1, p2, face_y_j)

        ax.plot([p1[0], p2[0]], [p1[1], p2[1]],
                color=color, lw=lw, alpha=alpha,
                linestyle=(0, (2.5, 2.5)), dash_capstyle='butt',
                zorder=zo)


def _member_center_line(ax, xi, yi, xj, yj, color='#b82b2b', lw=0.9, zo=50, alpha=1.0):
    """Draw a visible dashed centerline along the member."""
    try:
        ax.plot([xi, xj], [yi, yj], color=color, lw=lw,
                linestyle=(0, (6.0, 3.0)), dash_capstyle='butt',
                solid_capstyle='butt', zorder=zo, alpha=alpha)
    except Exception:
        pass


def _member_face_rect(ax, xi, yi, xj, yj, B_ft, fc, face_y_i=None, face_y_j=None,
                      ec='#000000', lw=0.6, alpha=1.0, zo=30):
    dx, dy = xj - xi, yj - yi
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-9:
        return
    hx, hy = -dy / L * B_ft / 2, dx / L * B_ft / 2

    def _intersect_y(p1, p2, yface):
        x1, y1 = p1; x2, y2 = p2
        if abs(y2 - y1) < 1e-12:
            return (x1, yface)
        t = (yface - y1) / (y2 - y1)
        return (x1 + t * (x2 - x1), yface)

    i_plus = (xi + hx, yi + hy)
    i_minus = (xi - hx, yi - hy)
    j_plus = (xj + hx, yj + hy)
    j_minus = (xj - hx, yj - hy)

    if face_y_i is not None:
        i_plus = _intersect_y(i_plus, j_plus, face_y_i)
        i_minus = _intersect_y(i_minus, j_minus, face_y_i)
    if face_y_j is not None:
        j_plus = _intersect_y(i_plus, j_plus, face_y_j)
        j_minus = _intersect_y(i_minus, j_minus, face_y_j)

    pts = [i_plus, i_minus, j_minus, j_plus]
    # Draw only the outer outline (no filled face)
    ax.add_patch(plt.Polygon(pts, closed=True, fc='none', ec=ec, lw=lw, alpha=alpha, zorder=zo))


def _member_face_inset_rect(ax, xi, yi, xj, yj, outer_B_ft, inset_ft, fc,
                            face_y_i=None, face_y_j=None, alpha=1.0, zo=3):
    # Inset rendering removed for outline-only mode (no-op)
    return


def _intersect_point_to_yface(p1, p2, yface):
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    if abs(y2 - y1) < 1e-12:
        return (x1, yface, z1)
    t = (yface - y1) / (y2 - y1)
    return (x1 + t * (x2 - x1), yface, z1 + t * (z2 - z1))


def _member_prism_faces(xi, yi, xj, yj, B_ft, face_y_i=None, face_y_j=None):
    dx, dy = xj - xi, yj - yi
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-9:
        return []
    ux, uy = dx / L, dy / L
    # local square section axes
    wx, wy, wz = -uy, ux, 0.0
    vx, vy, vz = 0.0, 0.0, 1.0
    h = B_ft / 2.0

    def pt(x, y, su, sv):
        return (x + h * (su * wx + sv * vx),
                y + h * (su * wy + sv * vy),
                h * (su * wz + sv * vz))

    p0 = pt(xi, yi, -1, -1)
    p1 = pt(xi, yi,  1, -1)
    p2 = pt(xi, yi,  1,  1)
    p3 = pt(xi, yi, -1,  1)
    q0 = pt(xj, yj, -1, -1)
    q1 = pt(xj, yj,  1, -1)
    q2 = pt(xj, yj,  1,  1)
    q3 = pt(xj, yj, -1,  1)

    start_pts = [p0, p1, p2, p3]
    end_pts = [q0, q1, q2, q3]

    if face_y_i is not None:
        start_pts = [_intersect_point_to_yface(ps, pe, face_y_i) for ps, pe in zip(start_pts, end_pts)]
    if face_y_j is not None:
        end_pts = [_intersect_point_to_yface(ps, pe, face_y_j) for ps, pe in zip(start_pts, end_pts)]

    p0, p1, p2, p3 = start_pts
    q0, q1, q2, q3 = end_pts

    return [
        [p0, p1, p2, p3],
        [q0, q1, q2, q3],
        [p0, p1, q1, q0],
        [p1, p2, q2, q1],
        [p2, p3, q3, q2],
        [p3, p0, q0, q3],
    ]


def _add_member_prism(ax, xi, yi, xj, yj, B_ft, base_fc, shade_fc, alpha=1.0,
                      face_y_i=None, face_y_j=None):
    faces = _member_prism_faces(xi, yi, xj, yj, B_ft, face_y_i=face_y_i, face_y_j=face_y_j)
    if not faces:
        return
    # Use neutral face colors (no tension/compression tint) for all prism faces
    colors = [base_fc] * len(faces)
    poly = Poly3DCollection(faces, facecolors=colors, edgecolors='#ffffff', linewidths=0.12, alpha=alpha)
    ax.add_collection3d(poly)


def draw_truss_view(ax, nodes, members, n_panels, loads=None, title='HSS Truss',
                    support_nodes=None, total_weight_lbs=None, hide_verticals=False):
    ax.cla()
    fig = ax.get_figure()
    ax.set_facecolor('#f0f3f8')
    span  = nodes[n_panels][0]
    depth = nodes[n_panels + 1][1]
    n     = n_panels

    visible_members = [m for m in members if not (hide_verticals and m.get('type') == 'VERTICAL')]
    max_force = max((abs(m.get('force', 0.0)) for m in members), default=1.0)
    top_B_ft = max((m.get('section', {}).get('B', 2.0) / 12.0
                    for m in members if m.get('type') == 'TOP_CHORD'), default=2.0 / 12.0)
    bot_B_ft = max((m.get('section', {}).get('B', 2.0) / 12.0
                    for m in members if m.get('type') == 'BOTTOM_CHORD'), default=2.0 / 12.0)

    def _skip_for_display(mem):
        if hide_verticals and mem.get('type') == 'VERTICAL':
            return True
        # For Warren display with top-chord support symbols, hide the small end
        # bottom-chord stubs that belong to the hidden end verticals.
        if hide_verticals and mem.get('type') == 'BOTTOM_CHORD':
            if mem.get('i') == 0 or mem.get('j') == n:
                return True
        return False

    # ── Draw members using true HSS width in model units ────────────────
    for mem in members:
        if _skip_for_display(mem):
            continue
        xi, yi = nodes[mem['i']]
        xj, yj = nodes[mem['j']]
        sec    = mem.get('section') or {}
        B_in   = sec.get('B', 2.0)
        B_ft   = B_in / 12.0
        force  = mem.get('force', 0.0)
        role   = mem.get('role', 'TENSION')
        mtype  = mem.get('type', '')

        # Base colour by member type
        if mtype == 'TOP_CHORD':
            base_clr = '#2f3854'
        elif mtype == 'BOTTOM_CHORD':
            base_clr = '#39445f'
        elif mtype == 'VERTICAL':
            base_clr = '#556079'
        else:
            base_clr = '#4a546e'

        dx, dy = xj - xi, yj - yi
        L_mem = math.sqrt(dx * dx + dy * dy)
        if L_mem < 1e-9:
            continue
        gap = 0.0
        ux, uy = dx / L_mem, dy / L_mem
        xs, ys = xi + ux * gap, yi + uy * gap
        xe, ye = xj - ux * gap, yj - uy * gap

        face_y_i = None
        face_y_j = None
        if mtype in ('DIAGONAL', 'VERTICAL'):
            if yi > yj:
                face_y_i = yi - top_B_ft * 0.5
                face_y_j = yj + bot_B_ft * 0.5
            elif yi < yj:
                face_y_i = yi + bot_B_ft * 0.5
                face_y_j = yj - top_B_ft * 0.5

        border_ft = min(max(B_ft * 0.009, 0.0008), B_ft * 0.028)
        hidden_inset_ft = min(max(B_ft * 0.13, border_ft * 2.4), B_ft * 0.24)
        if mtype in ('DIAGONAL', 'VERTICAL'):
            _member_face_rect(ax, xs, ys, xe, ye, B_ft, '#24304d',
                              face_y_i=face_y_i, face_y_j=face_y_j,
                              ec='#000000', lw=0.6, zo=30)
            _member_face_inset_rect(ax, xs, ys, xe, ye, B_ft, border_ft, base_clr,
                                    face_y_i=face_y_i, face_y_j=face_y_j,
                                    alpha=1.0, zo=4)
        else:
            _member_rect(ax, xs, ys, xe, ye, B_ft, '#24304d', ec='#000000', lw=0.6, zo=30)
            _member_inset_rect(ax, xs, ys, xe, ye, B_ft, border_ft, base_clr, alpha=1.0, zo=4)
        # Inner force shading removed — draw members without tension/compression colours
        # (Previously used _force_shade to tint inner inset; intentionally skipped.)
        # Draw inner hidden edge (dashed)
        _member_hidden_edge(ax, xs, ys, xe, ye, B_ft, hidden_inset_ft,
                    color='#aeb8cd', lw=0.65, zo=35,
                            face_y_i=face_y_i, face_y_j=face_y_j, alpha=0.95)

        # Draw visible dashed centerline along the member
        _member_center_line(ax, xs, ys, xe, ye)

    # ── Joint markers ────────────────────────────────────────────────────
    visible_node_ids = set()
    for mem in members:
        if _skip_for_display(mem):
            continue
        visible_node_ids.add(mem['i'])
        visible_node_ids.add(mem['j'])
    # Joint markers removed for outline-only view

    # ── Support symbols ──────────────────────────────────────────────────
    h  = depth * 0.18
    left_support, right_support = support_nodes or (0, n)
    x0, y0 = nodes[left_support]
    ax.add_patch(plt.Polygon(
        [[x0, y0], [x0 - h, y0 - h * 1.4], [x0 + h, y0 - h * 1.4]],
        closed=True, fc='#26a65b', ec='#1a7d42', zorder=6))
    ax.plot([x0 - h * 1.1, x0 + h * 1.1],
            [y0 - h * 1.4, y0 - h * 1.4], color='#1a7d42', lw=2, zorder=6)
    ax.text(x0, y0 - h * 2.0, 'PIN', ha='center', fontsize=7,
            color='#26a65b', fontweight='bold')

    xr, yr = nodes[right_support]
    ax.add_patch(plt.Polygon(
        [[xr, yr], [xr - h, yr - h * 1.4], [xr + h, yr - h * 1.4]],
        closed=True, fc='#26a65b', ec='#1a7d42', zorder=6))
    ax.add_patch(plt.Circle((xr, yr - h * 1.4 - h * 0.6), h * 0.5,
                             fc='#26a65b', ec='#1a7d42', zorder=6))
    ax.text(xr, yr - h * 2.6, 'ROLLER', ha='center', fontsize=7,
            color='#26a65b', fontweight='bold')

    # ── Load arrows ──────────────────────────────────────────────────────
    if loads:
        max_p = max((abs(fy) for _, (_, fy) in loads.items()), default=1.0)
        arr_h = depth * 0.50
        top_xs = [nodes[n + 1 + k][0] for k in range(n + 1)]
        y_udl  = depth + arr_h * 0.15
        ax.plot([min(top_xs), max(top_xs)], [y_udl, y_udl],
                color='#c0392b', lw=2.5, zorder=7)
        for nid, (fx, fy) in loads.items():
            if abs(fy) < 0.001:
                continue
            x, y = nodes[nid]
            ln = arr_h * abs(fy) / max_p
            ax.annotate('', xy=(x, y), xytext=(x, y + ln),
                arrowprops=dict(arrowstyle='->', color='#c0392b',
                                lw=1.5, mutation_scale=12))

    # ── Dimension lines ──────────────────────────────────────────────────
    yd = -depth * 0.45
    ax.annotate('', xy=(span, yd), xytext=(0, yd),
                arrowprops=dict(arrowstyle='<->', color='#444455', lw=1.0))
    ax.text(span / 2, yd - depth * 0.10,
            'Span = %.2f ft  (%.0f in)' % (span, span * 12),
            ha='center', va='top', fontsize=8, color='#222233')
    xd = -span * 0.055
    ax.annotate('', xy=(xd, depth), xytext=(xd, 0),
                arrowprops=dict(arrowstyle='<->', color='#444455', lw=1.0))
    ax.text(xd - span * 0.005, depth / 2,
            'd=%.2f ft' % depth,
            ha='right', va='center', fontsize=8, color='#222233', rotation=90)
    if total_weight_lbs is not None:
        ax.text(0.015, 0.97,
                'Total Weight = %.0f lb  (%.1f plf)' % (total_weight_lbs, total_weight_lbs / max(span, 1e-9)),
                transform=ax.transAxes, ha='left', va='top', fontsize=8.5,
                color='#1f2a44', fontweight='bold',
                bbox=dict(fc='white', ec='#cdd4e5', alpha=0.92, pad=0.5))

    # ── Section size legend (line-width examples) ────────────────────────
    type_members = {}
    for mem in members:
        sec = mem.get('section')
        if sec is None: continue
        type_members.setdefault(mem['type'], []).append(mem)

    # Label one representative chord member and all visible web members.
    for mtype, mems in type_members.items():
        draw_mems = [m for m in mems if not _skip_for_display(m)]
        if not draw_mems:
            continue
        label_mems = draw_mems if mtype in ('DIAGONAL', 'VERTICAL') else [draw_mems[len(draw_mems) // 2]]
        for mem in label_mems:
            sec = mem.get('section')
            if sec is None:
                continue
            xi, yi = nodes[mem['i']]; xj, yj = nodes[mem['j']]
            mx, my = (xi + xj) / 2, (yi + yj) / 2
            ang = math.degrees(math.atan2(yj - yi, xj - xi))
            if ang > 90:
                ang -= 180
            if ang < -90:
                ang += 180
            ax.text(mx, my, sec['name'],
                    ha='center', va='center', fontsize=10.2,
                    color='white', fontweight='bold',
                    rotation=ang, rotation_mode='anchor', zorder=9,
                    bbox=dict(fc='#1e2438', ec='none', alpha=0.78, pad=0.95))

    # ── Axes formatting ──────────────────────────────────────────────────
    margin_x = span * 0.10
    ax.set_xlim(-margin_x, span + margin_x)
    ax.set_ylim(-depth * 0.80, depth + depth * 0.90)
    ax.set_xlabel('Length (ft)', fontsize=9)
    ax.set_ylabel('Height (ft)', fontsize=9)
    ax.set_title(title, fontsize=9, fontweight='bold', pad=6)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.08, linestyle='--')

    # Section-size legend using proxy lines
    sample_B = sorted(set(
        m.get('section', {}).get('B', 2.0) for m in visible_members if m.get('section')
    ))
    legend_lines = [
        plt.Line2D([0], [0], color='#1a66ff', lw=3, label='Tension'),
        plt.Line2D([0], [0], color='#e84118', lw=3, label='Compression'),
        plt.Line2D([0], [0], color='#26a65b', lw=8, label='Support'),
        plt.Line2D([0], [0], color='#c0392b', lw=2, label='Applied load (wu factored)'),
    ]
    if sample_B:
        legend_lines.insert(0, plt.Line2D([0], [0], color='#2c3e6b',
            lw=6,
            label='Member  (true-width from HSS B dimension)'))
    ax.legend(handles=legend_lines, fontsize=8, loc='upper right',
              framealpha=0.88, edgecolor='#cccccc')
    ax.set_aspect('equal', adjustable='datalim')
    ax.set_anchor('C')
    fig.subplots_adjust(left=0.05, right=0.985, bottom=0.12, top=0.90)
def draw_truss_view_3d(ax, nodes, members, n_panels, title='3D Geometry View', support_nodes=None,
                       hide_verticals=False):
    ax.cla()
    ax.set_facecolor('#f0f3f8')
    span = nodes[n_panels][0]
    depth = nodes[n_panels + 1][1]
    max_force = max((abs(m.get('force', 0.0)) for m in members), default=1.0)
    top_B_ft = max((m.get('section', {}).get('B', 2.0) / 12.0
                    for m in members if m.get('type') == 'TOP_CHORD'), default=2.0 / 12.0)
    bot_B_ft = max((m.get('section', {}).get('B', 2.0) / 12.0
                    for m in members if m.get('type') == 'BOTTOM_CHORD'), default=2.0 / 12.0)

    def _skip_for_display(mem):
        if hide_verticals and mem.get('type') == 'VERTICAL':
            return True
        if hide_verticals and mem.get('type') == 'BOTTOM_CHORD':
            if mem.get('i') == 0 or mem.get('j') == n_panels:
                return True
        return False

    visible_members = [m for m in members if not _skip_for_display(m)]
    max_B_ft = max((m.get('section', {}).get('B', 2.0) / 12.0 for m in visible_members), default=2.0 / 12.0)

    for mem in visible_members:
        xi, yi = nodes[mem['i']]
        xj, yj = nodes[mem['j']]
        B_ft = (mem.get('section') or {}).get('B', 2.0) / 12.0
        mtype = mem.get('type', '')
        if mtype == 'TOP_CHORD':
            base = '#2f3854'
        elif mtype == 'BOTTOM_CHORD':
            base = '#39445f'
        elif mtype == 'VERTICAL':
            base = '#556079'
        else:
            base = '#4a546e'
        shade = _force_shade(mem.get('force', 0.0), mem.get('role', 'TENSION'), max_force)
        face_y_i = None
        face_y_j = None
        if mtype in ('DIAGONAL', 'VERTICAL'):
            if yi > yj:
                face_y_i = yi - top_B_ft * 0.5
                face_y_j = yj + bot_B_ft * 0.5
            elif yi < yj:
                face_y_i = yi + bot_B_ft * 0.5
                face_y_j = yj - top_B_ft * 0.5
        _add_member_prism(ax, xi, yi, xj, yj, B_ft, base, shade, alpha=0.98,
                          face_y_i=face_y_i, face_y_j=face_y_j)

    visible_node_ids = sorted({nid for m in visible_members for nid in (m['i'], m['j'])})
    xs = [nodes[i][0] for i in visible_node_ids]
    ys = [nodes[i][1] for i in visible_node_ids]
    ax.scatter(xs, ys, [0.0] * len(visible_node_ids), s=6, c='#31405f', alpha=0.65, depthshade=False)

    # Supports: left pin bottom chord, right roller top chord
    left_support, right_support = support_nodes or (0, n_panels)
    x0, y0 = nodes[left_support]
    xr, yr = nodes[right_support]
    ax.scatter([x0], [y0], [0.0], s=120, c='#26a65b', marker='^', depthshade=False)
    ax.text(x0, y0 - depth * 0.16, 0.0, 'PIN', color='#26a65b', fontsize=7)
    ax.scatter([xr], [yr], [0.0], s=120, c='#26a65b', marker='o', depthshade=False)
    ax.text(xr, yr - depth * 0.16, 0.0, 'ROLLER', color='#26a65b', fontsize=7)

    ax.set_xlim(-span * 0.06, span * 1.06)
    ax.set_ylim(-depth * 0.45, depth * 1.25)
    ax.set_zlim(-max_B_ft * 0.90, max_B_ft * 0.90)
    ax.set_xlabel('Length (ft)', fontsize=9)
    ax.set_ylabel('Height (ft)', fontsize=9)
    ax.set_zlabel('Width (ft)', fontsize=9)
    ax.set_title('Geometry 3D  |  exact member solids', fontsize=10, fontweight='bold', pad=8)
    ax.view_init(elev=20, azim=-60)
    try:
        ax.set_box_aspect((span * 1.12, depth * 1.70, max_B_ft * 2.0))
    except Exception:
        pass
    ax.set_position([0.02, 0.05, 0.96, 0.88])
    ax.set_proj_type('persp', focal_length=1.8)
    try:
        ax.dist = 7
    except Exception:
        pass
    ax.grid(True, alpha=0.10)


def draw_force_chart(ax, members):
    ax.cla()
    ax.set_facecolor('#f8f9fc')
    type_short = {'BOTTOM_CHORD': 'BC', 'TOP_CHORD': 'TC',
                  'VERTICAL': 'V', 'DIAGONAL': 'D'}
    counts = {}
    labels, forces, colors = [], [], []
    for mem in members:
        t = mem['type']
        counts[t] = counts.get(t, 0) + 1
        labels.append('%s%d' % (type_short[t], counts[t]))
        f = mem.get('force', 0.0)
        forces.append(f)
        colors.append('#4a9eff' if f >= 0 else '#ff5252')
    x = np.arange(len(labels))
    ax.bar(x, forces, color=colors, edgecolor='white', linewidth=0.4, width=0.8)
    ax.axhline(0, color='#333', linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_ylabel('Axial Force (kips)', fontsize=9)
    ax.set_title('Member Forces  [blue = tension  |  red = compression]',
                 fontsize=10, fontweight='bold')
    ax.grid(True, axis='y', alpha=0.22, linestyle='--')
    ax.tick_params(labelsize=8)


def draw_dcr_chart(ax, members):
    ax.cla()
    ax.set_facecolor('#f8f9fc')
    type_short = {'BOTTOM_CHORD': 'BC', 'TOP_CHORD': 'TC',
                  'VERTICAL': 'V', 'DIAGONAL': 'D'}
    counts = {}
    labels, dcrs, colors = [], [], []
    for mem in members:
        t = mem['type']
        counts[t] = counts.get(t, 0) + 1
        labels.append('%s%d' % (type_short[t], counts[t]))
        dcr = mem.get('DCR', 0.0)
        dcrs.append(min(dcr, 1.5))
        if dcr > 1.0:   c = '#cc0000'
        elif dcr > 0.8: c = CLR_ORANGE
        elif dcr > 0.5: c = CLR_YELLOW
        else:           c = CLR_GREEN
        colors.append(c)
    x = np.arange(len(labels))
    ax.bar(x, dcrs, color=colors, edgecolor='white', linewidth=0.4, width=0.8)
    ax.axhline(1.0, color='red', lw=1.5, linestyle='--', label='Limit DCR = 1.0')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_ylabel('Demand / Capacity Ratio (DCR)', fontsize=9)
    ax.set_title('Stress Utilisation  [green<0.5  yellow<0.8  orange<1.0  red=OVER]',
                 fontsize=10, fontweight='bold')
    ax.legend(fontsize=8)
    ax.grid(True, axis='y', alpha=0.22, linestyle='--')
    ax.tick_params(labelsize=8)


def draw_deflection(ax, nodes, members, n_panels, disps_in, defl_ratio, defl_limit):
    ax.cla()
    ax.set_facecolor('#f8f9fc')
    span  = nodes[n_panels][0]
    depth = nodes[n_panels + 1][1]
    max_d = max(abs(d[1]) for d in disps_in) / 12.0
    if max_d < 0.0001:
        ax.text(0.5, 0.5, 'No deflection data', ha='center', va='center',
                transform=ax.transAxes, fontsize=12, color='#888')
        return
    disp_scale = depth * 0.4 / max_d
    for mem in members:
        xi, yi = nodes[mem['i']]; xj, yj = nodes[mem['j']]
        ax.plot([xi, xj], [yi, yj], color='#c8cce8', lw=0.8, alpha=0.5, zorder=1)

    def dnode(idx):
        x, y = nodes[idx]
        return (x + disps_in[idx][0] / 12.0 * disp_scale,
                y + disps_in[idx][1] / 12.0 * disp_scale)

    for mem in members:
        xi, yi = dnode(mem['i']); xj, yj = dnode(mem['j'])
        ax.plot([xi, xj], [yi, yj], color='#ff6b35', lw=1.8, zorder=2)
    for idx in range(len(nodes)):
        x, y = dnode(idx)
        ax.plot(x, y, 'o', ms=2.5, color='#cc3300', zorder=3, mew=0)
    ax.set_xlim(-span * 0.05, span * 1.05)
    ax.set_ylim(-depth * 0.5, depth * 1.4)
    ax.set_xlabel('Length (ft)', fontsize=9)
    ax.set_ylabel('Height (ft, exaggerated)', fontsize=9)
    max_in = max_d * 12.0
    defl_pass_str = 'PASS' if defl_ratio >= defl_limit else 'FAIL'
    ax.set_title(
        ('Deflected Shape  (exag. %.0fx)  |  Max = %.3f in  (L/%.0f)  '
         '[Limit L/%d – %s]') % (disp_scale, max_in, defl_ratio, defl_limit, defl_pass_str),
        fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.18, linestyle='--')
    ax.tick_params(labelsize=8)
    ghost = mpatches.Patch(color='#c8cce8', label='Undeformed', alpha=0.6)
    defd  = mpatches.Patch(color='#ff6b35', label='Deflected (exaggerated)')
    ax.legend(handles=[ghost, defd], fontsize=8)



# ═══════════════════════════════════════════════════════════════════════════
#  REPORT GENERATOR
# ═══════════════════════════════════════════════════════════════════════════

def build_report(span_ft, dl_kpf, ll_kpf, wu_kpf, depth_ft, n_panels,
                 truss_type, defl_limit, summary, members):
    display_panels = _display_panels_from_internal(n_panels, truss_type)
    lines = []
    sep  = '=' * 72
    sep2 = '-' * 72
    lines += [sep,
              '  HSS TRUSS DESIGNER  -  DESIGN REPORT',
              '  Kerkhoff Engineering',
              '  Generated: ' + datetime.now().strftime('%Y-%m-%d  %H:%M'),
              sep, '']
    lines += ['DESIGN INPUTS', sep2,
              '  Truss Type          : %s' % truss_type,
              '  Span                : %.2f ft  (%.0f in)' % (span_ft, span_ft * 12),
              '  Depth               : %.2f ft  (%.0f in)' % (depth_ft, depth_ft * 12),
              '  Top Panels          : %d' % display_panels,
              '  Panel Length        : %.2f ft  (%.1f in)' % (
                  span_ft / n_panels, span_ft / n_panels * 12),
              '  Dead Load (service) : %.3f kip/ft' % dl_kpf,
              '  Live Load (service) : %.3f kip/ft' % ll_kpf,
              '  Factored Load (wu)  : %.3f kip/ft  [1.2D + 1.6L]' % wu_kpf,
              '  Deflection Limit    : L / %d' % defl_limit,
              '']
    tc  = summary.get('top_chord')
    bc  = summary.get('bottom_chord')
    web = summary.get('web')
    rxns       = summary.get('reactions', {})
    n          = n_panels
    rl         = rxns.get(0,  [0, 0])
    rr         = rxns.get(n,  [0, 0])
    defl_ratio = summary.get('defl_ratio', 9999)
    defl_ok    = summary.get('defl_ok', True)
    max_dcr    = max(m.get('DCR', 0.0) for m in members)
    total_wt   = summary.get('total_weight_lbs', 0)
    wb         = summary.get('weight_breakdown', {})
    cost_est   = total_wt * STEEL_COST_PER_LB
    lines += ['GOVERNING SECTIONS', sep2,
              '  Top Chord    : %s' % (tc['name']  if tc  else 'N/A'),
              '  Bottom Chord : %s' % (bc['name']  if bc  else 'N/A'),
              '  Web Members  : %s' % (web['name'] if web else 'N/A'),
              '']
    lines += ['DESIGN SUMMARY', sep2,
              '  Reactions    : Left = %.2f kips  |  Right = %.2f kips' % (
                  abs(rl[1]), abs(rr[1])),
              '  Max Defl.    : %.4f in   (L / %.0f)   [Limit L/%d  ->  %s]' % (
                  summary.get('max_defl_in', 0), defl_ratio, defl_limit,
                  'PASS' if defl_ok else 'FAIL'),
              '  Max DCR      : %.3f   [%s]' % (max_dcr, 'PASS' if max_dcr <= 1.0 else 'FAIL'),
              '  Total Weight : %.0f lb   (%.1f plf)' % (total_wt, total_wt / span_ft),
              '    Top Chord  : %.0f lb' % wb.get('TOP_CHORD',    0),
              '    Bot. Chord : %.0f lb' % wb.get('BOTTOM_CHORD', 0),
              '    Diagonals  : %.0f lb' % wb.get('DIAGONAL',     0),
              '    Verticals  : %.0f lb' % wb.get('VERTICAL',     0),
              '  Est. Cost    : $%.0f  (@ $%.2f/lb installed)' % (cost_est, STEEL_COST_PER_LB),
              '']
    lines += ['CODE BASIS', sep2,
              '  CISC S16-style LSD basis',
              '  Material: ASTM A500 Grade C',
              '  Fy = 46 ksi    Fu = 62 ksi    E = 29,000 ksi',
              '  phi_t = 0.90  (tension)    phi_c = 0.90  (compression)',
              '  K_chord = 0.65             K_web = 0.75',
              '  KL/r limit = 200',
              '']
    lines += ['MEMBER SCHEDULE', sep2]
    hdr = ('%-4s  %-14s  %-18s  %7s  %9s  %9s  %7s  %-12s  %5s  %-8s' %
           ('#', 'Type', 'Section', 'L (ft)', 'Force(k)', 'Cap.(k)', 'DCR',
            'Role', 'b/t', 'Status'))
    lines += [hdr, '-' * len(hdr)]
    for i, m in enumerate(members):
        sec = m.get('section', {})
        lines.append('%-4d  %-14s  %-18s  %7.2f  %9.1f  %9.1f  %7.3f  %-12s  %5.1f  %-8s' % (
            i + 1, m['type'], sec.get('name', 'N/A'),
            m.get('length_ft', 0), m.get('force', 0), m.get('capacity', 0),
            m.get('DCR', 0), m.get('role', ''), m.get('bt', 0),
            'OVER' if m.get('DCR', 0) > 1.0 else ('SLENDER' if m.get('slender', False) else 'OK'),
        ))
    lines += ['', sep, '  END OF REPORT', sep]
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  DIALOGS
# ═══════════════════════════════════════════════════════════════════════════

class AddManualDesignDialog(tk.Toplevel):
    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.title('Add Previous / Manual Design')
        self.geometry('440x510')
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.on_save = on_save
        self._build()

    def _build(self):
        fields = [
            ('Span (ft)',                    '60.0'),
            ('DL (kip/ft)',                  '0.9'),
            ('LL (kip/ft)',                  '0.6'),
            ('Depth (ft)',                   '5.0'),
            ('Top Panels',                   '23'),
            ('Top Chord (e.g. HSS6X6X3/8)', 'HSS6X6X3/8'),
            ('Bottom Chord',                 'HSS6X6X3/8'),
            ('Web (Diag/Vert)',              'HSS4X4X3/16'),
            ('Notes',                        ''),
        ]
        self.entries = {}
        tk.Label(self, text='Add Previous / Manual Design', bg=CLR_BG, fg=CLR_ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(pady=(14, 6))
        for label, default in fields:
            row = tk.Frame(self, bg=CLR_BG)
            row.pack(fill='x', padx=20, pady=4)
            tk.Label(row, text=label + ':', bg=CLR_BG, fg=CLR_TEXT,
                     width=28, anchor='w').pack(side='left')
            e = tk.Entry(row, bg=CLR_ENTRY, fg=CLR_TEXT,
                         insertbackground=CLR_TEXT, relief='flat', width=22)
            e.insert(0, default)
            e.pack(side='left')
            self.entries[label] = e
        tk.Button(self, text='Save Design', command=self._save,
                  bg=CLR_ACCENT, fg='white', relief='flat',
                  padx=12, pady=7).pack(pady=14)

    def _save(self):
        try:
            span   = float(self.entries['Span (ft)'].get())
            dl     = float(self.entries['DL (kip/ft)'].get())
            ll     = float(self.entries['LL (kip/ft)'].get())
            depth  = float(self.entries['Depth (ft)'].get())
            panels = _internal_panels_from_display(int(self.entries['Top Panels'].get()))
            tc     = self.entries['Top Chord (e.g. HSS6X6X3/8)'].get().strip()
            bc     = self.entries['Bottom Chord'].get().strip()
            web_s  = self.entries['Web (Diag/Vert)'].get().strip()
            notes  = self.entries['Notes'].get().strip()
        except ValueError as e:
            messagebox.showerror('Input Error', str(e), parent=self)
            return
        wu = factored_load(dl, ll)
        db.add_manual_design(span, wu, depth, panels, tc, bc, web_s,
                             notes + ' [DL=%.3f LL=%.3f]' % (dl, ll))
        if self.on_save:
            self.on_save()
        self.destroy()


class PreviousDesignsDialog(tk.Toplevel):
    def __init__(self, parent, on_load=None):
        super().__init__(parent)
        self.title('Previous HSS Truss Designs Database')
        self.geometry('1120x520')
        self.configure(bg=CLR_BG)
        self.resizable(True, True)
        self.on_load = on_load
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg=CLR_PANEL, pady=6)
        toolbar.pack(fill='x', side='top')
        for text, cmd in [
            ('Load Selected Design', self._load_selected),
            ('Add Manual Design',    lambda: AddManualDesignDialog(self, on_save=self._refresh)),
            ('Delete Selected',      self._delete_selected),
            ('Refresh',              self._refresh),
        ]:
            tk.Button(toolbar, text=text, command=cmd, bg=CLR_BTN, fg=CLR_TEXT,
                      relief='flat', padx=8, pady=4,
                      cursor='hand2').pack(side='left', padx=5)
        frame = tk.Frame(self, bg=CLR_BG)
        frame.pack(fill='both', expand=True, padx=8, pady=8)
        cols = ('ID', 'Date', 'Span(ft)', 'wu(k/ft)', 'Depth(ft)', 'Top Panels',
                'Top Chord', 'Bot Chord', 'Web', 'Wt(lb)', 'Defl(in)', 'L/d', 'Notes')
        self.tree = ttk.Treeview(frame, columns=cols, show='headings', height=20)
        widths    = (40, 130, 65, 75, 65, 50, 130, 130, 130, 70, 70, 60, 220)
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor='center')
        sb_y = ttk.Scrollbar(frame, orient='vertical',   command=self.tree.yview)
        sb_x = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side='right', fill='y')
        sb_x.pack(side='bottom', fill='x')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self._load_selected())

    def _refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for d in db.load_all():
            self.tree.insert('', 'end', values=(
                d.get('id', ''), d.get('date', ''),
                d.get('span_ft', ''), d.get('load_kpf', ''),
                d.get('depth_ft', ''), _display_panels_from_internal(d.get('n_panels', 0)),
                d.get('top_chord', ''), d.get('bottom_chord', ''),
                d.get('web', ''), d.get('total_weight_lbs', ''),
                d.get('max_defl_in', ''), d.get('defl_ratio', ''),
                d.get('notes', ''),
            ))

    def _load_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning('No selection', 'Select a design first.', parent=self)
            return
        v = self.tree.item(sel[0])['values']
        design = {'span_ft': float(v[2]), 'load_kpf': float(v[3]),
                  'depth_ft': float(v[4]), 'n_panels': _internal_panels_from_display(int(v[5]))}
        if self.on_load:
            self.on_load(design)
        self.destroy()

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        v   = self.tree.item(sel[0])['values']
        did = int(v[0])
        if messagebox.askyesno('Confirm Delete', 'Delete design ID %d?' % did, parent=self):
            db.delete_design(did)
            self._refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg=CLR_PANEL, pady=6)
        toolbar.pack(fill='x', side='top')
        for text, cmd in [
            ('Load Selected Design', self._load_selected),
            ('Add Manual Design',    lambda: AddManualDesignDialog(self, on_save=self._refresh)),
            ('Delete Selected',      self._delete_selected),
            ('Refresh',              self._refresh),
        ]:
            tk.Button(toolbar, text=text, command=cmd, bg=CLR_BTN, fg=CLR_TEXT,
                      relief='flat', padx=8, pady=4,
                      cursor='hand2').pack(side='left', padx=5)


# ═══════════════════════════════════════════════════════════════════════════
#  MEMBER TABLE FRAME
# ═══════════════════════════════════════════════════════════════════════════

class MemberTableFrame(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=CLR_BG)
        cols = ('#', 'Type', 'Section', 'L(ft)', 'Force(k)', 'Cap(k)',
                'DCR', 'Role', 'b/t', 'Limit', 'Wt(lb)', 'Status')
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=24)
        widths    = (35, 110, 140, 55, 80, 80, 55, 100, 55, 55, 65, 70)
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor='center')
        self.tree.tag_configure('tension',     background='#eaf4ff')
        self.tree.tag_configure('compression', background='#fff4ea')
        self.tree.tag_configure('overloaded',  background='#ffdddd')
        self.tree.tag_configure('slender',     background='#fff0cc')
        sb_y = ttk.Scrollbar(self, orient='vertical',   command=self.tree.yview)
        sb_x = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side='right', fill='y')
        sb_x.pack(side='bottom', fill='x')
        self.tree.pack(fill='both', expand=True)

    def populate(self, members):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for i, m in enumerate(members):
            sec     = m.get('section', {})
            dcr     = m.get('DCR', 0.0)
            slender = m.get('slender', False)
            role    = m.get('role', '')
            wt_mem  = sec.get('wt', 0) * m.get('length_ft', 0)
            if dcr > 1.0:           tag = 'overloaded'
            elif slender:           tag = 'slender'
            elif role == 'TENSION': tag = 'tension'
            else:                   tag = 'compression'
            status = 'OVER' if dcr > 1.0 else ('SLENDER' if slender else 'OK')
            self.tree.insert('', 'end', tags=(tag,), values=(
                i + 1, m['type'], sec.get('name', 'N/A'),
                '%.2f' % m.get('length_ft', 0),
                '%.1f' % m.get('force', 0),
                '%.1f' % m.get('capacity', 0),
                '%.3f' % dcr, role,
                '%.1f' % m.get('bt', 0), '%.1f' % m.get('bt_limit', 0),
                '%.1f' % wt_mem, status,
            ))


# ═══════════════════════════════════════════════════════════════════════════
#  REPORT TAB FRAME
# ═══════════════════════════════════════════════════════════════════════════

class ReportFrame(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=CLR_BG)
        tb = tk.Frame(self, bg=CLR_PANEL2, pady=4)
        tb.pack(fill='x', side='top')
        tk.Button(tb, text='Copy to Clipboard', command=self._copy,
                  bg=CLR_BTN, fg=CLR_TEXT, relief='flat',
                  padx=8, pady=3, cursor='hand2').pack(side='left', padx=6)
        tk.Button(tb, text='Save Report (.txt)', command=self._save_txt,
                  bg=CLR_BTN, fg=CLR_TEXT, relief='flat',
                  padx=8, pady=3, cursor='hand2').pack(side='left', padx=4)
        self._txt = tk.Text(self, bg='#0d1117', fg='#c9d1d9',
                            font=('Consolas', 9), relief='flat',
                            wrap='none', state='disabled')
        sb_y = ttk.Scrollbar(self, orient='vertical',   command=self._txt.yview)
        sb_x = ttk.Scrollbar(self, orient='horizontal', command=self._txt.xview)
        self._txt.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side='right',  fill='y')
        sb_x.pack(side='bottom', fill='x')
        self._txt.pack(fill='both', expand=True)

    def set_text(self, text):
        self._txt.config(state='normal')
        self._txt.delete('1.0', 'end')
        self._txt.insert('end', text)
        self._txt.config(state='disabled')

    def get_text(self):
        return self._txt.get('1.0', 'end')

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.get_text())

    def _save_txt(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('Text files', '*.txt'), ('All files', '*.*')],
            title='Save Design Report')
        if not path:
            return
        with open(path, 'w') as f:
            f.write(self.get_text())
        messagebox.showinfo('Saved', 'Report saved to:\n' + path)


def _section_names():
    return [s['name'] for s in SECTIONS_BY_AREA]


def _sep(parent):
    tk.Frame(parent, bg=CLR_SEP, height=1).pack(fill='x', padx=10, pady=7)





# ═══════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION WINDOW
# ═══════════════════════════════════════════════════════════════════════════

class TrussDesignerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('HSS Truss Designer  v2.0  |  CISC S16  |  Kerkhoff Engineering')
        self.geometry('1540x890')
        self.configure(bg=CLR_BG)
        self.minsize(1200, 700)
        self._members   = []
        self._nodes     = []
        self._summary   = {}
        self._n_panels  = 0
        self._depth_ft  = 0.0
        self._dl_kpf    = 0.0
        self._ll_kpf    = 0.0
        self._wu_kpf    = 0.0
        self._build_menu()
        self._build_main_layout()
        self.update()
        self.after(100, self._draw_placeholder)
        self.bind('<F5>', lambda e: self._calculate())

    # ── Menu ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self, bg=CLR_PANEL, fg=CLR_TEXT)
        self.config(menu=menubar)
        file_m = tk.Menu(menubar, tearoff=0, bg=CLR_PANEL, fg=CLR_TEXT)
        file_m.add_command(label='Calculate  (F5)',              command=self._calculate)
        file_m.add_command(label='Save Design to Database',      command=self._save_design)
        file_m.add_separator()
        file_m.add_command(label='Export Member Schedule (CSV)', command=self._export_csv)
        file_m.add_command(label='Export Design Report (.txt)',  command=self._export_report_txt)
        file_m.add_separator()
        file_m.add_command(label='Exit', command=self.quit)
        menubar.add_cascade(label='File', menu=file_m)
        db_m = tk.Menu(menubar, tearoff=0, bg=CLR_PANEL, fg=CLR_TEXT)
        db_m.add_command(label='View / Load Previous Designs', command=self._open_prev_designs)
        db_m.add_command(label='Add Manual / Previous Design', command=self._add_manual)
        menubar.add_cascade(label='Database', menu=db_m)
        help_m = tk.Menu(menubar, tearoff=0, bg=CLR_PANEL, fg=CLR_TEXT)
        help_m.add_command(label='About', command=self._about)
        menubar.add_cascade(label='Help', menu=help_m)

    # ── Main layout ───────────────────────────────────────────────────────

    def _build_main_layout(self):
        left = tk.Frame(self, bg=CLR_PANEL, width=308)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        self._build_left_panel(left)
        right = tk.Frame(self, bg=CLR_BG)
        right.pack(side='left', fill='both', expand=True)
        self._build_right_panel(right)

    # ── Left panel ────────────────────────────────────────────────────────

    def _build_left_panel(self, parent):
        # Scrollable inner frame
        canvas = tk.Canvas(parent, bg=CLR_PANEL, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg=CLR_PANEL)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _on_configure)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind_all('<MouseWheel>',
                       lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units'))

        p = inner

        # Header
        tk.Label(p, text='HSS TRUSS DESIGNER', bg=CLR_PANEL, fg=CLR_ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(pady=(14, 1))
        tk.Label(p, text='CISC S16  |  ASTM A500 Gr-C  |  LSD',
                 bg=CLR_PANEL, fg=CLR_MUTED, font=('Segoe UI', 7)).pack()
        _sep(p)

        # Geometry inputs
        tk.Label(p, text='GEOMETRY', bg=CLR_PANEL, fg=CLR_YELLOW,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=14, pady=(0, 4))
        self._inputs = {}
        for label, key, default in [
            ('Span (ft)',   'span',   '60.0'),
            ('Depth (ft)',  'depth',  'Auto'),
            ('Top Panels',  'panels', 'Auto'),
        ]:
            row = tk.Frame(p, bg=CLR_PANEL)
            row.pack(fill='x', padx=14, pady=3)
            tk.Label(row, text=label, bg=CLR_PANEL, fg=CLR_TEXT,
                     font=('Segoe UI', 8), width=12, anchor='w').pack(side='left')
            var = tk.StringVar(value=default)
            ent = tk.Entry(row, textvariable=var, bg=CLR_ENTRY, fg=CLR_TEXT,
                           insertbackground=CLR_TEXT, relief='flat',
                           width=12, font=('Segoe UI', 9))
            ent.pack(side='left', padx=(4, 0))
            ent.bind('<Return>', lambda e: self._calculate())
            self._inputs[key] = var

        # Truss type
        row = tk.Frame(p, bg=CLR_PANEL)
        row.pack(fill='x', padx=14, pady=3)
        tk.Label(row, text='Truss Type', bg=CLR_PANEL, fg=CLR_TEXT,
                 font=('Segoe UI', 8), width=12, anchor='w').pack(side='left')
        self._truss_type_var = tk.StringVar(value=TRUSS_TYPES[0])
        _cb1 = ttk.Combobox(row, textvariable=self._truss_type_var,
                     values=TRUSS_TYPES, state='readonly', width=18,
                     font=('Segoe UI', 8))
        _cb1.pack(side='left', padx=(4, 0))
        _cb1.configure(foreground='black', background='white')
        _sep(p)

        # Load inputs
        tk.Label(p, text='LOADS  (service, kip/ft)', bg=CLR_PANEL, fg=CLR_YELLOW,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=14, pady=(0, 4))
        for label, key, default in [
            ('Dead (k/ft)', 'dl', '0.9'),
            ('Live (k/ft)', 'll', '0.6'),
        ]:
            row = tk.Frame(p, bg=CLR_PANEL)
            row.pack(fill='x', padx=14, pady=3)
            tk.Label(row, text=label, bg=CLR_PANEL, fg=CLR_TEXT,
                     font=('Segoe UI', 8), width=12, anchor='w').pack(side='left')
            var = tk.StringVar(value=default)
            ent = tk.Entry(row, textvariable=var, bg=CLR_ENTRY, fg=CLR_TEXT,
                           insertbackground=CLR_TEXT, relief='flat',
                           width=12, font=('Segoe UI', 9))
            ent.pack(side='left', padx=(4, 0))
            ent.bind('<Return>', lambda e: self._calculate())
            self._inputs[key] = var

        self._wu_label_var = tk.StringVar(value='wu = -- k/ft')
        tk.Label(p, textvariable=self._wu_label_var, bg=CLR_PANEL, fg=CLR_TEAL,
                 font=('Segoe UI', 8, 'italic')).pack(anchor='w', padx=14, pady=(2, 0))

        def _sched(*_):
            # Cancel any pending recalc timer and schedule a new one.
            # Do NOT touch depth/panels here — let _calculate read them as-is.
            try:
                if hasattr(self, '_calc_timer') and self._calc_timer is not None:
                    self.after_cancel(self._calc_timer)
            except Exception:
                pass
            self._calc_timer = self.after(900, self._on_auto_calc)

        self._inputs['span'].trace_add('write', _sched)
        self._inputs['dl'].trace_add('write', _sched)
        self._inputs['ll'].trace_add('write', _sched)
        _sep(p)

        # Deflection limit
        tk.Label(p, text='DEFLECTION LIMIT', bg=CLR_PANEL, fg=CLR_YELLOW,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=14, pady=(0, 4))
        row = tk.Frame(p, bg=CLR_PANEL)
        row.pack(fill='x', padx=14, pady=3)
        tk.Label(row, text='Limit (L/)', bg=CLR_PANEL, fg=CLR_TEXT,
                 font=('Segoe UI', 8), width=12, anchor='w').pack(side='left')
        self._defl_limit_var = tk.StringVar(value='360')
        _cb2 = ttk.Combobox(row, textvariable=self._defl_limit_var,
                     values=['180', '240', '300', '360', '480', '600'],
                     state='readonly', width=10,
                     font=('Segoe UI', 8))
        _cb2.pack(side='left', padx=(4, 0))
        _cb2.configure(foreground='black', background='white')
        _sep(p)

        # Section Override
        _ovr_hdr = tk.Frame(p, bg=CLR_PANEL)
        _ovr_hdr.pack(fill='x', padx=14, pady=(0, 4))
        tk.Label(_ovr_hdr, text='SECTION OVERRIDE', bg=CLR_PANEL, fg=CLR_YELLOW,
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        self._ovr_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(_ovr_hdr, text='Enable', variable=self._ovr_enabled,
                       bg=CLR_PANEL, fg=CLR_TEXT, selectcolor=CLR_ENTRY,
                       activebackground=CLR_PANEL,
                       command=self._toggle_overrides).pack(side='right')

        self._ovr_frame = tk.Frame(p, bg=CLR_PANEL)
        self._ovr_frame.pack(fill='x', padx=14, pady=(0, 4))
        self._sec_names = _section_names()
        self._override_vars         = {}
        self._override_enabled_vars = {}
        for mtype, label in [('TOP_CHORD', 'Top Chord'),
                              ('BOTTOM_CHORD', 'Bot. Chord'),
                              ('DIAGONAL', 'Diagonal'),
                              ('VERTICAL', 'Vertical')]:
            row = tk.Frame(self._ovr_frame, bg=CLR_PANEL)
            row.pack(fill='x', pady=2)
            en_var = tk.BooleanVar(value=False)
            tk.Checkbutton(row, variable=en_var, bg=CLR_PANEL,
                           selectcolor=CLR_ENTRY,
                           activebackground=CLR_PANEL).pack(side='left')
            tk.Label(row, text=label, bg=CLR_PANEL, fg=CLR_TEXT,
                     font=('Segoe UI', 8), width=10, anchor='w').pack(side='left')
            sec_var = tk.StringVar(value=self._sec_names[10])
            _cbo = ttk.Combobox(row, textvariable=sec_var,
                         values=self._sec_names, state='readonly',
                         width=17, font=('Segoe UI', 7))
            _cbo.pack(side='left', padx=(2, 0))
            _cbo.configure(foreground='black', background='white')
            self._override_vars[mtype]         = sec_var
            self._override_enabled_vars[mtype] = en_var
        self._toggle_overrides()
        _sep(p)

        # Action buttons
        tk.Button(p, text='CALCULATE  (F5)', command=self._calculate,
                  bg=CLR_ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief='flat', cursor='hand2', pady=9).pack(fill='x', padx=14, pady=(0, 5))
        row2 = tk.Frame(p, bg=CLR_PANEL)
        row2.pack(fill='x', padx=14, pady=2)
        for text, cmd in [('Save Design', self._save_design),
                          ('Prev. Designs', self._open_prev_designs)]:
            tk.Button(row2, text=text, command=cmd, bg=CLR_BTN, fg=CLR_TEXT,
                      relief='flat', cursor='hand2', pady=5,
                      padx=4).pack(side='left', fill='x', expand=True, padx=2)
        row3 = tk.Frame(p, bg=CLR_PANEL)
        row3.pack(fill='x', padx=14, pady=2)
        for text, cmd in [('Optimize (Min. Wt)', self._optimize),
                          ('Export CSV', self._export_csv)]:
            tk.Button(row3, text=text, command=cmd, bg=CLR_BTN2, fg=CLR_TEXT,
                      relief='flat', cursor='hand2', pady=5,
                      padx=4).pack(side='left', fill='x', expand=True, padx=2)
        tk.Button(p, text='+ Add Manual Design', command=self._add_manual,
                  bg='#1a2e1a', fg=CLR_GREEN, relief='flat',
                  cursor='hand2', pady=5).pack(fill='x', padx=14, pady=(4, 0))
        _sep(p)

        # Design results
        tk.Label(p, text='DESIGN RESULTS', bg=CLR_PANEL, fg=CLR_YELLOW,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=14, pady=(0, 4))
        self._result_vars = {}
        result_fields = [
            ('Top Chord',      'top_chord',   CLR_TEXT),
            ('Bot. Chord',     'bot_chord',   CLR_TEXT),
            ('Web Members',    'web',         CLR_TEXT),
            ('Depth',          'depth_res',   CLR_TEXT),
            ('Top Panels',     'panels_res',  CLR_TEXT),
            ('Panel Length',   'panel_len',   CLR_TEXT),
            ('wu (factored)',  'wu_res',      CLR_TEAL),
            ('Total Weight',   'weight',      CLR_TEXT),
            ('  Top Chord',    'wt_tc',       CLR_MUTED),
            ('  Bot. Chord',   'wt_bc',       CLR_MUTED),
            ('  Diagonals',    'wt_diag',     CLR_MUTED),
            ('  Verticals',    'wt_vert',     CLR_MUTED),
            ('Est. Cost',      'cost',        CLR_YELLOW),
            ('Max Defl.',      'deflection',  CLR_TEXT),
            ('L / defl.',      'defl_ratio',  CLR_TEXT),
            ('Defl. Check',    'defl_check',  CLR_TEXT),
            ('Left Reaction',  'react_l',     CLR_TEXT),
            ('Right Reaction', 'react_r',     CLR_TEXT),
            ('Max DCR',        'max_dcr',     CLR_TEXT),
        ]
        for label, key, fg in result_fields:
            row = tk.Frame(p, bg=CLR_PANEL)
            row.pack(fill='x', padx=14, pady=1)
            tk.Label(row, text=label + ':', bg=CLR_PANEL, fg=CLR_MUTED,
                     font=('Segoe UI', 8), width=14, anchor='w').pack(side='left')
            var = tk.StringVar(value='--')
            self._result_vars[key] = var
            tk.Label(row, textvariable=var, bg=CLR_PANEL, fg=fg,
                     font=('Segoe UI', 8, 'bold'), anchor='w').pack(side='left')

        self._status_var = tk.StringVar(value='Enter inputs and click Calculate.')
        self._status_lbl = tk.Label(p, textvariable=self._status_var, bg='#0e1322',
                                    fg=CLR_MUTED, font=('Segoe UI', 7),
                                    wraplength=284, justify='left', anchor='w')
        self._status_lbl.pack(fill='x', padx=10, pady=8, side='bottom')

    def _toggle_overrides(self):
        state = 'normal' if self._ovr_enabled.get() else 'disabled'
        for w in self._ovr_frame.winfo_children():
            for child in w.winfo_children():
                try: child.config(state=state)
                except Exception: pass

    # ── Right panel ───────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill='both', expand=True, padx=6, pady=6)
        self._nb = nb

        def _scroll_zoom(event, canvas, ax):
            if event.inaxes is None: return
            scale = 0.85 if event.button == 'up' else (1.0 / 0.85)
            xd, yd = event.xdata, event.ydata
            ax.set_xlim([xd + (x - xd) * scale for x in ax.get_xlim()])
            ax.set_ylim([yd + (y - yd) * scale for y in ax.get_ylim()])
            canvas.draw_idle()

        def _scroll_zoom_3d(event, canvas, ax):
            scale = 0.85 if event.button == 'up' else (1.0 / 0.85)
            xlim = ax.get_xlim3d(); ylim = ax.get_ylim3d(); zlim = ax.get_zlim3d()
            xc = 0.5 * (xlim[0] + xlim[1])
            yc = 0.5 * (ylim[0] + ylim[1])
            zc = 0.5 * (zlim[0] + zlim[1])
            xr = 0.5 * (xlim[1] - xlim[0]) * scale
            yr = 0.5 * (ylim[1] - ylim[0]) * scale
            zr = 0.5 * (zlim[1] - zlim[0]) * scale
            ax.set_xlim3d(xc - xr, xc + xr)
            ax.set_ylim3d(yc - yr, yc + yr)
            ax.set_zlim3d(zc - zr, zc + zr)
            canvas.draw_idle()

        def make_tab(label):
            f      = tk.Frame(nb, bg='white')
            nb.add(f, text='  %s  ' % label)
            fig    = Figure(figsize=(10, 5))
            fig.set_facecolor('#f8f9fc')
            ax     = fig.add_subplot(111)
            canvas = FigureCanvasTkAgg(fig, f)
            NavigationToolbar2Tk(canvas, f).pack(side='bottom')
            canvas.get_tk_widget().pack(fill='both', expand=True)
            canvas.mpl_connect('scroll_event', lambda e: _scroll_zoom(e, canvas, ax))
            return fig, ax, canvas

        def make_tab_3d(label):
            f      = tk.Frame(nb, bg='white')
            nb.add(f, text='  %s  ' % label)
            fig    = Figure(figsize=(10, 5))
            fig.set_facecolor('#f8f9fc')
            ax     = fig.add_subplot(111, projection='3d')
            canvas = FigureCanvasTkAgg(fig, f)
            NavigationToolbar2Tk(canvas, f).pack(side='bottom')
            canvas.get_tk_widget().pack(fill='both', expand=True)
            canvas.mpl_connect('scroll_event', lambda e: _scroll_zoom_3d(e, canvas, ax))
            return fig, ax, canvas

        self._fig_truss,  self._ax_truss,  self._cv_truss  = make_tab('Truss View')
        self._fig_geo3d,  self._ax_geo3d,  self._cv_geo3d  = make_tab_3d('Geometry 3D')
        self._fig_forces, self._ax_forces, self._cv_forces = make_tab('Member Forces')
        self._fig_dcr,    self._ax_dcr,    self._cv_dcr    = make_tab('Stress Ratios')
        self._fig_defl,   self._ax_defl,   self._cv_defl   = make_tab('Deflection')

        tab_tbl = tk.Frame(nb, bg=CLR_BG)
        nb.add(tab_tbl, text='  Member Table  ')
        self._mem_table = MemberTableFrame(tab_tbl)
        self._mem_table.pack(fill='both', expand=True)

        tab_rpt = tk.Frame(nb, bg=CLR_BG)
        nb.add(tab_rpt, text='  Design Report  ')
        self._report_frame = ReportFrame(tab_rpt)
        self._report_frame.pack(fill='both', expand=True)

    def _on_auto_calc(self):
        """Called by the debounce timer."""
        self._calc_timer = None
        self._calculate(silent=True)

    def _draw_placeholder(self):
        for ax, cv in [(self._ax_truss, self._cv_truss),
                       (self._ax_geo3d, self._cv_geo3d),
                       (self._ax_forces, self._cv_forces),
                       (self._ax_dcr, self._cv_dcr),
                       (self._ax_defl, self._cv_defl)]:
            ax.cla()
            if getattr(ax, 'name', '') == '3d':
                ax.set_axis_off()
                ax.text2D(0.5, 0.5, 'Enter inputs and press  CALCULATE  (F5)',
                          ha='center', va='center', fontsize=13,
                          color='#aaaacc', transform=ax.transAxes,
                          fontfamily='Segoe UI')
            else:
                ax.axis('off')
                ax.text(0.5, 0.5, 'Enter inputs and press  CALCULATE  (F5)',
                        ha='center', va='center', fontsize=13,
                        color='#aaaacc', transform=ax.transAxes,
                        fontfamily='Segoe UI')
            cv.draw()

    # ── Input helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_ft(text):
        """Parse a length in decimal ft or feet-inches notation.
        Accepts:  80  |  80.5  |  80-0  |  80-6  |  80'  |  80'6"  |  80' 6"
        Returns value in decimal feet, or raises ValueError.
        """
        import re
        s = text.strip()
        # Feet+inches with apostrophe: 80'6" or 80' 6" or 80'
        m = re.match(r"^([\d.]+)'\s*([\d.]*)\"?$", s)
        if m:
            ft  = float(m.group(1))
            ins = float(m.group(2)) if m.group(2) else 0.0
            return ft + ins / 12.0
        # Feet-inches with dash or space: 80-6  or  80 6
        m = re.match(r'^([\d.]+)[\s\-]+([\d.]+)$', s)
        if m:
            return float(m.group(1)) + float(m.group(2)) / 12.0
        # Plain decimal (also handles trailing " like 7.5")
        try:
            return float(s.rstrip('"').strip())
        except ValueError:
            pass
        raise ValueError

    def _get_span(self):
        try:
            v = self._parse_ft(self._inputs['span'].get())
            if v <= 0: raise ValueError
            return v
        except Exception:
            raise ValueError(
                'Span must be a positive number in ft.\n'
                'Examples: 80  or  80.5  or  80-6  (80ft 6in)')

    def _get_dl(self):
        try:
            s = self._inputs['dl'].get().strip()
            if s == '': return 0.0
            v = float(s)
            if v < 0: raise ValueError
            return v
        except Exception: raise ValueError('Dead load must be >= 0 (kip/ft).')

    def _get_ll(self):
        try:
            s = self._inputs['ll'].get().strip()
            if s == '': return 0.0
            v = float(s)
            if v < 0: raise ValueError
            return v
        except Exception: raise ValueError('Live load must be >= 0 (kip/ft).')

    def _get_depth(self, span_ft):
        val = self._inputs['depth'].get().strip().lower()
        if val in ('auto', '', '0'): return recommended_depth(span_ft)
        try:
            v = self._parse_ft(val)
            if v <= 0: raise ValueError
            return v
        except Exception:
            raise ValueError(
                'Depth must be positive ft (or Auto).\n'
                'Examples: 7  or  7.5  or  7-6  (7ft 6in)')

    def _get_panels(self, span_ft):
        val = self._inputs['panels'].get().strip().lower()
        if val in ('auto', '', '0'): return recommended_panels(span_ft)
        try:
            v = int(float(val))          # tolerate "9.0" etc.
            truss_type = self._truss_type_var.get().strip() or TRUSS_TYPES[0]
            v = max(2 if truss_type == 'Warren w/ Verticals' else 4, v)
            return _internal_panels_from_display(v, truss_type)
        except Exception: raise ValueError('Top Panels must be an integer >= 2 for Warren, or >= 4 for Pratt/Howe (or Auto).')

    def _get_defl_limit(self):
        try: return int(self._defl_limit_var.get())
        except Exception: return 360

    def _get_override_sections(self):
        if not self._ovr_enabled.get(): return {}
        result = {}
        for mtype, var in self._override_vars.items():
            if self._override_enabled_vars[mtype].get():
                name = var.get()
                if name in SECTIONS:
                    result[mtype] = SECTIONS[name]
        return result

    # ── Calculate ─────────────────────────────────────────────────────────

    def _calculate(self, silent=False):
        """Run analysis.  silent=True suppresses the error messagebox (used by
        the auto-recalc debounce so typing does not pop up dialog boxes)."""
        self._status_var.set('Calculating...')
        self._status_lbl.config(fg=CLR_TEAL)
        self.update_idletasks()
        depth_is_auto = self._inputs['depth'].get().strip().lower() in ('', '0', 'auto')
        panels_is_auto = self._inputs['panels'].get().strip().lower() in ('', '0', 'auto')
        try:
            span_ft    = self._get_span()
            dl_kpf     = self._get_dl()
            ll_kpf     = self._get_ll()
            wu_kpf     = factored_load(dl_kpf, ll_kpf)
            if wu_kpf <= 0:
                self._status_var.set('Enter Dead and/or Live load (k/ft) then Calculate.')
                self._status_lbl.config(fg=CLR_ORANGE)
                return
            depth_ft   = self._get_depth(span_ft)
            n_panels   = self._get_panels(span_ft)
            defl_limit = self._get_defl_limit()
            truss_type = self._truss_type_var.get().strip() or TRUSS_TYPES[0]
            overrides  = self._get_override_sections()
        except ValueError as e:
            msg = str(e)
            if not silent:
                messagebox.showerror('Input Error', msg)
            self._status_var.set('Input error: ' + msg.split('\n')[0])
            self._status_lbl.config(fg=CLR_RED)
            return

        self._wu_label_var.set('wu = %.3f k/ft  (1.25D+1.5L)' % wu_kpf)

        try:
            nodes, members = build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels)
            members, summary = design_members(
                members, nodes, n_panels, wu_kpf,
                override_sections=overrides, defl_limit=defl_limit,
                truss_type=truss_type)
        except Exception as e:
            messagebox.showerror('Analysis Error', str(e))
            self._status_var.set('Analysis error: ' + str(e))
            self._status_lbl.config(fg=CLR_RED)
            return

        self._members  = members
        self._nodes    = nodes
        self._summary  = summary
        self._n_panels = n_panels
        self._depth_ft = depth_ft
        self._dl_kpf   = dl_kpf
        self._ll_kpf   = ll_kpf
        self._wu_kpf   = wu_kpf

        # Update depth/panels fields only when those inputs are Auto
        self._calc_timer = None
        if depth_is_auto:
            self._inputs['depth'].set('%.2f' % depth_ft)
        if panels_is_auto:
            self._inputs['panels'].set(str(_display_panels_from_internal(n_panels, truss_type)))

        tc         = summary['top_chord']
        bc         = summary['bottom_chord']
        web        = summary['web']
        rxns       = summary['reactions']
        wb         = summary.get('weight_breakdown', {})
        max_dcr    = max(m.get('DCR', 0.0) for m in members)
        a          = nodes[n_panels][0] / n_panels
        display_panels = _display_panels_from_internal(n_panels, truss_type)
        total_wt   = summary['total_weight_lbs']
        cost_est   = total_wt * STEEL_COST_PER_LB
        defl_ok    = summary.get('defl_ok', True)
        defl_ratio = summary.get('defl_ratio', 9999)

        self._result_vars['top_chord'].set(tc['name']  if tc  else 'N/A')
        self._result_vars['bot_chord'].set(bc['name']  if bc  else 'N/A')
        self._result_vars['web'].set(web['name'] if web else 'N/A')
        self._result_vars['depth_res'].set('%.2f ft  (%.0f in)' % (depth_ft, depth_ft * 12))
        self._result_vars['panels_res'].set('%d top panels  (%d bays)' % (display_panels, n_panels))
        self._result_vars['panel_len'].set('%.2f ft  (%.1f in)' % (a, a * 12))
        self._result_vars['wu_res'].set('%.3f k/ft' % wu_kpf)
        self._result_vars['weight'].set('%.0f lbs  (%.1f plf)' % (total_wt, total_wt / span_ft))
        self._result_vars['wt_tc'].set('%.0f lb'   % wb.get('TOP_CHORD',    0))
        self._result_vars['wt_bc'].set('%.0f lb'   % wb.get('BOTTOM_CHORD', 0))
        self._result_vars['wt_diag'].set('%.0f lb' % wb.get('DIAGONAL',     0))
        self._result_vars['wt_vert'].set('%.0f lb' % wb.get('VERTICAL',     0))
        self._result_vars['cost'].set('$%.0f  (@$%.2f/lb est.)' % (cost_est, STEEL_COST_PER_LB))
        self._result_vars['deflection'].set('%.3f in' % summary['max_defl_in'])
        self._result_vars['defl_ratio'].set('L / %.0f' % defl_ratio)
        defl_txt = ('PASS (L/%.0f >= L/%d)' if defl_ok else 'FAIL (L/%.0f < L/%d)') % (
            defl_ratio, defl_limit)
        self._result_vars['defl_check'].set(defl_txt)
        left_support, right_support = summary.get('support_nodes', (0, n_panels))
        rl = rxns.get(left_support, [0, 0]); rr = rxns.get(right_support, [0, 0])
        self._result_vars['react_l'].set('%.1f kips' % abs(rl[1]))
        self._result_vars['react_r'].set('%.1f kips' % abs(rr[1]))
        self._result_vars['max_dcr'].set(
            '%.3f  %s' % (max_dcr, 'PASS' if max_dcr <= 1.0 else 'FAIL'))

        title = ('%s  |  Span=%.1fft  wu=%.2fk/ft  d=%.1fft  Top Panels=%d  Wt=%.0flb  |  TC:%s  BC:%s  Web:%s'
                 % (truss_type, span_ft, wu_kpf, depth_ft,
                display_panels, total_wt,
                    tc['name'] if tc else 'N/A',
                    bc['name'] if bc else 'N/A',
                    web['name'] if web else 'N/A'))
        loads = summary['loads']
        disps = summary['disps_in']
        support_nodes = summary.get('display_support_nodes', summary.get('support_nodes', (0, n_panels)))

        try:
            hide_verticals = (truss_type == 'Warren w/ Verticals')
            draw_truss_view(self._ax_truss, nodes, members, n_panels, loads, title,
                    support_nodes=support_nodes, total_weight_lbs=total_wt,
                    hide_verticals=hide_verticals)
            self._cv_truss.draw()
            self._cv_truss.flush_events()
            draw_truss_view_3d(self._ax_geo3d, nodes, members, n_panels, title,
                       support_nodes=support_nodes,
                       hide_verticals=hide_verticals)
            self._cv_geo3d.draw()
            self._cv_geo3d.flush_events()
            draw_force_chart(self._ax_forces, members)
            self._fig_forces.tight_layout()
            self._cv_forces.draw()
            self._cv_forces.flush_events()
            draw_dcr_chart(self._ax_dcr, members)
            self._fig_dcr.tight_layout()
            self._cv_dcr.draw()
            self._cv_dcr.flush_events()
            draw_deflection(self._ax_defl, nodes, members, n_panels, disps,
                            defl_ratio, defl_limit)
            self._cv_defl.draw()
            self._cv_defl.flush_events()
        except Exception as draw_err:
            import traceback
            self._status_var.set('Draw error: ' + str(draw_err))
            self._status_lbl.config(fg=CLR_RED)
            traceback.print_exc()
            return

        self._mem_table.populate(members)

        report_txt = build_report(
            span_ft, dl_kpf, ll_kpf, wu_kpf, depth_ft, n_panels,
            truss_type, defl_limit, summary, members)
        self._report_frame.set_text(report_txt)

        overstressed = [m for m in members if m.get('DCR', 0) > 1.0]
        slender      = [m for m in members if m.get('slender', False)]
        status = 'Done. %d members designed.' % len(members)
        if overstressed: status += '  WARNING: %d overstressed!' % len(overstressed)
        if slender:      status += '  WARNING: %d slender walls.' % len(slender)
        if not defl_ok:  status += '  WARNING: Deflection exceeds L/%d.' % defl_limit
        self._status_var.set(status)
        self._status_lbl.config(
            fg=CLR_GREEN if not overstressed and defl_ok else CLR_ORANGE)

    # ── Optimize ──────────────────────────────────────────────────────────

    def _optimize(self):
        if not self._summary:
            messagebox.showwarning('Optimize', 'Run a design first before optimizing.')
            return
        try:
            span_ft    = self._get_span()
            dl_kpf     = self._get_dl()
            ll_kpf     = self._get_ll()
            wu_kpf     = factored_load(dl_kpf, ll_kpf)
            defl_limit = self._get_defl_limit()
            truss_type = self._truss_type_var.get().strip() or TRUSS_TYPES[0]
            overrides  = self._get_override_sections()
        except ValueError as e:
            messagebox.showerror('Input Error', str(e)); return

        self._status_var.set('Optimizing...')
        self.update_idletasks()

        base_depth  = self._get_depth(span_ft)
        base_panels = self._get_panels(span_ft)
        depths  = sorted(set(max(2.0, round(base_depth * f * 12.0) / 12.0)
                     for f in (0.75, 0.875, 1.0, 1.125, 1.25, 1.5)))
        panels  = sorted(set([max(4, base_panels + d) for d in (-2, -1, 0, 1, 2)]))

        best_wt, best_depth, best_panels = 1e18, None, None
        for d in depths:
            for n in panels:
                try:
                    nodes, members = build_geometry_for_type(truss_type, span_ft, d, n)
                    mems, summ     = design_members(members, nodes, n, wu_kpf,
                                                    override_sections=overrides,
                                                    defl_limit=defl_limit,
                                                    truss_type=truss_type)
                    if max(m.get('DCR', 0) for m in mems) > 1.0: continue
                    if not summ.get('defl_ok', True): continue
                    wt = summ['total_weight_lbs']
                    if wt < best_wt:
                        best_wt = wt; best_depth = d; best_panels = n
                except Exception:
                    continue

        if best_depth is None:
            messagebox.showwarning('Optimize', 'No valid design found in search space.')
            return

        self._inputs['depth'].set('%.2f' % best_depth)
        self._inputs['panels'].set(str(_display_panels_from_internal(best_panels, truss_type)))
        self._calculate()
        messagebox.showinfo('Optimized',
            'Minimum-weight design found:\n'
            '  Depth   = %.2f ft  (%.0f in)\n'
            '  Top Panels  = %d\n'
            '  Weight  = %.0f lbs\n\n'
            '(Strength OK + deflection <= L/%d)' % (
                best_depth, best_depth * 12, _display_panels_from_internal(best_panels, truss_type), best_wt, defl_limit))

    # ── Save / Export ─────────────────────────────────────────────────────

    def _save_design(self):
        if not self._summary:
            messagebox.showwarning('No Design', 'Calculate a design first.'); return
        notes = simpledialog.askstring(
            'Notes', 'Optional notes (or leave blank):', parent=self) or ''
        tc  = self._summary['top_chord']
        bc  = self._summary['bottom_chord']
        web = self._summary['web']
        db.save_design(
            span_ft=float(self._inputs['span'].get()),
            load_kpf=self._wu_kpf,
            depth_ft=self._depth_ft,
            n_panels=self._n_panels,
            top_chord=tc['name']  if tc  else 'N/A',
            bottom_chord=bc['name'] if bc else 'N/A',
            web=web['name'] if web else 'N/A',
            total_weight_lbs=self._summary['total_weight_lbs'],
            max_defl_in=self._summary['max_defl_in'],
            defl_ratio=self._summary['defl_ratio'],
            notes=notes + '  [DL=%.3f LL=%.3f]' % (self._dl_kpf, self._ll_kpf),
        )
        messagebox.showinfo('Saved', 'Design saved to database.')

    def _export_csv(self):
        if not self._members:
            messagebox.showwarning('No Design', 'Calculate a design first.'); return
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')],
            title='Export Member Schedule')
        if not path: return
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['#', 'Type', 'Section', 'L_ft', 'Force_kips',
                             'Capacity_kips', 'DCR', 'Role', 'b_t', 'b_t_limit',
                             'Weight_lb', 'Status'])
            for i, m in enumerate(self._members):
                sec = m.get('section', {})
                wt  = sec.get('wt', 0) * m.get('length_ft', 0)
                writer.writerow([
                    i + 1, m['type'], sec.get('name', 'N/A'),
                    '%.3f' % m.get('length_ft', 0),
                    '%.2f' % m.get('force', 0),
                    '%.2f' % m.get('capacity', 0),
                    '%.4f' % m.get('DCR', 0),
                    m.get('role', ''),
                    '%.2f' % m.get('bt', 0), '%.2f' % m.get('bt_limit', 0),
                    '%.2f' % wt,
                    'OVER' if m.get('DCR', 0) > 1.0 else (
                        'SLENDER' if m.get('slender', False) else 'OK'),
                ])
        messagebox.showinfo('Exported', 'Member schedule saved to:\n' + path)

    def _export_report_txt(self):
        if not self._summary:
            messagebox.showwarning('No Design', 'Calculate a design first.'); return
        self._report_frame._save_txt()

    # ── Database / dialogs ────────────────────────────────────────────────

    def _open_prev_designs(self):
        PreviousDesignsDialog(self, on_load=self._load_prev_design)

    def _add_manual(self):
        AddManualDesignDialog(self)

    def _load_prev_design(self, design):
        wu = design.get('load_kpf', 1.5)
        # Rough split assuming DL:LL ~ 60:40 at service
        dl = round(wu / (1.2 + 1.6 * 0.667), 3)
        ll = round(dl * 0.667, 3)
        self._inputs['span'].set(str(design['span_ft']))
        self._inputs['dl'].set(str(dl))
        self._inputs['ll'].set(str(ll))
        self._inputs['depth'].set(str(design['depth_ft']))
        truss_type = self._truss_type_var.get().strip() or TRUSS_TYPES[0]
        self._inputs['panels'].set(str(_display_panels_from_internal(design['n_panels'], truss_type)))
        self._status_var.set('Previous design loaded. Click CALCULATE.')
        self._calculate()

    def _about(self):
        msg = (
            'HSS Truss Designer  v2.0\n'
            '========================\n\n'
            'Truss types: Warren w/ Verticals, Pratt, Howe\n'
            'CISC S16-style HSS design workflow (ASTM A500 Grade C).\n'
            'LSD design basis.\n\n'
            'Load factoring: 1.25D + 1.5L\n'
            'Fy=46 ksi  Fu=62 ksi  E=29,000 ksi\n'
            'K_chord=0.65  K_web=0.75  KL/r limit=200\n\n'
            'Analysis: Direct Stiffness Method (2D truss).\n'
            'Loads applied at top chord panel points.\n'
            'Supports: pin (left) + roller (right).\n\n'
            'New in v2.0:\n'
            '  - Dead + Live load inputs w/ LSD factoring\n'
            '  - Pratt & Howe truss types\n'
            '  - Deflection limit selector\n'
            '  - Section override per member group\n'
            '  - Minimum-weight optimizer\n'
            '  - CSV export & text design report\n'
            '  - Steel cost estimate\n'
            '  - Weight breakdown by member type\n\n'
            'Kerkhoff Engineering'
        )
        messagebox.showinfo('About HSS Truss Designer', msg)


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Create the app FIRST so tkinter has a real root before Style is configured.
    # Creating ttk.Style() before any Tk window would spawn a blank phantom tk window.
    _launcher_log('main.py starting')
    app = TrussDesignerApp()
    _launcher_log('main.py created TrussDesignerApp successfully')

    style = ttk.Style(app)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure('TNotebook',      background=CLR_BG,   borderwidth=0)
    style.configure('TNotebook.Tab',  background=CLR_BTN,  foreground=CLR_TEXT,
                    padding=[10, 5],  font=('Segoe UI', 9))
    style.map('TNotebook.Tab',
              background=[('selected', CLR_ACCENT)],
              foreground=[('selected', 'white')])
    style.configure('Treeview',       background='#f0f4f8', fieldbackground='#f0f4f8',
                    rowheight=22,     font=('Segoe UI', 8))
    style.configure('Treeview.Heading', font=('Segoe UI', 8, 'bold'),
                    background='#d0d8e8')
    style.configure('TCombobox',      fieldbackground='white', background='white',
                    foreground='black', selectbackground=CLR_ACCENT,
                    selectforeground='white')
    style.map('TCombobox',
              fieldbackground=[('readonly', 'white'), ('disabled', CLR_ENTRY)],
              foreground=[('readonly', 'black'), ('disabled', CLR_MUTED)],
              selectbackground=[('readonly', CLR_ACCENT)],
              selectforeground=[('readonly', 'white')])
    app.update_idletasks()
    _launcher_log(f"main.py UI initialized successfully; window state={app.state()}")
    app.after(0, lambda: _launcher_log('main.py entered mainloop successfully'))
    app.mainloop()
    _launcher_log('main.py mainloop exited')
