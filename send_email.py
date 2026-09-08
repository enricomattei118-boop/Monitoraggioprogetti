"""
send_email.py
Compone e invia il report via SMTP (Gmail/Outlook con app password).
Documenti presentati come link (nessun allegato fisico), raggruppati per
sezione monitorata, con un indice riassuntivo in cima al report.
"""

import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from collections import OrderedDict

COLORE_PRIMARIO = "#1a5276"
COLORE_SFONDO_PAGINA = "#f4f6f8"
COLORE_ERRORE_BG = "#fdecea"
COLORE_ERRORE_BORDO = "#d93025"
COLORE_OK_BORDO = "#2e7d32"
COLORE_VARIATO_BG = "#fff8e1"
COLORE_VARIATO_BORDO = "#f9a825"


def _badge(testo: str, colore: str) -> str:
    return (
        f'<span style="display:inline-block;background:{colore};color:#fff;'
        f'font-size:11px;font-weight:bold;padding:2px 8px;border-radius:10px;'
        f'letter-spacing:.3px;">{testo}</span>'
    )


def _raggruppa_per_sezione(documenti: list[dict]) -> "OrderedDict[str, list[dict]]":
    """Raggruppa i documenti per nome sezione, mantenendo l'ordine di prima comparsa."""
    gruppi: "OrderedDict[str, list[dict]]" = OrderedDict()
    for d in documenti:
        sezione = d.get("sezione_menu") or "Altro"
        gruppi.setdefault(sezione, []).append(d)
    return gruppi


def _sezione_documenti_html(documenti: list[dict]) -> str:
    """Genera l'HTML dei documenti raggruppati per sezione, con intestazioni di gruppo."""
    if not documenti:
        return ""

    gruppi = _raggruppa_per_sezione(documenti)
    blocchi_sezione = []
    for nome_sezione, docs in gruppi.items():
        righe = []
        for d in docs:
            titolo = d.get("titolo") or d.get("nome_file") or "(senza titolo)"
            nome_file = d.get("nome_file") or ""
            data = d.get("data") or ""
            link = d.get("download_url")
            link_html = f'<a href="{link}" style="color:{COLORE_PRIMARIO};text-decoration:none;font-weight:600;">Apri &rarr;</a>' if link else '<span style="color:#999;">link non disponibile</span>'
            righe.append(f"""
            <tr>
              <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:13px;color:#222;">{titolo}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:12px;color:#777;white-space:nowrap;">{data}</td>
              <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:12px;white-space:nowrap;">{link_html}</td>
            </tr>
            """)

        blocchi_sezione.append(f"""
        <div style="margin:14px 0 6px 0;">
          <div style="font-size:13px;font-weight:700;color:{COLORE_PRIMARIO};text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px;">
            {nome_sezione} <span style="color:#999;font-weight:400;text-transform:none;">({len(docs)})</span>
          </div>
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            {''.join(righe)}
          </table>
        </div>
        """)

    return "".join(blocchi_sezione)


def _blocco_progetto(r: dict) -> str:
    id_vip = r["id_vip"]
    nome = r.get("nome_progetto") or "(nome non disponibile)"
    titolo_breve = r.get("titolo_breve") or ""
    intestazione = f"Progetto {id_vip} - {titolo_breve}" if titolo_breve else f"Progetto {id_vip}"

    if r["stato"] == "non_disponibile":
        return f"""
        <div id="progetto-{id_vip}" style="margin-bottom:20px;padding:16px 18px;background:#f5f5f5;
             border-left:4px solid #999;border-radius:6px;">
          <table style="width:100%;margin-bottom:6px;"><tr>
            <td style="font-size:15px;font-weight:700;color:#222;">{intestazione}</td>
            <td style="text-align:right;white-space:nowrap;">{_badge("NON ANCORA DISPONIBILE", "#999")}</td>
          </tr></table>
          <p style="margin:0 0 8px 0;font-size:13px;color:#555;font-style:italic;">{nome}</p>
          <p style="margin:0;font-size:13px;color:#666;">{r['messaggio']}</p>
        </div>
        """

    if r["stato"] in ("errore", "errore_parziale"):
        etichetta = "ERRORE" if r["stato"] == "errore" else "ERRORE PARZIALE"
        return f"""
        <div id="progetto-{id_vip}" style="margin-bottom:20px;padding:16px 18px;background:{COLORE_ERRORE_BG};
             border-left:4px solid {COLORE_ERRORE_BORDO};border-radius:6px;">
          <table style="width:100%;margin-bottom:6px;"><tr>
            <td style="font-size:15px;font-weight:700;color:#222;">{intestazione}</td>
            <td style="text-align:right;white-space:nowrap;">{_badge(etichetta, COLORE_ERRORE_BORDO)}</td>
          </tr></table>
          <p style="margin:0 0 8px 0;font-size:13px;color:#555;font-style:italic;">{nome}</p>
          <p style="margin:0;font-size:13px;color:#a33;">{r['messaggio']}</p>
        </div>
        """

    ha_variazioni_dettagli = "nessuna variazione" not in r['confronto_dettagli_procedura'].lower()
    ha_variazioni_doc = bool(r["documenti_allegati"]) and "nessun nuovo documento" not in r['confronto_documentazione'].lower()
    variato = ha_variazioni_dettagli or ha_variazioni_doc

    badge_stato = _badge("VARIAZIONI RILEVATE", COLORE_VARIATO_BORDO) if variato else _badge("NESSUNA VARIAZIONE", "#888")
    bordo_alto = COLORE_VARIATO_BORDO if variato else COLORE_OK_BORDO

    documenti_html = _sezione_documenti_html(r["documenti_allegati"])
    riepilogo_doc = r['confronto_documentazione'] if not documenti_html else ""

    return f"""
    <div id="progetto-{id_vip}" style="margin-bottom:22px;padding:16px 18px;background:#fff;
         border:1px solid #e2e2e2;border-top:4px solid {bordo_alto};border-radius:6px;
         box-shadow:0 1px 2px rgba(0,0,0,0.04);">
      <table style="width:100%;margin-bottom:4px;"><tr>
        <td style="font-size:15px;font-weight:700;color:{COLORE_PRIMARIO};">{intestazione}</td>
        <td style="text-align:right;white-space:nowrap;">{badge_stato}</td>
      </tr></table>
      <p style="margin:0 0 12px 0;font-size:13px;color:#555;font-style:italic;">{nome}</p>

      <div style="font-size:12px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.3px;margin-bottom:2px;">
        Dettagli Procedura
      </div>
      <p style="margin:0 0 10px 0;font-size:13px;color:#333;white-space:pre-wrap;background:#f7f7f7;padding:8px 10px;border-radius:4px;">{r['confronto_dettagli_procedura']}</p>

      <div style="font-size:12px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.3px;margin-bottom:2px;">
        Documentazione
      </div>
      {f'<p style="margin:0;font-size:13px;color:#333;background:#f7f7f7;padding:8px 10px;border-radius:4px;">{riepilogo_doc}</p>' if riepilogo_doc else ''}
      {documenti_html}
    </div>
    """


def _indice_html(risultati: list[dict]) -> str:
    """Piccolo sommario cliccabile in cima al report, utile con molti progetti."""
    righe = []
    for r in risultati:
        id_vip = r["id_vip"]
        etichetta = r.get("titolo_breve") or (r.get("nome_progetto") or "")[:70]
        if r["stato"] == "non_disponibile":
            badge = _badge("N/D", "#999")
        elif r["stato"] in ("errore", "errore_parziale"):
            badge = _badge("ERRORE", COLORE_ERRORE_BORDO)
        else:
            variato = ("nessuna variazione" not in r['confronto_dettagli_procedura'].lower()) or \
                      (bool(r["documenti_allegati"]) and "nessun nuovo documento" not in r['confronto_documentazione'].lower())
            badge = _badge("VARIAZIONI", COLORE_VARIATO_BORDO) if variato else _badge("OK", "#888")
        righe.append(f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;">
            <a href="#progetto-{id_vip}" style="color:{COLORE_PRIMARIO};text-decoration:none;font-weight:600;">{id_vip}</a>
            <span style="color:#777;"> - {etichetta}</span>
          </td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;">{badge}</td>
        </tr>
        """)

    return f"""
    <div style="background:#fff;border:1px solid #e2e2e2;border-radius:6px;padding:10px 16px;margin-bottom:24px;">
      <div style="font-size:13px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.3px;margin:6px 0;">
        Indice ({len(risultati)} progetti)
      </div>
      <table style="width:100%;border-collapse:collapse;">
        {''.join(righe)}
      </table>
    </div>
    """


def costruisci_html(risultati: list[dict]) -> str:
    data_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    indice = _indice_html(risultati) if len(risultati) > 1 else ""
    blocchi = "".join(_blocco_progetto(r) for r in risultati)

    return f"""
    <html>
    <head>
      <meta name="format-detection" content="address=no">
      <meta name="format-detection" content="telephone=no">
      <meta name="format-detection" content="date=no">
      <meta name="format-detection" content="email=no">
    </head>
    <body style="font-family:-apple-system,Segoe UI,Arial,Helvetica,sans-serif;
                 color:#222;background:{COLORE_SFONDO_PAGINA};margin:0;padding:24px 12px;">
      <div style="max-width:760px;margin:0 auto;">
        <h2 style="color:{COLORE_PRIMARIO};margin:0 0 4px 0;">Report monitoraggio progetti VIA</h2>
        <p style="color:#777;font-size:13px;margin:0 0 20px 0;">{data_str}</p>
        {indice}
        {blocchi}
      </div>
    </body>
    </html>
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
