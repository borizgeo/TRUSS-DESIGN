# Headless sample design runner
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from engine import build_geometry_for_type, recommended_depth, recommended_panels, factored_load, design_members
import main
import database as db

OUT_DIR = os.path.join(os.path.dirname(__file__), 'sample_output')
os.makedirs(OUT_DIR, exist_ok=True)

# Sample inputs
span_ft = 30.0
depth_ft = recommended_depth(span_ft)
n_panels = recommended_panels(span_ft)
dl_kpf = 0.06
ll_kpf = 0.03
truss_type = 'Warren w/ Verticals'

wu_kpf = factored_load(dl_kpf, ll_kpf)

# Build geometry and design
nodes, members = build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels)
mems, summ = design_members(members, nodes, n_panels, wu_kpf, truss_type=truss_type)

# Plot using the drawing helper from main
fig = plt.figure(figsize=(8, 4.5), dpi=150)
ax = fig.add_subplot(111)
main.draw_truss_view(ax, nodes, mems, n_panels, loads=summ.get('loads'), title='Sample HSS Truss', support_nodes=summ.get('support_nodes'), total_weight_lbs=summ.get('total_weight_lbs'))
img_path = os.path.join(OUT_DIR, 'sample_truss.png')
fig.savefig(img_path, bbox_inches='tight')
plt.close(fig)

# Export member schedule CSV
csv_path = os.path.join(OUT_DIR, 'sample_schedule.csv')
with open(csv_path, 'w', newline='') as f:
    import csv
    writer = csv.writer(f)
    writer.writerow(['#', 'Type', 'Section', 'L_ft', 'Force_kips',
                     'Capacity_kips', 'DCR', 'Role', 'b_t', 'b_t_limit',
                     'Weight_lb', 'Status'])
    for i, m in enumerate(mems):
        sec = m.get('section', {})
        wt = sec.get('wt', 0) * m.get('length_ft', 0)
        writer.writerow([
            i + 1, m['type'], sec.get('name', 'N/A'),
            '%.3f' % m.get('length_ft', 0),
            '%.2f' % m.get('force', 0),
            '%.2f' % m.get('capacity', 0),
            '%.4f' % m.get('DCR', 0),
            m.get('role', ''),
            '%.2f' % m.get('bt', 0), '%.2f' % m.get('bt_limit', 0),
            '%.2f' % wt,
            'OVER' if m.get('DCR', 0) > 1.0 else ('SLENDER' if m.get('slender', False) else 'OK'),
        ])

# Save design to database
db.save_design(span_ft, wu_kpf, depth_ft, n_panels,
               summ.get('top_chord', {}).get('name') if summ.get('top_chord') else 'N/A',
               summ.get('bottom_chord', {}).get('name') if summ.get('bottom_chord') else 'N/A',
               summ.get('web', {}).get('name') if summ.get('web') else 'N/A',
               summ.get('total_weight_lbs', 0), summ.get('max_defl_in', 0), summ.get('defl_ratio', 0), notes='Sample run')

print('Saved:', img_path)
print('CSV:', csv_path)
print('Database entry added to designs_database.json')
