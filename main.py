#!/usr/bin/env python3
# main.py
# Orchestratore eseguito da GitHub Actions.
#
# Flusso:
#  1. Controlla se e' passata una fascia oraria (6:00, 10:00, 14:00 o 18:00
#     ora italiana) per cui non abbiamo ancora inviato il report oggi, salvo
#     test manuali forzati. Tollerante ai ritardi di GitHub Actions: se il
#     cron scatta in ritardo (es. il cron delle 18:00 parte alle 22:23),
#     esegue comunque, purche' non abbiamo gia' inviato per quella fascia.
#  2. Legge progetti.csv (lista ID_VIP da monitorare)
#  3. Per ciascun progetto: scraping (scraper.py)
#  4. Carica lo snapshot precedente da state/{id_vip}.json (se esiste)
#  5. Confronta vecchio vs nuovo (compare.py)
#  6. Invia report via email (send_email.py)
#  7. Salva il nuovo snapshot in state/{id_vip}.json (il workflow lo committa)
#  8. Segna la fascia come "inviata oggi" in state/_ultimo_invio.json

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
FILE_ULTIMO_INVIO = STATE_DIR / "_ultimo_invio.json"

FASCE_ORARIE = [6, 10, 14, 18]  # ore italiane in cui il report va effettivamente eseguito


def _leggi_ultimo_invio() -> dict:
    if FILE_ULTIMO_INVIO.exists():
        try:
            return json.loads(FILE_ULTIMO_INVIO.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _segna_invio_effettuato(data_str: str, fascia: int):
    dati = _leggi_ultimo_invio()
    dati[data_str] = fascia
    FILE_ULTIMO_INVIO.write_text(json.dumps(dati, indent=2), encoding="utf-8")


def fascia_da_eseguire() -> int | None:
    """Ritorna la fascia oraria (6/10/14/18) da eseguire ora, o None se non
    c'e' nulla da fare. Tollerante ai ritardi: prende la fascia piu' recente
    gia' passata oggi per cui non risulta ancora un invio registrato."""
    ora_italiana = datetime.now(ZoneInfo("Europe/Rome"))
    data_str = ora_italiana.strftime("%Y-%m-%d")
    ora = ora_italiana.hour

    fasce_passate = [f for f in FASCE_ORARIE if f <= ora]
    if not fasce_passate:
        return None  # e' ancora prima delle 6:00, nessuna fascia e' ancora arrivata

    ultima_fascia_passata = max(fasce_passate)

    gia_inviate_oggi = _leggi_ultimo_invio()
    ultima_registrata = gia_inviate_oggi.get(data_str)

    if ultima_registrata == ultima_fascia_passata:
        return None  # gia' inviato per questa fascia oggi

    return ultima_fascia_passata


def leggi_progetti() -> list[dict]:
    """Legge progetti.csv. Supporta sia il formato con 'titolo_breve' (etichetta
    personalizzata mostrata al posto del lungo nome ufficiale nel report) sia
    il vecchio formato senza (in quel caso titolo_breve resta vuoto e il
    report usa il nome ufficiale del progetto come prima)."""
    with open(PROGETTI_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        progetti = []
        for row in reader:
            id_vip = row.get("id_vip", "").strip()
            if not id_vip:
                continue
            progetti.append({
                "id_vip": id_vip,
                "titolo_breve": (row.get("titolo_breve") or "").strip(),
            })
        return progetti


def leggi_id_vip_list() -> list[str]:
    return [p["id_vip"] for p in leggi_progetti()]


def carica_stato_precedente(id_vip: str) -> dict | None:
    path = STATE_DIR / f"{id_vip}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def salva_stato(id_vip: str, dati: dict):
    path = STATE_DIR / f"{id_vip}.json"
    path.write_text(json.dumps(dati, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main():
    forza = os.environ.get("FORZA_ESECUZIONE", "false").lower() == "true"

    if forza:
        print("[main] Esecuzione forzata (test manuale), salto il controllo orario.")
    else:
        fascia = fascia_da_eseguire()
        ora_italiana = datetime.now(ZoneInfo("Europe/Rome"))
        print(f"[main] Ora attuale in Italia: {ora_italiana.strftime('%H:%M')}")
        if fascia is None:
            print("[main] Nessuna fascia oraria da eseguire (o gia' inviato oggi per la fascia corrente). Esco.")
            sys.exit(0)
        print(f"[main] Eseguo per la fascia delle {fascia}:00 (puo' essere in ritardo rispetto all'orario nominale).")

    progetti = leggi_progetti()
    id_vip_list = [p["id_vip"] for p in progetti]
    mappa_titoli_brevi = {p["id_vip"]: p["titolo_breve"] for p in progetti}
    print(f"[main] Progetti da monitorare: {id_vip_list}")

    risultati_scraping = asyncio.run(analizza_tutti(id_vip_list))

    risultati_report = []
    for dati_attuali in risultati_scraping:
        id_vip = dati_attuali["id_vip"]
        dati_precedenti = carica_stato_precedente(id_vip)

        riassunto = genera_riassunto_progetto(id_vip, dati_precedenti, dati_attuali)
        riassunto["titolo_breve"] = mappa_titoli_brevi.get(id_vip, "")
        risultati_report.append(riassunto)

        if dati_attuali.get("trovato"):
            salva_stato(id_vip, dati_attuali)

    invia_report(risultati_report, DESTINATARIO)

    if not forza:
        ora_italiana = datetime.now(ZoneInfo("Europe/Rome"))
        _segna_invio_effettuato(ora_italiana.strftime("%Y-%m-%d"), fascia)


if __name__ == "__main__":
    main()
