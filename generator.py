import json
import html
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PODRAZUMEVANA_SLIKA = "https://placeholder.com"

def uzmi_rss(url, izvor_naziv):
    stavke = []
    feed = feedparser.parse(url)
    for entry in feed.entries[:8]:
        slika = PODRAZUMEVANA_SLIKA
        if "media_content" in entry and entry.media_content:
            slika = entry.media_content[0].get("url", slika)
        elif "media_thumbnail" in entry and entry.media_thumbnail:
            slika = entry.media_thumbnail[0].get("url", slika)
        elif "summary" in entry:
            soup = BeautifulSoup(entry.summary, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                slika = img["src"]
        stavke.append({
            "naslov": entry.get("title", "Bez naslova"),
            "link": entry.get("link", "#"),
            "slika": slika,
            "izvor": izvor_naziv
        })
    return stavke

def uzmi_html(cfg):
    stavke = []
    try:
        r = requests.get(cfg["url"], headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        kartice = soup.select(cfg["kartica_selektor"])[:8]
        for k in kartice:
            a_tag = k.select_one(cfg["naslov_selektor"])
            if not a_tag:
                continue
            naslov = a_tag.get_text(strip=True)
            link = urljoin(cfg["url"], a_tag.get("href", "#"))
            img_tag = k.select_one(cfg.get("slika_selektor", "img"))
            slika = PODRAZUMEVANA_SLIKA
            if img_tag:
                src = img_tag.get("src") or img_tag.get("data-src")
                if src:
                    slika = urljoin(cfg["url"], src)
            stavke.append({
                "naslov": naslov,
                "link": link,
                "slika": slika,
                "izvor": cfg["naziv"]
            })
    except Exception as e:
        print(f"Greska za {cfg['naziv']}: {e}")
    return stavke

def generisi():
    with open("izvori.json", "r", encoding="utf-8") as f:
        kategorije = json.load(f)

    svi_podaci = {}
    for kat, izvori in kategorije.items():
        svi_podaci[kat] = []
        for iz in izvori:
            if iz["tip"] == "rss":
                svi_podaci[kat].extend(uzmi_rss(iz["url"], iz["naziv"]))
            elif iz["tip"] == "html":
                svi_podaci[kat].extend(uzmi_html(iz))

    vreme = datetime.now().strftime("%d.%m.%Y. u %H:%M")
    dugmici = ['<button class="tab active" onclick="filtriraj(\'sve\', this)">Sve vesti</button>']
    kartice_html = []

    for kat, vesti in svi_podaci.items():
        kat_safe = html.escape(kat)
        dugmici.append(f'<button class="tab" onclick="filtriraj(\'{kat_safe}\', this)">{kat_safe}</button>')
        for v in vesti:
            kartice_html.append(f"""
            <a href="{html.escape(v['link'])}" target="_blank" rel="noopener" class="card" data-kat="{kat_safe}">
                <img src="{html.escape(v['slika'])}" alt="" loading="lazy" onerror="this.src='{PODRAZUMEVANA_SLIKA}'">
                <div class="card-body">
                    <span class="badge">{kat_safe} • {html.escape(v['izvor'])}</span>
                    <h3>{html.escape(v['naslov'])}</h3>
                </div>
            </a>""")

    html_stranica = f"""<!DOCTYPE html>
<html lang="sr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Moj Portal</title>
    <style>
        body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        header {{ max-width: 1200px; margin: 0 auto 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
        .tabs {{ max-width: 1200px; margin: 0 auto 25px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .tab {{ background: #1e293b; color: #cbd5e1; border: 1px solid #334155; padding: 8px 16px; border-radius: 20px; cursor: pointer; font-size: 14px; }}
        .tab.active, .tab:hover {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
        .grid {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }}
        .card {{ background: #1e293b; border-radius: 12px; overflow: hidden; text-decoration: none; color: inherit; display: flex; flex-direction: column; transition: transform 0.2s; border: 1px solid #334155; }}
        .card:hover {{ transform: translateY(-4px); border-color: #3b82f6; }}
        .card img {{ width: 100%; height: 170px; object-fit: cover; background: #0f172a; }}
        .card-body {{ padding: 15px; flex: 1; display: flex; flex-direction: column; gap: 8px; }}
        .badge {{ font-size: 12px; color: #38bdf8; font-weight: 600; }}
        .card h3 {{ margin: 0; font-size: 16px; line-height: 1.4; }}
    </style>
</head>
<body>
    <header>
        <h1>Moj Portal</h1>
        <small style="color:#94a3b8">Ažurirano: {vreme} (UTC)</small>
    </header>
    <div class="tabs">{''.join(dugmici)}</div>
    <div class="grid">{''.join(kartice_html)}</div>
    <script>
        function filtriraj(kat, btn) {{
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.card').forEach(c => {{
                c.style.display = (kat === 'sve' || c.dataset.kat === kat) ? 'flex' : 'none';
            }});
        }}
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_stranica)

if __name__ == "__main__":
    generisi()
