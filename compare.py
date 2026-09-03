"""
compare.py (versione gratuita, senza API esterne)
Confronta lo snapshot corrente di un progetto con quello salvato al giro
precedente usando difflib (libreria standard Python, nessun costo).
"""

import difflib


def confronta_testi(id_vip: str, sezione: str, testo_precedente: str | None, testo_attuale: str) -> str:
    """Ritorna una descrizione testuale delle differenze tra due versioni di testo.
    Se non esiste una versione precedente, segnala che è la prima rilevazione."""
    if not testo_precedente:
        return (
            f"Prima rilevazione per '{sezione}' del progetto {id_vip}: "
            "nessun confronto disponibile, verrà usato come baseline per il prossimo giro."
        )

    if testo_precedente.strip() == testo_attuale.strip():
        return f"Nessuna variazione rilevata in '{sezione}'."

    righe_precedenti = testo_precedente.splitlines()
    righe_attuali = testo_attuale.splitlines()

    diff = difflib.unified_diff(
        righe_precedenti, righe_attuali,
        lineterm="", n=0
    )

    aggiunte = []
    rimosse = []
    for riga in diff:
        if riga.startswith("+++") or riga.startswith("---") or riga.startswith("@@"):
            continue
        if riga.startswith("+"):
            testo_pulito = riga[1:].strip()
            if testo_pulito:
                aggiunte.append(testo_pulito)
        elif riga.startswith("-"):
            testo_pulito = riga[1:].strip()
            if testo_pulito:
                rimosse.append(testo_pulito)

    if not aggiunte and not rimosse:
        return f"Nessuna variazione sostanziale rilevata in '{sezione}' (solo differenze di spaziatura/formattazione)."

    parti = [f"Variazioni rilevate in '{sezione}':"]
    if aggiunte:
        parti.append("\nContenuto AGGIUNTO/MODIFICATO:")
        for riga in aggiunte[:30]:
            parti.append(f"  + {riga}")
        if len(aggiunte) > 30:
            parti.append(f"  ... e altre {len(aggiunte) - 30} righe aggiunte")

    if rimosse:
        parti.append("\nContenuto RIMOSSO/SOSTITUITO:")
        for riga in rimosse[:30]:
            parti.append(f"  - {riga}")
        if len(rimosse) > 30:
            parti.append(f"  ... e altre {len(rimosse) - 30} righe rimosse")

    return "\n".join(parti)


def genera_riassunto_progetto(id_vip: str, dati_precedenti: dict | None, dati_attuali: dict) -> dict:
    """Genera il blocco di confronto completo per un progetto (dettagli + documentazione)."""
    if not dati_attuali.get("trovato"):
        return {
            "id_vip": id_vip,
            "stato": "errore",
            "messaggio": dati_attuali.get("errore", "Progetto non trovato"),
        }

    testo_prec_dettagli = (dati_precedenti or {}).get("dettagli_procedura")
    testo_att_dettagli = dati_attuali.get("dettagli_procedura", "")

    testo_prec_doc = ((dati_precedenti or {}).get("documentazione") or {}).get("esportato_testo")
    testo_att_doc = (dati_attuali.get("documentazione") or {}).get("esportato_testo", "")

    confronto_dettagli = confronta_testi(id_vip, "Dettagli Procedura", testo_prec_dettagli, testo_att_dettagli)
    confronto_doc = confronta_testi(id_vip, "Documentazione (Esporta)", testo_prec_doc, testo_att_doc)

    nuovi_documenti = dati_attuali.get("documentazione", {}).get("documenti_scaricati", [])

    return {
        "id_vip": id_vip,
        "stato": "ok",
        "confronto_dettagli_procedura": confronto_dettagli,
        "confronto_documentazione": confronto_doc,
        "documenti_allegati": nuovi_documenti,
    }
