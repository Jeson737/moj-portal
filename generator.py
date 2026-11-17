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
    "login", "register", "tag/", "category/", "autor/", "kategorija"/, "oglasi/"
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
            if content and "logo" not in content.lower():
                return urljoin(link, content)
    except Exception:
        pass
    return None

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
            slika = uzmi_og_sliku_browser(page, link) or PODRAZUMEVANA_SLIKA

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
        # 1. Direktna provera RSS-a kroz pravi Chromium pregledač
        for test_url in (url, url.rstrip("/") + "/feed/", url.rstrip("/") + "/rss"):
            try:
                resp = page.goto(test_url, wait_until="domcontentloaded", timeout=12000)
                if resp and resp.ok:
                    sadrzaj_feed = page.evaluate("() => document.body.innerText")
                    if "<rss" in sadrzaj_feed[:800].lower() or "<feed" in sadrzaj_feed[:800].lower():
                        stavke = parsiraj_rss_sadrzaj(sadrzaj_feed, naziv, page)
                        if stavke:
                            print(f"[{naziv}] Ucitano iz RSS-a ({test_url}): {len(stavke)}")
                            return stavke
            except Exception:
                pass

        # 2. Otvaranje stranice u Chromium pregledaču
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            dugme = page.locator("button:has-text('Prihvatam'), button:has-text('Slažem se'), button:has-text('Accept'), a:has-text('Prihvatam')").first
            if dugme.is_visible(timeout=2000):
                dugme.click()
        except Exception:
            pass

        page.wait_for_timeout(2000)
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1500)
        sadrzaj = page.content()
        soup = BeautifulSoup(sadrzaj, "html.parser")

        # 3. Provera skrivenog RSS linka u <head>
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

        # 4. Univerzalno izvlacenje clanaka sa stranice
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
            if len(kandidati) >= 12:
                break

        stavke = []
        for naslov, link in kandidati:
            slika = uzmi_og_sliku_browser(page, link)
            if not slika:
                continue
            stavke.append({
                "naslov": naslov,
                "link": link,
                "slika": slika,
                "izvor": naziv
            })
            if len(stavke) >= 6:
                break
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
        * {{ box-sizing: border-box; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; background-color: #f7f4eb !important; color: #1c1917 !important; margin: 0; padding: 12px; }}
        header {{ max-width: 1200px; margin: 0 auto 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
        header h1 {{ font-size: 20px; margin: 0; color: #292524; }}
        .search-wrap {{ display: flex; gap: 6px; flex: 1; max-width: 460px; min-width: 260px; }}
        .search-box {{ flex: 1; min-width: 120px; padding: 7px 14px; border-radius: 20px; border: 1px solid #d6d0c4; background-color: #ffffff; color: #1c1917; font-size: 13px; outline: none; }}
        .btn-action {{ background-color: #b45309; color: #ffffff; border: none; padding: 7px 13px; border-radius: 20px; cursor: pointer; font-size: 12px; font-weight: 600; white-space: nowrap; }}
        .btn-save {{ background-color: #ede7db; color: #44403c; border: 1px solid #d6d0c4; }}
        .tabs {{ max-width: 1200px; margin: 0 auto 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
        .tab {{ background-color: #ede7db; color: #44403c; border: 1px solid #d6d0c4; padding: 6px 12px; border-radius: 16px; cursor: pointer; font-size: 12px; display: inline-flex; align-items: center; gap: 6px; }}
        .tab.active, .tab:hover {{ background-color: #b45309; color: #ffffff; border-color: #b45309; }}
        .tab .del-x {{ font-weight: bold; opacity: 0.75; padding: 0 2px; }}
        .status-msg {{ max-width: 1200px; margin: 0 auto 12px; font-size: 12px; color: #78716c; display: none; }}
        .grid {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 10px; }}
        .card {{ background-color: #fffdf8 !important; border-radius: 10px; overflow: hidden; text-decoration: none; color: #1c1917 !important; display: flex; flex-direction: column; border: 1px solid #e5dec9; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
        .card img {{ width: 100%; height: 85px; object-fit: cover; background-color: #ede7db; display: block; }}
        .card-body {{ padding: 10px; flex: 1; display: flex; flex-direction: column; gap: 5px; background-color: #fffdf8; }}
        .badge {{ font-size: 10px; color: #b45309; font-weight: 700; text-transform: uppercase; }}
        .card h3 {{ margin: 0; font-size: 12px; line-height: 1.35; font-weight: 600; color: #1c1917 !important; }}
        footer {{ max-width: 1200px; margin: 24px auto 0; text-align: center; color: #78716c; font-size: 11px; }}
    </style>
</head>
<body>
    <header>
        <h1>Moj Portal</h1>
        <div class="search-wrap">
            <input type="text" id="pretraga" class="search-box" placeholder="Pretraži ili upiši novu temu..." oninput="osveziPrikaz()" onkeydown="if(event.key==='Enter') pretraziUzivo()">
            <button class="btn-action" onclick="pretraziUzivo()">Traži temu</button>
            <button id="btnSacuvaj" class="btn-action btn-save" style="display:none;" onclick="sacuvajTrenutnuTemu()">+ Sačuvaj</button>
        </div>
    </header>
    <div class="tabs" id="tabsBar">{''.join(dugmici)}</div>
    <div id="statusPoruka" class="status-msg"></div>
    <div class="grid" id="vestiGrid">{''.join(kartice_html)}</div>
    <footer>Ažurirano: {vreme} (UTC)</footer>
    <script>
        let aktivnaKat = 'sve';
        let poslednjaLiveTema = '';
        const REZERVNA_SLIKA = "{PODRAZUMEVANA_SLIKA}";

        function postaviKategoriju(kat, btn) {{
            aktivnaKat = kat;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            if (btn) btn.classList.add('active');
            document.getElementById('statusPoruka').style.display = 'none';
            osveziPrikaz();
        }}

        function osveziPrikaz() {{
            const pojam = document.getElementById('pretraga').value.toLowerCase().trim();
            document.querySelectorAll('.card').forEach(c => {{
                const poklapaKat = (aktivnaKat === 'sve' && !c.dataset.live) || (c.dataset.kat === aktivnaKat);
                const tekstKartice = c.innerText.toLowerCase();
                const poklapaTekst = (!pojam || tekstKartice.includes(pojam) || c.dataset.live === '1');
                c.style.display = (poklapaKat && poklapaTekst) ? 'flex' : 'none';
            }});
        }}

        async function pretraziUzivo(zadatiPojam, dugmeTab) {{
            const inputEl = document.getElementById('pretraga');
            const pojam = (zadatiPojam || inputEl.value).trim();
            if (!pojam) return;

            if (zadatiPojam) inputEl.value = pojam;
            poslednjaLiveTema = pojam;
            aktivnaKat = 'live:' + pojam.toLowerCase();

            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            if (dugmeTab) dugmeTab.classList.add('active');

            const statusEl = document.getElementById('statusPoruka');
            statusEl.style.display = 'block';
            statusEl.textContent = 'Pretražujem sveže vesti za: "' + pojam + '"...';

            const sacuvane = ucitajSacuvaneTeme();
            const vecSacuvana = sacuvane.some(t => t.toLowerCase() === pojam.toLowerCase());
            document.getElementById('btnSacuvaj').style.display = vecSacuvana ? 'none' : 'inline-block';

            document.querySelectorAll('.card[data-live="1"]').forEach(el => el.remove());
            osveziPrikaz();

            try {{
                const q = encodeURIComponent(pojam + ' when:7d');
                const rssUrl = 'https://news.' + 'google.' + 'com/rss/search?q=' + q + '&hl=sr&gl=RS&ceid=RS:sr';
                const apiUrl = 'https://rss2json.com' + encodeURIComponent(rssUrl);
                const resp = await fetch(apiUrl);
                const data = await resp.json();

                if (!data.items || data.items.length === 0) {{
                    statusEl.textContent = 'Nema pronađenih vesti za temu "' + pojam + '".';
                    return;
                }}

                const grid = document.getElementById('vestiGrid');
                data.items.slice(0, 12).forEach(item => {{
                    const a = document.createElement('a');
                    a.href = item.link;
                    a.target = '_blank';
                    a.rel = 'noopener';
                    a.className = 'card';
                    a.dataset.kat = aktivnaKat;
                    a.dataset.live = '1';

                    const deloviNaslova = item.title.split(' - ');
                    const izvor = deloviNaslova.length > 1 ? deloviNaslova.pop() : 'Vesti';
                    const cistNaslov = deloviNaslova.join(' - ');

                    a.innerHTML = `
                        <img src="${{REZERVNA_SLIKA}}" alt="" loading="lazy">
                        <div class="card-body">
                            <span class="badge">${{escapeHtml(pojam)}} • ${{escapeHtml(izvor)}}</span>
                            <h3>${{escapeHtml(cistNaslov)}}</h3>
                        </div>`;
                    grid.prepend(a);
                }});
                statusEl.textContent = 'Prikazano ' + Math.min(data.items.length, 12) + ' vesti za temu "' + pojam + '".';
            }} catch (e) {{
                statusEl.textContent = 'Greška pri učitavanju teme. Pokušaj ponovo.';
            }}
        }}

        function ucitajSacuvaneTeme() {{
            try {{
                return JSON.parse(localStorage.getItem('moj_portal_teme') || '[]');
            }} catch (e) {{
                return [];
            }}
        }}

        function sacuvajTrenutnuTemu() {{
            if (!poslednjaLiveTema) return;
            const teme = ucitajSacuvaneTeme();
            if (!teme.some(t => t.toLowerCase() === poslednjaLiveTema.toLowerCase())) {{
                teme.push(poslednjaLiveTema);
                localStorage.setItem('moj_portal_teme', JSON.stringify(teme));
                renderujSacuvaneTabove();
            }}
            document.getElementById('btnSacuvaj').style.display = 'none';
        }}

        function obrisiSacuvanuTemu(e, tema) {{
            e.stopPropagation();
            const teme = ucitajSacuvaneTeme().filter(t => t !== tema);
            localStorage.setItem('moj_portal_teme', JSON.stringify(teme));
            renderujSacuvaneTabove();
            if (aktivnaKat === 'live:' + tema.toLowerCase()) {{
                postaviKategoriju('sve', document.querySelector('.tab'));
            }}
        }}

        function renderujSacuvaneTabove() {{
            document.querySelectorAll('.tab[data-saved="1"]').forEach(el => el.remove());
            const bar = document.getElementById('tabsBar');
            ucitajSacuvaneTeme().forEach(tema => {{
                const btn = document.createElement('button');
                btn.className = 'tab';
                btn.dataset.saved = '1';
                if (aktivnaKat === 'live:' + tema.toLowerCase()) btn.classList.add('active');
                btn.innerHTML = `<span>${{escapeHtml(tema)}}</span><span class="del-x" title="Ukloni temu">×</span>`;
                btn.onclick = () => pretraziUzivo(tema, btn);
                btn.querySelector('.del-x').onclick = (e) => obrisiSacuvanuTemu(e, tema);
                bar.appendChild(btn);
            }});
        }}

        function escapeHtml(str) {{
            return String(str).replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
        }}

        renderujSacuvaneTabove();
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_stranica)

if __name__ == "__main__":
    generisi()
