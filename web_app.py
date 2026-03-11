import socket

import pandas as pd
import streamlit as st

from webapp_core import (
    DEFLECTION_LIMITS,
    TRUSS_TYPES,
    build_override_sections,
    create_dcr_figure,
    create_deflection_figure,
    create_force_figure,
    create_truss_figure,
    create_truss_interactive_figure,
    default_depth,
    default_display_panels,
    load_saved_designs,
    optimize_design,
    run_design,
    save_result_to_database,
    section_options,
)


st.set_page_config(
    page_title='HSS Truss Designer',
    page_icon='//',
    layout='wide',
    initial_sidebar_state='expanded',
)


st.markdown(
    """
    <style>
    :root {
        --canvas: #161b28;
        --panel: rgba(28, 36, 55, 0.90);
        --panel-2: rgba(34, 40, 64, 0.92);
        --ink: #dce6f0;
        --muted: #8ea1bc;
        --accent: #4a9eff;
        --accent-2: #26c6da;
        --line: rgba(144, 168, 196, 0.16);
        --ok: #2a9d8f;
        --warn: #dd6b20;
        --danger: #bc4749;
    }
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(74,158,255,0.18), transparent 30%),
            radial-gradient(circle at top right, rgba(38,198,218,0.12), transparent 34%),
            linear-gradient(180deg, #101521 0%, #171d2c 45%, #141a28 100%);
        color: var(--ink);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1c2437 0%, #202844 100%);
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] * {
        color: var(--ink);
    }
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2rem;
        max-width: 1560px;
    }
    .hero-card, .status-card, .surface-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 1.15rem 1.25rem;
        backdrop-filter: blur(10px);
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.20);
    }
    .hero-title {
        font-size: 2.35rem;
        font-weight: 700;
        letter-spacing: -0.03em;
        margin-bottom: 0.25rem;
        color: #f5fbff;
    }
    .hero-subtitle {
        color: var(--muted);
        font-size: 1rem;
    }
    .metric-card {
        background: var(--panel-2);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 0.8rem 0.95rem;
        min-height: 104px;
    }
    .metric-label {
        font-size: 0.78rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        margin-top: 0.2rem;
        color: #f5fbff;
    }
    .status-ok {
        border-left: 6px solid var(--ok);
    }
    .status-warn {
        border-left: 6px solid var(--warn);
    }
    .small-note {
        color: var(--muted);
        font-size: 0.92rem;
    }
    .section-title {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: var(--accent-2);
        margin-bottom: 0.3rem;
        font-weight: 700;
    }
    .stat-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.8rem;
    }
    .stat-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 0.85rem 0.95rem;
    }
    .stat-card strong {
        display: block;
        font-size: 1rem;
        margin-top: 0.18rem;
        color: #f5fbff;
    }
    .geometry-card {
        padding: 0.75rem 0.85rem 0.4rem 0.85rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.45rem;
        margin-top: 0.35rem;
    }
    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.04);
        border: 1px solid var(--line);
        border-radius: 999px;
        color: var(--ink);
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(74,158,255,0.18);
        border-color: rgba(74,158,255,0.34);
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 18px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_metric_card(label, value):
    st.markdown(
        '<div class="metric-card"><div class="metric-label">%s</div><div class="metric-value">%s</div></div>' % (label, value),
        unsafe_allow_html=True,
    )


def render_stat_block(items):
    blocks = []
    for label, value in items:
        blocks.append('<div class="stat-card"><span class="small-note">%s</span><strong>%s</strong></div>' % (label, value))
    st.markdown('<div class="stat-grid">%s</div>' % ''.join(blocks), unsafe_allow_html=True)


def current_hostname():
    return socket.gethostname()


def collect_inputs():
    options = section_options()
    with st.sidebar:
        st.markdown('## Design Inputs')
        st.caption('Run this on the server, then let colleagues open http://%s:8501' % current_hostname())
        with st.form('design_inputs'):
            truss_type = st.selectbox('Truss type', TRUSS_TYPES, index=0)
            span_ft = st.number_input('Span (ft)', min_value=10.0, value=60.0, step=1.0)
            dl_kpf = st.number_input('Dead load (kip/ft)', min_value=0.0, value=0.90, step=0.05, format='%.3f')
            ll_kpf = st.number_input('Live load (kip/ft)', min_value=0.0, value=0.60, step=0.05, format='%.3f')
            auto_depth = st.checkbox('Auto depth', value=True)
            suggested_depth = default_depth(span_ft)
            depth_ft = suggested_depth if auto_depth else st.number_input('Depth (ft)', min_value=2.0, value=float(suggested_depth), step=0.5)
            auto_panels = st.checkbox('Auto top panels', value=True)
            suggested_panels = default_display_panels(span_ft, truss_type)
            display_panels = suggested_panels if auto_panels else int(st.number_input('Top panels', min_value=2, value=int(suggested_panels), step=1))
            defl_limit = st.selectbox('Deflection limit', DEFLECTION_LIMITS, index=2, format_func=lambda value: 'L / %d' % value)
            st.markdown('### Section Overrides')
            top_override = st.selectbox('Top chord', options, index=0)
            bottom_override = st.selectbox('Bottom chord', options, index=0)
            diagonal_override = st.selectbox('Diagonal', options, index=0)
            vertical_override = st.selectbox('Vertical', options, index=0)
            col1, col2 = st.columns(2)
            calculate_clicked = col1.form_submit_button('Calculate', use_container_width=True)
            optimize_clicked = col2.form_submit_button('Optimize', use_container_width=True)

    overrides = build_override_sections({
        'TOP_CHORD': top_override,
        'BOTTOM_CHORD': bottom_override,
        'DIAGONAL': diagonal_override,
        'VERTICAL': vertical_override,
    })
    return {
        'truss_type': truss_type,
        'span_ft': span_ft,
        'dl_kpf': dl_kpf,
        'll_kpf': ll_kpf,
        'depth_ft': depth_ft,
        'display_panels': display_panels,
        'defl_limit': defl_limit,
        'overrides': overrides,
        'calculate_clicked': calculate_clicked,
        'optimize_clicked': optimize_clicked,
        'auto_depth': auto_depth,
        'auto_panels': auto_panels,
        'suggested_depth': suggested_depth,
        'suggested_panels': suggested_panels,
    }


inputs = collect_inputs()

if 'result' not in st.session_state:
    st.session_state['result'] = None

if inputs['calculate_clicked']:
    try:
        st.session_state['result'] = run_design(
            inputs['span_ft'],
            inputs['dl_kpf'],
            inputs['ll_kpf'],
            inputs['depth_ft'],
            inputs['display_panels'],
            inputs['truss_type'],
            inputs['defl_limit'],
            override_sections=inputs['overrides'],
        )
        st.session_state['flash_message'] = 'Design updated.'
    except Exception as error:
        st.session_state['flash_error'] = str(error)

if inputs['optimize_clicked']:
    try:
        st.session_state['result'] = optimize_design(
            inputs['span_ft'],
            inputs['dl_kpf'],
            inputs['ll_kpf'],
            inputs['depth_ft'],
            inputs['display_panels'],
            inputs['truss_type'],
            inputs['defl_limit'],
            override_sections=inputs['overrides'],
        )
        st.session_state['flash_message'] = st.session_state['result'].get('optimization_note', 'Optimization completed.')
    except Exception as error:
        st.session_state['flash_error'] = str(error)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-title">HSS Truss Designer</div>
        <div class="hero-subtitle">LAN-hosted design workstation for internal engineering use. The browser edition now mirrors the desktop workflow more closely and keeps the truss view front and center.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if inputs['auto_depth'] or inputs['auto_panels']:
    note_parts = []
    if inputs['auto_depth']:
        note_parts.append('Auto depth = %.2f ft' % inputs['suggested_depth'])
    if inputs['auto_panels']:
        note_parts.append('Auto top panels = %d' % inputs['suggested_panels'])
    st.markdown('<p class="small-note">%s</p>' % ' | '.join(note_parts), unsafe_allow_html=True)

if st.session_state.get('flash_error'):
    st.error(st.session_state.pop('flash_error'))
if st.session_state.get('flash_message'):
    st.success(st.session_state.pop('flash_message'))

result = st.session_state.get('result')
if result is None:
    st.info('Enter the truss inputs in the sidebar, then choose Calculate or Optimize.')
    st.stop()

summary = result['summary']
status_class = 'status-ok' if not result['warnings'] else 'status-warn'
status_text = 'Ready for review.' if not result['warnings'] else 'Warnings: ' + ' '.join(result['warnings'])

st.markdown('<div class="status-card %s">%s</div>' % (status_class, status_text), unsafe_allow_html=True)

metric_cols = st.columns(4)
with metric_cols[0]:
    render_metric_card('Total Weight', '%.0f lb' % summary['total_weight_lbs'])
with metric_cols[1]:
    render_metric_card('Max DCR', '%.3f' % result['max_dcr'])
with metric_cols[2]:
    render_metric_card('Max Deflection', '%.3f in' % summary['max_defl_in'])
with metric_cols[3]:
    render_metric_card('Factored Load', '%.3f k/ft' % result['wu_kpf'])

tab_overview, tab_plots, tab_schedule, tab_report, tab_database = st.tabs([
    'Overview', 'Plots', 'Schedule', 'Report', 'Database'
])

with tab_overview:
    st.markdown('<div class="surface-card geometry-card">', unsafe_allow_html=True)
    truss_figure = create_truss_interactive_figure(result['nodes'], result['members'], summary, result['truss_type'])
    st.plotly_chart(
        truss_figure,
        use_container_width=True,
        config={
            'scrollZoom': True,
            'displaylogo': False,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
        },
    )
    st.markdown('</div>', unsafe_allow_html=True)

    summary_col1, summary_col2, summary_col3 = st.columns([1.05, 1.05, 1.15])
    with summary_col1:
        st.markdown('<div class="surface-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Governing Sections</div>', unsafe_allow_html=True)
        render_stat_block([
            ('Top chord', summary['top_chord']['name']),
            ('Bottom chord', summary['bottom_chord']['name']),
            ('Web', summary['web']['name']),
            ('Top panels', str(result['display_panels'])),
        ])
        st.markdown('</div>', unsafe_allow_html=True)
    with summary_col2:
        st.markdown('<div class="surface-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Performance</div>', unsafe_allow_html=True)
        render_stat_block([
            ('Deflection', '%.3f in (L / %.0f)' % (summary['max_defl_in'], summary['defl_ratio'])),
            ('Deflection check', 'PASS' if summary['defl_ok'] else 'FAIL'),
            ('Estimated steel cost', '$%.0f' % (summary['total_weight_lbs'] * 1.25)),
            ('Weight / ft', '%.1f plf' % (summary['total_weight_lbs'] / max(result['span_ft'], 1e-9))),
        ])
        st.markdown('</div>', unsafe_allow_html=True)
    with summary_col3:
        st.markdown('<div class="surface-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Reactions And Notes</div>', unsafe_allow_html=True)
        left_support, right_support = summary['support_nodes']
        left_rxn = abs(summary['reactions'][left_support][1])
        right_rxn = abs(summary['reactions'][right_support][1])
        render_stat_block([
            ('Left reaction', '%.2f kips' % left_rxn),
            ('Right reaction', '%.2f kips' % right_rxn),
            ('Warnings', 'None' if not result['warnings'] else str(len(result['warnings']))),
            ('Truss type', result['truss_type']),
        ])
        if result.get('optimization_note'):
            st.info(result['optimization_note'])
        st.markdown('</div>', unsafe_allow_html=True)
    if result['similar_designs']:
        st.markdown('### Similar Saved Designs')
        st.dataframe(pd.DataFrame(result['similar_designs']), use_container_width=True, hide_index=True)
    else:
        st.caption('No similar saved designs found in the local database.')

with tab_plots:
    plot_col1, plot_col2 = st.columns(2)
    with plot_col1:
        force_figure = create_force_figure(result['members'])
        st.pyplot(force_figure, use_container_width=True)
        deflection_figure = create_deflection_figure(
            result['nodes'],
            result['members'],
            result['n_panels'],
            summary['disps_in'],
            summary['defl_ratio'],
            result['defl_limit'],
        )
        st.pyplot(deflection_figure, use_container_width=True)
    with plot_col2:
        dcr_figure = create_dcr_figure(result['members'])
        st.pyplot(dcr_figure, use_container_width=True)
        st.markdown('### Weight Breakdown')
        weight_df = pd.DataFrame([
            {'Group': key.replace('_', ' ').title(), 'Weight_lb': value}
            for key, value in summary['weight_breakdown'].items()
        ])
        st.dataframe(weight_df, use_container_width=True, hide_index=True)

with tab_schedule:
    st.download_button(
        'Download member schedule (.csv)',
        data=result['schedule_csv'],
        file_name='member_schedule.csv',
        mime='text/csv',
        use_container_width=True,
    )
    st.dataframe(pd.DataFrame(result['schedule_rows']), use_container_width=True, hide_index=True)

with tab_report:
    st.download_button(
        'Download design report (.txt)',
        data=result['report_text'],
        file_name='design_report.txt',
        mime='text/plain',
        use_container_width=True,
    )
    st.text_area('Design report', value=result['report_text'], height=540)

with tab_database:
    notes = st.text_input('Optional notes before saving', key='save_notes')
    if st.button('Save current design to database', use_container_width=True):
        try:
            save_result_to_database(result, notes=notes)
            st.success('Design saved to designs_database.json')
        except Exception as error:
            st.error(str(error))
    saved_designs = load_saved_designs()
    if saved_designs:
        st.markdown('### Saved Designs')
        st.dataframe(pd.DataFrame(saved_designs), use_container_width=True, hide_index=True)
    else:
        st.caption('No saved designs yet.')