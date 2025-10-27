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

import pandas as pd
import streamlit as st

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



def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


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
    schema = """
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT NOT NULL,
        city TEXT,
        phone TEXT,
        lead_time_days INTEGER,
        vat_number TEXT
    );

    CREATE TABLE IF NOT EXISTS dict_types (type TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS dict_seasons (season TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS dict_sizes (size TEXT PRIMARY KEY);

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER,
        sku TEXT UNIQUE,
        type TEXT,
        season TEXT,
        size TEXT,
        cost REAL,
        price REAL,
        qty INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    );

    CREATE TABLE IF NOT EXISTS movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        mtype TEXT NOT NULL,
        causale INTEGER NOT NULL DEFAULT 0,
        qty INTEGER NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sku) REFERENCES items(sku) ON DELETE CASCADE
    );
    """
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.executescript(schema)
        # Migrazioni leggere
        def add_col_if_missing(table, col, ddl):
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            if col not in cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        add_col_if_missing('suppliers','city','city TEXT')
        add_col_if_missing('suppliers','phone','phone TEXT')
        add_col_if_missing('suppliers','lead_time_days','lead_time_days INTEGER')
        add_col_if_missing('suppliers','vat_number','vat_number TEXT')
        add_col_if_missing('items','qty','qty INTEGER DEFAULT 0')
        add_col_if_missing('items','created_at','created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP')
        add_col_if_missing('items','cost','cost REAL')
        add_col_if_missing('items','price','price REAL')
        add_col_if_missing('movements','causale','causale INTEGER NOT NULL DEFAULT 0')
        conn.commit()
        # Seed
        if cur.execute("SELECT COUNT(*) FROM dict_types").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_types(type) VALUES (?)", [(t,) for t in ["TSHIRT","JEANS","GIUBBOTTO","ABITO"]])
        if cur.execute("SELECT COUNT(*) FROM dict_seasons").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_seasons(season) VALUES (?)", [(s,) for s in ["SS25","FW25","AI25"]])
        if cur.execute("SELECT COUNT(*) FROM dict_sizes").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_sizes(size) VALUES (?)", [(x,) for x in ["XS","S","M","L","XL","40","42","44"]])
        conn.commit()


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


def query_df(sql: str, params: Tuple = ()):  # -> DataFrame
    with closing(get_conn()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql: str, params: Tuple = ()):  # -> lastrowid
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid


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
                    "INSERT OR REPLACE INTO suppliers(code, name, city, phone, lead_time_days, vat_number) VALUES (?,?,?,?,?,?)",
                    (code or None, name, city or None, phone or None, int(lead), vat or None),
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
            execute("INSERT OR IGNORE INTO dict_types(type) VALUES (?)", (new_t.upper(),))
            st.rerun()
        new_s = colB.text_input("Nuova stagione", key="new_season")
        if colB.button("Aggiungi stagione", key="btn_add_season") and new_s:
            execute("INSERT OR IGNORE INTO dict_seasons(season) VALUES (?)", (new_s.upper(),))
            st.rerun()
        new_z = colC.text_input("Nuova taglia", key="new_size")
        if colC.button("Aggiungi taglia", key="btn_add_size") and new_z:
            execute("INSERT OR IGNORE INTO dict_sizes(size) VALUES (?)", (new_z.upper(),))
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
                "INSERT OR IGNORE INTO items(supplier_id, sku, type, season, size, cost, price, qty) VALUES (?,?,?,?,?,?,?,?)",
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

        with st.expander("Scanner con fotocamera (QR)", expanded=False):
            st.caption("Usa la fotocamera del telefono per leggere un **QR code** con dentro lo SKU. (Serve OpenCV: `pip install opencv-python`)")
            if cv2 is None:
                st.warning("Modulo OpenCV non disponibile. Installa con: pip install opencv-python")
            cam_img = st.camera_input("Inquadra il QR dell'articolo")
            decoded_sku = None
            if cam_img is not None:
                decoded_sku = decode_qr_from_bytes(cam_img.getvalue())
                if not decoded_sku:
                    st.error("Nessun QR riconosciuto. Assicurati che l'etichetta sia un QR e ben a fuoco.")
            if decoded_sku:
                st.success(f"QR letto: {decoded_sku}")
                exists = query_df("SELECT sku, qty FROM items WHERE sku=?", (decoded_sku,))
                if exists.empty:
                    st.error("SKU non trovato nel catalogo.")
                else:
                    st.info(f"Giacenza attuale: {int(exists.iloc[0]['qty'])}")
                    qc1, qc2 = st.columns([1,1])
                    mtype_cam = qc1.selectbox("Tipo movimento", ['CARICO','SCARICO','RETTIFICA +','RETTIFICA -'], key="scan_mtype_cam")
                    qty_cam = int(qc2.number_input("Quantità", value=1, min_value=1, step=1, key="scan_qty_cam"))
                    note_cam = st.text_input("Nota", key="scan_note_cam")
                    if st.button("Registra (da fotocamera)"):
                        signed = (qty_cam if mtype_cam=='CARICO' else -qty_cam if mtype_cam=='SCARICO' else qty_cam if mtype_cam=='RETTIFICA +' else -qty_cam)
                        execute(
                            "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                            (decoded_sku, 'RETTIFICA' if mtype_cam.startswith('RETTIFICA') else mtype_cam, 1 if mtype_cam=='CARICO' else 2 if mtype_cam=='SCARICO' else 3 if mtype_cam=='RETTIFICA +' else 4, signed, note_cam or None, datetime.now().isoformat(timespec='seconds')),
                        )
                        execute("UPDATE items SET qty = qty + ? WHERE sku = ?", (signed, decoded_sku))
                        st.success("Registrato.")

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

    sql = "SELECT id, created_at, sku, mtype, causale, qty, note FROM movements WHERE date(created_at) BETWEEN ? AND ?"
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

    if mode == "Periodo (movimenti e pivot)":
        c1, c2, c3 = st.columns(3)
        d_from = c1.date_input("Dal", value=date.today().replace(day=1))
        d_to = c2.date_input("Al", value=date.today())
        order_opt = c3.selectbox(
            "Ordina per",
            ["Articolo", "Più movimentato", "Più venduto", "Valore magazzino", "Costo medio"],
            index=0,
        )

        mov = query_df(
            "SELECT sku AS articolo, mtype AS tipo_movimento, qty AS quantita, date(created_at) AS data "
            "FROM movements WHERE date(created_at) BETWEEN ? AND ?",
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
        st.markdown("---")
        kpi_card("Valore totale magazzino (filtrato)", fmt_money(totale_valore), icon="💰")

    else:
        c1, _ = st.columns([1,2])
        ref_date = c1.date_input("Data di riferimento (giacenza storica)", value=date.today())
        st.caption("La giacenza è la somma dei movimenti fino alle 23:59:59 della data selezionata. Valore a costo attuale.")

        ref_dt_end = f"{ref_date.isoformat()} 23:59:59"
        mov_to_ref = query_df(
            "SELECT sku AS articolo, SUM(qty) AS giacenza_ref FROM movements WHERE datetime(created_at) <= ? GROUP BY sku",
            (ref_dt_end,),
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

    st.markdown("---")
    kpi_card("Valore totale magazzino alla data (giacenze > 0)", fmt_money(totale_asof), icon="💰")


if __name__ == '__main__':
    main()
         