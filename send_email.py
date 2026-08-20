"""
send_email.py
Compone e invia il report via SMTP (Gmail/Outlook con app password),
con eventuali documenti allegati (osservazioni/pareri).
"""

import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path


def costruisci_html(risultati: list[dict]) -> str:
    righe = []
    for r in risultati:
        id_vip = r["id_vip"]
        if r["stato"] == "errore":
            righe.append(f"<h3>Progetto {id_vip} — ERRORE</h3><p>{r['messaggio']}</p><hr>")
            continue

        allegati_html = ""
        if r["documenti_allegati"]:
            items = "".join(
                f"<li>{d.get('etichetta')}: {'allegato' if 'path' in d else 'ERRORE - ' + d.get('errore', '')}</li>"
                for d in r["documenti_allegati"]
            )
            allegati_html = f"<p><b>Documenti trovati (colonna D):</b></p><ul>{items}</ul>"

        righe.append(f"""
        <h3>Progetto {id_vip}</h3>
        <p><b>Variazioni Dettagli Procedura:</b><br>{r['confronto_dettagli_procedura'].replace(chr(10), '<br>')}</p>
        <p><b>Variazioni Documentazione:</b><br>{r['confronto_documentazione'].replace(chr(10), '<br>')}</p>
        {allegati_html}
        <hr>
        """)

    data_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""
    <html><body>
    <h2>Report monitoraggio progetti VIA — {data_str}</h2>
    {''.join(righe)}
    </body></html>
    """


def invia_report(risultati: list[dict], destinatario: str):
    smtp_host = os.environ["SMTP_HOST"]        # es. smtp.gmail.com
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    msg = EmailMessage()
    msg["Subject"] = f"Report progetti VIA — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    msg["From"] = smtp_user
    msg["To"] = destinatario

    html = costruisci_html(risultati)
    msg.set_content("Il tuo client email non supporta HTML. Attiva la visualizzazione HTML.")
    msg.add_alternative(html, subtype="html")

    # Allegati: tutti i documenti scaricati nelle colonne D richieste
    for r in risultati:
        if r.get("stato") != "ok":
            continue
        for doc in r.get("documenti_allegati", []):
            path = doc.get("path")
            if path and Path(path).exists():
                data = Path(path).read_bytes()
                msg.add_attachment(
                    data,
                    maintype="application",
                    subtype="octet-stream",
                    filename=Path(path).name,
                )

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"[send_email] Report inviato a {destinatario}")
