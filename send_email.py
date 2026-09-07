"""
send_email.py
Compone e invia il report via SMTP (Gmail/Outlook con app password),
con eventuali PDF allegati (osservazioni/pareri nuovi rispetto al giro precedente).
"""

import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path


def costruisci_html(risultati: list[dict]) -> str:
    blocchi = []
    for r in risultati:
        id_vip = r["id_vip"]
        nome = r.get("nome_progetto") or "(nome non disponibile)"

        if r["stato"] in ("errore", "errore_parziale"):
            etichetta = "ERRORE" if r["stato"] == "errore" else "ERRORE PARZIALE (progetto trovato, scraping incompleto)"
            blocchi.append(f"""
            <div style="margin-bottom:24px;padding:12px;background:#fdecea;border-left:4px solid #d93025;">
              <h3 style="margin:0 0 6px 0;">Progetto {id_vip} - {etichetta}</h3>
              <p style="margin:0 0 4px 0;font-size:14px;color:#555;"><i>{nome}</i></p>
              <p style="margin:0;">{r['messaggio']}</p>
            </div>
            """)
            continue

        allegati_html = ""
        if r["documenti_allegati"]:
            items = "".join(
                f"<li>[{d.get('sezione_menu')}] {d.get('titolo')} "
                f"({d.get('nome_file')}, {d.get('data')})"
                + (f' - <a href="{d["download_url"]}">apri/scarica</a>' if d.get("download_url") else "")
                + "</li>"
                for d in r["documenti_allegati"]
            )
            allegati_html = f"<p><b>Nuovi documenti nelle sezioni monitorate:</b></p><ul>{items}</ul>"

        blocchi.append(f"""
        <div style="margin-bottom:28px;padding:14px;border:1px solid #ddd;border-radius:6px;">
          <h3 style="margin:0 0 4px 0;color:#1a5276;">Progetto {id_vip}</h3>
          <p style="margin:0 0 12px 0;font-size:14px;color:#555;"><i>{nome}</i></p>

          <p style="margin:8px 0 2px 0;"><b>Variazioni Dettagli Procedura</b></p>
          <pre style="white-space:pre-wrap;font-family:inherit;background:#f7f7f7;padding:8px;border-radius:4px;margin:0 0 12px 0;">{r['confronto_dettagli_procedura']}</pre>

          <p style="margin:8px 0 2px 0;"><b>Variazioni Documentazione</b></p>
          <pre style="white-space:pre-wrap;font-family:inherit;background:#f7f7f7;padding:8px;border-radius:4px;margin:0 0 12px 0;">{r['confronto_documentazione']}</pre>

          {allegati_html}
        </div>
        """)

    data_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""
    <html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;">
    <h2>Report monitoraggio progetti VIA - {data_str}</h2>
    {''.join(blocchi)}
    </body></html>
    """


def invia_report(risultati: list[dict], destinatario: str):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    msg = EmailMessage()
    msg["Subject"] = f"Report progetti VIA - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    msg["From"] = smtp_user
    msg["To"] = destinatario

    html = costruisci_html(risultati)
    msg.set_content("Il tuo client email non supporta HTML. Attiva la visualizzazione HTML.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"[send_email] Report inviato a {destinatario}")
