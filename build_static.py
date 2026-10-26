#!/usr/bin/env python3
"""Génère les pages HTML statiques de TIMITÉ STRATÉGIE à partir du site lui-même.
Le site (app.js) lit le Google Sheet ; ce script l'ouvre dans un navigateur invisible,
attend que les données soient chargées, puis enregistre le contenu de chaque page
dans un vrai fichier HTML (lisible sans JavaScript, indexable par les moteurs et les IA).
Usage :  python3 build_static.py            (à la racine du dépôt)"""
import base64, hashlib, html, json, os, re, sys, threading, datetime, http.server, socketserver, functools
from playwright.sync_api import sync_playwright

SITE = "https://timitestrategie.github.io/timite-strategie/"
ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = ["accueil","a-propos","services","realisations","equipements","mediatheque","partenaires","actualites","carrieres","contact"]
TITLES = {"accueil":"","a-propos":"L'entreprise","services":"Nos services","realisations":"Nos réalisations","equipements":"Équipements","mediatheque":"Médiathèque","partenaires":"Partenaires","actualites":"Actualités","carrieres":"Carrières","contact":"Contact"}
esc = lambda t: html.escape(t, quote=True)

def serve():
    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
        def log_message(self, *a): pass
    h = Q
    srv = socketserver.TCPServer(("127.0.0.1", 0), h); srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]

def snapshot(pw, port, route):
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width":1440,"height":900}, reduced_motion="reduce")
    p = ctx.new_page()
    p.goto(f"http://127.0.0.1:{port}/_probe.html#/{route}", wait_until="domcontentloaded")
    p.wait_for_selector("#app main", state="attached", timeout=30000)
    try: p.wait_for_function("window.__synced===true", timeout=45000)
    except Exception: print("  (Sheet non joint : valeurs par défaut)", route)
    p.wait_for_timeout(1500)
    d = p.evaluate("""() => {
      const app = document.querySelector('#app').cloneNode(true);
      app.querySelectorAll('#modal').forEach(e => e.innerHTML = '');
      app.querySelectorAll('.rv').forEach(e => e.classList.add('in'));
      app.querySelectorAll('img.fade').forEach(e => e.classList.add('ok'));
      const lead = document.querySelector('.pagehead .lead, .pagehead p');
      return { body: app.innerHTML, title: document.title,
               desc: (document.querySelector('meta[name=description]')||{}).content || '',
               lead: lead ? lead.textContent.trim() : '',
               ld: (document.getElementById('ld')||{}).textContent || '{}' };
    }""")
    b.close(); return d

def extract_images(t, base):
    def one(m):
        ext = {"jpeg":"jpg","svg+xml":"svg"}.get(m.group(1), m.group(1))
        raw = base64.b64decode(m.group(2))
        name = hashlib.sha1(raw).hexdigest()[:12] + "." + ext
        fp = os.path.join(ROOT,name)
        if not os.path.exists(fp): open(fp,"wb").write(raw)
        return base + name
    return re.sub(r"data:image/([\w+]+);base64,([A-Za-z0-9+/=]+)", one, t)

def fix_links(t, base, existing):
    def one(m):
        pg = m.group(1)
        if pg not in existing: return 'href="#/%s"' % pg
        return 'href="%s"' % ("./" if pg == "accueil" else pg + ".html")
    return re.sub(r'href="#/([a-z-]+)(?:\?[^"]*)?"', one, t)

def sri(path):
    return "sha384-" + base64.b64encode(hashlib.sha384(open(path,"rb").read()).digest()).decode()

def main():
    tpl = open(os.path.join(ROOT,"template.html"),encoding="utf8").read()
    probe = (tpl.replace(' integrity="{{SRI}}"','').replace("{{TITLE}}","").replace("{{DESC}}","").replace("{{ROUTE}}","accueil")
                .replace("{{CANON}}",SITE).replace("{{SITE}}",SITE).replace("{{LD}}","{}").replace("{{BASE}}","").replace("{{BODY}}",""))
    open(os.path.join(ROOT,"_probe.html"),"w",encoding="utf8").write(probe)
    srv, port = serve()
    with sync_playwright() as pw:
        first = snapshot(pw, port, "accueil")
        present = [p for p in PAGES if p == "accueil" or f'href="#/{p}"' in first["body"]]
        # les pages liées uniquement depuis le pied de page ou le menu sont comprises
        snaps = {"accueil": first}
        for r in present:
            if r != "accueil": snaps[r] = snapshot(pw, port, r)
    srv.shutdown()
    os.remove(os.path.join(ROOT,"_probe.html"))
    today = datetime.date.today().isoformat()
    sri_app = sri(os.path.join(ROOT,"app.js"))
    urls = []
    old_sm = os.path.join(ROOT,"sitemap.xml")
    old_dates = dict(re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", open(old_sm,encoding="utf8").read())) if os.path.exists(old_sm) else {}
    dates = {}
    for r in present:
        d = snaps[r]; base = ""
        canon = SITE if r == "accueil" else SITE + r + ".html"
        desc = d["desc"] if r == "accueil" else (d["lead"] or d["desc"])
        desc = re.sub(r"\s+"," ",desc).strip()[:300]
        try:
            ld = json.loads(d["ld"]); ld["url"] = SITE; ld["image"] = SITE + "og.png"
            ld = json.dumps(ld, ensure_ascii=False).replace("</","<\\/")
        except Exception: ld = "{}"
        body = extract_images(fix_links(d["body"], base, present), base)
        out = (tpl.replace("{{TITLE}}",esc(d["title"])).replace("{{DESC}}",esc(desc)).replace("{{ROUTE}}",r)
                  .replace("{{CANON}}",canon).replace("{{SITE}}",SITE).replace("{{LD}}",ld)
                  .replace("{{BASE}}",base).replace("{{SRI}}",sri_app).replace("{{BODY}}",body))
        out = extract_images(out, base)
        dest = os.path.join(ROOT,"index.html" if r == "accueil" else r + ".html")
        before = open(dest,encoding="utf8").read() if os.path.exists(dest) else None
        if before != out: open(dest,"w",encoding="utf8").write(out)
        dates[canon] = today if (before != out or canon not in old_dates) else old_dates[canon]
        urls.append(canon); print("OK", r, len(out)//1024, "Ko")
    used = set()
    for r in present:
        dest = os.path.join(ROOT,"index.html" if r == "accueil" else r + ".html")
        used |= set(re.findall(r"([0-9a-f]{12}\.\w+)", open(dest,encoding="utf8").read()))
    for f in os.listdir(ROOT):
        if re.fullmatch(r"[0-9a-f]{12}\.\w+", f) and f not in used: os.remove(os.path.join(ROOT,f))
    sm = ['<?xml version="1.0" encoding="UTF-8"?>','<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{u}</loc><lastmod>{dates[u]}</lastmod></url>" for u in urls] + ["</urlset>"]
    open(os.path.join(ROOT,"sitemap.xml"),"w",encoding="utf8").write("\n".join(sm)+"\n")
    open(os.path.join(ROOT,"404.html"),"w",encoding="utf8").write(f'''<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>Page introuvable — TIMITÉ STRATÉGIE</title></head><body style="font-family:Arial,sans-serif;max-width:560px;margin:60px auto;padding:0 20px;color:#1C2430"><h1>Page introuvable</h1><p>Cette page n'existe pas ou a été déplacée.</p><p><a href="{SITE}">Retour à l'accueil de TIMITÉ STRATÉGIE</a> · <a href="{SITE}contact.html">Nous contacter</a></p></body></html>''')
    print("sitemap + 404 écrits ;", len(urls), "pages")

if __name__ == "__main__":
    main()
