"""
main.py
Orchestratore eseguito da GitHub Actions due volte al giorno.

Flusso:
 1. Legge progetti.csv (lista ID_VIP da monitorare)
 2. Per ciascun progetto: scraping (scraper.py)
 3. Carica lo snapshot precedente da state/{id_vip}.json (se esiste)
 4. Confronta vecchio vs nuovo con Claude (compare.py)
 5. Invia report via email (send_email.py)
 6. Salva il nuovo snapshot in state/{id_vip}.json (verrà committato dal workflow)
"""

import asyncio
import csv
import json
import os
from pathlib import Path

from scraper import analizza_tutti
from compare import genera_riassunto_progetto
from send_email import invia_report

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)
PROGETTI_CSV = Path("progetti.csv")
DESTINATARIO = os.environ["REPORT_TO_EMAIL"]


def leggi_id_vip_list() -> list[str]:
    with open(PROGETTI_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["id_vip"].strip() for row in reader if row["id_vip"].strip()]


def carica_stato_precedente(id_vip: str) -> dict | None:
    path = STATE_DIR / f"{id_vip}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def salva_stato(id_vip: str, dati: dict):
    path = STATE_DIR / f"{id_vip}.json"
    # Non salviamo il testo enorme dei documenti binari, solo i metadati + testo dettagli/export
    path.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    id_vip_list = leggi_id_vip_list()
    print(f"[main] Progetti da monitorare: {id_vip_list}")

    risultati_scraping = asyncio.run(analizza_tutti(id_vip_list))

    risultati_report = []
    for dati_attuali in risultati_scraping:
        id_vip = dati_attuali["id_vip"]
        dati_precedenti = carica_stato_precedente(id_vip)

        riassunto = genera_riassunto_progetto(id_vip, dati_precedenti, dati_attuali)
        risultati_report.append(riassunto)

        # Salva lo stato solo se lo scraping è andato a buon fine
        if dati_attuali.get("trovato"):
            salva_stato(id_vip, dati_attuali)

    invia_report(risultati_report, DESTINATARIO)


if __name__ == "__main__":
    main()
