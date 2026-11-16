import json
import html
import re
import feedparser
from itertools import zip_longest
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse

PODRAZUMEVANA_SLIKA = "https://placehold.co"
ZABRANJENE_RECI = (
    "kontakt", "o-nama", "impressum", "marketing", "oglasi-za-posao",
    "prijava", "registracija", "politika-privatnosti", "uslovi-koriscenja",
    "login", "register", "tag/", "category/", "autor/", "kategorija/"
)

def prvi_element(lista):
    return next(iter(lista), {})

def je_clanak_link(base_url, href, tekst):
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    puni_url = urljoin(base_url, href)
    p_base = urlparse(base_url)
    p_link = urlparse(puni_url)

    if p_base.netloc.replace("www.", "") != p_link.netloc.replace("www.", ""):
        return False
    putanja = p_link.path.strip("/")
    if not putanja or len(putanja) < 10:
        return False
    if any(z in puni_url.lower() for z in ZABRANJENE_RECI):
        return False
    if len(tekst) < 22 or len(tekst.split()) < 4:
        return False
    return ("-" in putanja) or bool(re.search(r"\d{3,}", putanja))

def uzmi_og_sliku_browser(page, link):
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=12000)
        og = page.locator("meta[property='og:image']").first
        if og.count() > 0:
            content = og.get_attribute("content")
            if content:
                return urljoin(link, content)
    except Exception:
        pass
    return PODRAZUMEVANA_SLIKA

def parsiraj_rss_sadrzaj(xml_tekst, izvor_naziv, page):
    stavke = []
    feed = feedparser.parse(xml_tekst)
    for entry in feed.entries[:6]:
        slika = PODRAZUMEVANA_SLIKA
        mc = prvi_element(entry.get("media_content", ()))
        mt = prvi_element(entry.get("media_thumbnail", ()))
        enc = prvi_element(entry.get("enclosures", ()))

        if mc.get("url"):
            slika = mc.get("url")
        elif mt.get("url"):
            slika = mt.get("url")
        elif enc.get("href"):
            slika = enc.get("href")
        elif "summary" in entry:
            soup = BeautifulSoup(entry.summary, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                slika = img["src"]

        link = entry.get("link", "#")
        if slika == PODRAZUMEVANA_SLIKA and link != "#":
            slika = uzmi_og_sliku_browser(page, link)

        stavke.append({
            "naslov": entry.get("title", "Bez naslova"),
            "link": link,
            "slika": slika,
            "izvor": izvor_naziv
        })
    return stavke

def obradi_sajt(page, naziv, url):
    if not url.startswith("http"):
        url = "https://" + url
    print(f"--- Obradjujem: {naziv} ({url}) ---")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        sadrzaj = page.content()
        soup = BeautifulSoup(sadrzaj, "html.parser")

        if "<rss" in sadrzaj[:500].lower() or "<feed" in sadrzaj[:500].lower():
            stavke = parsiraj_rss_sadrzaj(sadrzaj, naziv, page)
            if stavke:
                print(f"[{naziv}] Ucitano direktno iz RSS-a: {len(stavke)}")
                return stavke

        rss_tag = soup.find("link", type=re.compile(r"rss|atom", re.I))
        if rss_tag and rss_tag.get("href"):
            rss_url = urljoin(url, rss_tag["href"])
            try:
                resp = page.request.get(rss_url, timeout=10000)
                if resp.ok:
                    stavke = parsiraj_rss_sadrzaj(resp.text(), naziv, page)
                    if stavke:
                        print(f"[{naziv}] Automatski pronadjen RSS ({rss_url}): {len(stavke)}")
                        return stavke
            except Exception:
                pass

        vidjeni = set()
        kandidati = []
        for a in soup.find_all("a", href=True):
            tekst = " ".join(a.get_text().split())
            href = a["href"]
            puni_link = urljoin(url, href)
            if puni_link in vidjeni:
                continue
            if je_clanak_link(url, href, tekst):
                vidjeni.add(puni_link)
                kandidati.append((tekst, puni_link))
            if len(kandidati) >= 6:
                break

        stavke = []
        for naslov, link in kandidati:
            slika = uzmi_og_sliku_browser(page, link)
            stavke.append({
                "naslov": naslov,
                "link": link,
                "slika": slika,
                "izvor": naziv
            })
        print(f"[{naziv}] Ucitano univerzalno preko pregledača: {len(stavke)}")
        return stavke
    except Exception as e:
        print(f"[{naziv}] Greska: {e}")
        return []

def izmesaj_liste(liste_po_izvorima):
    izmesano = []
    for grupa in zip_longest(*liste_po_izvorima):
        for stavka in grupa:
            if stavka is not None:
                izmesano.append(stavka)
    return izmesano

def generisi():
    with open("izvori.json", "r", encoding="utf-8") as f:
        kategorije = json.load(f)

    svi_podaci = {}
    sve_liste_za_pocetnu = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="sr-RS"
        )
        page = context.new_page()

        for kat, izvori in kategorije.items():
            liste_u_kategoriji = []
            for iz in izvori:
                rezultat = obradi_sajt(page, iz["naziv"], iz["url"])
                for r in rezultat:
                    r["kategorija"] = kat
                liste_u_kategoriji.append(rezultat)
                sve_liste_za_pocetnu.append(rezultat)
            svi_podaci[kat] = izmesaj_liste(liste_u_kategoriji)

        browser.close()

    sve_vesti_izmesano = izmesaj_liste(sve_liste_za_pocetnu)

    vreme = datetime.now().strftime("%d.%m.%Y. u %H:%M")
    dugmici = ['<button class="tab active" onclick="postaviKategoriju(\'sve\', this)">Sve vesti</button>']
    for kat in svi_podaci.keys():
        kat_safe = html.escape(kat)
        dugmici.append(f'<button class="tab" onclick="postaviKategoriju(\'{kat_safe}\', this)">{kat_safe}</button>')

    kartice_html = []
    for v in sve_vesti_izmesano:
        kat_safe = html.escape(v["kategorija"])
        izvor_safe = html.escape(v["izvor"])
        naslov_safe = html.escape(v["naslov"])
        kartice_html.append(f"""
        <a href="{html.escape(v['link'])}" target="_blank" rel="noopener" class="card" data-kat="{kat_safe}">
            <img src="{html.escape(v['slika'])}" alt="" loading="lazy" onerror="this.src='{PODRAZUMEVANA_SLIKA}'">
            <div class="card-body">
                <span class="badge">{kat_safe} • {izvor_safe}</span>
                <h3>{naslov_safe}</h3>
            </div>
        </a>""")

    html_stranica = f"""<!DOCTYPE html>
<html lang="sr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="referrer" content="no-referrer">
    <title>Moj Portal</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        header {{ max-width: 1200px; margin: 0 auto 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }}
        .search-box {{ width: 100%; max-width: 320px; padding: 10px 15px; border-radius: 20px; border: 1px solid #334155; background: #1e293b; color: #f8fafc; font-size: 14px; outline: none; }}
        .search-box:focus {{ border-color: #3b82f6; }}
        .tabs {{ max-width: 1200px; margin: 0 auto 25px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .tab {{ background: #1e293b; color: #cbd5e1; border: 1px solid #334155; padding: 8px 16px; border-radius: 20px; cursor: pointer; font-size: 14px; transition: all 0.2s; }}
        .tab.active, .tab:hover {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
        .grid {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }}
        .card {{ background: #1e293b; border-radius: 12px; overflow: hidden; text-decoration: none; color: inherit; display: flex; flex-direction: column; transition: transform 0.2s, border-color 0.2s; border: 1px solid #334155; }}
        .card:hover {{ transform: translateY(-4px); border-color: #3b82f6; }}
        .card img {{ width: 100%; height: 170px; object-fit: cover; background: #0f172a; }}
        .card-body {{ padding: 15px; flex: 1; display: flex; flex-direction: column; gap: 8px; }}
        .badge {{ font-size: 12px; color: #38bdf8; font-weight: 600; }}
        .card h3 {{ margin: 0; font-size: 16px; line-height: 1.4; }}
        footer {{ max-width: 1200px; margin: 30px auto 0; text-align: center; color: #64748b; font-size: 13px; }}
    </style>
</head>
<body>
    <header>
        <h1>Moj Portal</h1>
        <input type="text" id="pretraga" class="search-box" placeholder="Pretraži vesti..." oninput="osveziPrikaz()">
    </header>
    <div class="tabs">{''.join(dugmici)}</div>
    <div class="grid">{''.join(kartice_html)}</div>
    <footer>Ažurirano: {vreme} (UTC)</footer>
    <script>
        let aktivnaKat = 'sve';

        function postaviKategoriju(kat, btn) {{
            aktivnaKat = kat;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            osveziPrikaz();
        }}

                function osveziPrikaz() {{
            const pojam = document.getElementById('pretraga').value.toLowerCase().trim();
            document.querySelectorAll('.card').forEach(c => {{
                const poklapaKat = (aktivnaKat === 'sve' || c.dataset.kat === aktivnaKat);
                const tekstKartice = c.innerText.toLowerCase();
                const poklapaTekst = (!pojam || tekstKartice.includes(pojam));
                c.style.display = (poklapaKat && poklapaTekst) ? 'flex' : 'none';
            }});
        }}
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_stranica)

if __name__ == "__main__":
    generisi()
