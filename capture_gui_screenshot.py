import os
import time
from PIL import ImageGrab
import main

OUT_DIR = os.path.join(os.path.dirname(__file__), 'sample_output')
os.makedirs(OUT_DIR, exist_ok=True)

path = os.path.join(OUT_DIR, 'gui_screenshot.png')

app = main.TrussDesignerApp()
# Bring window to front
try:
    app.lift()
    app.attributes('-topmost', True)
    app.update()
    time.sleep(0.3)
    app.attributes('-topmost', False)
except Exception:
    pass

# Allow widgets to render
app.update()
app.update_idletasks()
time.sleep(0.4)

x = app.winfo_rootx()
y = app.winfo_rooty()
w = app.winfo_width()
h = app.winfo_height()

# If width/height are zero, try geometry parsing
if w == 0 or h == 0:
    geom = app.winfo_geometry()
    try:
        size = geom.split('+')[0]
        w, h = map(int, size.split('x'))
    except Exception:
        w = max(800, w)
        h = max(600, h)

bbox = (x, y, x + w, y + h)
img = ImageGrab.grab(bbox)
img.save(path)

print('Saved:', path)

app.destroy()
