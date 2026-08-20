"""
compare.py
Confronta lo snapshot corrente di un progetto con quello salvato al giro
precedente, usando Claude per produrre un riassunto leggibile delle
variazioni (non solo un diff riga per riga).
"""

import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-6"


def confronta_testi(id_vip: str, sezione: str, testo_precedente: str | None, testo_attuale: str) -> str:
    """Ritorna una sintesi in italiano delle differenze tra due versioni di testo.
    Se non esiste una versione precedente, segnala che è la prima rilevazione."""
    if not testo_precedente:
        return (
            f"Prima rilevazione per '{sezione}' del progetto {id_vip}: "
            "nessun confronto disponibile, verrà usato come baseline per il prossimo giro."
        )

    if testo_precedente.strip() == testo_attuale.strip():
        return f"Nessuna variazione rilevata in '{sezione}'."

    prompt = f"""Confronta queste due versioni del contenuto "{sezione}" relativo al progetto VIA con codice {id_vip}.

VERSIONE PRECEDENTE:
---
{testo_precedente[:8000]}
---

VERSIONE ATTUALE:
---
{testo_attuale[:8000]}
---

Elenca in modo sintetico e puntuale (bullet points) SOLO le variazioni sostanziali
(nuovi documenti, cambio di stato/fase della procedura, nuove date, nuovi pareri,
modifiche a scadenze). Ignora differenze puramente di formattazione o spazi.
Se non ci sono variazioni sostanziali, scrivi semplicemente "Nessuna variazione sostanziale."
Rispondi in italiano, in modo conciso."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


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
