import copy
import io
import math
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go

import database as db
from engine import (
    TRUSS_TYPES,
    build_geometry_for_type,
    design_members,
    factored_load,
    recommended_depth,
    recommended_panels,
)
from sections import SECTIONS, SECTIONS_BY_AREA


STEEL_COST_PER_LB = 1.25
DEFLECTION_LIMITS = [180, 240, 360, 480, 600]
CLR_BG = '#1a1f2e'
CLR_PANEL = '#222840'
CLR_PANEL2 = '#1e2438'
CLR_ACCENT = '#4a9eff'
CLR_TEXT = '#dce6f0'
CLR_MUTED = '#7a8baa'
CLR_GREEN = '#3ddc84'
CLR_YELLOW = '#ffd740'
CLR_RED = '#ff5252'
CLR_ORANGE = '#ff9800'


def _member_rect(ax, xi, yi, xj, yj, width_ft, edge='#000000', lw=0.6, alpha=1.0, zorder=30):
    dx, dy = xj - xi, yj - yi
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return
    hx, hy = -dy / length * width_ft / 2.0, dx / length * width_ft / 2.0
    points = [(xi + hx, yi + hy), (xi - hx, yi - hy), (xj - hx, yj - hy), (xj + hx, yj + hy)]
    ax.add_patch(plt.Polygon(points, closed=True, fc='none', ec=edge, lw=lw, alpha=alpha, zorder=zorder))


def _intersect_y(p1, p2, y_face):
    x1, y1 = p1
    x2, y2 = p2
    if abs(y2 - y1) < 1e-12:
        return (x1, y_face)
    t = (y_face - y1) / (y2 - y1)
    return (x1 + t * (x2 - x1), y_face)


def _member_face_rect(ax, xi, yi, xj, yj, width_ft, face_y_i=None, face_y_j=None,
                      edge='#000000', lw=0.6, alpha=1.0, zorder=30):
    dx, dy = xj - xi, yj - yi
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return
    hx, hy = -dy / length * width_ft / 2.0, dx / length * width_ft / 2.0
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
    points = [i_plus, i_minus, j_minus, j_plus]
    ax.add_patch(plt.Polygon(points, closed=True, fc='none', ec=edge, lw=lw, alpha=alpha, zorder=zorder))


def _member_hidden_edge(ax, xi, yi, xj, yj, outer_width_ft, inset_ft, color='#aeb8cd',
                        lw=0.65, zorder=35, face_y_i=None, face_y_j=None, alpha=0.95):
    dx, dy = xj - xi, yj - yi
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return
    nx, ny = -dy / length, dx / length
    offset = max(outer_width_ft * 0.5 - inset_ft, outer_width_ft * 0.10)
    for sign in (1.0, -1.0):
        p1 = (xi + sign * nx * offset, yi + sign * ny * offset)
        p2 = (xj + sign * nx * offset, yj + sign * ny * offset)
        if face_y_i is not None:
            p1 = _intersect_y(p1, p2, face_y_i)
        if face_y_j is not None:
            p2 = _intersect_y(p1, p2, face_y_j)
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=color, lw=lw, alpha=alpha,
                linestyle=(0, (2.5, 2.5)), dash_capstyle='butt', zorder=zorder)


def _member_center_line(ax, xi, yi, xj, yj, color='#b82b2b', lw=0.9, zorder=50, alpha=1.0):
    ax.plot([xi, xj], [yi, yj], color=color, lw=lw, linestyle=(0, (6.0, 3.0)),
            dash_capstyle='butt', solid_capstyle='butt', zorder=zorder, alpha=alpha)


def _draw_supports(ax, nodes, support_nodes, depth_ft):
    left_support, right_support = support_nodes
    marker_size = depth_ft * 0.18 if depth_ft else 1.0
    x0, y0 = nodes[left_support]
    xr, yr = nodes[right_support]
    ax.add_patch(plt.Polygon(
        [[x0, y0], [x0 - marker_size, y0 - marker_size * 1.4], [x0 + marker_size, y0 - marker_size * 1.4]],
        closed=True, fc='#26a65b', ec='#1a7d42', zorder=7))
    ax.plot([x0 - marker_size * 1.1, x0 + marker_size * 1.1],
            [y0 - marker_size * 1.4, y0 - marker_size * 1.4], color='#1a7d42', lw=2, zorder=7)
    ax.text(x0, y0 - marker_size * 2.0, 'PIN', ha='center', fontsize=8, color='#26a65b', fontweight='bold')
    ax.add_patch(plt.Polygon(
        [[xr, yr], [xr - marker_size, yr - marker_size * 1.4], [xr + marker_size, yr - marker_size * 1.4]],
        closed=True, fc='#26a65b', ec='#1a7d42', zorder=7))
    ax.add_patch(plt.Circle((xr, yr - marker_size * 1.4 - marker_size * 0.6), marker_size * 0.5,
                            fc='#26a65b', ec='#1a7d42', zorder=7))
    ax.text(xr, yr - marker_size * 2.6, 'ROLLER', ha='center', fontsize=8, color='#26a65b', fontweight='bold')


def _draw_loads(ax, nodes, n_panels, loads, depth_ft):
    if not loads:
        return
    max_load = max((abs(load[1]) for load in loads.values()), default=1.0)
    arrow_height = depth_ft * 0.50 if depth_ft else 1.0
    top_xs = [nodes[n_panels + 1 + index][0] for index in range(n_panels + 1)]
    y_line = depth_ft + arrow_height * 0.15
    ax.plot([min(top_xs), max(top_xs)], [y_line, y_line], color='#c0392b', lw=2.5, zorder=7)
    for node_id, (_, load_y) in loads.items():
        if abs(load_y) < 1e-9:
            continue
        x, y = nodes[node_id]
        length = arrow_height * abs(load_y) / max_load
        ax.annotate('', xy=(x, y), xytext=(x, y + length),
                    arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.5, mutation_scale=12), zorder=8)


def _draw_dimensions(ax, span_ft, depth_ft):
    y_dim = -depth_ft * 0.45
    x_dim = -span_ft * 0.055
    ax.annotate('', xy=(span_ft, y_dim), xytext=(0, y_dim),
                arrowprops=dict(arrowstyle='<->', color='#444455', lw=1.0))
    ax.text(span_ft / 2.0, y_dim - depth_ft * 0.10,
            'Span = %.2f ft  (%.0f in)' % (span_ft, span_ft * 12.0),
            ha='center', va='top', fontsize=8.5, color='#222233')
    ax.annotate('', xy=(x_dim, depth_ft), xytext=(x_dim, 0),
                arrowprops=dict(arrowstyle='<->', color='#444455', lw=1.0))
    ax.text(x_dim - span_ft * 0.005, depth_ft / 2.0, 'd = %.2f ft' % depth_ft,
            ha='right', va='center', fontsize=8.5, color='#222233', rotation=90)


def _draw_section_labels(ax, nodes, members, hide_verticals, right_support_node):
    type_members = {}
    for member in members:
        section = member.get('section')
        if section is None:
            continue
        if hide_verticals and member.get('type') == 'VERTICAL':
            continue
        if hide_verticals and member.get('type') == 'BOTTOM_CHORD' and (member.get('i') == 0 or member.get('j') == right_support_node):
            continue
        type_members.setdefault(member['type'], []).append(member)
    for member_type, member_group in type_members.items():
        labeled = member_group if member_type in ('DIAGONAL', 'VERTICAL') else [member_group[len(member_group) // 2]]
        for member in labeled:
            xi, yi = nodes[member['i']]
            xj, yj = nodes[member['j']]
            angle = math.degrees(math.atan2(yj - yi, xj - xi))
            if angle > 90:
                angle -= 180
            if angle < -90:
                angle += 180
            ax.text((xi + xj) / 2.0, (yi + yj) / 2.0, member['section']['name'],
                    ha='center', va='center', fontsize=10.0, color='white', fontweight='bold',
                    rotation=angle, rotation_mode='anchor', zorder=10,
                    bbox=dict(fc='#1e2438', ec='none', alpha=0.78, pad=0.9))


def display_panels_from_internal(n_panels, truss_type='Warren w/ Verticals'):
    n_panels = int(n_panels)
    if truss_type == 'Warren w/ Verticals':
        return max(2, n_panels // 2)
    return max(4, n_panels)


def internal_panels_from_display(display_panels, truss_type='Warren w/ Verticals'):
    display_panels = int(display_panels)
    if truss_type == 'Warren w/ Verticals':
        return max(4, display_panels * 2)
    return max(4, display_panels)


def default_depth(span_ft):
    return recommended_depth(span_ft)


def default_display_panels(span_ft, truss_type):
    return display_panels_from_internal(recommended_panels(span_ft), truss_type)


def section_options():
    return ['Auto'] + [section['name'] for section in SECTIONS_BY_AREA]


def build_override_sections(selected_names):
    overrides = {}
    for member_type, section_name in selected_names.items():
        if section_name and section_name != 'Auto':
            overrides[member_type] = copy.deepcopy(SECTIONS[section_name])
    return overrides


def build_member_schedule_rows(members):
    rows = []
    for index, member in enumerate(members, start=1):
        section = member.get('section', {})
        weight_lb = section.get('wt', 0.0) * member.get('length_ft', 0.0)
        if member.get('DCR', 0.0) > 1.0:
            status = 'OVER'
        elif member.get('slender', False):
            status = 'SLENDER'
        else:
            status = 'OK'
        rows.append({
            '#': index,
            'Type': member.get('type', ''),
            'Section': section.get('name', 'N/A'),
            'L_ft': round(member.get('length_ft', 0.0), 3),
            'Force_kips': round(member.get('force', 0.0), 2),
            'Capacity_kips': round(member.get('capacity', 0.0), 2),
            'DCR': round(member.get('DCR', 0.0), 4),
            'Role': member.get('role', ''),
            'b_t': round(member.get('bt', 0.0), 2),
            'b_t_limit': round(member.get('bt_limit', 0.0), 2),
            'Weight_lb': round(weight_lb, 2),
            'Status': status,
        })
    return rows


def build_member_schedule_csv(members):
    output = io.StringIO()
    output.write('#,Type,Section,L_ft,Force_kips,Capacity_kips,DCR,Role,b_t,b_t_limit,Weight_lb,Status\n')
    for row in build_member_schedule_rows(members):
        output.write(
            f"{row['#']},{row['Type']},{row['Section']},{row['L_ft']:.3f},{row['Force_kips']:.2f},"
            f"{row['Capacity_kips']:.2f},{row['DCR']:.4f},{row['Role']},{row['b_t']:.2f},"
            f"{row['b_t_limit']:.2f},{row['Weight_lb']:.2f},{row['Status']}\n"
        )
    return output.getvalue()


def build_report(span_ft, dl_kpf, ll_kpf, wu_kpf, depth_ft, n_panels,
                 truss_type, defl_limit, summary, members):
    display_panels = display_panels_from_internal(n_panels, truss_type)
    lines = []
    sep = '=' * 72
    sep2 = '-' * 72
    lines += [
        sep,
        '  HSS TRUSS DESIGNER  -  WEB DESIGN REPORT',
        '  Kerkhoff Engineering',
        '  Generated: ' + datetime.now().strftime('%Y-%m-%d  %H:%M'),
        sep,
        '',
    ]
    lines += [
        'DESIGN INPUTS', sep2,
        '  Truss Type          : %s' % truss_type,
        '  Span                : %.2f ft  (%.0f in)' % (span_ft, span_ft * 12),
        '  Depth               : %.2f ft  (%.0f in)' % (depth_ft, depth_ft * 12),
        '  Top Panels          : %d' % display_panels,
        '  Panel Length        : %.2f ft  (%.1f in)' % (span_ft / n_panels, span_ft / n_panels * 12),
        '  Dead Load (service) : %.3f kip/ft' % dl_kpf,
        '  Live Load (service) : %.3f kip/ft' % ll_kpf,
        '  Factored Load (wu)  : %.3f kip/ft  [1.25D + 1.5L]' % wu_kpf,
        '  Deflection Limit    : L / %d' % defl_limit,
        '',
    ]
    top_chord = summary.get('top_chord')
    bottom_chord = summary.get('bottom_chord')
    web = summary.get('web')
    reactions = summary.get('reactions', {})
    left_support, right_support = summary.get('support_nodes', (0, n_panels))
    reaction_left = reactions.get(left_support, [0, 0])
    reaction_right = reactions.get(right_support, [0, 0])
    defl_ratio = summary.get('defl_ratio', 9999)
    defl_ok = summary.get('defl_ok', True)
    max_dcr = max(member.get('DCR', 0.0) for member in members)
    total_weight_lbs = summary.get('total_weight_lbs', 0.0)
    weight_breakdown = summary.get('weight_breakdown', {})
    cost_estimate = total_weight_lbs * STEEL_COST_PER_LB
    lines += [
        'GOVERNING SECTIONS', sep2,
        '  Top Chord    : %s' % (top_chord['name'] if top_chord else 'N/A'),
        '  Bottom Chord : %s' % (bottom_chord['name'] if bottom_chord else 'N/A'),
        '  Web Members  : %s' % (web['name'] if web else 'N/A'),
        '',
    ]
    lines += [
        'DESIGN SUMMARY', sep2,
        '  Reactions    : Left = %.2f kips  |  Right = %.2f kips' % (abs(reaction_left[1]), abs(reaction_right[1])),
        '  Max Defl.    : %.4f in   (L / %.0f)   [Limit L/%d  ->  %s]' % (
            summary.get('max_defl_in', 0.0), defl_ratio, defl_limit, 'PASS' if defl_ok else 'FAIL'),
        '  Max DCR      : %.3f   [%s]' % (max_dcr, 'PASS' if max_dcr <= 1.0 else 'FAIL'),
        '  Total Weight : %.0f lb   (%.1f plf)' % (total_weight_lbs, total_weight_lbs / span_ft),
        '    Top Chord  : %.0f lb' % weight_breakdown.get('TOP_CHORD', 0.0),
        '    Bot. Chord : %.0f lb' % weight_breakdown.get('BOTTOM_CHORD', 0.0),
        '    Diagonals  : %.0f lb' % weight_breakdown.get('DIAGONAL', 0.0),
        '    Verticals  : %.0f lb' % weight_breakdown.get('VERTICAL', 0.0),
        '  Est. Cost    : $%.0f  (@ $%.2f/lb installed)' % (cost_estimate, STEEL_COST_PER_LB),
        '',
    ]
    lines += ['MEMBER SCHEDULE', sep2]
    header = ('%-4s  %-14s  %-18s  %7s  %9s  %9s  %7s  %-12s  %5s  %-8s' %
              ('#', 'Type', 'Section', 'L (ft)', 'Force(k)', 'Cap.(k)', 'DCR', 'Role', 'b/t', 'Status'))
    lines += [header, '-' * len(header)]
    for index, member in enumerate(members, start=1):
        section = member.get('section', {})
        status = 'OVER' if member.get('DCR', 0.0) > 1.0 else ('SLENDER' if member.get('slender', False) else 'OK')
        lines.append(
            '%-4d  %-14s  %-18s  %7.2f  %9.1f  %9.1f  %7.3f  %-12s  %5.1f  %-8s' % (
                index,
                member.get('type', ''),
                section.get('name', 'N/A'),
                member.get('length_ft', 0.0),
                member.get('force', 0.0),
                member.get('capacity', 0.0),
                member.get('DCR', 0.0),
                member.get('role', ''),
                member.get('bt', 0.0),
                status,
            )
        )
    lines += ['', sep, '  END OF REPORT', sep]
    return '\n'.join(lines)


def run_design(span_ft, dl_kpf, ll_kpf, depth_ft, display_panels, truss_type,
               defl_limit, override_sections=None):
    wu_kpf = factored_load(dl_kpf, ll_kpf)
    n_panels = internal_panels_from_display(display_panels, truss_type)
    nodes, members = build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels)
    members, summary = design_members(
        members,
        nodes,
        n_panels,
        wu_kpf,
        override_sections=override_sections or {},
        defl_limit=defl_limit,
        truss_type=truss_type,
    )
    report_text = build_report(
        span_ft,
        dl_kpf,
        ll_kpf,
        wu_kpf,
        depth_ft,
        n_panels,
        truss_type,
        defl_limit,
        summary,
        members,
    )
    max_dcr = max(member.get('DCR', 0.0) for member in members)
    warnings = []
    overstressed = [member for member in members if member.get('DCR', 0.0) > 1.0]
    slender = [member for member in members if member.get('slender', False)]
    if overstressed:
        warnings.append(f'{len(overstressed)} members exceed DCR 1.0.')
    if slender:
        warnings.append(f'{len(slender)} members exceed local slenderness limits.')
    if not summary.get('defl_ok', True):
        warnings.append(f"Deflection exceeds L/{defl_limit}.")
    return {
        'span_ft': span_ft,
        'dl_kpf': dl_kpf,
        'll_kpf': ll_kpf,
        'wu_kpf': wu_kpf,
        'depth_ft': depth_ft,
        'display_panels': display_panels,
        'n_panels': n_panels,
        'truss_type': truss_type,
        'defl_limit': defl_limit,
        'nodes': nodes,
        'members': members,
        'summary': summary,
        'report_text': report_text,
        'schedule_rows': build_member_schedule_rows(members),
        'schedule_csv': build_member_schedule_csv(members),
        'similar_designs': db.find_similar(span_ft, wu_kpf),
        'max_dcr': max_dcr,
        'warnings': warnings,
    }


def optimize_design(span_ft, dl_kpf, ll_kpf, base_depth_ft, base_display_panels,
                    truss_type, defl_limit, override_sections=None):
    wu_kpf = factored_load(dl_kpf, ll_kpf)
    base_panels = internal_panels_from_display(base_display_panels, truss_type)
    depths = sorted(set(max(2.0, round(base_depth_ft * factor * 12.0) / 12.0)
                        for factor in (0.75, 0.875, 1.0, 1.125, 1.25, 1.5)))
    panel_candidates = sorted(set(max(4, base_panels + delta) for delta in (-2, -1, 0, 1, 2)))

    best_result = None
    best_weight = float('inf')
    for depth_ft in depths:
        for n_panels in panel_candidates:
            try:
                nodes, members = build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels)
                designed_members, summary = design_members(
                    members,
                    nodes,
                    n_panels,
                    wu_kpf,
                    override_sections=override_sections or {},
                    defl_limit=defl_limit,
                    truss_type=truss_type,
                )
            except Exception:
                continue
            if max(member.get('DCR', 0.0) for member in designed_members) > 1.0:
                continue
            if not summary.get('defl_ok', True):
                continue
            total_weight = summary.get('total_weight_lbs', float('inf'))
            if total_weight < best_weight:
                best_weight = total_weight
                best_result = (depth_ft, display_panels_from_internal(n_panels, truss_type))

    if best_result is None:
        raise ValueError('No valid design found in the current optimization search space.')

    best_depth_ft, best_display_panels = best_result
    optimized = run_design(
        span_ft,
        dl_kpf,
        ll_kpf,
        best_depth_ft,
        best_display_panels,
        truss_type,
        defl_limit,
        override_sections=override_sections,
    )
    optimized['optimization_note'] = (
        'Minimum-weight design found at %.2f ft depth, %d top panels, %.0f lb total weight.' % (
            best_depth_ft,
            best_display_panels,
            optimized['summary']['total_weight_lbs'],
        )
    )
    return optimized


def save_result_to_database(result, notes=''):
    summary = result['summary']
    top_chord = summary.get('top_chord')
    bottom_chord = summary.get('bottom_chord')
    web = summary.get('web')
    return db.save_design(
        span_ft=result['span_ft'],
        load_kpf=result['wu_kpf'],
        depth_ft=result['depth_ft'],
        n_panels=result['n_panels'],
        top_chord=top_chord['name'] if top_chord else 'N/A',
        bottom_chord=bottom_chord['name'] if bottom_chord else 'N/A',
        web=web['name'] if web else 'N/A',
        total_weight_lbs=summary.get('total_weight_lbs', 0.0),
        max_defl_in=summary.get('max_defl_in', 0.0),
        defl_ratio=summary.get('defl_ratio', 0.0),
        notes=notes + '  [DL=%.3f LL=%.3f]' % (result['dl_kpf'], result['ll_kpf']),
    )


def load_saved_designs():
    return db.load_all()


def create_truss_figure(nodes, members, summary, truss_type, title_suffix=''):
    span = nodes[max(member['j'] for member in members if member['type'] == 'BOTTOM_CHORD')][0]
    depth = max(y for _, y in nodes)
    aspect_ratio = span / max(depth, 1.0)
    figure_height = min(max(6.6, 4.6 + 0.22 * aspect_ratio), 9.4)
    figure, axis = plt.subplots(figsize=(15.5, figure_height))
    figure.patch.set_facecolor('#f1ebdf')
    axis.set_facecolor('#f0f3f8')
    support_nodes = summary.get('display_support_nodes', summary.get('support_nodes', (0, len(nodes) // 2 - 1)))
    real_support_nodes = summary.get('support_nodes', support_nodes)
    right_support_real = real_support_nodes[1]
    hide_verticals = truss_type == 'Warren w/ Verticals'
    top_width_ft = max((member.get('section', {}).get('B', 2.0) / 12.0
                        for member in members if member.get('type') == 'TOP_CHORD'), default=2.0 / 12.0)
    bottom_width_ft = max((member.get('section', {}).get('B', 2.0) / 12.0
                           for member in members if member.get('type') == 'BOTTOM_CHORD'), default=2.0 / 12.0)

    def skip_member(member):
        if hide_verticals and member.get('type') == 'VERTICAL':
            return True
        if hide_verticals and member.get('type') == 'BOTTOM_CHORD' and (member.get('i') == 0 or member.get('j') == right_support_real):
            return True
        return False

    visible_members = [member for member in members if not skip_member(member)]
    for member in visible_members:
        xi, yi = nodes[member['i']]
        xj, yj = nodes[member['j']]
        section = member.get('section') or {}
        width_ft = section.get('B', 2.0) / 12.0
        member_type = member.get('type', '')
        face_y_i = None
        face_y_j = None
        if member_type in ('DIAGONAL', 'VERTICAL'):
            if yi > yj:
                face_y_i = yi - top_width_ft * 0.5
                face_y_j = yj + bottom_width_ft * 0.5
            elif yi < yj:
                face_y_i = yi + bottom_width_ft * 0.5
                face_y_j = yj - top_width_ft * 0.5
        hidden_inset_ft = min(max(width_ft * 0.13, 0.012), width_ft * 0.24)
        if member_type in ('DIAGONAL', 'VERTICAL'):
            _member_face_rect(axis, xi, yi, xj, yj, width_ft, face_y_i=face_y_i, face_y_j=face_y_j, edge='#000000', lw=0.7, zorder=30)
        else:
            _member_rect(axis, xi, yi, xj, yj, width_ft, edge='#000000', lw=0.7, zorder=30)
        _member_hidden_edge(axis, xi, yi, xj, yj, width_ft, hidden_inset_ft, color='#9ea9c7',
                            face_y_i=face_y_i, face_y_j=face_y_j, zorder=35)
        _member_center_line(axis, xi, yi, xj, yj, color='#b82b2b', lw=0.85, zorder=36, alpha=0.92)

    _draw_supports(axis, nodes, support_nodes, depth)
    _draw_loads(axis, nodes, right_support_real, summary.get('loads', {}), depth)
    _draw_dimensions(axis, span, depth)
    _draw_section_labels(axis, nodes, members, hide_verticals, right_support_real)

    total_weight = summary.get('total_weight_lbs', 0.0)
    weight_breakdown = summary.get('weight_breakdown', {})
    max_dcr = max(member.get('DCR', 0.0) for member in members)
    deflection_state = 'PASS' if summary.get('defl_ok', True) else 'FAIL'
    axis.text(
        0.016,
        0.985,
        'Total Weight = %.0f lb  |  DCR max = %.3f\nTop = %.0f lb  |  Bottom = %.0f lb  |  Web = %.0f lb\nDeflection = %.3f in  (%s)' % (
            total_weight,
            max_dcr,
            weight_breakdown.get('TOP_CHORD', 0.0),
            weight_breakdown.get('BOTTOM_CHORD', 0.0),
            weight_breakdown.get('DIAGONAL', 0.0) + weight_breakdown.get('VERTICAL', 0.0),
            summary.get('max_defl_in', 0.0),
            deflection_state,
        ),
        transform=axis.transAxes,
        ha='left',
        va='top',
        fontsize=9.2,
        color='#1f2a44',
        fontweight='bold',
        bbox=dict(fc='white', ec='#cdd4e5', alpha=0.95, pad=0.55),
    )

    axis.set_title('Truss Geometry%s' % (f' | {title_suffix}' if title_suffix else ''), fontsize=13, fontweight='bold', pad=12)
    axis.set_xlabel('Length (ft)', fontsize=10)
    axis.set_ylabel('Height (ft)', fontsize=10)
    axis.tick_params(labelsize=8)
    axis.grid(True, alpha=0.08, linestyle='--')
    axis.set_aspect('equal', adjustable='datalim')
    axis.set_anchor('C')
    margin_x = max(span * 0.10, 2.0)
    margin_top = max(depth * 0.90, 2.5)
    margin_bottom = max(depth * 0.85, 2.0)
    axis.set_xlim(-margin_x, span + margin_x)
    axis.set_ylim(-margin_bottom, depth + margin_top)
    figure.subplots_adjust(left=0.055, right=0.985, bottom=0.11, top=0.92)
    return figure


def create_truss_interactive_figure(nodes, members, summary, truss_type, title_suffix=''):
    span = nodes[max(member['j'] for member in members if member['type'] == 'BOTTOM_CHORD')][0]
    depth = max(y for _, y in nodes)
    support_nodes = summary.get('display_support_nodes', summary.get('support_nodes', (0, len(nodes) // 2 - 1)))
    real_support_nodes = summary.get('support_nodes', support_nodes)
    right_support_real = real_support_nodes[1]
    hide_verticals = truss_type == 'Warren w/ Verticals'
    top_width_ft = max((member.get('section', {}).get('B', 2.0) / 12.0
                        for member in members if member.get('type') == 'TOP_CHORD'), default=2.0 / 12.0)
    bottom_width_ft = max((member.get('section', {}).get('B', 2.0) / 12.0
                           for member in members if member.get('type') == 'BOTTOM_CHORD'), default=2.0 / 12.0)

    def skip_member(member):
        if hide_verticals and member.get('type') == 'VERTICAL':
            return True
        if hide_verticals and member.get('type') == 'BOTTOM_CHORD' and (member.get('i') == 0 or member.get('j') == right_support_real):
            return True
        return False

    figure = go.Figure()
    palette = {
        'TOP_CHORD': '#23395b',
        'BOTTOM_CHORD': '#406e8e',
        'DIAGONAL': '#8a5a44',
        'VERTICAL': '#6b9080',
    }

    for member in members:
        if skip_member(member):
            continue
        xi, yi = nodes[member['i']]
        xj, yj = nodes[member['j']]
        section = member.get('section') or {}
        width_ft = section.get('B', 2.0) / 12.0
        dx, dy = xj - xi, yj - yi
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-9:
            continue
        hx, hy = -dy / length * width_ft / 2.0, dx / length * width_ft / 2.0
        face_y_i = None
        face_y_j = None
        if member.get('type') in ('DIAGONAL', 'VERTICAL'):
            if yi > yj:
                face_y_i = yi - top_width_ft * 0.5
                face_y_j = yj + bottom_width_ft * 0.5
            elif yi < yj:
                face_y_i = yi + bottom_width_ft * 0.5
                face_y_j = yj - top_width_ft * 0.5
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
        xs = [i_plus[0], i_minus[0], j_minus[0], j_plus[0], i_plus[0]]
        ys = [i_plus[1], i_minus[1], j_minus[1], j_plus[1], i_plus[1]]
        hover = '%s<br>%s<br>Force %.2f k<br>DCR %.3f' % (
            member.get('type', ''),
            section.get('name', 'N/A'),
            member.get('force', 0.0),
            member.get('DCR', 0.0),
        )
        figure.add_trace(go.Scatter(
            x=xs,
            y=ys,
            mode='lines',
            fill='toself',
            line=dict(color='#0c111a', width=1.2),
            fillcolor=palette.get(member.get('type'), '#495057'),
            opacity=0.96,
            hovertemplate=hover + '<extra></extra>',
            showlegend=False,
        ))
        figure.add_trace(go.Scatter(
            x=[xi, xj],
            y=[yi, yj],
            mode='lines',
            line=dict(color='#b82b2b', width=1, dash='dash'),
            hoverinfo='skip',
            showlegend=False,
        ))

    visible_nodes = sorted({node_id for member in members if not skip_member(member) for node_id in (member['i'], member['j'])})
    figure.add_trace(go.Scatter(
        x=[nodes[idx][0] for idx in visible_nodes],
        y=[nodes[idx][1] for idx in visible_nodes],
        mode='markers',
        marker=dict(size=5, color='#102542'),
        hoverinfo='skip',
        showlegend=False,
    ))

    left_support, right_support = support_nodes
    lx, ly = nodes[left_support]
    rx, ry = nodes[right_support]
    figure.add_trace(go.Scatter(x=[lx], y=[ly - depth * 0.05], mode='markers', marker=dict(size=18, color='#26a65b', symbol='triangle-up'), name='Pin'))
    figure.add_trace(go.Scatter(x=[rx], y=[ry - depth * 0.05], mode='markers', marker=dict(size=15, color='#26a65b', symbol='circle'), name='Roller'))

    for node_id, (_, load_y) in summary.get('loads', {}).items():
        if abs(load_y) < 1e-9:
            continue
        x, y = nodes[node_id]
        figure.add_annotation(
            x=x,
            y=y,
            ax=x,
            ay=y + depth * 0.32,
            xref='x',
            yref='y',
            axref='x',
            ayref='y',
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1.8,
            arrowcolor='#c0392b',
        )

    total_weight = summary.get('total_weight_lbs', 0.0)
    max_dcr = max(member.get('DCR', 0.0) for member in members)
    figure.add_annotation(
        xref='paper',
        yref='paper',
        x=0.012,
        y=0.99,
        text='Weight %.0f lb | Max DCR %.3f | Defl %.3f in' % (total_weight, max_dcr, summary.get('max_defl_in', 0.0)),
        showarrow=False,
        align='left',
        font=dict(size=12, color='#1f2a44'),
        bgcolor='rgba(255,255,255,0.92)',
        bordercolor='#cdd4e5',
        borderpad=6,
    )

    margin_x = max(span * 0.10, 2.0)
    margin_top = max(depth * 0.90, 2.5)
    margin_bottom = max(depth * 0.85, 2.0)
    figure.update_layout(
        title='Truss Geometry%s' % (f' | {title_suffix}' if title_suffix else ''),
        paper_bgcolor='#f1ebdf',
        plot_bgcolor='#f0f3f8',
        margin=dict(l=25, r=25, t=65, b=35),
        xaxis=dict(title='Length (ft)', range=[-margin_x, span + margin_x], showgrid=True, gridcolor='rgba(0,0,0,0.07)', zeroline=False),
        yaxis=dict(title='Height (ft)', range=[-margin_bottom, depth + margin_top], showgrid=True, gridcolor='rgba(0,0,0,0.07)', zeroline=False, scaleanchor='x', scaleratio=1),
        hovermode='closest',
        showlegend=False,
        dragmode='pan',
    )
    return figure


def create_force_figure(members):
    figure, axis = plt.subplots(figsize=(10.5, 4.2))
    axis.set_facecolor('#f7f5ef')
    labels = []
    forces = []
    colors = []
    counts = {}
    type_short = {'BOTTOM_CHORD': 'BC', 'TOP_CHORD': 'TC', 'VERTICAL': 'V', 'DIAGONAL': 'D'}
    for member in members:
        member_type = member['type']
        counts[member_type] = counts.get(member_type, 0) + 1
        labels.append('%s%d' % (type_short[member_type], counts[member_type]))
        force = member.get('force', 0.0)
        forces.append(force)
        colors.append('#2a6f97' if force >= 0 else '#bc4749')
    positions = np.arange(len(labels))
    axis.bar(positions, forces, color=colors, edgecolor='white', linewidth=0.6)
    axis.axhline(0.0, color='#222222', linewidth=0.8)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=90, fontsize=7)
    axis.set_ylabel('Axial Force (kips)')
    axis.set_title('Member Forces')
    axis.grid(True, axis='y', alpha=0.22, linestyle='--')
    figure.tight_layout()
    return figure


def create_dcr_figure(members):
    figure, axis = plt.subplots(figsize=(10.5, 4.2))
    axis.set_facecolor('#f7f5ef')
    labels = []
    values = []
    colors = []
    counts = {}
    type_short = {'BOTTOM_CHORD': 'BC', 'TOP_CHORD': 'TC', 'VERTICAL': 'V', 'DIAGONAL': 'D'}
    for member in members:
        member_type = member['type']
        counts[member_type] = counts.get(member_type, 0) + 1
        labels.append('%s%d' % (type_short[member_type], counts[member_type]))
        dcr = member.get('DCR', 0.0)
        values.append(min(dcr, 1.5))
        if dcr > 1.0:
            colors.append('#bc4749')
        elif dcr > 0.8:
            colors.append('#dd6b20')
        elif dcr > 0.5:
            colors.append('#e9c46a')
        else:
            colors.append('#2a9d8f')
    positions = np.arange(len(labels))
    axis.bar(positions, values, color=colors, edgecolor='white', linewidth=0.6)
    axis.axhline(1.0, color='#9b2226', linewidth=1.4, linestyle='--')
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=90, fontsize=7)
    axis.set_ylabel('DCR')
    axis.set_title('Demand / Capacity')
    axis.grid(True, axis='y', alpha=0.22, linestyle='--')
    figure.tight_layout()
    return figure


def create_deflection_figure(nodes, members, n_panels, disps_in, defl_ratio, defl_limit):
    figure, axis = plt.subplots(figsize=(10.5, 4.2))
    axis.set_facecolor('#f7f5ef')
    span = nodes[n_panels][0]
    depth = nodes[n_panels + 1][1]
    max_deflection_ft = max(abs(displacement[1]) for displacement in disps_in) / 12.0
    if max_deflection_ft < 1e-6:
        axis.text(0.5, 0.5, 'No deflection data', ha='center', va='center', transform=axis.transAxes)
        return figure
    scale = depth * 0.4 / max_deflection_ft if depth else 1.0
    for member in members:
        xi, yi = nodes[member['i']]
        xj, yj = nodes[member['j']]
        axis.plot([xi, xj], [yi, yj], color='#b8c0d9', linewidth=0.9, alpha=0.7)

    def displaced_node(node_index):
        x, y = nodes[node_index]
        return (
            x + disps_in[node_index][0] / 12.0 * scale,
            y + disps_in[node_index][1] / 12.0 * scale,
        )

    for member in members:
        xi, yi = displaced_node(member['i'])
        xj, yj = displaced_node(member['j'])
        axis.plot([xi, xj], [yi, yj], color='#bc4749', linewidth=1.8)

    axis.set_xlim(-span * 0.05, span * 1.05)
    axis.set_ylim(-depth * 0.45, depth * 1.35)
    axis.set_xlabel('Length (ft)')
    axis.set_ylabel('Height (ft, exaggerated)')
    axis.set_title('Deflected Shape | Max = %.3f in | L/%.0f vs L/%d' % (
        max_deflection_ft * 12.0,
        defl_ratio,
        defl_limit,
    ))
    axis.grid(True, alpha=0.18, linestyle='--')
    undeformed = mpatches.Patch(color='#b8c0d9', label='Undeformed')
    deflected = mpatches.Patch(color='#bc4749', label='Deflected')
    axis.legend(handles=[undeformed, deflected], fontsize=8)
    figure.tight_layout()
    return figure