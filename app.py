# -*- coding: utf-8 -*-
"""
Gestionale negozio abbigliamento — RESTYLE UI/UX
- Look & feel moderno con typography, colori coerenti e "cards"
- Miglior uso di icone/emoji, badge e metriche
- Tabelle con column_config (badge, number format) e azzurro desaturato
- Sidebar raffinata con brand header
- Mini utility per KPI cards ed helper di layout

NOTE: aggiungi (opzionale) un file .streamlit/config.toml per i colori nativi di Streamlit:

[theme]
primaryColor="#2563EB"
backgroundColor="#0B1220"
secondaryBackgroundColor="#111827"
textColor="#E5E7EB"
font="sans serif"

Puoi copiare la logica originale: questa versione mantiene le stesse funzionalità
ma applica uno stile più curato.
"""

import os
import io
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.lower().startswith("postgresql") if DATABASE_URL else False
_engine: Engine | None = None

import sqlite3
# compat: closing() può non essere disponibile in alcuni ambienti
try:
    from contextlib import closing
except Exception:  # fallback di sicurezza
    from contextlib import contextmanager
    @contextmanager
    def closing(obj):
        try:
            yield obj
        finally:
            try:
                obj.close()
            except Exception:
                pass
from datetime import datetime, date
from typing import Tuple, Optional
from streamlit_webrtc import webrtc_streamer, WebRtcMode  # pip install streamlit-webrtc av

import av, time
import pandas as pd
import streamlit as st

try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAS_ZBAR = True
except Exception:
    HAS_ZBAR = False

# opzionale per scansione QR via fotocamera
try:
    import cv2  # pip install opencv-python
except Exception:
    cv2 = None

DB_PATH = os.environ.get("APP_DB_PATH", "store.db")

# -----------------------------------------------------
# 🔧 UTIL: STILE & COMPONENTI UI
# -----------------------------------------------------

def apply_global_css():
    st.markdown(
        """
        <style>
            /* Typography: Inter + SF like */
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

            html, body, [class*="css"]  {
                font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Helvetica Neue', Arial, "Noto Sans", sans-serif;
            }

            header[data-testid="stHeader"] { backdrop-filter: blur(6px); background: rgba(11,18,32,0.4); }
            #MainMenu { visibility: hidden; }
            footer { visibility: hidden; }
            .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1200px; }
            .ui-card { background: linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.02) 100%); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 16px 18px; box-shadow: 0 6px 20px rgba(0,0,0,0.25); }
            .kpi-title { font-size: 0.85rem; color: #9CA3AF; margin-bottom: 6px; letter-spacing: .02em; }
            .kpi-value { font-size: 1.8rem; font-weight: 700; }
            .kpi-sub { font-size: .85rem; color: #9CA3AF; }
            div.stButton > button, .stDownloadButton button { border-radius: 12px; padding: 0.6rem 1rem; font-weight: 600; border: 1px solid rgba(255,255,255,0.12); }
            div.stButton > button:hover { transform: translateY(-1px); transition: transform .12s ease; }
            .stTextInput input, .stNumberInput input, .stSelectbox [data-baseweb="select"] { border-radius: 12px !important; }
            .stDataFrame, .stDataEditor { border-radius: 14px; overflow: hidden; }
            section[data-testid="stSidebar"]>div { padding-top: .5rem; }
            .brand-box { display:flex; align-items:center; gap:.6rem; padding:.4rem .6rem; border-radius:12px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.07); }
            .brand-title { font-weight:700; letter-spacing:.02em; }
        </style>
        """,
        unsafe_allow_html=True,
    )

def excel_download_button(df: pd.DataFrame, filename: str, label: str = "⬇️ Esporta Excel"):
    """Crea un pulsante per scaricare un DataFrame in formato .xlsx."""
    if df is None or df.empty:
        st.caption("Nessun dato da esportare.")
        return
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Dati")
    st.download_button(
        label=label,
        data=buf.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def badge_col(label: str, *, help: str | None = None, options=None):
    """Compat: prova a usare BadgeColumn, altrimenti ripiega su TextColumn."""
    try:
        BadgeColumn = st.column_config.BadgeColumn  # disponibile su Streamlit recenti
        return BadgeColumn(label, help=help, options=options)
    except Exception:
        return st.column_config.TextColumn(label, help=help)


def badge_options_from(df: pd.DataFrame, col: str):
    """Restituisce una lista di BadgeColumn.Option se disponibile, altrimenti None.
    Evita AttributeError su versioni vecchie di Streamlit.
    """
    try:
        Opt = st.column_config.BadgeColumn.Option
    except Exception:
        return None
    if df is None or df.empty or col not in df.columns:
        return None
    try:
        vals = sorted(pd.Series(df[col]).dropna().astype(str).unique())
        return [Opt(v) for v in vals]
    except Exception:
        return None



def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if DATABASE_URL:
            _engine = create_engine(DATABASE_URL, pool_pre_ping=True)  # Postgres (Supabase)
        else:
            # fallback locale SQLite solo se DATABASE_URL non è impostata
            _engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    return _engine
    

from sqlalchemy import text

def _to_text_with_binds(sql: str, params):
    """
    Converte i ? posizionali in :p1, :p2 ... e restituisce (TextClause, dict_bind).
    Così puoi continuare a scrivere SQL con i ? anche su Postgres.
    """
    if isinstance(params, (list, tuple)):
        bind = {f"p{i}": v for i, v in enumerate(params, 1)}
        for i in range(1, len(params) + 1):
            sql = sql.replace("?", f":p{i}", 1)
    elif isinstance(params, dict):
        bind = params
    else:
        bind = {}
    return text(sql), bind


def kpi_card(title: str, value: str, sub: Optional[str] = None, icon: Optional[str] = None):
    icon = icon or ""
    with st.container():
        st.markdown(
            f"""
            <div class=\"ui-card\">
              <div class=\"kpi-title\">{icon} {title}</div>
              <div class=\"kpi-value\">{value}</div>
              {f'<div class=\"kpi-sub\">{sub}</div>' if sub else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )


def page_header(title: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div style=\"display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:10px;gap:12px;\">
          <div>
            <h1 style=\"margin:0;font-weight:800;letter-spacing:.01em\">{title}</h1>
            <div style=\"opacity:.75\">{subtitle}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def init_db():
     # Se usiamo Postgres (DATABASE_URL presente), lo schema è già creato su Supabase: non fare nulla qui.
    if DATABASE_URL:
        return
    # ... lascia invariato il resto dello schema SQLite per l'uso locale ...


# --------------- UTILS ----------------

def decode_qr_from_bytes(img_bytes: bytes) -> Optional[str]:
    if cv2 is None or not img_bytes:
        return None
    import numpy as np
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    detector = cv2.QRCodeDetector()
    try:
        data, _, _ = detector.detectAndDecode(img)
    except Exception:
        data = ""
    return data.strip() or None


def fmt_thousands(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)


def fmt_money(x: float) -> str:
    try:
        s = f"{float(x):,.2f}"
        s = s.replace(",", "_")
        s = s.replace(".", ",")
        s = s.replace("_", ".")
        return "€ " + s
    except Exception:
        return f"€ {x}"


def format_df_for_display(df: pd.DataFrame, int_cols=None, money_cols=None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    int_cols = int_cols or []
    money_cols = money_cols or []
    dff = df.copy()
    for c in int_cols:
        if c in dff.columns:
            dff[c] = dff[c].apply(fmt_thousands)
    for c in money_cols:
        if c in dff.columns:
            dff[c] = dff[c].apply(fmt_money)
    return dff


def query_df(sql: str, params: tuple | dict = ()):
    t, b = _to_text_with_binds(sql, params)
    with get_engine().connect() as conn:
        return pd.read_sql_query(t, conn, params=b)


def execute(sql: str, params: tuple | dict = ()):
    t, b = _to_text_with_binds(sql, params)
    with get_engine().begin() as conn:
        conn.execute(t, b)


def recalc_qty_from_movements(sku: str):
    df = query_df("SELECT qty FROM movements WHERE sku= ?", (sku,))
    total = int(df['qty'].sum()) if not df.empty else 0
    execute("UPDATE items SET qty=? WHERE sku=?", (total, sku))


# --------------- UI --------------------

def sidebar_brand():
    with st.sidebar:
        st.markdown(
            """
            <div class="brand-box">
              <div style="font-size:1.3rem">🧥</div>
              <div>
                <div class="brand-title">Boutique Manager</div>
                <div style="font-size:.8rem;opacity:.75">Gestionale Magazzino</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Rapido. Elegante. Intuitivo.")


def main():
    st.set_page_config(page_title="Gestionale Abbigliamento", page_icon="🧥", layout="wide")
    apply_global_css()
    sidebar_brand()
    init_db()

    # Sidebar menu con icone
    menu = st.sidebar.radio(
        "Navigazione",
        ["Dashboard", "Fornitori", "Articoli", "Movimenti", "Dettagli", "Analisi"],
        format_func=lambda x: {
            "Dashboard": "🏠 Dashboard",
            "Fornitori": "🏷️ Fornitori",
            "Articoli": "👕 Articoli",
            "Movimenti": "🔄 Movimenti",
            "Dettagli": "🔎 Dettagli articolo",
            "Analisi": "📊 Analisi",
        }[x],
    )

    if menu == "Dashboard":
        page_dashboard()
    elif menu == "Fornitori":
        page_suppliers()
    elif menu == "Articoli":
        page_items()
    elif menu == "Movimenti":
        page_movements()
    elif menu == "Dettagli":
        page_item_details()
    else:
        page_analysis()


# --------------- PAGES -----------------

def get_item_stats(sku: str):
    """Restituisce info base e KPI di un articolo."""
    info = query_df(
        "SELECT i.sku, i.type, i.season, i.size, i.cost, i.price, i.qty, s.name AS supplier "
        "FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id WHERE i.sku=?",
        (sku,),
    )
    if info.empty:
        return None, None
    row = info.iloc[0]
    sold_df = query_df(
        "SELECT SUM(ABS(qty)) AS sold FROM movements WHERE sku=? AND (UPPER(mtype)='SCARICO' OR causale=2)",
        (sku,),
    )
    sold = int(sold_df.iloc[0]['sold'] or 0)
    kpi = {
        "qty": int(row["qty"] or 0),
        "sold": sold,
        "avg_cost": float(row["cost"] or 0.0),
        "price": float(row["price"] or 0.0),
    }
    return row, kpi


def render_item_kpis(row, kpi):
    c1, c2, c3 = st.columns(3)
    with c1: kpi_card("Giacenza attuale", f"{kpi['qty']} pz", sub=f"SKU {row['sku']}", icon="📦")
    with c2: kpi_card("Totale venduto", f"{kpi['sold']} pz", sub="Somma scarichi", icon="🧾")
    with c3: kpi_card("Costo medio", fmt_money(kpi['avg_cost']), sub=f"Prezzo: {fmt_money(kpi['price'])}", icon="💶")

    st.caption(f"Tipo: **{row['type']}**, Stagione: **{row['season']}**, Taglia: **{row['size']}**, Fornitore: **{row['supplier'] or '-'}**")


def page_item_details():
    page_header("Dettagli articolo", "Scansiona o seleziona uno SKU per vedere i KPI")

    t1, t2 = st.tabs(["📷 Scanner", "🔍 Seleziona"])

    with t1:
        colA, colB = st.columns([2,1])
        scanned = colA.text_input("SKU letto (scanner USB)")
        if scanned:
            row, kpi = get_item_stats(scanned)
            if row is None:
                st.error("SKU non trovato.")
            else:
                render_item_kpis(row, kpi)
                recent = query_df("SELECT created_at AS data, mtype AS tipo, qty AS qta, note FROM movements WHERE sku=? ORDER BY id DESC LIMIT 10", (scanned,))
                st.subheader("Ultimi movimenti")
                st.dataframe(recent, use_container_width=True, hide_index=True)

        st.markdown("— oppure —")
        st.caption("QR con fotocamera (richiede OpenCV)")
        if cv2 is None:
            st.warning("OpenCV non disponibile: pip install opencv-python")
        cam_img = st.camera_input("Inquadra il QR dell'articolo")
        if cam_img is not None and cv2 is not None:
            decoded_sku = decode_qr_from_bytes(cam_img.getvalue())
            if not decoded_sku:
                st.error("QR non riconosciuto.")
            else:
                row, kpi = get_item_stats(decoded_sku)
                if row is None:
                    st.error("SKU non trovato.")
                else:
                    st.success(f"QR: {decoded_sku}")
                    render_item_kpis(row, kpi)
                    recent = query_df("SELECT created_at AS data, mtype AS tipo, qty AS qta, note FROM movements WHERE sku=? ORDER BY id DESC LIMIT 10", (decoded_sku,))
                    st.subheader("Ultimi movimenti")
                    st.dataframe(recent, use_container_width=True, hide_index=True)

    with t2:
        all_items = query_df("SELECT sku FROM items ORDER BY created_at DESC")
        if all_items.empty:
            st.info("Nessun articolo in archivio.")
        else:
            sku = st.selectbox("Scegli SKU", all_items['sku'])
            row, kpi = get_item_stats(sku)
            render_item_kpis(row, kpi)
            recent = query_df("SELECT created_at AS data, mtype AS tipo, qty AS qta, note FROM movements WHERE sku=? ORDER BY id DESC LIMIT 10", (sku,))
            st.subheader("Ultimi movimenti")
            st.dataframe(recent, use_container_width=True, hide_index=True)





def page_dashboard():
    page_header("Dashboard", "Panoramica rapida del tuo magazzino")
    items = query_df("SELECT COUNT(*) AS n, COALESCE(SUM(qty),0) AS tot FROM items")
    n = int(items.at[0, 'n']) if not items.empty else 0
    tot = int(items.at[0, 'tot']) if not items.empty else 0

    c1, c2, c3 = st.columns([1,1,1])
    with c1: kpi_card("Articoli a catalogo", fmt_thousands(n), "Codici univoci", "📚")
    with c2: kpi_card("Giacenza totale", fmt_thousands(tot) + " pz", "Aggiornata dai movimenti", "📦")
    with c3:
        # Valore indicativo magazzino
        df = query_df("SELECT SUM(qty*cost) AS val FROM items")
        val = float(df.iloc[0]['val'] or 0.0)
        kpi_card("Valore magazzino", fmt_money(val), "A costo", "💶")

    st.divider()
    st.info("Suggerimento: usa la sezione **Analisi** per report più avanzati.")


def page_suppliers():
    page_header("Fornitori", "Anagrafiche e tempi di consegna")

    with st.expander("➕ Nuovo/Modifica fornitore", expanded=True):
        with st.form("supplier_form", clear_on_submit=True):
            c1, c2 = st.columns([1,2])
            code = c1.text_input("Codice (es. ZAR)")
            name = c2.text_input("Nome fornitore *")
            c3, c4 = st.columns(2)
            city = c3.text_input("Località")
            phone = c4.text_input("Telefono")
            c5, c6 = st.columns(2)
            lead = c5.number_input("Tempi consegna (giorni)", min_value=0, value=0)
            vat = c6.text_input("P. IVA")
            colb1, colb2 = st.columns([1,4])
            submitted = colb1.form_submit_button("💾 Salva")
            if submitted and name:
                execute(
                            """
                            INSERT INTO suppliers(code, name, city, phone, lead_time_days, vat_number)
                            VALUES (:code, :name, :city, :phone, :lead, :vat)
                            ON CONFLICT (code) DO UPDATE
                            SET name = EXCLUDED.name,
                                city = EXCLUDED.city,
                                phone = EXCLUDED.phone,
                                lead_time_days = EXCLUDED.lead_time_days,
                                vat_number = EXCLUDED.vat_number
                            """,
                            {"code": code or None, "name": name, "city": city or None, "phone": phone or None,
                            "lead": int(lead), "vat": vat or None}
                        )
                st.success("Fornitore salvato.")

    st.subheader("Elenco")
    df = query_df("SELECT id, code, name, city, phone, lead_time_days AS lead_days, vat_number AS piva FROM suppliers ORDER BY name")
    view = df.drop(columns=['id']) if not df.empty else df
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "code": st.column_config.TextColumn("Codice", help="Codice interno"),
            "name": st.column_config.TextColumn("Nome", width="medium"),
            "city": st.column_config.TextColumn("Località"),
            "phone": st.column_config.TextColumn("Telefono"),
            "lead_days": st.column_config.NumberColumn("Lead Time (gg)", format="%d"),
            "piva": st.column_config.TextColumn("P. IVA"),
        },
    )
    excel_download_button(view, "fornitori.xlsx")


    with st.expander("✏️ Modifica / 🗑️ Elimina"):
        if df.empty:
            st.info("Nessun fornitore da modificare.")
        else:
            colm1, colm2 = st.columns(2)
            sel = colm1.selectbox("Scegli fornitore", df['name'])
            row = df[df['name'] == sel].iloc[0]
            n_code = colm2.text_input("Codice", value=row['code'] or "")
            cmo1, cmo2 = st.columns(2)
            n_city = cmo1.text_input("Località", value=row['city'] or "")
            n_phone = cmo2.text_input("Telefono", value=row['phone'] or "")
            cmo3, cmo4 = st.columns(2)
            n_lead = cmo3.number_input("Tempi consegna (gg)", min_value=0, value=int(row['lead_days'] or 0))
            n_vat = cmo4.text_input("P. IVA", value=row['piva'] or "")
            cta1, cta2, cta3 = st.columns([1,1,4])
            if cta1.button("💾 Aggiorna"):
                execute(
                    "UPDATE suppliers SET code=?, name=?, city=?, phone=?, lead_time_days=?, vat_number=? WHERE id=?",
                    (n_code or None, sel, n_city or None, n_phone or None, int(n_lead), n_vat or None, int(df[df['name']==sel]['id'].iloc[0]))
                )
                st.success("Fornitore aggiornato.")
                st.rerun()
            to_del = cta2.selectbox("Elimina…", df.apply(lambda r: f"{r['id']} — {r['name']} ({r['code'] or ''})", axis=1))
            if cta2.button("🗑️ Elimina"):
                fid = int(to_del.split(' — ')[0])
                used = query_df("SELECT COUNT(*) AS n FROM items WHERE supplier_id=?", (fid,)).iloc[0]['n']
                if used:
                    st.error("Impossibile eliminare: esistono articoli collegati.")
                else:
                    execute("DELETE FROM suppliers WHERE id=?", (fid,))
                    st.success("Fornitore eliminato.")
                    st.rerun()


def page_items():
    page_header("Articoli", "Catalogo prodotti, dizionari e prezzi")
    suppliers = query_df("SELECT id, name FROM suppliers ORDER BY name")
    if suppliers.empty:
        st.info("Inserisci prima almeno un fornitore nella sezione Fornitori.")
        return

    # Dizionari
    dict_types = query_df("SELECT type FROM dict_types ORDER BY type")["type"].tolist()
    dict_seasons = query_df("SELECT season FROM dict_seasons ORDER BY season")["season"].tolist()
    dict_sizes = query_df("SELECT size FROM dict_sizes ORDER BY size")["size"].tolist()

    with st.expander("🗂️ Gestione dizionari (Tipo / Stagione / Taglia)", expanded=False):
        colA, colB, colC = st.columns(3)
        new_t = colA.text_input("Nuovo tipo", key="new_type")
        if colA.button("Aggiungi tipo", key="btn_add_type") and new_t:
            execute("INSERT INTO dict_types(type) VALUES (?) ON CONFLICT DO NOTHING", (new_t.upper(),))
            st.rerun()
        new_s = colB.text_input("Nuova stagione", key="new_season")
        if colB.button("Aggiungi stagione", key="btn_add_season") and new_s:
            execute("INSERT INTO dict_seasons(season) VALUES (?) ON CONFLICT DO NOTHING", (new_s.upper(),))
            st.rerun()
        new_z = colC.text_input("Nuova taglia", key="new_size")
        if colC.button("Aggiungi taglia", key="btn_add_size") and new_z:
            execute("INSERT INTO dict_sizes(size) VALUES (?) ON CONFLICT DO NOTHING", (new_z.upper(),))
            st.rerun()

        st.markdown("---")
        dcol1, dcol2, dcol3 = st.columns(3)
        del_t = dcol1.selectbox("Elimina tipo (se non usato)", ["—"] + dict_types, key="del_type")
        if dcol1.button("Elimina tipo", key="btn_del_type") and del_t != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE type=?", (del_t,)).iloc[0]['n']
            if used: st.error("Non puoi eliminare: è usato da alcuni articoli.")
            else:
                execute("DELETE FROM dict_types WHERE type=?", (del_t,))
                st.success("Tipo eliminato.")
                st.rerun()
        del_s = dcol2.selectbox("Elimina stagione (se non usata)", ["—"] + dict_seasons, key="del_season")
        if dcol2.button("Elimina stagione", key="btn_del_season") and del_s != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE season=?", (del_s,)).iloc[0]['n']
            if used: st.error("Non puoi eliminare: è usata da alcuni articoli.")
            else:
                execute("DELETE FROM dict_seasons WHERE season=?", (del_s,))
                st.success("Stagione eliminata.")
                st.rerun()
        del_z = dcol3.selectbox("Elimina taglia (se non usata)", ["—"] + dict_sizes, key="del_size")
        if dcol3.button("Elimina taglia", key="btn_del_size") and del_z != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE size=?", (del_z,)).iloc[0]['n']
            if used: st.error("Non puoi eliminare: è usata da alcuni articoli.")
            else:
                execute("DELETE FROM dict_sizes WHERE size=?", (del_z,))
                st.success("Taglia eliminata.")
                st.rerun()

    with st.form("item_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2,1,1])
        supplier_name = c1.selectbox("Fornitore", suppliers['name'])
        type_ = c2.selectbox("Tipo abito", dict_types)
        season = c3.selectbox("Stagione", dict_seasons)
        c4, c5, c6, c7 = st.columns([1,1,1,1])
        size = c4.selectbox("Taglia", dict_sizes)
        cost = c5.number_input("Costo (€)", min_value=0.0, step=0.01)
        price = c6.number_input("Prezzo (€)", min_value=0.0, step=0.01)
        qty0 = c7.number_input("Quantità iniziale", min_value=0, step=1)
        submitted = st.form_submit_button("➕ Crea articolo")
        if submitted:
            sid = int(suppliers[suppliers['name'] == supplier_name]['id'].iloc[0])
            sku = f"{supplier_name[:3].upper()}-{type_[:3].upper()}-{season}-{size}"
            execute(
                    "INSERT INTO items(supplier_id, sku, type, season, size, cost, price, qty) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO NOTHING",
                    (sid, sku, type_.upper(), season.upper(), size.upper(), float(cost), float(price), int(qty0)),
                )

            if qty0:
                execute(
                    "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                    (sku, 'CARICO', 1, int(qty0), 'Giacenza iniziale', datetime.now().isoformat(timespec='seconds')),
                )
            st.success(f"Articolo {sku} creato.")

    st.subheader("Elenco articoli")
    df = query_df(
        "SELECT i.sku, i.type, i.season, i.size, i.cost, i.price, i.qty, s.name AS supplier FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id ORDER BY i.created_at DESC"
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "sku": st.column_config.TextColumn("SKU", help="Codice articolo"),
            "type": badge_col("Tipo", help="Categoria", options=badge_options_from(df, 'type')),
            "season": badge_col("Stagione"),
            "size": badge_col("Taglia"),
            "cost": st.column_config.NumberColumn("Costo", format="€ %.2f"),
            "price": st.column_config.NumberColumn("Prezzo", format="€ %.2f"),
            "qty": st.column_config.NumberColumn("Giacenza", format="%d"),
            "supplier": st.column_config.TextColumn("Fornitore"),
        },
    )
    excel_download_button(df, "articoli.xlsx")


def page_movements():
    page_header("Movimenti", "Carico, scarico e rettifiche")
    items = query_df("SELECT sku, qty FROM items ORDER BY sku")
    if items.empty:
        st.info("Nessun articolo presente.")
        return

    t1, t2 = st.tabs(["📷 Scanner", "✍️ Manuale"])

    with t1:
        with st.expander("Scanner barcode/QR (USB)", expanded=True):
            st.caption("Gli scanner USB digitano lo SKU e inviano Invio. Inquadra/leggi il barcode e verifica che lo SKU compaia nel campo.")
            scanned = st.text_input("SKU letto", key="scan_input")
            if scanned:
                exists = query_df("SELECT sku, qty FROM items WHERE sku=?", (scanned,))
                if exists.empty:
                    st.error("SKU non trovato.")
                else:
                    st.success(f"Trovato {scanned} — Giacenza attuale: {int(exists.iloc[0]['qty'])}")
                    sc1, sc2 = st.columns([1,1])
                    mtype_s = sc1.selectbox("Tipo movimento", ['CARICO','SCARICO','RETTIFICA +','RETTIFICA -'], key="scan_mtype_usb")
                    qty_s = int(sc2.number_input("Quantità", value=1, min_value=1, step=1, key="scan_qty_usb"))
                    note_s = st.text_input("Nota", key="scan_note_usb")
                    if st.button("Registra (da scanner USB)"):
                        signed = (qty_s if mtype_s=='CARICO' else -qty_s if mtype_s=='SCARICO' else qty_s if mtype_s=='RETTIFICA +' else -qty_s)
                        execute(
                            "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                            (scanned, 'RETTIFICA' if mtype_s.startswith('RETTIFICA') else mtype_s, 1 if mtype_s=='CARICO' else 2 if mtype_s=='SCARICO' else 3 if mtype_s=='RETTIFICA +' else 4, signed, note_s or None, datetime.now().isoformat(timespec='seconds')),
                        )
                        execute("UPDATE items SET qty = qty + ? WHERE sku = ?", (signed, scanned))
                        st.success("Registrato.")

        with st.expander("📹 Scanner live (QR + EAN/Code128)", expanded=True):
            st.caption("Lettura continua via webcam. Seleziona 'Auto' per registrare subito.")

            # antirafﬁca / stato
            if "detected_sku" not in st.session_state:
                st.session_state["detected_sku"] = None
            if "last_fire_ts" not in st.session_state:
                st.session_state["last_fire_ts"] = 0.0

            auto_register = st.checkbox("Auto-registra SCARICO 1 pz al rilevamento", value=False)

            qr = cv2.QRCodeDetector() if cv2 is not None else None

            def video_frame_callback(frame: av.VideoFrame) -> av.VideoFrame:
                img = frame.to_ndarray(format="bgr24")

                # --- QR (OpenCV) ---
                if qr is not None:
                    try:
                        data, _, _ = qr.detectAndDecode(img)
                        if data:
                            st.session_state["detected_sku"] = data.strip()
                    except Exception:
                        pass

                # --- EAN/Code128 (pyzbar) ---
                if HAS_ZBAR:
                    try:
                        for obj in zbar_decode(img):
                            st.session_state["detected_sku"] = obj.data.decode("utf-8").strip()
                            break  # prendi il primo valido
                    except Exception:
                        pass

                return av.VideoFrame.from_ndarray(img, format="bgr24")

            webrtc_ctx = webrtc_streamer(
                key="qr-ean-live",
                mode=WebRtcMode.SENDRECV,
                video_frame_callback=video_frame_callback,
                media_stream_constraints={"video": True, "audio": False},
            )

            det = st.session_state.get("detected_sku")
            now = time.time()
            if det:
                st.success(f"Rilevato: **{det}**")

                # azione automatica (1 evento ogni 2s)
                if auto_register and now - st.session_state["last_fire_ts"] > 2.0:
                    exists = query_df("SELECT sku FROM items WHERE sku=?", (det,))
                    if exists.empty:
                        st.error("SKU non trovato nel catalogo.")
                    else:
                        execute(
                            "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                            (det, 'SCARICO', 2, -1, 'Auto da scanner live', datetime.now().isoformat(timespec='seconds')),
                        )
                        execute("UPDATE items SET qty = qty - 1 WHERE sku = ?", (det,))
                        st.session_state["last_fire_ts"] = now
                        st.toast("Scarico 1 pz registrato ✅")

                # pulsanti rapidi
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("Carico +1"): 
                    execute("INSERT INTO movements(sku, mtype, causale, qty, created_at) VALUES (?,?,?,?,?)",
                            (det, 'CARICO', 1, 1, datetime.now().isoformat(timespec='seconds')))
                    execute("UPDATE items SET qty = qty + 1 WHERE sku = ?", (det,))
                    st.toast("Carico +1 registrato")
                if c2.button("Scarico −1"):
                    execute("INSERT INTO movements(sku, mtype, causale, qty, created_at) VALUES (?,?,?,?,?)",
                            (det, 'SCARICO', 2, -1, datetime.now().isoformat(timespec='seconds')))
                    execute("UPDATE items SET qty = qty - 1 WHERE sku = ?", (det,))
                    st.toast("Scarico −1 registrato")
                if c3.button("Rettifica +1"):
                    execute("INSERT INTO movements(sku, mtype, causale, qty, created_at) VALUES (?,?,?,?,?)",
                            (det, 'RETTIFICA', 3, 1, datetime.now().isoformat(timespec='seconds')))
                    execute("UPDATE items SET qty = qty + 1 WHERE sku = ?", (det,))
                    st.toast("Rettifica +1 registrata")
                if c4.button("Rettifica −1"):
                    execute("INSERT INTO movements(sku, mtype, causale, qty, created_at) VALUES (?,?,?,?,?)",
                            (det, 'RETTIFICA', 4, -1, datetime.now().isoformat(timespec='seconds')))
                    execute("UPDATE items SET qty = qty - 1 WHERE sku = ?", (det,))
                    st.toast("Rettifica −1 registrata")



    with t2:
        with st.form("mov_form", clear_on_submit=True):
            c1, c2, c3 = st.columns([2,1,1])
            sku = c1.selectbox("Articolo (SKU)", items['sku'])
            mtype = c2.selectbox("Tipo", ['CARICO','SCARICO','RETTIFICA +','RETTIFICA -'])
            qty = int(c3.number_input("Quantità", value=1, min_value=1, step=1))
            note = st.text_input("Nota (opzionale)")
            d = st.date_input("Data movimento", value=date.today())
            submitted = st.form_submit_button("📥 Registra movimento")
            if submitted:
                signed = (qty if mtype=='CARICO' else -qty if mtype=='SCARICO' else qty if mtype=='RETTIFICA +' else -qty)
                execute(
                    "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                    (sku, 'RETTIFICA' if mtype.startswith('RETTIFICA') else mtype, 1 if mtype=='CARICO' else 2 if mtype=='SCARICO' else 3 if mtype=='RETTIFICA +' else 4, signed, note or None, datetime.combine(d, datetime.min.time()).isoformat()),
                )
                execute("UPDATE items SET qty = qty + ? WHERE sku = ?", (signed, sku))
                st.success("Movimento registrato.")

    st.subheader("Storico movimenti")
    f1, f2, f3 = st.columns(3)
    d_from = f1.date_input("Dal", value=date.today().replace(day=1), key="mov_from")
    d_to = f2.date_input("Al", value=date.today(), key="mov_to")
    all_skus = items['sku'].tolist()
    sku_filter = f3.selectbox("SKU (tutti)", ["(tutti)"] + all_skus, key="mov_sku_filter")

    date_expr = "created_at::date" if IS_PG else "date(created_at)"
    sql = f"SELECT id, created_at, sku, mtype, causale, qty, note FROM movements " \
      f"WHERE {date_expr} BETWEEN ? AND ?"
    params = [d_from.isoformat(), d_to.isoformat()]
    if sku_filter != "(tutti)":
        sql += " AND sku=?"
        params.append(sku_filter)
    sql += " ORDER BY id DESC LIMIT 200"

    mov = query_df(sql, tuple(params))

    st.dataframe(
        mov,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d"),
            "created_at": st.column_config.DatetimeColumn("Data"),
            "sku": st.column_config.TextColumn("SKU"),
            "mtype": badge_col("Tipo"),
            "causale": st.column_config.NumberColumn("Cod. Causale", format="%d", help="1=CARICO, 2=SCARICO, 3=RETTIFICA+, 4=RETTIFICA-"),
            "qty": st.column_config.NumberColumn("Quantità", format="%d"),
            "note": st.column_config.TextColumn("Nota"),
        },
    )
    excel_download_button(mov, f"movimenti_{d_from}_{d_to}.xlsx")


    st.markdown("**Elimina movimento**")
    if not mov.empty:
        choice = st.selectbox(
            "Seleziona movimento da eliminare",
            mov.apply(lambda r: f"{r['id']} — {r['created_at']} — {r['sku']} — {r['mtype']} {r['qty']}", axis=1),
            key="mov_del_select",
        )
        if st.button("🗑️ Elimina movimento", key="mov_del_btn"):
            mid = int(choice.split(' — ')[0])
            row = query_df("SELECT sku FROM movements WHERE id=?", (mid,))
            if row.empty:
                st.error("Movimento non trovato.")
            else:
                sku_to_fix = row.iloc[0]['sku']
                execute("DELETE FROM movements WHERE id=?", (mid,))
                recalc_qty_from_movements(sku_to_fix)
                st.success("Movimento eliminato e giacenza ricalcolata.")
                st.rerun()


# Chiudiamo la funzione page_analysis correttamente

def page_analysis():
    page_header("Analisi", "Pivot, filtri e giacenze storiche")

    mode = st.radio(
        "Modalità di analisi",
        ["Periodo (movimenti e pivot)", "Storica al… (giacenza e valore a una data)"],
        horizontal=True,
    )

    col1, col2, col3 = st.columns(3)
    price_max = col1.number_input("Prezzo/Costo massimo (€)", min_value=0.0, value=0.0, step=0.10)
    min_stock = int(col2.number_input("Giacenza minima", min_value=0, value=0))
    max_stock = int(col3.number_input("Giacenza massima (0 = nessun limite)", min_value=0, value=0))

    df_items = query_df(
        "SELECT i.sku AS articolo, i.type AS tipo, i.season AS stagione, i.size AS taglia, "
        "i.cost AS costo, i.price AS prezzo, i.qty AS giacenza, s.name AS fornitore "
        "FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id"
    )
    if df_items.empty:
        st.warning("Nessun articolo presente nel database.")
        return

    # --- 🔹 Filtri aggiuntivi per stagione e taglia ---
    colf1, colf2 = st.columns(2)
    stagioni = ["(tutte)"] + sorted(df_items["stagione"].dropna().unique().tolist())
    taglie = ["(tutte)"] + sorted(df_items["taglia"].dropna().unique().tolist())

    filtro_stagione = colf1.selectbox("Filtra per stagione", stagioni, index=0)
    filtro_taglia = colf2.selectbox("Filtra per taglia", taglie, index=0)

    # Applica i filtri prima di qualsiasi analisi
    if filtro_stagione != "(tutte)":
        df_items = df_items[df_items["stagione"] == filtro_stagione]
    if filtro_taglia != "(tutte)":
        df_items = df_items[df_items["taglia"] == filtro_taglia]

    # ------------------------------------------------------------
    # MODALITÀ 1: pivot sul periodo
    # ------------------------------------------------------------
    if mode == "Periodo (movimenti e pivot)":
        c1, c2, c3 = st.columns(3)
        d_from = c1.date_input("Dal", value=date.today().replace(day=1))
        d_to = c2.date_input("Al", value=date.today())
        order_opt = c3.selectbox(
            "Ordina per",
            ["Articolo", "Più movimentato", "Più venduto", "Valore magazzino", "Costo medio"],
            index=0,
        )
        date_expr = "created_at::date" if IS_PG else "date(created_at)"
        mov = query_df(
            f"SELECT sku AS articolo, mtype AS tipo_movimento, qty AS quantita, {date_expr} AS data "
            f"FROM movements WHERE {date_expr} BETWEEN ? AND ?",
            (d_from.isoformat(), d_to.isoformat()),
        )

        df_items["Valore Magazzino (€)"] = (df_items["giacenza"] * df_items["costo"]).round(2)

        vendite = (
            mov[mov["tipo_movimento"].str.upper() == "SCARICO"].groupby("articolo")["quantita"].sum().abs().reset_index().rename(columns={"quantita": "Vendite"})
            if not mov.empty else pd.DataFrame(columns=["articolo", "Vendite"])
        )

        mov_count = (
            mov.groupby("articolo")["quantita"].count().reset_index().rename(columns={"quantita": "Movimentazioni"})
            if not mov.empty else pd.DataFrame(columns=["articolo", "Movimentazioni"])
        )

        pivot_df = (
            df_items.groupby(["articolo", "tipo", "stagione", "taglia", "fornitore"], as_index=False)
            .agg({"giacenza": "sum", "costo": "mean", "Valore Magazzino (€)": "sum"})
            .rename(columns={"giacenza": "Giacenza", "costo": "Costo Medio"})
        )
        pivot_df = pivot_df.merge(vendite, on="articolo", how="left").merge(mov_count, on="articolo", how="left")
        pivot_df[["Vendite", "Movimentazioni"]] = pivot_df[["Vendite", "Movimentazioni"]].fillna(0)

        if price_max > 0:
            pivot_df = pivot_df[pivot_df["Costo Medio"] <= price_max]
        if min_stock > 0:
            pivot_df = pivot_df[pivot_df["Giacenza"] >= min_stock]
        if max_stock > 0:
            pivot_df = pivot_df[pivot_df["Giacenza"] <= max_stock]

        if order_opt == "Più venduto":
            pivot_df = pivot_df.sort_values(by="Vendite", ascending=False)
        elif order_opt == "Più movimentato":
            pivot_df = pivot_df.sort_values(by="Movimentazioni", ascending=False)
        elif order_opt == "Valore magazzino":
            pivot_df = pivot_df.sort_values(by="Valore Magazzino (€)", ascending=False)
        elif order_opt == "Costo medio":
            pivot_df = pivot_df.sort_values(by="Costo Medio", ascending=False)
        else:
            pivot_df = pivot_df.sort_values(by="articolo")

        totale_valore = pivot_df["Valore Magazzino (€)"].sum()

        st.subheader("📊 Vista di periodo")
        st.dataframe(
            pivot_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "articolo": st.column_config.TextColumn("Articolo (SKU)"),
                "tipo": badge_col("Tipo"),
                "stagione": badge_col("Stagione"),
                "taglia": badge_col("Taglia"),
                "fornitore": st.column_config.TextColumn("Fornitore"),
                "Giacenza": st.column_config.NumberColumn("Giacenza", format="%d"),
                "Costo Medio": st.column_config.NumberColumn("Costo Medio", format="€ %.2f"),
                "Valore Magazzino (€)": st.column_config.NumberColumn("Valore Magazzino (€)", format="€ %.2f"),
                "Vendite": st.column_config.NumberColumn("Vendite", format="%d"),
                "Movimentazioni": st.column_config.NumberColumn("Movimentazioni", format="%d"),
            },
        )
        excel_download_button(pivot_df, f"analisi_periodo_{d_from}_{d_to}.xlsx")
        st.markdown("---")
        kpi_card("Valore totale magazzino (filtrato)", fmt_money(totale_valore), icon="💰")

    # ------------------------------------------------------------
    # MODALITÀ 2: giacenza/valore alla data (AS-OF)
    # ------------------------------------------------------------
    else:
        c1, _ = st.columns([1,2])
        ref_date = c1.date_input("Data di riferimento (giacenza storica)", value=date.today())
        st.caption("La giacenza è la somma dei movimenti fino alle 23:59:59 della data selezionata. Valore a costo attuale.")

        ref_dt_end = f"{ref_date.isoformat()} 23:59:59"
        time_cmp = "created_at <= :p1" if IS_PG else "datetime(created_at) <= :p1"
        mov_to_ref = query_df(
            f"SELECT sku AS articolo, SUM(qty) AS giacenza_ref FROM movements WHERE {time_cmp} GROUP BY sku",
            {"p1": f"{ref_date.isoformat()} 23:59:59"},
        )

        asof_df = df_items.merge(mov_to_ref, on="articolo", how="left")
        asof_df["giacenza_ref"] = asof_df["giacenza_ref"].fillna(0).astype(int)

        if price_max > 0:
            asof_df = asof_df[asof_df["costo"] <= price_max]
        if min_stock > 0:
            asof_df = asof_df[asof_df["giacenza_ref"] >= min_stock]
        if max_stock > 0:
            asof_df = asof_df[asof_df["giacenza_ref"] <= max_stock]

        asof_df["Valore Magazzino alla data (€)"] = (asof_df["giacenza_ref"] * asof_df["costo"]).round(2)
        asof_pivot = (
            asof_df.groupby(["articolo", "tipo", "stagione", "taglia", "fornitore"], as_index=False)
            .agg({"giacenza_ref": "sum", "costo": "mean", "Valore Magazzino alla data (€)": "sum"})
            .rename(columns={"giacenza_ref": "Giacenza alla data", "costo": "Costo Medio"})
            .sort_values(by="articolo")
        )

        totale_asof = asof_pivot.loc[asof_pivot["Giacenza alla data"] > 0, "Valore Magazzino alla data (€)"].sum()

        st.subheader("📅 Vista storica al giorno selezionato")
        st.dataframe(
            asof_pivot,
            use_container_width=True,
            hide_index=True,
            column_config={
                "articolo": st.column_config.TextColumn("Articolo (SKU)"),
                "tipo": badge_col("Tipo"),
                "stagione": badge_col("Stagione"),
                "taglia": badge_col("Taglia"),
                "fornitore": st.column_config.TextColumn("Fornitore"),
                "Giacenza alla data": st.column_config.NumberColumn("Giacenza", format="%d"),
                "Costo Medio": st.column_config.NumberColumn("Costo Medio", format="€ %.2f"),
                "Valore Magazzino alla data (€)": st.column_config.NumberColumn("Valore (€)", format="€ %.2f"),
            },
        )
        excel_download_button(asof_pivot, f"analisi_asof_{ref_date}.xlsx")
        st.markdown("---")
        kpi_card("Valore totale magazzino alla data (giacenze > 0)", fmt_money(totale_asof), icon="💰")


# Assicurati che il main sia presente alla fine del file una sola volta
if __name__ == '__main__':
    main()

         