"""Bundle dashboard/index.html + data.js into one self-contained HTML file.

The result (dist/ueh-trajectory-mvp.html) can be opened directly or uploaded to
any static host (UEH web server, GitHub Pages, Netlify, ...).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
data = (ROOT / "dashboard" / "data.js").read_text(encoding="utf-8")
tag = '<script src="data.js"></script>'
assert tag in html
out = html.replace(tag, "<script>\n" + data.replace("</script", "<\\/script") + "\n</script>")
dest = ROOT / "dist" / "ueh-trajectory-mvp.html"
dest.parent.mkdir(exist_ok=True)
dest.write_text(out, encoding="utf-8")
print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
