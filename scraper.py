"""
scraper.py
Naviga va.mite.gov.it per un dato ID_VIP e restituisce:
  - testo della pagina "Dettagli Procedura"
  - contenuto esportato dalla pagina "Documentazione" -> "Esporta"
  - lista di documenti scaricati per le colonne "osservazioni/pareri" richieste

NOTA IMPORTANTE:
Il sito usa bot-detection e la struttura HTML esatta dei pulsanti
("Dettagli Procedura", menu dei 3 puntini, "Documentazione", "Esporta")
non è stata verificata contro il sito live in fase di sviluppo di questo
script (fetch diretto bloccato). I selettori sotto sono placeholder
ragionevoli basati sulla descrizione fornita: VANNO VERIFICATI aprendo
il sito con un browser reale e ispezionando l'HTML (tasto destro ->
Ispeziona) sui link indicati. Cerca i commenti "# TODO VERIFICARE".
"""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "https://va.mite.gov.it"
SEARCH_URL = f"{BASE_URL}/it-IT/Ricerca/Via"

# Colonne documento da intercettare e allegare al report
DOCUMENTI_DA_ALLEGARE = [
    "Osservazioni del pubblico",
    "Pareri/Osservazioni Enti",
    "Pareri/Osservazioni Enti (II)",
    "Pareri/Osservazioni Enti (III)",
    "Osservazioni del Pubblico inviate oltre i termini",
]

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


async def cerca_progetto(page, id_vip: str) -> str | None:
    """Va sulla pagina di ricerca, inserisce il codice procedura, apre la scheda del progetto.
    Ritorna l'URL della pagina Info del progetto, o None se non trovato."""
    await page.goto(SEARCH_URL, wait_until="networkidle")

    # TODO VERIFICARE: selettore del campo "Codice procedura (ID_VIP)".
    # Placeholder: cerco un input il cui name/id contenga "IdVip" o label associata.
    campo = page.locator("input[name*='IdVip' i], input[id*='IdVip' i]").first
    await campo.fill(id_vip)

    # TODO VERIFICARE: selettore del bottone di ricerca (spesso "Cerca" o icona lente)
    bottone_cerca = page.get_by_role("button", name=re.compile("cerca", re.I)).first
    await bottone_cerca.click()
    await page.wait_for_load_state("networkidle")

    # TODO VERIFICARE: selettore del link risultato che porta a /Oggetti/Info/{id}
    link_risultato = page.locator(f"a[href*='/Oggetti/Info/']").first
    if await link_risultato.count() == 0:
        return None
    href = await link_risultato.get_attribute("href")
    return BASE_URL + href if href.startswith("/") else href


async def estrai_dettagli_procedura(page, info_url: str) -> str:
    """Apre la pagina Info, clicca sul menu dei 3 puntini, poi su 'Dettagli Procedura',
    ed estrae il testo della pagina risultante."""
    await page.goto(info_url, wait_until="networkidle")

    # TODO VERIFICARE: selettore del menu "3 puntini"
    menu_puntini = page.locator("button[aria-label*='menu' i], .dropdown-toggle, [class*='ellipsis']").first
    await menu_puntini.click()

    # TODO VERIFICARE: testo esatto del link "Dettagli Procedura"
    link_dettagli = page.get_by_text("Dettagli Procedura", exact=False).first
    async with page.expect_navigation():
        await link_dettagli.click()

    await page.wait_for_load_state("networkidle")
    testo = await page.inner_text("body")
    return testo.strip()


async def estrai_documentazione(page, info_url: str, id_vip: str) -> dict:
    """Apre la pagina Info, clicca su 'Documentazione', poi su 'Esporta',
    ed estrae il contenuto esportato. Scarica anche eventuali documenti
    nelle colonne D richieste (Osservazioni/Pareri)."""
    await page.goto(info_url, wait_until="networkidle")

    # TODO VERIFICARE: selettore del link "Documentazione" (icona documento)
    link_doc = page.get_by_role("link", name=re.compile("documentazione", re.I)).first
    async with page.expect_navigation():
        await link_doc.click()
    await page.wait_for_load_state("networkidle")

    risultato = {"esportato_testo": "", "documenti_scaricati": []}

    # --- Click su "Esporta" in basso a sinistra ---
    # TODO VERIFICARE: selettore/testo esatto del link "Esporta"
    link_esporta = page.get_by_text("Esporta", exact=False).first
    if await link_esporta.count() > 0:
        async with page.expect_download() as download_info:
            await link_esporta.click()
        download = await download_info.value
        export_path = DOWNLOAD_DIR / f"{id_vip}_export_{download.suggested_filename}"
        await download.save_as(export_path)
        # Se è un file di testo/csv leggibile lo carichiamo, altrimenti teniamo solo il path
        try:
            risultato["esportato_testo"] = export_path.read_text(errors="ignore")
        except Exception:
            risultato["esportato_testo"] = f"[file binario salvato: {export_path}]"
        risultato["esportato_path"] = str(export_path)

    # --- Ricerca righe con le colonne D richieste e download documenti collegati ---
    # TODO VERIFICARE: struttura della tabella documenti (probabilmente una <table> con colonne)
    righe = page.locator("table tr")
    n_righe = await righe.count()
    for i in range(n_righe):
        riga = righe.nth(i)
        testo_riga = await riga.inner_text()
        for etichetta in DOCUMENTI_DA_ALLEGARE:
            if etichetta.lower() in testo_riga.lower():
                link_scarica = riga.locator("a").first
                if await link_scarica.count() > 0:
                    try:
                        async with page.expect_download() as download_info:
                            await link_scarica.click()
                        download = await download_info.value
                        nome_file = f"{id_vip}_{etichetta.replace(' ', '_').replace('/', '-')}_{download.suggested_filename}"
                        doc_path = DOWNLOAD_DIR / nome_file
                        await download.save_as(doc_path)
                        risultato["documenti_scaricati"].append({
                            "etichetta": etichetta,
                            "path": str(doc_path),
                        })
                    except Exception as e:
                        risultato["documenti_scaricati"].append({
                            "etichetta": etichetta,
                            "errore": str(e),
                        })

    return risultato


async def analizza_progetto(browser, id_vip: str) -> dict:
    """Orchestratore per un singolo progetto: cerca, estrae dettagli e documentazione."""
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    dati = {"id_vip": id_vip, "trovato": False}
    try:
        info_url = await cerca_progetto(page, id_vip)
        if info_url is None:
            dati["errore"] = "Progetto non trovato nella ricerca"
            return dati

        dati["trovato"] = True
        dati["info_url"] = info_url
        dati["dettagli_procedura"] = await estrai_dettagli_procedura(page, info_url)
        dati["documentazione"] = await estrai_documentazione(page, info_url, id_vip)
        dati["hash_dettagli"] = hashlib.sha256(
            dati["dettagli_procedura"].encode("utf-8")
        ).hexdigest()
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
    print(json.dumps(ris, indent=2, ensure_ascii=False))
