"""
scraper.py
Naviga va.mite.gov.it per un dato ID_VIP (Codice procedura) e restituisce:
  - nome del progetto
  - testo della pagina "Dettagli Procedura"
  - elenco documenti della pagina "Documentazione" (tutte le sezioni, per il diff)
  - documenti scaricati (PDF) delle sezioni di interesse:
    "Osservazioni del Pubblico", "Pareri/Osservazioni Enti" (e varianti I/II/III)

Selettori verificati manualmente sul sito reale (settembre 2026):
  - campo ricerca:        input#input-cercaIdVipera  -> premi Invio -> redirect a /Oggetti/Info/{id}
  - nome progetto:        primo <h2> della pagina Info
  - link Dettagli Proc.:  a.icona-dettaglio-procedura
  - link Documentazione:  a.icona-documentazione-tecnico-amm -> /Oggetti/Documentazione/{id}/{procId}
  - filtro per sezione:   span.leaf[data-raggruppamentoid=N] -> submit GET a
                          /Oggetti/Documentazione/{id}/{procId}?RaggruppamentoID=N
                          (N e' specifico per progetto: va letto dal menu, non e' fisso)
  - righe tabella:        table.Documentazione tr, colonne Titolo/Nome file/Sezione/
                          Codice elaborato/Data/Scala/Dimensione
  - download PDF diretto: a.icona-pdf[href] -> link diretto al file, no popup
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "https://va.mite.gov.it"
SEARCH_URL = f"{BASE_URL}/it-IT/Ricerca/Via"

# Nomi delle sezioni da allegare nel report. Match "startswith" per coprire
# varianti numerate come "Pareri/Osservazioni Enti (I)", "(II)", "(III)".
SEZIONI_DA_ALLEGARE = [
    "osservazioni del pubblico inviate oltre i termini",
    "osservazioni del pubblico",
    "pareri/osservazioni enti",
]

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def sezione_di_interesse(nome_sezione: str) -> bool:
    nome_pulito = nome_sezione.strip().lower()
    return any(nome_pulito.startswith(t) for t in SEZIONI_DA_ALLEGARE)


async def cerca_e_apri_progetto(page, id_vip: str) -> dict:
    """Cerca il codice procedura e sfrutta il redirect automatico alla pagina Info."""
    await page.goto(SEARCH_URL, wait_until="networkidle")
    campo = page.locator("input#input-cercaIdVipera")
    await campo.fill(id_vip)
    await campo.press("Enter")

    try:
        await page.wait_for_url("**/Oggetti/Info/**", timeout=15000)
    except Exception:
        return {"trovato": False, "errore": "Nessun redirect a pagina Info: codice non trovato o pagina cambiata"}

    return {"trovato": True, "info_url": page.url}


async def estrai_nome_progetto(page) -> str:
    h2 = page.locator("h2").first
    if await h2.count() == 0:
        return ""
    return (await h2.inner_text()).strip()


async def estrai_dettagli_procedura(page, info_url: str) -> str:
    await page.goto(info_url, wait_until="networkidle")
    link_dettagli = page.locator("a.icona-dettaglio-procedura")
    if await link_dettagli.count() == 0:
        raise RuntimeError("Link 'Dettagli procedura' non trovato sulla pagina Info")

    async with page.expect_navigation():
        await link_dettagli.click()
    await page.wait_for_load_state("networkidle")

    testo = await page.inner_text("body")
    return testo.strip()


async def estrai_mappa_sezioni(page) -> dict:
    """Legge il menu laterale e ritorna {nome_sezione: raggruppamento_id}."""
    spans = page.locator("span.leaf[data-raggruppamentoid]")
    n = await spans.count()
    mappa = {}
    for i in range(n):
        span = spans.nth(i)
        nome = (await span.inner_text()).strip()
        rid = await span.get_attribute("data-raggruppamentoid")
        mappa[nome] = rid
    return mappa


async def estrai_righe_tabella(page) -> list[dict]:
    """Estrae le righe della tabella documenti correntemente visualizzata."""
    righe_loc = page.locator("table.Documentazione tr")
    n = await righe_loc.count()
    documenti = []
    for i in range(n):
        riga = righe_loc.nth(i)
        celle = riga.locator("td")
        n_celle = await celle.count()
        if n_celle == 0:
            continue  # riga di intestazione (th, non td)

        testi = [await celle.nth(j).inner_text() for j in range(n_celle)]
        # Colonne attese: Titolo, Nome file, Sezione, Codice elaborato, Data, Scala, Dimensione, [metadato], [download]
        doc = {
            "titolo": testi[0].strip() if len(testi) > 0 else "",
            "nome_file": testi[1].strip() if len(testi) > 1 else "",
            "sezione": testi[2].strip() if len(testi) > 2 else "",
            "codice_elaborato": testi[3].strip() if len(testi) > 3 else "",
            "data": testi[4].strip() if len(testi) > 4 else "",
        }

        link_pdf = riga.locator("a.icona-pdf")
        if await link_pdf.count() > 0:
            doc["download_url"] = await link_pdf.first.get_attribute("href")
        else:
            doc["download_url"] = None

        documenti.append(doc)
    return documenti


async def vai_a_pagina_successiva(page) -> bool:
    """Clicca sul link 'pagina successiva' della paginazione, se esiste. Ritorna True se ha navigato."""
    # La paginazione mostra numeri di pagina e "ultima"; cerchiamo un link con testo
    # uguale al numero di pagina corrente + 1, tra i link della paginazione.
    pagina_corrente = page.locator(".pagination .current, .pagination strong").first
    # Fallback semplice: cerchiamo un link ">" o il numero successivo esplicito
    link_successiva = page.get_by_role("link", name=re.compile(r"^(succ|next|>|»)", re.I)).first
    if await link_successiva.count() > 0:
        async with page.expect_navigation():
            await link_successiva.click()
        return True
    return False


async def estrai_documenti_sezione(page, base_doc_url: str, mappa_sezioni: dict, nome_sezione_menu: str) -> list[dict]:
    """Va sulla pagina filtrata per una specifica sezione (via RaggruppamentoID) e
    raccoglie tutti i documenti di quella sezione, scorrendo le pagine se necessario."""
    rid = mappa_sezioni.get(nome_sezione_menu)
    if rid is None:
        return []  # questa sezione non esiste per questo progetto

    url_filtrato = f"{base_doc_url}?RaggruppamentoID={rid}"
    await page.goto(url_filtrato, wait_until="networkidle")

    tutti_documenti = []
    max_pagine = 20  # sicurezza anti-loop
    for _ in range(max_pagine):
        tutti_documenti.extend(await estrai_righe_tabella(page))
        ha_pagina_dopo = await vai_a_pagina_successiva(page)
        if not ha_pagina_dopo:
            break

    return tutti_documenti


async def scarica_documento(page, url: str, dest_path: Path):
    """Scarica un PDF tramite richiesta diretta autenticata dal contesto del browser."""
    response = await page.context.request.get(url)
    dest_path.write_bytes(await response.body())


async def estrai_documentazione(page, info_url: str, id_vip: str) -> dict:
    await page.goto(info_url, wait_until="networkidle")
    link_doc = page.locator("a.icona-documentazione-tecnico-amm")
    if await link_doc.count() == 0:
        raise RuntimeError("Link 'Documentazione' non trovato sulla pagina Info")

    doc_href = await link_doc.get_attribute("href")
    base_doc_url = BASE_URL + doc_href if doc_href.startswith("/") else doc_href

    await page.goto(base_doc_url, wait_until="networkidle")

    mappa_sezioni = await estrai_mappa_sezioni(page)

    risultato = {
        "sezioni_disponibili": list(mappa_sezioni.keys()),
        "documenti_di_interesse": [],
        "elenco_completo_prima_pagina": await estrai_righe_tabella(page),
    }

    documenti_scaricati = []
    for nome_sezione_menu, rid in mappa_sezioni.items():
        if not sezione_di_interesse(nome_sezione_menu):
            continue

        docs = await estrai_documenti_sezione(page, base_doc_url, mappa_sezioni, nome_sezione_menu)
        for doc in docs:
            doc["sezione_menu"] = nome_sezione_menu
            if doc.get("download_url"):
                nome_pulito = re.sub(r"[^a-zA-Z0-9_.-]", "_", doc["nome_file"] or "documento.pdf")
                dest = DOWNLOAD_DIR / f"{id_vip}_{nome_sezione_menu.replace('/', '-')}_{nome_pulito}"
                try:
                    await scarica_documento(page, doc["download_url"], dest)
                    doc["path_locale"] = str(dest)
                except Exception as e:
                    doc["errore_download"] = str(e)
            documenti_scaricati.append(doc)

    risultato["documenti_di_interesse"] = documenti_scaricati
    return risultato


async def analizza_progetto(browser, id_vip: str) -> dict:
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    dati = {"id_vip": id_vip, "trovato": False}
    try:
        ricerca = await cerca_e_apri_progetto(page, id_vip)
        if not ricerca["trovato"]:
            dati["errore"] = ricerca["errore"]
            return dati

        dati["trovato"] = True
        info_url = ricerca["info_url"]
        dati["info_url"] = info_url

        await page.goto(info_url, wait_until="networkidle")
        dati["nome_progetto"] = await estrai_nome_progetto(page)

        dati["dettagli_procedura"] = await estrai_dettagli_procedura(page, info_url)
        dati["hash_dettagli"] = hashlib.sha256(dati["dettagli_procedura"].encode("utf-8")).hexdigest()

        dati["documentazione"] = await estrai_documentazione(page, info_url, id_vip)

    except Exception as e:
        dati["errore"] = f"Errore durante scraping: {e}"
    finally:
        await context.close()

    return dati


async def analizza_tutti(id_vip_list: list[str]) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        risultati = []
        for id_vip in id_vip_list:
            print(f"[scraper] Analizzo progetto {id_vip}...")
            dati = await analizza_progetto(browser, id_vip)
            risultati.append(dati)
        await browser.close()
        return risultati


if __name__ == "__main__":
    import sys
    ids = sys.argv[1:] if len(sys.argv) > 1 else ["8651"]
    ris = asyncio.run(analizza_tutti(ids))
    print(json.dumps(ris, indent=2, ensure_ascii=False, default=str))
