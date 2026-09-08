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
    "documentazione integrativa",  # copre le foglie sotto il nodo "Integrazioni (I)" nel menu
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


async def trova_indice_riga_procedura(page, id_vip: str):
    """Come trova_riga_procedura, ma ritorna l'INDICE (posizione) della riga
    invece del Locator, utile per poi leggere le righe .datiAmministrativi
    che la seguono immediatamente nell'HTML."""
    righe = page.locator("tr.trProcedura")
    n = await righe.count()
    for i in range(n):
        riga = righe.nth(i)
        celle = riga.locator("td")
        if await celle.count() < 3:
            continue
        codice_procedura = (await celle.nth(2).inner_text()).strip()
        if codice_procedura == str(id_vip).strip():
            return i
    return None


async def trova_riga_procedura(page, id_vip: str):
    """Cerca nella tabella 'Scegli la procedura' (table.DatiAmministrativiResTable)
    la riga <tr class="trProcedura"> la cui colonna 'Codice procedura' corrisponde
    all'ID_VIP cercato. Necessario perche' un progetto puo' avere piu' sotto-
    procedimenti nel tempo (es. piu' Verifiche di Ottemperanza), ciascuno con
    il proprio link 'Dettagli procedura' e 'Documentazione'.

    Struttura HTML (verificata sul sito reale):
      <tr class="trProcedura">
        <td>Verifica di Ottemperanza</td>   <!-- tipo procedura -->
        <td></td>
        <td>8678</td>                        <!-- CODICE PROCEDURA = id_vip -->
        <td>28/06/2022</td>                  <!-- data avvio -->
        <td>Verifica amministrativa</td>     <!-- stato -->
        <td><a class="icona-dettaglio-procedura">...</a></td>
        <td><a class="icona-documentazione-tecnico-amm" href="...">...</a></td>
      </tr>

    Ritorna il Locator della riga corrispondente, o None se non trovata
    (in quel caso il chiamante puo' fare fallback sulla prima riga disponibile).
    """
    indice = await trova_indice_riga_procedura(page, id_vip)
    if indice is None:
        return None
    return page.locator("tr.trProcedura").nth(indice)


async def estrai_dettagli_procedura(page, info_url: str, id_vip: str) -> str:
    """I dati di dettaglio del procedimento (Codice procedura, Oggetto, Date,
    Responsabile, Stato) sono GIA' presenti nell'HTML della pagina Info, dentro
    righe <tr class="datiAmministrativi" style="display:none"> che seguono
    immediatamente la <tr class="trProcedura"> del procedimento specifico
    (fino alla prossima trProcedura o fine tabella). Le leggiamo direttamente,
    senza bisogno di cliccare per aprire il modal: e' piu' veloce e affidabile,
    soprattutto quando la pagina ha decine di procedimenti (es. Tempa Rossa),
    caso in cui il click sul modal generico rischiava di leggere i dati
    del procedimento sbagliato o di andare in timeout."""
    await page.goto(info_url, wait_until="networkidle")

    indice = await trova_indice_riga_procedura(page, id_vip)
    tutte_le_righe = page.locator("tr.trProcedura, tr.datiAmministrativi")
    n_totale = await tutte_le_righe.count()

    if indice is None:
        print(f"[scraper] ATTENZIONE {id_vip}: nessuna riga tr.trProcedura con codice esatto trovata")
        raise RuntimeError(
            f"Nessun procedimento con Codice procedura = {id_vip} trovato nella tabella "
            "'Scegli la procedura' di questa pagina."
        )

    # Troviamo la posizione della riga trProcedura target dentro la lista mista
    # (trProcedura + datiAmministrativi in ordine di documento), poi leggiamo
    # tutte le righe datiAmministrativi successive fino alla prossima trProcedura.
    righe_trProcedura = page.locator("tr.trProcedura")
    riga_target = righe_trProcedura.nth(indice)

    # xpath: tutti i <tr class="datiAmministrativi"> che sono "following-sibling"
    # della riga target, fermandoci alla prima "trProcedura" successiva.
    righe_dettaglio = riga_target.locator(
        "xpath=following-sibling::tr[contains(@class,'datiAmministrativi') "
        "and count(preceding-sibling::tr[contains(@class,'trProcedura')]) = "
        f"{indice + 1}]"
    )

    n_dettaglio = await righe_dettaglio.count()
    righe_testo = []
    for i in range(n_dettaglio):
        riga = righe_dettaglio.nth(i)
        celle = riga.locator("td")
        n_celle = await celle.count()
        if n_celle >= 2:
            etichetta = (await celle.nth(0).inner_text()).strip()
            valore = (await celle.nth(1).inner_text()).strip()
            righe_testo.append(f"{etichetta} {valore}")

    if not righe_testo:
        raise RuntimeError(
            f"Trovato il procedimento {id_vip} ma nessuna riga di dettaglio "
            "(datiAmministrativi) associata."
        )

    return "\n".join(righe_testo)


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
    """Torna sulla pagina Documentazione (non filtrata), clicca sullo <span> della sezione
    voluta (come farebbe un utente reale, così il form JS/submit funziona esattamente
    come sul sito), e raccoglie tutti i documenti risultanti, scorrendo le pagine se serve.

    NOTA: alcune sezioni (es. le foglie sotto "Integrazioni (I)") vivono dentro un nodo
    dell'albero collassato di default (style="display: none" sul <ul> genitore).
    Se lo span target non è visibile, cerchiamo il suo <li class="expandable"> antenato
    più vicino e clicchiamo la sua "hitarea" per espanderlo prima di procedere."""
    await page.goto(base_doc_url, wait_until="networkidle")

    span_sezione = page.locator(f"span.leaf[data-raggruppamentoid='{mappa_sezioni[nome_sezione_menu]}']")
    if await span_sezione.count() == 0:
        print(f"[scraper] ATTENZIONE: span per sezione '{nome_sezione_menu}' non ritrovato al secondo giro")
        return []

    target = span_sezione.first
    if not await target.is_visible():
        print(f"[scraper] '{nome_sezione_menu}': span non visibile, provo a espandere il nodo padre...")
        hitarea = target.locator(
            "xpath=ancestor::li[contains(@class,'expandable')][1]/div[contains(@class,'hitarea')]"
        )
        if await hitarea.count() > 0:
            await hitarea.first.click()
            await target.wait_for(state="visible", timeout=5000)
        else:
            print(f"[scraper] '{nome_sezione_menu}': nessun nodo espandibile trovato, forzo visibilita' via JS")
            await target.evaluate("el => { el.style.display = 'block'; let p = el.closest('ul'); while (p) { p.style.display = 'block'; p = p.parentElement ? p.parentElement.closest('ul') : null; } }")

    async with page.expect_navigation():
        await target.click()
    await page.wait_for_load_state("networkidle")

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

    riga = await trova_riga_procedura(page, id_vip)
    if riga is not None:
        link_doc = riga.locator("a.icona-documentazione-tecnico-amm")
    else:
        print(f"[scraper] ATTENZIONE {id_vip}: nessuna riga tr.trProcedura con codice esatto trovata, uso fallback .first")
        link_doc = page.locator("a.icona-documentazione-tecnico-amm").first

    if await link_doc.count() == 0:
        raise RuntimeError(
            "Link 'Documentazione' non trovato: la procedura e' ancora "
            "in fase iniziale (es. 'Verifica amministrativa') e la documentazione "
            "non e' stata ancora pubblicata sul sito."
        )

    doc_href = await link_doc.get_attribute("href")
    if not doc_href:
        raise RuntimeError(
            "Link 'Documentazione' presente ma senza href: la procedura "
            "e' ancora in fase iniziale e la documentazione non e' stata ancora pubblicata."
        )
    base_doc_url = BASE_URL + doc_href if doc_href.startswith("/") else doc_href
    print(f"[scraper] {id_vip}: pagina Documentazione = {base_doc_url}")

    await page.goto(base_doc_url, wait_until="networkidle")

    mappa_sezioni = await estrai_mappa_sezioni(page)
    print(f"[scraper] {id_vip}: sezioni trovate nel menu = {list(mappa_sezioni.keys())}")

    risultato = {
        "sezioni_disponibili": list(mappa_sezioni.keys()),
        "documenti_di_interesse": [],
        "elenco_completo_prima_pagina": await estrai_righe_tabella(page),
    }

    documenti_scaricati = []
    for nome_sezione_menu, rid in mappa_sezioni.items():
        interesse = sezione_di_interesse(nome_sezione_menu)
        print(f"[scraper] {id_vip}: sezione '{nome_sezione_menu}' (rid={rid}) -> di interesse: {interesse}")
        if not interesse:
            continue

        docs = await estrai_documenti_sezione(page, base_doc_url, mappa_sezioni, nome_sezione_menu)
        print(f"[scraper] {id_vip}: trovati {len(docs)} documenti in '{nome_sezione_menu}'")
        for doc in docs:
            doc["sezione_menu"] = nome_sezione_menu
            if not doc.get("download_url"):
                print(f"[scraper] {id_vip}: documento senza download_url: {doc}")
            documenti_scaricati.append(doc)

    risultato["documenti_di_interesse"] = documenti_scaricati
    return risultato


async def analizza_progetto(browser, id_vip: str) -> dict:
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    dati = {"id_vip": id_vip, "trovato": False}
    try:
        print(f"[scraper] {id_vip}: avvio ricerca...")
        ricerca = await cerca_e_apri_progetto(page, id_vip)
        if not ricerca["trovato"]:
            dati["errore"] = ricerca["errore"]
            print(f"[scraper] {id_vip}: ricerca fallita: {ricerca['errore']}")
            return dati

        dati["trovato"] = True
        info_url = ricerca["info_url"]
        dati["info_url"] = info_url
        print(f"[scraper] {id_vip}: trovato, info_url={info_url}")

        await page.goto(info_url, wait_until="networkidle")
        dati["nome_progetto"] = await estrai_nome_progetto(page)
        print(f"[scraper] {id_vip}: nome progetto = {dati['nome_progetto'][:60]}...")

        print(f"[scraper] {id_vip}: estraggo Dettagli Procedura...")
        dati["dettagli_procedura"] = await estrai_dettagli_procedura(page, info_url, id_vip)
        dati["hash_dettagli"] = hashlib.sha256(dati["dettagli_procedura"].encode("utf-8")).hexdigest()
        print(f"[scraper] {id_vip}: Dettagli Procedura OK ({len(dati['dettagli_procedura'])} caratteri)")

        print(f"[scraper] {id_vip}: estraggo Documentazione...")
        dati["documentazione"] = await estrai_documentazione(page, info_url, id_vip)
        print(f"[scraper] {id_vip}: Documentazione OK")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        dati["errore"] = f"Errore durante scraping: {e}"
        print(f"[scraper] {id_vip}: ECCEZIONE:\n{tb}")
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
