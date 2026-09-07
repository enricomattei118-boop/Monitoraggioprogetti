"""
compare.py (versione gratuita, senza API esterne)
Confronta lo snapshot corrente di un progetto con quello del giro precedente
usando difflib (libreria standard, nessun costo) sia sui "Dettagli Procedura"
sia sull'elenco documenti della Documentazione.
"""

import difflib


def confronta_testi(id_vip: str, sezione: str, testo_precedente: str | None, testo_attuale: str) -> str:
    if not testo_precedente:
        return (
            f"Prima rilevazione per '{sezione}': nessun confronto disponibile, "
            "verra' usato come base per il prossimo giro."
        )

    if testo_precedente.strip() == testo_attuale.strip():
        return f"Nessuna variazione rilevata in '{sezione}'."

    righe_precedenti = testo_precedente.splitlines()
    righe_attuali = testo_attuale.splitlines()
    diff = difflib.unified_diff(righe_precedenti, righe_attuali, lineterm="", n=0)

    aggiunte, rimosse = [], []
    for riga in diff:
        if riga.startswith(("+++", "---", "@@")):
            continue
        if riga.startswith("+"):
            t = riga[1:].strip()
            if t:
                aggiunte.append(t)
        elif riga.startswith("-"):
            t = riga[1:].strip()
            if t:
                rimosse.append(t)

    if not aggiunte and not rimosse:
        return f"Nessuna variazione sostanziale in '{sezione}' (solo differenze di formattazione)."

    parti = [f"Variazioni rilevate in '{sezione}':"]
    if aggiunte:
        parti.append("Contenuto AGGIUNTO/MODIFICATO:")
        for r in aggiunte[:30]:
            parti.append(f"  + {r}")
        if len(aggiunte) > 30:
            parti.append(f"  ... e altre {len(aggiunte) - 30} righe")
    if rimosse:
        parti.append("Contenuto RIMOSSO/SOSTITUITO:")
        for r in rimosse[:30]:
            parti.append(f"  - {r}")
        if len(rimosse) > 30:
            parti.append(f"  ... e altre {len(rimosse) - 30} righe")

    return "\n".join(parti)


def confronta_elenco_documenti(docs_precedenti: list[dict] | None, docs_attuali: list[dict]) -> tuple[str, list[dict]]:
    """Confronta l'elenco documenti (sezioni di interesse) tra due rilevazioni.
    Ritorna (descrizione testuale delle variazioni, lista dei documenti NUOVI da allegare)."""
    docs_precedenti = docs_precedenti or []

    chiavi_precedenti = {(d.get("nome_file"), d.get("sezione_menu")) for d in docs_precedenti}
    nuovi = [d for d in docs_attuali if (d.get("nome_file"), d.get("sezione_menu")) not in chiavi_precedenti]

    if not docs_precedenti and not docs_attuali:
        return "Nessun documento presente nelle sezioni monitorate.", []

    if not docs_precedenti:
        msg = f"Prima rilevazione: {len(docs_attuali)} documento/i trovato/i nelle sezioni monitorate (vedi allegati)."
        return msg, docs_attuali

    if not nuovi:
        return "Nessun nuovo documento nelle sezioni monitorate rispetto al giro precedente.", []

    righe = [f"Trovati {len(nuovi)} nuovo/i documento/i nelle sezioni monitorate:"]
    for d in nuovi:
        righe.append(f"  - [{d.get('sezione_menu')}] {d.get('titolo')} ({d.get('nome_file')}, {d.get('data')})")
    return "\n".join(righe), nuovi


def genera_riassunto_progetto(id_vip: str, dati_precedenti: dict | None, dati_attuali: dict) -> dict:
    if not dati_attuali.get("trovato"):
        return {
            "id_vip": id_vip,
            "nome_progetto": (dati_precedenti or {}).get("nome_progetto", ""),
            "stato": "errore",
            "messaggio": dati_attuali.get("errore", "Progetto non trovato"),
        }

    # IMPORTANTE: anche se 'trovato' è True (la ricerca ha funzionato), lo scraping
    # potrebbe essere fallito più avanti (es. Dettagli Procedura o Documentazione).
    # In quel caso 'errore' è comunque valorizzato: lo segnaliamo esplicitamente
    # invece di generare un report "pulito" che nasconde il problema.
    if dati_attuali.get("errore"):
        errore = dati_attuali["errore"]
        # Caso "non ancora disponibile" (fase iniziale, es. Verifica amministrativa):
        # non e' un guasto tecnico, quindi lo segnaliamo con uno stato piu' neutro.
        if "fase iniziale" in errore.lower() or "verifica amministrativa" in errore.lower():
            return {
                "id_vip": id_vip,
                "nome_progetto": dati_attuali.get("nome_progetto", ""),
                "stato": "non_disponibile",
                "messaggio": errore,
            }
        return {
            "id_vip": id_vip,
            "nome_progetto": dati_attuali.get("nome_progetto", ""),
            "stato": "errore_parziale",
            "messaggio": errore,
        }

    testo_prec_dettagli = (dati_precedenti or {}).get("dettagli_procedura")
    testo_att_dettagli = dati_attuali.get("dettagli_procedura", "")
    confronto_dettagli = confronta_testi(id_vip, "Dettagli Procedura", testo_prec_dettagli, testo_att_dettagli)

    docs_prec = ((dati_precedenti or {}).get("documentazione") or {}).get("documenti_di_interesse", [])
    docs_att = (dati_attuali.get("documentazione") or {}).get("documenti_di_interesse", [])
    confronto_doc, nuovi_allegati = confronta_elenco_documenti(docs_prec, docs_att)

    return {
        "id_vip": id_vip,
        "nome_progetto": dati_attuali.get("nome_progetto", ""),
        "info_url": dati_attuali.get("info_url", ""),
        "stato": "ok",
        "confronto_dettagli_procedura": confronto_dettagli,
        "confronto_documentazione": confronto_doc,
        "documenti_allegati": nuovi_allegati,
    }
