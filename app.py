# -*- coding: utf-8 -*-
"""
Gestionale negozio abbigliamento — funzionalità estese
- Fornitori con campi: codice, nome, località, telefono, tempi di consegna (gg), P.IVA
- Cataloghi (liste) per: Tipo abito, Stagione, Taglia — con possibilità di aggiungere nuove voci
- Articoli con costi, prezzi, giacenza
- Movimenti con data (Carico/Scarico/Rettifica) e storico
- Dashboard + Analisi con filtri per data, costo e giacenza
"""

import os
import sqlite3
from contextlib import closing
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

# ---------------- DB -----------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


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
        causale INTEGER NOT NULL DEFAULT 0, -- 1=CARICO, 2=SCARICO, 3=RETTIFICA+, 4=RETTIFICA-
        qty INTEGER NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sku) REFERENCES items(sku) ON DELETE CASCADE
    );
    """
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.executescript(schema)
        # --- Migrazioni leggere: aggiungi colonne se mancano ---
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
        # mov.causale (1,2,3,4)
        add_col_if_missing('movements','causale','causale INTEGER NOT NULL DEFAULT 0')
        conn.commit()
        # Seed dizionari se vuoti
        if cur.execute("SELECT COUNT(*) FROM dict_types").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_types(type) VALUES (?)", [(t,) for t in ["TSHIRT","JEANS","GIUBBOTTO","ABITO"]])
        if cur.execute("SELECT COUNT(*) FROM dict_seasons").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_seasons(season) VALUES (?)", [(s,) for s in ["SS25","FW25","AI25"]])
        if cur.execute("SELECT COUNT(*) FROM dict_sizes").fetchone()[0] == 0:
            cur.executemany("INSERT INTO dict_sizes(size) VALUES (?)", [(x,) for x in ["XS","S","M","L","XL","40","42","44"]])
        conn.commit()


# --------------- UTILS ----------------

def decode_qr_from_bytes(img_bytes: bytes) -> Optional[str]:
    """Decodifica un QR code da bytes immagine usando OpenCV.
    Restituisce il testo (SKU) oppure None se non trovato.
    """
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
        # 1) format US 1,234,567.89 -> 2) swap first decimal dot with comma
        s = f"{float(x):,.2f}"
        s = s.replace(",", "_")  # 1.234.567_89
        s = s.replace(".", ",")  # 1,234,567_89
        s = s.replace("_", ".")  # 1.234.567,89
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
    # Con i segni: CARICO positivo, SCARICO negativo, RETTIFICA usa il segno immesso
    df = query_df("SELECT qty FROM movements WHERE sku=?", (sku,))
    total = int(df['qty'].sum()) if not df.empty else 0
    execute("UPDATE items SET qty=? WHERE sku=?", (total, sku))


# --------------- UI --------------------

def main():
    st.set_page_config(page_title="Gestionale Negozio Abbigliamento", layout="wide")
    st.title("🧾 Gestionale magazzino — Negozio di Abbigliamento")
    init_db()

    menu = st.sidebar.radio("Menu", ["Dashboard", "Fornitori", "Articoli", "Movimenti", "Analisi"])

    if menu == "Dashboard":
        page_dashboard()
    elif menu == "Fornitori":
        page_suppliers()
    elif menu == "Articoli":
        page_items()
    elif menu == "Movimenti":
        page_movements()
    else:
        page_analysis()


# --------------- PAGES -----------------

def page_dashboard():
    st.header("📊 Dashboard")
    items = query_df("SELECT COUNT(*) AS n, COALESCE(SUM(qty),0) AS tot FROM items")
    n = int(items.at[0, 'n']) if not items.empty else 0
    tot = int(items.at[0, 'tot']) if not items.empty else 0
    c1, c2 = st.columns(2)
    c1.metric("Articoli a catalogo", fmt_thousands(n))
    c2.metric("Giacenza totale (pz)", fmt_thousands(tot))
    st.caption("La giacenza è aggiornata dai movimenti.")


def page_suppliers():
    st.header("🏷️ Fornitori")
    with st.form("supplier_form", clear_on_submit=True):
        c1, c2 = st.columns([1,2])
        code = c1.text_input("Codice (es. ZAR)")
        name = c2.text_input("Nome fornitore")
        city = st.text_input("Località")
        phone = st.text_input("Telefono")
        lead = st.number_input("Tempi consegna (giorni)", min_value=0, value=0)
        vat = st.text_input("P. IVA")
        submitted = st.form_submit_button("Salva fornitore")
        if submitted and name:
            execute(
                "INSERT OR REPLACE INTO suppliers(code, name, city, phone, lead_time_days, vat_number) VALUES (?,?,?,?,?,?)",
                (code or None, name, city or None, phone or None, int(lead), vat or None),
            )
            st.success("Fornitore salvato.")

    st.subheader("Elenco")
    df = query_df("SELECT id, code, name, city, phone, lead_time_days AS lead_days, vat_number AS piva FROM suppliers ORDER BY name")
    st.dataframe(df.drop(columns=['id']), use_container_width=True, hide_index=True)

    with st.expander("✏️ Modifica fornitore"):
        if df.empty:
            st.info("Nessun fornitore da modificare.")
        else:
            sel = st.selectbox("Scegli", df['name'])
            row = df[df['name'] == sel].iloc[0]
            n_code = st.text_input("Codice", value=row['code'] or "")
            n_name = st.text_input("Nome", value=row['name'])
            n_city = st.text_input("Località", value=row['city'] or "")
            n_phone = st.text_input("Telefono", value=row['phone'] or "")
            n_lead = st.number_input("Tempi consegna (giorni)", min_value=0, value=int(row['lead_days'] or 0))
            n_vat = st.text_input("P. IVA", value=row['piva'] or "")
            if st.button("Salva modifiche"):
                execute("UPDATE suppliers SET code=?, name=?, city=?, phone=?, lead_time_days=?, vat_number=? WHERE id=?",
                        (n_code or None, n_name, n_city or None, n_phone or None, int(n_lead), n_vat or None, int(df[df['name']==sel]['id'].iloc[0])))
                st.success("Fornitore aggiornato.")
                st.rerun()

    st.subheader("Elimina fornitore")
    if not df.empty:
        to_del = st.selectbox("Seleziona fornitore", df.apply(lambda r: f"{r['id']} — {r['name']} ({r['code'] or ''})", axis=1))
        if st.button("Elimina fornitore"):
            fid = int(to_del.split(' — ')[0])
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE supplier_id=?", (fid,)).iloc[0]['n']
            if used:
                st.error("Impossibile eliminare: esistono articoli collegati.")
            else:
                execute("DELETE FROM suppliers WHERE id=?", (fid,))
                st.success("Fornitore eliminato.")
                st.rerun()


def page_items():
    st.header("👕 Catalogo articoli")
    suppliers = query_df("SELECT id, name FROM suppliers ORDER BY name")
    if suppliers.empty:
        st.info("Inserisci prima almeno un fornitore nella sezione Fornitori.")
        return

    # Dizionari
    dict_types = query_df("SELECT type FROM dict_types ORDER BY type")['type'].tolist()
    dict_seasons = query_df("SELECT season FROM dict_seasons ORDER BY season")['season'].tolist()
    dict_sizes = query_df("SELECT size FROM dict_sizes ORDER BY size")['size'].tolist()

    with st.expander("➕ Gestione dizionari (Tipo/Stagione/Taglia)"):
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
        # Eliminazione sicura: consentita solo se non in uso
        dcol1, dcol2, dcol3 = st.columns(3)
        del_t = dcol1.selectbox("Elimina tipo (se non usato)", ["—"] + dict_types, key="del_type")
        if dcol1.button("Elimina tipo", key="btn_del_type") and del_t != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE type=?", (del_t,)).iloc[0]['n']
            if used:
                st.error("Non puoi eliminare: è usato da alcuni articoli.")
            else:
                execute("DELETE FROM dict_types WHERE type=?", (del_t,))
                st.success("Tipo eliminato.")
                st.rerun()
        del_s = dcol2.selectbox("Elimina stagione (se non usata)", ["—"] + dict_seasons, key="del_season")
        if dcol2.button("Elimina stagione", key="btn_del_season") and del_s != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE season=?", (del_s,)).iloc[0]['n']
            if used:
                st.error("Non puoi eliminare: è usata da alcuni articoli.")
            else:
                execute("DELETE FROM dict_seasons WHERE season=?", (del_s,))
                st.success("Stagione eliminata.")
                st.rerun()
        del_z = dcol3.selectbox("Elimina taglia (se non usata)", ["—"] + dict_sizes, key="del_size")
        if dcol3.button("Elimina taglia", key="btn_del_size") and del_z != "—":
            used = query_df("SELECT COUNT(*) AS n FROM items WHERE size=?", (del_z,)).iloc[0]['n']
            if used:
                st.error("Non puoi eliminare: è usata da alcuni articoli.")
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
        submitted = st.form_submit_button("Crea articolo")
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
    df = query_df("SELECT i.sku, i.type, i.season, i.size, i.cost, i.price, i.qty, s.name AS supplier FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id ORDER BY i.created_at DESC")
    df_disp = format_df_for_display(df, int_cols=["qty"], money_cols=["cost","price"])
    st.dataframe(df_disp, use_container_width=True, hide_index=True)


def page_movements():
    st.header("🔄 Movimenti di magazzino")
    items = query_df("SELECT sku, qty FROM items ORDER BY sku")
    if items.empty:
        st.info("Nessun articolo presente.")
        return

    with st.expander("📷 Scanner barcode/QR (USB)"):
        st.caption("Suggerimento: gli scanner USB digitano lo SKU e inviano Invio. Inquadra/leggi il barcode e verifica che lo SKU compaia nel campo.")
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

    with st.expander("📱 Scanner con fotocamera (QR)"):
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

    with st.form("mov_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2,1,1])
        sku = c1.selectbox("Articolo (SKU)", items['sku'])
        mtype = c2.selectbox("Tipo", ['CARICO','SCARICO','RETTIFICA +','RETTIFICA -'])
        qty = int(c3.number_input("Quantità", value=1, min_value=1, step=1))
        note = st.text_input("Nota (opzionale)")
        d = st.date_input("Data movimento", value=date.today())
        submitted = st.form_submit_button("Registra movimento")
        if submitted:
            signed = (
            qty if mtype=='CARICO' else
            -qty if mtype=='SCARICO' else
            qty if mtype=='RETTIFICA +' else
            -qty
        )
            execute(
                "INSERT INTO movements(sku, mtype, causale, qty, note, created_at) VALUES (?,?,?,?,?,?)",
                (sku, 'RETTIFICA' if mtype.startswith('RETTIFICA') else mtype, 1 if mtype=='CARICO' else 2 if mtype=='SCARICO' else 3 if mtype=='RETTIFICA +' else 4, signed, note or None, datetime.combine(d, datetime.min.time()).isoformat()),
            )
            execute("UPDATE items SET qty = qty + ? WHERE sku = ?", (signed, sku))
            st.success("Movimento registrato.")

    st.subheader("Storico movimenti")
    # Filtri per elenco movimenti
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
    mov_disp = format_df_for_display(mov, int_cols=["qty"])
    st.dataframe(mov_disp, use_container_width=True, hide_index=True)

    st.markdown("**Elimina movimento**")
    if not mov.empty:
        choice = st.selectbox(
            "Seleziona movimento da eliminare",
            mov.apply(lambda r: f"{r['id']} — {r['created_at']} — {r['sku']} — {r['mtype']} {r['qty']}", axis=1),
            key="mov_del_select",
        )
        if st.button("Elimina movimento", key="mov_del_btn"):
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
     st.header("📈 Analisi Movimenti avanzata — Pivot e indicatori")

    col1, col2, col3 = st.columns(3)
    d_from = col1.date_input("Dal", value=date.today().replace(day=1))
    d_to = col2.date_input("Al", value=date.today())
    cost_max = col3.number_input("Costo max (€)", min_value=0.0, value=0.0, step=0.10)

    col4, col5, col6 = st.columns(3)
    min_stock = int(col4.number_input("Giacenza min", min_value=0, value=0))
    max_stock = int(col5.number_input("Giacenza max (0 = nessun limite)", min_value=0, value=0))
    all_skus = query_df("SELECT sku FROM items ORDER BY sku")['sku'].tolist()
    sku_filter = col6.selectbox("Filtra per articolo (SKU)", ["(tutti)"] + all_skus)

    items_df = query_df("SELECT i.sku, i.type, i.season, i.size, i.cost, i.price, i.qty, s.name AS supplier FROM items i LEFT JOIN suppliers s ON s.id=i.supplier_id")

    if sku_filter != "(tutti)":
        items_df = items_df[items_df['sku'] == sku_filter]
    if cost_max > 0:
        items_df = items_df[items_df['cost'] <= cost_max]
    if min_stock > 0:
        items_df = items_df[items_df['qty'] >= min_stock]
    if max_stock > 0:
        items_df = items_df[items_df['qty'] <= max_stock]

    mov = query_df(
        "SELECT sku, mtype, qty, date(created_at) AS d FROM movements WHERE date(created_at) BETWEEN ? AND ?",
        (d_from.isoformat(), d_to.isoformat()),
    )

    if not mov.empty:
        agg = mov.pivot_table(index='sku', columns='mtype', values='qty', aggfunc='sum').fillna(0).reset_index()
        items_df = items_df.merge(agg, on='sku', how='left').fillna(0)
    else:
        for col in ['CARICO','SCARICO','RETTIFICA']:
            items_df[col] = 0

    items_df['valore_a_costo'] = (items_df['qty'] * items_df['cost']).round(2)
    items_df['valore_a_vendita'] = (items_df['qty'] * items_df['price']).round(2)
    items_df['uscite'] = items_df['SCARICO'].abs()

    items_df['costo_medio'] = items_df.apply(
        lambda r: r['cost'] if r['CARICO'] == 0 else round(r['valore_a_costo'] / max(r['CARICO'], 1), 2), axis=1
    )
    items_df['indice_rotazione'] = items_df.apply(
        lambda r: 0 if r['qty'] == 0 else round(r['uscite'] / r['qty'], 2), axis=1
    )

    st.subheader("📊 Analisi dettagliata")
    st.dataframe(items_df, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Articoli filtrati", fmt_thousands(len(items_df)))
    c2.metric("Giacenza totale (filtro)", fmt_thousands(int(items_df['qty'].sum())))
    c3.metric("Valore a costo (filtro)", fmt_money(items_df['valore_a_costo'].sum()))

    df_positive = items_df[items_df['qty'] > 0]
    if not df_positive.empty:
        costo_magazzino = (df_positive['qty'] * df_positive['cost']).sum()
        st.markdown(f"### 💰 Costo Magazzino ad oggi: **{fmt_money(costo_magazzino)}**")
    else:
        st.markdown("### 💰 Costo Magazzino ad oggi: **€ 0,00**")

if __name__ == '__main__':
    main()
