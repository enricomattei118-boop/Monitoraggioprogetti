"""
main.py
Orchestratore eseguito da GitHub Actions.

Flusso:
 1. Controlla se è l'ora giusta (12:00 o 18:00 ora italiana), salvo test manuali forzati
 2. Legge progetti.csv (lista ID_VIP da monitorare)
 3. Per ciascun progetto: scraping (scraper.py)
 4. Carica lo snapshot precedente da state/{id_vip}.json (se esiste)
 5. Confronta vecchio vs nuovo (compare.py)
 6. Invia report via email (send_email.py)
 7. Salva il nuovo snapshot in state/{id_vip}.json (il workflow lo committa)
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper import analizza_tutti
from compare import genera_riassunto_progetto
from send_email import invia_report

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)
PROGETTI_CSV = Path("progetti.csv")
DESTINATARIO = os.environ["REPORT_TO_EMAIL"]

ORARI_VALIDI = {12, 18}  # ore italiane in cui il report va effettivamente eseguito


def e_ora_di_eseguire() -> bool:
    forza = os.environ.get("FORZA_ESECUZIONE", "false").lower() == "true"
    if forza:
        print("[main] Esecuzione forzata (test manuale), salto il controllo orario.")
        return True

    ora_italiana = datetime.now(ZoneInfo("Europe/Rome")).hour
    print(f"[main] Ora attuale in Italia: {ora_italiana}")
    return ora_italiana in ORARI_VALIDI


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
    path.write_text(json.dumps(dati, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main():
    if not e_ora_di_eseguire():
        print("[main] Non è l'orario previsto (12:00 o 18:00 ora italiana). Esco senza fare nulla.")
        sys.exit(0)

    id_vip_list = leggi_id_vip_list()
    print(f"[main] Progetti da monitorare: {id_vip_list}")

    risultati_scraping = asyncio.run(analizza_tutti(id_vip_list))

    risultati_report = []
    for dati_attuali in risultati_scraping:
        id_vip = dati_attuali["id_vip"]
        dati_precedenti = carica_stato_precedente(id_vip)

        riassunto = genera_riassunto_progetto(id_vip, dati_precedenti, dati_attuali)
        risultati_report.append(riassunto)

        if dati_attuali.get("trovato"):
            salva_stato(id_vip, dati_attuali)

    invia_report(risultati_report, DESTINATARIO)


if __name__ == "__main__":
    main()
