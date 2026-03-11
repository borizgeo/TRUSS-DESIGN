# Minimal headless design runner that avoids importing main
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from engine import build_geometry_for_type, recommended_depth, recommended_panels, factored_load, design_members

OUT_DIR = os.path.join(os.path.dirname(__file__), 'sample_output')
os.makedirs(OUT_DIR, exist_ok=True)

span_ft = 30.0
depth_ft = recommended_depth(span_ft)
n_panels = recommended_panels(span_ft)
dl_kpf = 0.06
ll_kpf = 0.03
truss_type = 'Warren w/ Verticals'
wu_kpf = factored_load(dl_kpf, ll_kpf)

nodes, members = build_geometry_for_type(truss_type, span_ft, depth_ft, n_panels)
mems, summ = design_members(members, nodes, n_panels, wu_kpf, truss_type=truss_type)

fig, ax = plt.subplots(figsize=(8,4.5), dpi=150)
ax.set_aspect('equal')
ax.set_axis_off()
for m in mems:
    i, j = m['i'], m['j']
    xi, yi = nodes[i]; xj, yj = nodes[j]
    sec = m.get('section', {})
    B_in = sec.get('B', 2.0)
    lw = max(0.5, B_in / 4.0)
    ax.plot([xi, xj], [yi, yj], color='#2f3854', linewidth=lw, solid_capstyle='round')

img_path = os.path.join(OUT_DIR, 'simple_truss.png')
fig.savefig(img_path, bbox_inches='tight')
plt.close(fig)

csv_path = os.path.join(OUT_DIR, 'simple_schedule.csv')
with open(csv_path, 'w', newline='') as f:
    import csv
    writer = csv.writer(f)
    writer.writerow(['#','Type','Section','L_ft','Force_kips','Capacity_kips','DCR','Role','Weight_lb'])
    for i,m in enumerate(mems):
        sec = m.get('section',{})
        wt = sec.get('wt',0) * m.get('length_ft',0)
        writer.writerow([i+1, m['type'], sec.get('name','N/A'), '%.3f'%m.get('length_ft',0), '%.2f'%m.get('force',0), '%.2f'%m.get('capacity',0), '%.4f'%m.get('DCR',0), m.get('role',''), '%.2f'%wt])

print('Generated:', img_path, csv_path)
