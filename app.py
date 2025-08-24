# app.py — Supabase version that mirrors the JSON/Sheets logic you shared
# Features (same logic/UX):
# - Multi-brand (gulavit, takokak) via table mapping per brand
# - Login (tabel users_gulavit; fallback secrets)
# - Dashboard Pro (KPI, charts, Top items, Top events, Reorder insight + export)
# - Lihat Stok, Stock Card
# - Request IN (multi-item + DO wajib), OUT (manual + Excel), RETURN (manual + Excel)
# - Approve/Reject with select-all editor (batch)
# - Riwayat lengkap (with attachment download), Export filter, Reset database (per brand)
#
# NOTE:
# - Create tables for each brand:
#     inventory_gulavit | inventory_takokak
#     pending_gulavit   | pending_takokak
#     history_gulavit   | history_takokak
#   With columns (recommended):
#     inventory_*: code(text PK or unique), item(text), qty(int8), unit(text), category(text)
#     pending_*  : id bigserial PK, type(text: IN/OUT/RETURN), date(date/text), code, item, qty(int),
#                  unit, event, trans_type, do_number, attachment, user, timestamp
#     history_*  : id bigserial PK, action(text), item, qty(int), stock(int), unit, user,
#                  event, do_number, attachment, timestamp, date, code, trans_type
#
# - Users table:
#     users_gulavit: username(text PK), password(text), role(text: admin/approver/user)
#
# - File DO disimpan lokal (uploads/) -> ephemeral di hosting. Untuk permanen, pindahkan ke Supabase Storage.

import os
import base64
import json
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client, Client

# -------------------- CONFIG & STYLES --------------------
BANNER_URL = "https://media.licdn.com/dms/image/v2/D563DAQFDri8xlKNIvg/image-scale_191_1128/image-scale_191_1128/0/1678337293506/pesona_inti_rasa_cover?e=2147483647&v=beta&t=vHi0xtyAZsT9clHb0yBYPE8M9IaO2dNY6Cb_Vs3Ddlo"
ICON_URL   = "https://i.ibb.co/7C96T9y/favicon.png"
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

TRANS_TYPES = ["Support", "Penjualan"]   # OUT types
STD_REQ_COLS = ["date","code","item","qty","unit","event","trans_type","do_number","attachment","user","timestamp"]

BRANDS = ["gulavit","takokak"]
TABLES = {
    "gulavit": {"inv":"inventory_gulavit","pend":"pending_gulavit","hist":"history_gulavit"},
    "takokak": {"inv":"inventory_takokak","pend":"pending_takokak","hist":"history_takokak"},
}
USERS_TABLE = "users_gulavit"  # shared users

st.set_page_config(page_title="Inventory System", page_icon=ICON_URL, layout="wide")

# experimental_rerun shim
try:
    if not hasattr(st, "experimental_rerun"):
        st.experimental_rerun = st.rerun
except Exception:
    pass

# CSS (mirroring your look)
st.markdown("""
<style>
.main { background-color: #F8FAFC; }
h1, h2, h3 { color: #0F172A; }
.kpi-card {
  background: #ffffff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 18px 18px 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}
.kpi-title { font-size: 12px; color: #64748B; letter-spacing: .06em; text-transform: uppercase; }
.kpi-value { font-size: 26px; font-weight: 700; color: #16A34A; margin-top: 6px; }
.kpi-sub { font-size: 12px; color: #64748B; margin-top: 2px; }
.stButton>button {
  background-color: #0EA5E9; color: white; border-radius: 8px; height: 2.6em; width: 100%; border: none;
}
.stButton>button:hover { background-color: #0284C7; color: white; }
.smallcap{ font-size:12px; color:#64748B;}
.card {
  background: #ffffff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04); height: 100%;
}
</style>
""", unsafe_allow_html=True)

# Optional charts
try:
    import altair as alt
    _ALT_OK = True
except Exception:
    _ALT_OK = False


# -------------------- SUPABASE --------------------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# -------------------- UTILS --------------------
def ts_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _to_date_str(val):
    if val is None or str(val).strip() == "":
        return datetime.now().strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(val, errors="coerce").strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def _norm_event(s):
    return str(s).strip() if s is not None else "-"

def _norm_trans_type(s):
    s = "" if s is None else str(s).strip().lower()
    if s == "support": return "Support"
    if s == "penjualan": return "Penjualan"
    return None

def normalize_out_record(base: dict) -> dict:
    rec = {k: None for k in STD_REQ_COLS}
    rec.update({
        "date": _to_date_str(base.get("date")),
        "code": base.get("code", "-") or "-",
        "item": base.get("item", "-") or "-",
        "qty": int(pd.to_numeric(base.get("qty", 0), errors="coerce") or 0),
        "unit": base.get("unit", "-") or "-",
        "event": _norm_event(base.get("event", "-")),
        "trans_type": _norm_trans_type(base.get("trans_type")),
        "do_number": base.get("do_number", "-") or "-",
        "attachment": base.get("attachment"),
        "user": base.get("user", st.session_state.get("username","-")),
        "timestamp": base.get("timestamp", ts_text()),
    })
    return rec

def normalize_return_record(base: dict) -> dict:
    rec = {k: None for k in STD_REQ_COLS}
    rec.update({
        "date": _to_date_str(base.get("date")),
        "code": base.get("code", "-") or "-",
        "item": base.get("item", "-") or "-",
        "qty": int(pd.to_numeric(base.get("qty", 0), errors="coerce") or 0),
        "unit": base.get("unit", "-") or "-",
        "event": _norm_event(base.get("event", "-")),
        "trans_type": None,
        "do_number": "-",
        "attachment": None,
        "user": base.get("user", st.session_state.get("username","-")),
        "timestamp": base.get("timestamp", ts_text()),
    })
    return rec

def dataframe_to_excel_bytes(df: pd.DataFrame, sheet="Sheet1") -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name=sheet)
    bio.seek(0)
    return bio.read()

def make_master_template_bytes() -> bytes:
    cols = ["Kode Barang", "Nama Barang", "Qty", "Satuan", "Kategori"]
    df_tmpl = pd.DataFrame([{
        "Kode Barang": "ITM-0001", "Nama Barang": "Contoh Produk", "Qty": 10, "Satuan": "pcs", "Kategori": "Umum"
    }], columns=cols)
    return dataframe_to_excel_bytes(df_tmpl, "Template Master")

def make_out_template_bytes(inv_records: list) -> bytes:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cols = ["Tanggal", "Kode Barang", "Nama Barang", "Qty", "Event", "Tipe"]
    rows = []
    if inv_records:
        for r in inv_records[:2]:
            rows.append({
                "Tanggal": today, "Kode Barang": r["code"], "Nama Barang": r["name"],
                "Qty": 1, "Event": "Contoh event", "Tipe": "Support"
            })
    else:
        rows.append({
            "Tanggal": today, "Kode Barang": "ITM-0001", "Nama Barang": "Contoh Produk",
            "Qty": 1, "Event": "Contoh event", "Tipe": "Support"
        })
    return dataframe_to_excel_bytes(pd.DataFrame(rows, columns=cols), "Template OUT")

def make_return_template_bytes(inv_records: list) -> bytes:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cols = ["Tanggal", "Kode Barang", "Nama Barang", "Qty", "Event"]
    rows = []
    if inv_records:
        for r in inv_records[:2]:
            rows.append({
                "Tanggal": today, "Kode Barang": r["code"], "Nama Barang": r["name"],
                "Qty": 1, "Event": "Contoh event dari OUT"
            })
    else:
        rows.append({"Tanggal": today, "Kode Barang": "ITM-0001", "Nama Barang": "Contoh Produk", "Qty": 1, "Event": "Contoh event"})
    return dataframe_to_excel_bytes(pd.DataFrame(rows, columns=cols), "Template Retur")


# -------------------- LOAD DATA FROM SUPABASE --------------------
@st.cache_data(ttl=300)
def _load_users() -> dict:
    try:
        res = supabase.from_(USERS_TABLE).select("*").execute()
        df = pd.DataFrame(res.data or [])
        users = {}
        if not df.empty:
            for _, r in df.iterrows():
                users[str(r["username"])] = {"password": str(r["password"]), "role": str(r["role"])}
        if not users:
            users = {
                "admin": {"password": st.secrets.get("passwords", {}).get("admin","admin"), "role":"admin"},
                "user":  {"password": st.secrets.get("passwords", {}).get("user","user"),   "role":"user"},
            }
        return users
    except Exception:
        # fallback to secrets
        return {
            "admin": {"password": st.secrets.get("passwords", {}).get("admin","admin"), "role":"admin"},
            "user":  {"password": st.secrets.get("passwords", {}).get("user","user"),   "role":"user"},
        }

def _safe_select(table: str) -> pd.DataFrame:
    try:
        res = supabase.from_(table).select("*").execute()
        return pd.DataFrame(res.data or [])
    except Exception as e:
        st.warning(f"Tabel '{table}' tidak bisa dibaca: {e}")
        return pd.DataFrame([])

def load_brand_data(brand: str) -> dict:
    t = TABLES[brand]
    df_inv = _safe_select(t["inv"])
    df_pend = _safe_select(t["pend"])
    df_hist = _safe_select(t["hist"])

    # inventory -> dict by code
    inv = {}
    if not df_inv.empty:
        for _, r in df_inv.iterrows():
            inv[str(r.get("code","-"))] = {
                "name": str(r.get("item","-")),
                "qty": int(pd.to_numeric(r.get("qty",0), errors="coerce") or 0),
                "unit": str(r.get("unit","-")) if pd.notna(r.get("unit")) else "-",
                "category": str(r.get("category","Uncategorized")) if pd.notna(r.get("category")) else "Uncategorized",
            }

    # pending -> list of normalized dicts (keep id)
    pend = []
    if not df_pend.empty:
        for _, r in df_pend.iterrows():
            base = {k: r.get(k) for k in STD_REQ_COLS}
            base.update({"type": r.get("type"), "id": r.get("id")})
            # normalize to ensure columns exist/typing ok
            if base["type"] == "RETURN":
                rec = normalize_return_record(base)
            else:
                rec = normalize_out_record(base)
            rec["type"] = base["type"]
            rec["id"] = base["id"]
            pend.append(rec)

    # history -> list of dicts
    hist = df_hist.to_dict(orient="records") if not df_hist.empty else []

    return {
        "users": _load_users(),
        "inventory": inv,
        "pending_requests": pend,
        "history": hist,
    }

def invalidate_cache():
    st.cache_data.clear()


# -------------------- WRITES TO SUPABASE --------------------
def inv_insert(brand, code, item, qty, unit="-", category="Uncategorized"):
    t = TABLES[brand]
    supabase.from_(t["inv"]).insert({
        "code": code, "item": item, "qty": int(qty), "unit": unit or "-", "category": category or "Uncategorized"
    }).execute()
    supabase.from_(t["hist"]).insert({
        "action": "ADD_ITEM", "item": item, "qty": int(qty), "stock": int(qty),
        "unit": unit or "-", "user": st.session_state.username, "event": "-",
        "timestamp": ts_text(), "date": datetime.now().strftime("%Y-%m-%d"),
        "code": code, "trans_type": None, "do_number": "-", "attachment": None
    }).execute()
    invalidate_cache()

def inv_update_qty(brand, code, new_qty):
    t = TABLES[brand]
    supabase.from_(t["inv"]).update({"qty": int(new_qty)}).eq("code", code).execute()
    invalidate_cache()

def pending_add_many(brand, records: list):
    t = TABLES[brand]
    # Records contain keys from STD_REQ_COLS + 'type'
    if not records:
        return
    supabase.from_(t["pend"]).insert(records).execute()
    invalidate_cache()

def pending_delete_by_ids(brand, ids: list):
    t = TABLES[brand]
    if not ids: return
    for chunk in [ids[i:i+1000] for i in range(0, len(ids), 1000)]:
        supabase.from_(t["pend"]).delete().in_("id", chunk).execute()
    invalidate_cache()

def history_add(brand, rec: dict):
    t = TABLES[brand]
    supabase.from_(t["hist"]).insert(rec).execute()
    invalidate_cache()

def reset_brand(brand):
    t = TABLES[brand]
    supabase.from_(t["pend"]).delete().neq("id",-1).execute()
    supabase.from_(t["hist"]).delete().neq("id",-1).execute()
    supabase.from_(t["inv"]).delete().neq("code","").execute()
    invalidate_cache()


# -------------------- DASHBOARD HELPERS --------------------
def _prepare_history_df(data: dict) -> pd.DataFrame:
    hist = data.get("history", [])
    df = pd.DataFrame(hist)
    if df.empty:
        return df
    df["qty"] = pd.to_numeric(df.get("qty", 0), errors="coerce").fillna(0).astype(int)
    s_date = pd.to_datetime(df["date"], errors="coerce") if "date" in df.columns else pd.Series(pd.NaT, index=df.index)
    s_ts   = pd.to_datetime(df["timestamp"], errors="coerce") if "timestamp" in df.columns else pd.Series(pd.NaT, index=df.index)
    df["date_eff"] = s_date.fillna(s_ts).dt.floor("D")

    act = df.get("action","").astype(str).str.upper()
    df["type_norm"] = "-"
    df.loc[act.str.contains("APPROVE_IN"), "type_norm"] = "IN"
    df.loc[act.str.contains("APPROVE_OUT"), "type_norm"] = "OUT"
    df.loc[act.str.contains("APPROVE_RETURN"), "type_norm"] = "RETURN"

    for col in ["item","event","trans_type","unit"]:
        if col not in df.columns: df[col] = None
    df["event"] = df["event"].fillna("-").astype(str)
    df["trans_type"] = df["trans_type"].fillna("-").astype(str)

    df = df[df["type_norm"].isin(["IN","OUT","RETURN"])].copy()
    df = df.dropna(subset=["date_eff"])
    return df

def _kpi_card(title, value, change_text=None):
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">{title}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{change_text or ""}</div>
        </div>
    """, unsafe_allow_html=True)

def render_dashboard_pro(data: dict, brand_label: str, allow_download=True):
    try:
        df_hist = _prepare_history_df(data)
        inv_records = [
            {"Kode": code, "Nama Barang": it.get("name","-"), "Current Stock": int(it.get("qty",0)), "Unit": it.get("unit","-")}
            for code, it in data.get("inventory", {}).items()
        ]
        df_inv = pd.DataFrame(inv_records)

        st.markdown(f"## Dashboard — {brand_label}")
        st.caption("Semua metrik berbasis jumlah (qty). *Sales* = OUT dengan tipe **Penjualan**.")
        st.divider()

        today = pd.Timestamp.today().normalize()
        default_start = (today - pd.DateOffset(months=11)).replace(day=1)
        colF1, colF2 = st.columns(2)
        start_date = colF1.date_input("Tanggal mulai", value=default_start.date())
        end_date   = colF2.date_input("Tanggal akhir", value=today.date())

        if not df_hist.empty:
            mask = (df_hist["date_eff"] >= pd.Timestamp(start_date)) & (df_hist["date_eff"] <= pd.Timestamp(end_date))
            df_range = df_hist.loc[mask].copy()
        else:
            df_range = pd.DataFrame(columns=["date_eff","type_norm","qty","item","event","trans_type"])

        total_sku = int(len(df_inv)) if not df_inv.empty else 0
        total_qty = int(df_inv["Current Stock"].sum()) if not df_inv.empty else 0
        tot_in  = int(df_range.loc[df_range["type_norm"]=="IN", "qty"].sum()) if not df_range.empty else 0
        tot_out = int(df_range.loc[df_range["type_norm"]=="OUT","qty"].sum()) if not df_range.empty else 0
        tot_ret = int(df_range.loc[df_range["type_norm"]=="RETURN","qty"].sum()) if not df_range.empty else 0

        c1, c2, c3, c4 = st.columns(4)
        _kpi_card("Total SKU", f"{total_sku:,}", f"Brand {brand_label}")
        _kpi_card("Total Qty (Stock)", f"{total_qty:,}", f"Per {pd.Timestamp(end_date).strftime('%d %b %Y')}")
        _kpi_card("Total IN (periode)", f"{tot_in:,}", None)
        _kpi_card("Total OUT / Retur", f"{tot_out:,} / {tot_ret:,}", None)

        st.divider()

        def month_agg(df, tipe):
            d = df[df["type_norm"]==tipe].copy()
            if d.empty:
                return pd.DataFrame({"month": [], "qty": [], "Periode": [], "idx": []})
            d["month"] = d["date_eff"].dt.to_period("M").dt.to_timestamp()
            g = d.groupby("month", as_index=False)["qty"].sum().sort_values("month")
            g["Periode"] = g["month"].dt.strftime("%b %Y")
            g["idx"] = g["month"].dt.year.astype(int)*12 + g["month"].dt.month.astype(int)
            return g

        g_in  = month_agg(df_range,"IN")
        g_out = month_agg(df_range,"OUT")
        g_ret = month_agg(df_range,"RETURN")

        def _month_bar(container, dfm, title, color="#0EA5E9"):
            with container:
                st.markdown(f'<div class="card"><div class="smallcap">{title}</div>', unsafe_allow_html=True)
                if _ALT_OK and not dfm.empty:
                    chart = (
                        alt.Chart(dfm).mark_bar(size=28)
                        .encode(
                            x=alt.X("Periode:O", sort=alt.SortField(field="idx", order="ascending"), title="Periode"),
                            y=alt.Y("qty:Q", title="Qty"),
                            tooltip=[alt.Tooltip("month:T", title="Periode", format="%b %Y"), "qty:Q"],
                            color=alt.value(color)
                        ).properties(height=320)
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    if dfm.empty: st.info("Belum ada data.")
                    else: st.bar_chart(dfm.set_index("Periode")["qty"])
                st.markdown("</div>", unsafe_allow_html=True)

        cA, cB, cC = st.columns(3)
        _month_bar(cA, g_in,  "IN per Month",    "#22C55E")
        _month_bar(cB, g_out, "OUT per Month",   "#EF4444")
        _month_bar(cC, g_ret, "RETUR per Month", "#0EA5E9")

        st.divider()

        t1, t2 = st.columns([1,1])
        with t1:
            st.markdown('<div class="card"><div class="smallcap">Top 10 Items (Current Stock)</div>', unsafe_allow_html=True)
            if _ALT_OK and not df_inv.empty:
                top10 = df_inv.sort_values("Current Stock", ascending=False).head(10)
                chart = (alt.Chart(top10).mark_bar(size=22)
                         .encode(y=alt.Y("Nama Barang:N", sort="-x", title=None),
                                 x=alt.X("Current Stock:Q", title="Qty"),
                                 tooltip=["Nama Barang","Current Stock"])
                         .properties(height=360))
                st.altair_chart(chart, use_container_width=True)
            else:
                if df_inv.empty: st.info("Inventory kosong.")
                else: st.dataframe(df_inv.sort_values("Current Stock", ascending=False).head(10), use_container_width=True, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with t2:
            st.markdown('<div class="card"><div class="smallcap">Top 5 Event by OUT Qty</div>', unsafe_allow_html=True)
            df_ev = df_range[(df_range["type_norm"]=="OUT") & (df_range["event"].notna())].copy()
            df_ev = df_ev[df_ev["event"].astype(str).str.strip().ne("-")]
            ev_top = (df_ev.groupby("event", as_index=False)["qty"].sum().sort_values("qty", ascending=False).head(5))
            if _ALT_OK and not ev_top.empty:
                chart = (alt.Chart(ev_top).mark_bar(size=22)
                         .encode(y=alt.Y("event:N", sort="-x", title="Event"),
                                 x=alt.X("qty:Q", title="Qty"),
                                 tooltip=["event","qty"])
                         .properties(height=360))
                st.altair_chart(chart, use_container_width=True)
            else:
                if ev_top.empty: st.info("Belum ada OUT pada rentang ini.")
                else: st.dataframe(ev_top.rename(columns={"event":"Event","qty":"Qty"}), use_container_width=True, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()

        # Reorder insight
        st.subheader("Reorder Insight (berdasarkan OUT 3 bulan terakhir)")
        st.caption("Menghitung *Days of Cover* = stok saat ini / rata-rata OUT harian (3 bulan).")
        tgt_days = st.slider("Target Days of Cover", min_value=30, max_value=120, step=15, value=60)

        if df_inv.empty:
            st.info("Inventory kosong.")
            return

        ref_end = pd.Timestamp(end_date)
        last3_start = (ref_end - pd.DateOffset(months=3)).normalize() + pd.Timedelta(days=1)
        out3 = df_hist[(df_hist["type_norm"]=="OUT") & (df_hist["date_eff"] >= last3_start) & (df_hist["date_eff"] <= ref_end)]
        out3_item = out3.groupby("item")["qty"].sum().to_dict()

        rows = []
        for _, r in df_inv.iterrows():
            name = r["Nama Barang"]; stock = int(r["Current Stock"]); unit = r.get("Unit","-")
            last3 = int(out3_item.get(name, 0))
            avg_m = last3 / 3.0
            avg_daily = (avg_m / 30.0) if avg_m > 0 else 0.0
            doc = (stock / avg_daily) if avg_daily > 0 else float("inf")
            if doc == float("inf"): reco, urgency = "OK (tidak ada pemakaian)", 5
            elif doc < 15:         reco, urgency = "Order NOW (Urgent)", 1
            elif doc < 30:         reco, urgency = "Order bulan ini", 2
            elif doc < 60:         reco, urgency = "Order bulan depan", 3
            elif doc < 90:         reco, urgency = "Order 2 bulan lagi", 4
            else:                  reco, urgency = "OK (stok aman)", 5
            target_qty = int(max(0, (avg_daily * tgt_days) - stock)) if avg_daily > 0 else 0
            rows.append({
                "Nama Barang": name, "Unit": unit, "Current Stock": stock,
                "OUT 3 Bulan": last3, "Avg OUT / Bulan": round(avg_m,1),
                "Days of Cover": ("∞" if doc==float("inf") else int(round(doc))),
                "Rekomendasi": reco, "Saran Order (Qty)": target_qty, "_urgency": urgency
            })

        df_reorder = pd.DataFrame(rows).sort_values(["_urgency","Days of Cover"], ascending=[True, True]).drop(columns=["_urgency"])
        st.dataframe(df_reorder, use_container_width=True, hide_index=True)

        if allow_download and not df_reorder.empty:
            xls = BytesIO()
            with pd.ExcelWriter(xls, engine="xlsxwriter") as wr:
                df_reorder.to_excel(wr, sheet_name="Reorder Insight", index=False)
            xls.seek(0)
            st.download_button(
                "Unduh Excel Reorder Insight",
                data=xls.read(),
                file_name=f"Reorder_{brand_label.replace(' ','_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    except Exception as e:
        st.error(f"Dashboard error: {e}")


# -------------------- SESSION --------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username  = ""
    st.session_state.role      = ""
    st.session_state.current_brand = "gulavit"

for key in ["req_in_items","req_out_items","req_ret_items"]:
    if key not in st.session_state: st.session_state[key] = []

for key in ["notification"]:
    if key not in st.session_state: st.session_state[key] = None


# -------------------- LOGIN --------------------
if not st.session_state.logged_in:
    st.image(BANNER_URL, use_container_width=True)
    st.markdown("<div style='text-align:center;'><h1 style='margin-top:10px;'>Inventory Management System</h1></div>", unsafe_allow_html=True)
    st.subheader("Silakan Login untuk Mengakses Sistem")
    username = st.text_input("Username", placeholder="Masukkan username")
    password = st.text_input("Password", type="password", placeholder="Masukkan password")
    if st.button("Login"):
        users = _load_users()
        user = users.get(username)
        if user and user["password"] == password:
            st.session_state.logged_in = True
            st.session_state.username  = username
            st.session_state.role      = user["role"]
            st.success(f"Login berhasil sebagai {user['role'].upper()}")
            st.rerun()
        else:
            st.error("❌ Username atau password salah.")
    st.stop()


# -------------------- MAIN --------------------
role = st.session_state.role
st.image(BANNER_URL, use_container_width=True)

# Sidebar
st.sidebar.markdown(f"### 👋 Halo, {st.session_state.username}")
st.sidebar.caption(f"Role: **{role.upper()}**")
st.sidebar.divider()

brand_choice = st.sidebar.selectbox("Pilih Brand", BRANDS, format_func=lambda x: x.capitalize(), index=BRANDS.index(st.session_state.get("current_brand","gulavit")))
st.session_state.current_brand = brand_choice
DATA = load_brand_data(brand_choice)

if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.current_brand = "gulavit"
    st.rerun()

st.sidebar.divider()

if st.session_state.notification:
    nt = st.session_state.notification
    (st.success if nt["type"]=="success" else st.warning if nt["type"]=="warning" else st.error)(nt["message"])
    st.session_state.notification = None


# -------------------- ADMIN --------------------
def page_admin_dashboard():
    render_dashboard_pro(DATA, brand_label=st.session_state.current_brand.capitalize(), allow_download=False)

def page_admin_lihat_stok():
    st.markdown(f"## Stok Barang - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    inv = DATA["inventory"]
    if inv:
        df = pd.DataFrame([
            {"Kode": code, "Nama Barang": it["name"], "Qty": it["qty"], "Satuan": it.get("unit","-"), "Kategori": it.get("category","Uncategorized")}
            for code, it in inv.items()
        ])
        cats = ["Semua Kategori"] + sorted(df["Kategori"].dropna().unique().tolist())
        c1, c2 = st.columns(2)
        cat = c1.selectbox("Pilih Kategori", cats)
        q = c2.text_input("Cari Nama/Kode")
        view = df.copy()
        if cat != "Semua Kategori": view = view[view["Kategori"] == cat]
        if q:
            view = view[ view["Nama Barang"].str.contains(q, case=False) | view["Kode"].str.contains(q, case=False) ]
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada barang di inventory.")

def page_admin_stock_card():
    st.markdown(f"## Stock Card Barang - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    hist = DATA["history"]
    if not hist:
        st.info("Belum ada riwayat transaksi.")
        return
    item_names = sorted(list({it["name"] for it in DATA["inventory"].values()}))
    if not item_names:
        st.info("Belum ada master barang.")
        return
    sel = st.selectbox("Pilih Barang", item_names)
    if not sel: return
    filtered = [h for h in hist if h.get("item")==sel and (str(h.get("action","")).startswith("APPROVE") or str(h.get("action","")).startswith("ADD"))]
    if not filtered:
        st.info("Tidak ada transaksi yang disetujui untuk barang ini.")
        return
    rows, saldo = [], 0
    for h in sorted(filtered, key=lambda x: x.get("timestamp","")):
        act = str(h.get("action","")).upper()
        qty = int(pd.to_numeric(h.get("qty",0), errors="coerce") or 0)
        t_in = t_out = "-"
        ket = "N/A"
        if act == "ADD_ITEM":
            t_in = qty; saldo += qty; ket = "Initial Stock"
        elif act == "APPROVE_IN":
            t_in = qty; saldo += qty; ket = f"Request IN by {h.get('user','-')}"
            do = h.get("do_number","-")
            if do and do != "-": ket += f" (No. DO: {do})"
        elif act == "APPROVE_OUT":
            t_out = qty; saldo -= qty
            tipe = h.get("trans_type","-")
            ket = f"Request OUT ({tipe}) by {h.get('user','-')} for event: {h.get('event','-')}"
        elif act == "APPROVE_RETURN":
            t_in = qty; saldo += qty; ket = f"Retur by {h.get('user','-')} for event: {h.get('event','-')}"
        rows.append({
            "Tanggal": h.get("date", h.get("timestamp","")),
            "Keterangan": ket,
            "Masuk (IN)": t_in, "Keluar (OUT)": t_out, "Saldo Akhir": saldo
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def page_admin_tambah_master():
    st.markdown(f"## Tambah Master Barang - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    tab1, tab2 = st.tabs(["Input Manual", "Upload Excel"])
    with tab1:
        code = st.text_input("Kode Barang (unik & wajib)", placeholder="ITM-0001")
        name = st.text_input("Nama Barang")
        unit = st.text_input("Satuan (pcs/box/liter)")
        qty  = st.number_input("Jumlah Stok Awal", min_value=0, step=1)
        cat  = st.text_input("Kategori Barang", placeholder="Umum/Minuman/Makanan")
        if st.button("Tambah Barang Manual"):
            inv = DATA["inventory"]
            if not code.strip():
                st.error("Kode Barang wajib diisi.")
            elif code in inv:
                st.error(f"Kode '{code}' sudah ada.")
            elif not name.strip():
                st.error("Nama barang wajib diisi.")
            else:
                inv_insert(st.session_state.current_brand, code.strip(), name.strip(), int(qty), unit.strip() or "-", cat.strip() or "Uncategorized")
                st.success(f"Barang '{name}' berhasil ditambahkan.")
                st.experimental_rerun()
    with tab2:
        st.info("Format Excel: **Kode Barang | Nama Barang | Qty | Satuan | Kategori**")
        st.download_button("📥 Unduh Template Master Excel", data=make_master_template_bytes(),
                           file_name=f"Template_Master_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu = st.file_uploader("Upload File Excel Master", type=["xlsx"])
        if fu and st.button("Tambah dari Excel (Master)"):
            try:
                df_new = pd.read_excel(fu, engine="openpyxl")
                req = ["Kode Barang","Nama Barang","Qty","Satuan","Kategori"]
                miss = [c for c in req if c not in df_new.columns]
                if miss:
                    st.error(f"Kolom kurang: {', '.join(miss)}"); return
                added, errors = 0, []
                existing = set(DATA["inventory"].keys())
                for idx, r in df_new.iterrows():
                    code = str(r["Kode Barang"]).strip() if pd.notna(r["Kode Barang"]) else ""
                    name = str(r["Nama Barang"]).strip() if pd.notna(r["Nama Barang"]) else ""
                    if not code or not name:
                        errors.append(f"Baris {idx+2}: Kode/Nama wajib."); continue
                    if code in existing:
                        errors.append(f"Baris {idx+2}: Kode '{code}' sudah ada."); continue
                    qty  = int(pd.to_numeric(r["Qty"], errors="coerce") or 0)
                    unit = str(r["Satuan"]).strip() if pd.notna(r["Satuan"]) else "-"
                    cat  = str(r["Kategori"]).strip() if pd.notna(r["Kategori"]) else "Uncategorized"
                    inv_insert(st.session_state.current_brand, code, name, qty, unit, cat); added += 1
                if added: st.success(f"{added} item master berhasil ditambahkan.")
                if errors: st.warning("Beberapa baris dilewati:\n- " + "\n- ".join(errors))
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Gagal membaca Excel: {e}")

def page_admin_approve():
    st.markdown(f"## Approve / Reject Request Barang - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    pend = DATA["pending_requests"]
    if not pend:
        st.info("Tidak ada pending request.")
        return

    df = pd.DataFrame(pend)
    df["Lampiran"] = df["attachment"].apply(lambda x: "Ada" if x else "Tidak Ada")

    # selection flags
    if "approve_select_flags" not in st.session_state or len(st.session_state.approve_select_flags) != len(df):
        st.session_state.approve_select_flags = [False]*len(df)

    csel1, csel2 = st.columns([1,1])
    if csel1.button("Pilih semua"): st.session_state.approve_select_flags = [True]*len(df)
    if csel2.button("Kosongkan pilihan"): st.session_state.approve_select_flags = [False]*len(df)

    df["Pilih"] = st.session_state.approve_select_flags
    # make all other columns readonly
    col_cfg = {"Pilih": st.column_config.CheckboxColumn("Pilih", default=False)}
    for c in df.columns:
        if c != "Pilih":
            col_cfg[c] = st.column_config.TextColumn(c, disabled=True)
    edited = st.data_editor(df, key="editor_admin_approve", use_container_width=True, hide_index=True, column_config=col_cfg)
    st.session_state.approve_select_flags = edited["Pilih"].fillna(False).tolist()
    selected_idx = [i for i,v in enumerate(st.session_state.approve_select_flags) if v]

    col1, col2 = st.columns(2)
    if col1.button("Approve Selected"):
        if not selected_idx:
            st.session_state.notification = {"type":"warning","message":"Pilih setidaknya satu item untuk di-approve."}
            st.rerun()

        # Load fresh inventory for updates
        brand = st.session_state.current_brand
        inv_map = load_brand_data(brand)["inventory"]  # name-based processing per original logic

        approved_ids = []
        for i in selected_idx:
            req = pend[i]
            # find inventory row by item name (same as your reference logic)
            found_code = None
            for code, it in inv_map.items():
                if it.get("name") == req["item"]:
                    found_code = code
                    break
            if found_code is None:
                # if item not found, skip (original script simply matched by name)
                st.warning(f"Item '{req['item']}' tidak ditemukan di master; lewati.")
                continue

            cur = int(inv_map[found_code]["qty"])
            qty = int(req["qty"])
            t = str(req["type"]).upper()
            if t == "IN":
                new_qty = cur + qty
            elif t == "OUT":
                new_qty = cur - qty  # assume validated at request time; could be <= 0
            elif t == "RETURN":
                new_qty = cur + qty
            else:
                st.warning(f"Tipe tidak dikenali: {t}; lewati."); continue

            # update inventory
            inv_update_qty(brand, found_code, new_qty)
            inv_map[found_code]["qty"] = new_qty

            # history
            history_add(brand, {
                "action": f"APPROVE_{t}",
                "item": req["item"],
                "qty": int(req["qty"]),
                "stock": new_qty,
                "unit": req.get("unit","-"),
                "user": req.get("user", st.session_state.username),
                "event": req.get("event","-"),
                "do_number": req.get("do_number","-"),
                "attachment": req.get("attachment"),
                "timestamp": ts_text(),
                "date": req.get("date"),
                "code": found_code,
                "trans_type": req.get("trans_type")
            })

            approved_ids.append(req.get("id"))

        if approved_ids:
            pending_delete_by_ids(brand, approved_ids)
            st.session_state.notification = {"type": "success", "message": f"{len(approved_ids)} request di-approve."}
        else:
            st.session_state.notification = {"type": "warning", "message": "Tidak ada request valid yang diproses."}
        st.rerun()

    if col2.button("Reject Selected"):
        if not selected_idx:
            st.session_state.notification = {"type":"warning","message":"Pilih setidaknya satu item untuk di-reject."}
            st.rerun()

        brand = st.session_state.current_brand
        rejected_ids = []
        for i in selected_idx:
            req = pend[i]
            history_add(brand, {
                "action": f"REJECT_{str(req.get('type','-')).upper()}",
                "item": req.get("item","-"),
                "qty": int(pd.to_numeric(req.get("qty",0), errors="coerce") or 0),
                "stock": None,
                "unit": req.get("unit","-"),
                "user": req.get("user", st.session_state.username),
                "event": req.get("event","-"),
                "do_number": req.get("do_number","-"),
                "attachment": req.get("attachment"),
                "timestamp": ts_text(),
                "date": req.get("date"),
                "code": req.get("code"),
                "trans_type": req.get("trans_type")
            })
            rejected_ids.append(req.get("id"))

        if rejected_ids:
            pending_delete_by_ids(brand, rejected_ids)
            st.session_state.notification = {"type":"success","message":f"{len(rejected_ids)} request di-reject."}
        st.rerun()

def page_admin_riwayat():
    st.markdown(f"## Riwayat Lengkap - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    hist = DATA["history"]
    if not hist:
        st.info("Belum ada riwayat.")
        return
    all_keys = ["action","item","qty","stock","unit","user","event","do_number","attachment","timestamp","date","code","trans_type"]
    rows = []
    for h in hist:
        e = {k: h.get(k) for k in all_keys}
        for k, default in [("do_number","-"),("event","-"),("unit","-")]:
            if e.get(k) is None: e[k] = default
        rows.append(e)
    df = pd.DataFrame(rows)
    df["date_only"] = pd.to_datetime(df["date"].fillna(df["timestamp"]), errors="coerce").dt.date

    def get_dl(path):
        if path and os.path.exists(str(path)):
            with open(path, "rb") as f:
                b = base64.b64encode(f.read()).decode()
            name = os.path.basename(path)
            return f'<a href="data:application/pdf;base64,{b}" download="{name}">Unduh</a>'
        return "Tidak Ada"
    df["Lampiran"] = df["attachment"].apply(get_dl)

    c1, c2 = st.columns(2)
    start = c1.date_input("Tanggal Mulai", value=df["date_only"].min())
    end   = c2.date_input("Tanggal Akhir", value=df["date_only"].max())
    c3, c4, c5 = st.columns(3)
    users = ["Semua Pengguna"] + sorted(df["user"].dropna().unique().tolist())
    acts  = ["Semua Tipe"] + sorted(df["action"].dropna().unique().tolist())
    u_sel = c3.selectbox("Filter Pengguna", users)
    a_sel = c4.selectbox("Filter Tipe Aksi", acts)
    q     = c5.text_input("Cari Nama Barang")

    view = df[(df["date_only"] >= start) & (df["date_only"] <= end)].copy()
    if u_sel != "Semua Pengguna":
        view = view[view["user"] == u_sel]
    if a_sel != "Semua Tipe":
        view = view[view["action"] == a_sel]
    if q:
        view = view[view["item"].str.contains(q, case=False, na=False)]
    show_cols = ["action","date","code","item","qty","unit","stock","trans_type","user","event","do_number","timestamp","Lampiran"]
    show_cols = [c for c in show_cols if c in view.columns]
    st.markdown(view[show_cols].to_html(escape=False, index=False), unsafe_allow_html=True)

def page_admin_export():
    st.markdown(f"## Filter dan Unduh Laporan - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    inv = DATA["inventory"]
    if not inv:
        st.info("Tidak ada data untuk diexport.")
        return
    df = pd.DataFrame([
        {"Kode": code, "Nama Barang": it["name"], "Qty": it["qty"], "Satuan": it.get("unit","-"), "Kategori": it.get("category","Uncategorized")}
        for code, it in inv.items()
    ])
    cats = ["Semua Kategori"] + sorted(df["Kategori"].unique())
    c1, c2 = st.columns(2)
    cat = c1.selectbox("Pilih Kategori", cats)
    q   = c2.text_input("Cari berdasarkan Nama atau Kode")
    view = df.copy()
    if cat != "Semua Kategori": view = view[view["Kategori"] == cat]
    if q:
        view = view[ view["Nama Barang"].str.contains(q, case=False) | view["Kode"].str.contains(q, case=False) ]
    st.markdown("### Preview Laporan")
    st.dataframe(view, use_container_width=True, hide_index=True)
    if not view.empty:
        data = dataframe_to_excel_bytes(view, "Stok Barang Filtered")
        st.download_button("Unduh Laporan Excel", data=data,
                           file_name=f"Laporan_Inventori_{st.session_state.current_brand.capitalize()}_Filter.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.warning("Tidak ada data yang cocok dengan filter.")

def page_admin_reset():
    st.markdown(f"## Reset Database - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    st.warning(f"Aksi ini akan menghapus inventory, pending, & history untuk brand **{st.session_state.current_brand.capitalize()}**.")
    confirm = st.text_input("Ketik RESET untuk konfirmasi")
    if st.button("Reset Database") and confirm == "RESET":
        reset_brand(st.session_state.current_brand)
        st.session_state.notification = {"type":"success","message": f"✅ Database untuk {st.session_state.current_brand.capitalize()} berhasil direset!"}
        st.rerun()


# -------------------- USER PAGES (same logic) --------------------
def page_user_dashboard():
    render_dashboard_pro(DATA, brand_label=st.session_state.current_brand.capitalize(), allow_download=True)

def page_user_stock_card():
    page_admin_stock_card()

def page_user_request_in():
    st.markdown(f"## Request Barang Masuk (Multi Item) - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    items = list(DATA["inventory"].values())
    if not items:
        st.info("Belum ada master barang. Hubungi admin.")
        return

    col1, col2 = st.columns(2)
    idx = col1.selectbox("Pilih Barang", range(len(items)),
                         format_func=lambda x: f"{items[x]['name']} ({items[x]['qty']} {items[x].get('unit','-')})")
    qty = col2.number_input("Jumlah", min_value=1, step=1)

    if st.button("Tambah Item IN"):
        st.session_state.req_in_items.append({
            "item": items[idx]["name"],
            "qty": qty,
            "unit": items[idx].get("unit","-"),
            "event": "-"
        })
        st.success("Item IN ditambahkan ke daftar.")

    if st.session_state.req_in_items:
        st.subheader("Daftar Item Request IN")
        if "in_select_flags" not in st.session_state or len(st.session_state.in_select_flags) != len(st.session_state.req_in_items):
            st.session_state.in_select_flags = [False]*len(st.session_state.req_in_items)

        cA, cB = st.columns([1,1])
        if cA.button("Pilih semua", key="in_sel_all"):
            st.session_state.in_select_flags = [True]*len(st.session_state.req_in_items)
        if cB.button("Kosongkan pilihan", key="in_sel_none"):
            st.session_state.in_select_flags = [False]*len(st.session_state.req_in_items)

        df_in = pd.DataFrame(st.session_state.req_in_items)
        df_in["Pilih"] = st.session_state.in_select_flags
        edited_df_in = st.data_editor(df_in, key="editor_in", use_container_width=True, hide_index=True)
        st.session_state.in_select_flags = edited_df_in["Pilih"].fillna(False).tolist()

        if st.button("Hapus Item Terpilih", key="delete_in"):
            mask = st.session_state.in_select_flags
            if any(mask):
                st.session_state.req_in_items = [rec for rec, keep in zip(st.session_state.req_in_items, [not x for x in mask]) if keep]
                st.session_state.in_select_flags = [False]*len(st.session_state.req_in_items)
                st.rerun()
            else:
                st.info("Tidak ada baris yang dipilih.")

        st.divider()
        st.subheader("Informasi Wajib")
        do_number = st.text_input("Nomor Surat Jalan (wajib)", placeholder="Masukkan Nomor DO")
        uploaded_file = st.file_uploader("Upload PDF Delivery Order / Surat Jalan (wajib)", type=["pdf"])

        if st.button("Ajukan Request IN Terpilih"):
            mask = st.session_state.in_select_flags
            if not any(mask):
                st.warning("Pilih setidaknya satu item untuk diajukan.")
            elif not do_number.strip():
                st.error("Nomor Surat Jalan wajib diisi.")
            elif not uploaded_file:
                st.error("PDF Surat Jalan wajib diupload.")
            else:
                # save attachment
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                ext = uploaded_file.name.split(".")[-1].lower()
                path = os.path.join(UPLOADS_DIR, f"{st.session_state.username}_{ts}.{ext}")
                with open(path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                brand = st.session_state.current_brand
                inv_by_name = {it["name"]: (code, it.get("unit","-")) for code, it in load_brand_data(brand)["inventory"].items()}
                to_insert = []
                submit_count = 0
                new_state, new_flags = [], []
                for selected, rec in zip(mask, st.session_state.req_in_items):
                    if selected:
                        name = rec["item"]
                        code, unit = inv_by_name.get(name, ("-", rec.get("unit","-")))
                        base = {
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "code": code, "item": name, "qty": int(rec["qty"]),
                            "unit": unit, "event": "-",
                            "trans_type": None, "do_number": do_number.strip(),
                            "attachment": path, "user": st.session_state.username,
                            "timestamp": ts_text()
                        }
                        norm = normalize_out_record(base)
                        norm["type"] = "IN"
                        to_insert.append(norm); submit_count += 1
                    else:
                        new_state.append(rec); new_flags.append(False)
                if to_insert:
                    pending_add_many(brand, to_insert)
                st.session_state.req_in_items = new_state
                st.session_state.in_select_flags = new_flags
                st.success(f"{submit_count} request IN diajukan & menunggu approval.")
                st.rerun()

def page_user_request_out():
    st.markdown(f"## Request Barang Keluar (Multi Item) - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    items = list(DATA["inventory"].values())
    if not items:
        st.info("Belum ada master barang.")
        return

    tab1, tab2 = st.tabs(["Input Manual", "Upload Excel"])

    with tab1:
        col1, col2 = st.columns(2)
        idx = col1.selectbox("Pilih Barang", range(len(items)),
                             format_func=lambda x: f"{items[x]['name']} (Stok: {items[x]['qty']} {items[x].get('unit','-')})")
        max_qty = int(pd.to_numeric(items[idx].get("qty",0), errors="coerce") or 0)
        if max_qty < 1:
            qty = 0
            col2.number_input("Jumlah", min_value=0, max_value=0, step=1, value=0, disabled=True)
            st.warning("Stok item ini 0. Tidak bisa menambah request OUT.")
        else:
            qty = col2.number_input("Jumlah", min_value=1, max_value=max_qty, step=1)

        tipe = st.selectbox("Tipe Transaksi (wajib)", TRANS_TYPES, index=0)
        event_manual = st.text_input("Nama Event (wajib)", placeholder="Misal: Pameran, Acara Kantor")

        if st.button("Tambah Item OUT (Manual)"):
            if max_qty < 1:
                st.error("Stok 0 — tidak bisa menambah OUT untuk item ini.")
            elif not event_manual.strip():
                st.error("Event wajib diisi.")
            elif qty < 1:
                st.error("Jumlah harus minimal 1.")
            else:
                selected_name = items[idx]["name"]
                brand = st.session_state.current_brand
                inv_map = load_brand_data(brand)["inventory"]
                found_code = next((c for c, it in inv_map.items() if it.get("name")==selected_name), None)
                base = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "code": found_code if found_code else "-",
                    "item": selected_name,
                    "qty": int(qty),
                    "unit": items[idx].get("unit","-"),
                    "event": event_manual.strip(),
                    "trans_type": tipe,
                    "user": st.session_state.username
                }
                st.session_state.req_out_items.append(normalize_out_record(base))
                st.success("Item OUT (manual) ditambahkan ke daftar.")

    with tab2:
        st.info("Format kolom: **Tanggal | Kode Barang | Nama Barang | Qty | Event | Tipe** (Tipe = Support atau Penjualan)")
        inv_records = [{"code": c, "name": it.get("name","-")} for c,it in DATA["inventory"].items()]
        st.download_button("📥 Unduh Template Excel OUT",
                           data=make_out_template_bytes(inv_records),
                           file_name=f"Template_OUT_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        fu = st.file_uploader("Upload File Excel OUT", type=["xlsx"], key="out_excel_uploader")
        if fu and st.button("Tambah dari Excel (OUT)"):
            try:
                df_new = pd.read_excel(fu, engine="openpyxl")
            except Exception as e:
                st.error(f"Gagal membaca file Excel: {e}")
                df_new = None
            req = ["Tanggal","Kode Barang","Nama Barang","Qty","Event","Tipe"]
            if df_new is not None:
                miss = [c for c in req if c not in df_new.columns]
                if miss:
                    st.error(f"Kolom kurang: {', '.join(miss)}")
                else:
                    errors, added = [], 0
                    brand = st.session_state.current_brand
                    inv = load_brand_data(brand)["inventory"]
                    by_code = {code: (it.get("name"), it.get("unit","-"), it.get("qty",0)) for code,it in inv.items()}
                    by_name = {it.get("name"): (code, it.get("unit","-"), it.get("qty",0)) for code,it in inv.items()}
                    for ridx, row in df_new.iterrows():
                        try:
                            dt = pd.to_datetime(row["Tanggal"], errors="coerce")
                            date_str = dt.strftime("%Y-%m-%d") if pd.notna(dt) else datetime.now().strftime("%Y-%m-%d")
                            code_x = str(row["Kode Barang"]).strip() if pd.notna(row["Kode Barang"]) else ""
                            name_x = str(row["Nama Barang"]).strip() if pd.notna(row["Nama Barang"]) else ""
                            qty_x  = int(pd.to_numeric(row["Qty"], errors="coerce") or 0)
                            event_x = str(row["Event"]).strip() if pd.notna(row["Event"]) else ""
                            tipe_x = str(row["Tipe"]).strip().lower() if pd.notna(row["Tipe"]) else ""
                            if not event_x:
                                errors.append(f"Baris {ridx+2}: Event wajib."); continue
                            if tipe_x not in ["support","penjualan"]:
                                errors.append(f"Baris {ridx+2}: Tipe harus Support/Penjualan."); continue
                            tipe_norm = "Support" if tipe_x=="support" else "Penjualan"
                            inv_name, inv_unit, inv_stock = (None,None,None); inv_code = None
                            if code_x and code_x in by_code:
                                inv_name, inv_unit, inv_stock = by_code[code_x]; inv_code = code_x
                            elif name_x and name_x in by_name:
                                inv_code, inv_unit, inv_stock = by_name[name_x]; inv_name = name_x
                            else:
                                errors.append(f"Baris {ridx+2}: Item tidak ditemukan."); continue
                            if qty_x <= 0:
                                errors.append(f"Baris {ridx+2}: Qty harus > 0."); continue
                            if inv_stock is not None and qty_x > inv_stock:
                                errors.append(f"Baris {ridx+2}: Qty ({qty_x}) > stok ({inv_stock}) untuk '{inv_name}'."); continue
                            base = {"date": date_str, "code": inv_code if inv_code else "-", "item": inv_name,
                                    "qty": qty_x, "unit": inv_unit if inv_unit else "-",
                                    "event": event_x, "trans_type": tipe_norm, "user": st.session_state.username}
                            st.session_state.req_out_items.append(normalize_out_record(base)); added += 1
                        except Exception as e:
                            errors.append(f"Baris {ridx+2}: {e}")
                    if added: st.success(f"{added} baris ditambahkan ke daftar OUT.")
                    if errors: st.warning("Beberapa baris dilewati:\n- " + "\n- ".join(errors))

    if st.session_state.req_out_items:
        st.subheader("Daftar Item Request OUT")
        df_out = pd.DataFrame(st.session_state.req_out_items)
        pref = [c for c in ["date","code","item","qty","unit","event","trans_type"] if c in df_out.columns]
        df_out = df_out[pref]
        if "out_select_flags" not in st.session_state or len(st.session_state.out_select_flags) != len(st.session_state.req_out_items):
            st.session_state.out_select_flags = [False]*len(st.session_state.req_out_items)

        c1, c2 = st.columns([1,1])
        if c1.button("Pilih semua", key="out_sel_all"): st.session_state.out_select_flags = [True]*len(st.session_state.req_out_items)
        if c2.button("Kosongkan pilihan", key="out_sel_none"): st.session_state.out_select_flags = [False]*len(st.session_state.req_out_items)

        df_out["Pilih"] = st.session_state.out_select_flags
        edited_df_out = st.data_editor(df_out, key="editor_out", use_container_width=True, hide_index=True)
        st.session_state.out_select_flags = edited_df_out["Pilih"].fillna(False).tolist()

        if st.button("Hapus Item Terpilih", key="delete_out"):
            mask = st.session_state.out_select_flags
            if any(mask):
                st.session_state.req_out_items = [rec for rec, keep in zip(st.session_state.req_out_items, [not x for x in mask]) if keep]
                st.session_state.out_select_flags = [False]*len(st.session_state.req_out_items)
                st.rerun()
            else:
                st.info("Tidak ada baris yang dipilih.")

        st.divider()
        if st.button("Ajukan Request OUT Terpilih"):
            mask = st.session_state.out_select_flags
            if not any(mask):
                st.warning("Pilih setidaknya satu item untuk diajukan.")
            else:
                brand = st.session_state.current_brand
                submitted, to_insert = 0, []
                new_state, new_flags = [], []
                for selected, rec in zip(mask, st.session_state.req_out_items):
                    if selected:
                        base = rec.copy(); base["user"] = st.session_state.username
                        norm = normalize_out_record(base); norm["type"] = "OUT"
                        to_insert.append(norm); submitted += 1
                    else:
                        new_state.append(rec); new_flags.append(False)
                if to_insert:
                    pending_add_many(brand, to_insert)
                st.session_state.req_out_items = new_state
                st.session_state.out_select_flags = new_flags
                st.success(f"{submitted} request OUT diajukan & menunggu approval.")
                st.rerun()

def page_user_request_return():
    st.markdown(f"## Request Retur (Pengembalian) - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    items = list(DATA["inventory"].values())
    if not items:
        st.info("Belum ada master barang.")
        return

    # map event OUT approved per item
    hist = DATA.get("history", [])
    approved_out_map = {}
    for h in hist:
        if h.get("action") == "APPROVE_OUT":
            it = h.get("item"); ev = h.get("event")
            if it and ev and ev not in ["-", None, ""]:
                approved_out_map.setdefault(it, set()).add(ev)

    tab1, tab2 = st.tabs(["Input Manual", "Upload Excel"])
    with tab1:
        col1, col2 = st.columns(2)
        idx = col1.selectbox("Pilih Barang", range(len(items)),
                             format_func=lambda x: f"{items[x]['name']} (Stok Gudang: {items[x]['qty']} {items[x].get('unit','-')})")
        qty = col2.number_input("Jumlah Retur", min_value=1, step=1)
        item_name = items[idx]["name"]; unit_name = items[idx].get("unit","-")
        approved_events = sorted(list(approved_out_map.get(item_name, set())))
        if not approved_events:
            st.warning("Belum ada event OUT yang di-approve untuk item ini.")
            event_choice = None
        else:
            event_choice = st.selectbox("Pilih Event (berdasarkan OUT yang disetujui)", approved_events)
        if st.button("Tambah Item Retur (Manual)"):
            if not event_choice:
                st.error("Pilih event terlebih dahulu.")
            else:
                brand = st.session_state.current_brand
                inv = load_brand_data(brand)["inventory"]
                code = next((c for c, it in inv.items() if it.get("name")==item_name), "-")
                base = {"date": datetime.now().strftime("%Y-%m-%d"),
                        "code": code, "item": item_name, "qty": int(qty), "unit": unit_name,
                        "event": event_choice, "user": st.session_state.username}
                st.session_state.req_ret_items.append(normalize_return_record(base))
                st.success("Item Retur ditambahkan ke daftar.")

    with tab2:
        st.info("Format: **Tanggal | Kode Barang | Nama Barang | Qty | Event**")
        inv_records = [{"code": c, "name": it.get("name","-")} for c,it in DATA["inventory"].items()]
        st.download_button("📥 Unduh Template Excel Retur",
                           data=make_return_template_bytes(inv_records),
                           file_name=f"Template_Retur_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu = st.file_uploader("Upload File Excel Retur", type=["xlsx"], key="ret_excel_uploader")
        if fu and st.button("Tambah dari Excel (Retur)"):
            try:
                df_new = pd.read_excel(fu, engine="openpyxl")
            except Exception as e:
                st.error(f"Gagal membaca file Excel: {e}")
                df_new = None
            req = ["Tanggal","Kode Barang","Nama Barang","Qty","Event"]
            if df_new is not None:
                miss = [c for c in req if c not in df_new.columns]
                if miss:
                    st.error(f"Kolom kurang: {', '.join(miss)}")
                else:
                    errors, added = [], 0
                    brand = st.session_state.current_brand
                    inv = load_brand_data(brand)["inventory"]
                    by_code = {code: (it.get("name"), it.get("unit","-")) for code,it in inv.items()}
                    by_name = {it.get("name"): (code, it.get("unit","-")) for code,it in inv.items()}
                    # approved event map (by item)
                    approved_out_map = {}
                    for h in load_brand_data(brand)["history"]:
                        if h.get("action") == "APPROVE_OUT":
                            it = h.get("item"); ev = h.get("event")
                            if it and ev and ev not in ["-", None, ""]:
                                approved_out_map.setdefault(it, set()).add(ev)
                    for ridx, row in df_new.iterrows():
                        try:
                            dt = pd.to_datetime(row["Tanggal"], errors="coerce")
                            date_str = dt.strftime("%Y-%m-%d") if pd.notna(dt) else datetime.now().strftime("%Y-%m-%d")
                            code_x = str(row["Kode Barang"]).strip() if pd.notna(row["Kode Barang"]) else ""
                            name_x = str(row["Nama Barang"]).strip() if pd.notna(row["Nama Barang"]) else ""
                            qty_x  = int(pd.to_numeric(row["Qty"], errors="coerce") or 0)
                            event_x = str(row["Event"]).strip() if pd.notna(row["Event"]) else ""
                            if qty_x <= 0: errors.append(f"Baris {ridx+2}: Qty harus > 0."); continue
                            if not event_x: errors.append(f"Baris {ridx+2}: Event wajib."); continue
                            inv_name, inv_unit = (None,None); inv_code=None
                            if code_x and code_x in by_code: inv_name, inv_unit = by_code[code_x]; inv_code = code_x
                            elif name_x and name_x in by_name: inv_code, inv_unit = by_name[name_x]; inv_name = name_x
                            else: errors.append(f"Baris {ridx+2}: Item tidak ditemukan."); continue
                            valid_events = approved_out_map.get(inv_name, set())
                            exists = any(e.strip().lower()==event_x.strip().lower() for e in valid_events)
                            if not exists:
                                if not valid_events:
                                    errors.append(f"Baris {ridx+2}: Belum ada event OUT yang di-approve untuk '{inv_name}'."); continue
                                else:
                                    errors.append(f"Baris {ridx+2}: Event '{event_x}' tidak cocok. Tersedia: {', '.join(sorted(valid_events))}."); continue
                            base = {"date": date_str, "code": inv_code if inv_code else "-",
                                    "item": inv_name, "qty": qty_x, "unit": inv_unit if inv_unit else "-",
                                    "event": next((e for e in valid_events if e.strip().lower()==event_x.strip().lower()), event_x),
                                    "user": st.session_state.username}
                            st.session_state.req_ret_items.append(normalize_return_record(base)); added += 1
                        except Exception as e:
                            errors.append(f"Baris {ridx+2}: {e}")
                    if added: st.success(f"{added} baris retur ditambahkan.")
                    if errors: st.warning("Beberapa baris gagal:\n- " + "\n- ".join(errors))

    if st.session_state.req_ret_items:
        st.subheader("Daftar Item Request Retur")
        if "ret_select_flags" not in st.session_state or len(st.session_state.ret_select_flags) != len(st.session_state.req_ret_items):
            st.session_state.ret_select_flags = [False]*len(st.session_state.req_ret_items)

        c1, c2 = st.columns([1,1])
        if c1.button("Pilih semua", key="ret_sel_all"): st.session_state.ret_select_flags = [True]*len(st.session_state.req_ret_items)
        if c2.button("Kosongkan pilihan", key="ret_sel_none"): st.session_state.ret_select_flags = [False]*len(st.session_state.req_ret_items)

        df_ret = pd.DataFrame(st.session_state.req_ret_items)
        pref = [c for c in ["date","code","item","qty","unit","event"] if c in df_ret.columns]
        df_ret = df_ret[pref]
        df_ret["Pilih"] = st.session_state.ret_select_flags
        edited_df_ret = st.data_editor(df_ret, key="editor_ret", use_container_width=True, hide_index=True)
        st.session_state.ret_select_flags = edited_df_ret["Pilih"].fillna(False).tolist()

        if st.button("Hapus Item Terpilih", key="delete_ret"):
            mask = st.session_state.ret_select_flags
            if any(mask):
                st.session_state.req_ret_items = [rec for rec, keep in zip(st.session_state.req_ret_items, [not x for x in mask]) if keep]
                st.session_state.ret_select_flags = [False]*len(st.session_state.req_ret_items)
                st.rerun()
            else:
                st.info("Tidak ada baris yang dipilih.")

        st.divider()
        if st.button("Ajukan Request Retur Terpilih"):
            mask = st.session_state.ret_select_flags
            if not any(mask):
                st.warning("Pilih setidaknya satu item untuk diajukan.")
            else:
                brand = st.session_state.current_brand
                to_insert = []
                for selected, rec in zip(mask, st.session_state.req_ret_items):
                    if selected:
                        base = rec.copy(); base["user"] = st.session_state.username
                        norm = normalize_return_record(base); norm["type"] = "RETURN"
                        to_insert.append(norm)
                if to_insert:
                    pending_add_many(brand, to_insert)
                st.session_state.req_ret_items = [rec for rec, keep in zip(st.session_state.req_ret_items, [not x for x in mask]) if keep]
                st.session_state.ret_select_flags = [False]*len(st.session_state.req_ret_items)
                st.success("Request RETUR diajukan & menunggu approval.")
                st.rerun()

def page_user_riwayat():
    # My history + pending status (similar)
    st.markdown(f"## Riwayat Saya (dengan Status) - Brand {st.session_state.current_brand.capitalize()}")
    st.divider()
    hist = DATA.get("history", [])
    rows = []
    for h in hist:
        if h.get("user") != st.session_state.username: continue
        act = str(h.get("action","")).upper()
        if act.startswith("APPROVE_"):
            status = "APPROVED"; ttype = act.split("_",1)[-1]
        elif act.startswith("REJECT_"):
            status = "REJECTED"; ttype = act.split("_",1)[-1]
        elif act.startswith("ADD_"):
            status = "-"; ttype = "ADD"
        else:
            status = "-"; ttype = "-"
        rows.append({
            "Status": status, "Type": ttype, "Date": h.get("date"), "Code": h.get("code","-"),
            "Item": h.get("item","-"), "Qty": h.get("qty","-"), "Unit": h.get("unit","-"),
            "Trans. Tipe": h.get("trans_type","-"), "Event": h.get("event","-"),
            "DO": h.get("do_number","-"), "Timestamp": h.get("timestamp","-")
        })
    pend = DATA.get("pending_requests", [])
    for p in pend:
        if p.get("user") != st.session_state.username: continue
        rows.append({
            "Status": "PENDING", "Type": p.get("type","-"), "Date": p.get("date"), "Code": p.get("code","-"),
            "Item": p.get("item","-"), "Qty": p.get("qty","-"), "Unit": p.get("unit","-"),
            "Trans. Tipe": p.get("trans_type","-"), "Event": p.get("event","-"),
            "DO": p.get("do_number","-"), "Timestamp": p.get("timestamp","-")
        })
    if rows:
        df = pd.DataFrame(rows)
        try:
            df["ts"] = pd.to_datetime(df["Timestamp"], errors="coerce")
            df = df.sort_values("ts", ascending=False).drop(columns=["ts"])
        except Exception:
            pass
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Anda belum memiliki riwayat transaksi.")


# -------------------- ROUTING --------------------
if role == "admin":
    menu = st.sidebar.radio("📌 Menu Admin", [
        "Dashboard", "Lihat Stok Barang", "Stock Card", "Tambah Master Barang",
        "Approve Request", "Riwayat Lengkap", "Export Laporan ke Excel", "Reset Database"
    ])
    if   menu == "Dashboard":                 page_admin_dashboard()
    elif menu == "Lihat Stok Barang":         page_admin_lihat_stok()
    elif menu == "Stock Card":                page_admin_stock_card()
    elif menu == "Tambah Master Barang":      page_admin_tambah_master()
    elif menu == "Approve Request":           page_admin_approve()
    elif menu == "Riwayat Lengkap":           page_admin_riwayat()
    elif menu == "Export Laporan ke Excel":   page_admin_export()
    elif menu == "Reset Database":            page_admin_reset()

else:  # user / approver -> follow "user" UX from your reference
    user_menu = st.sidebar.radio("📌 Menu User", [
        "Dashboard", "Stock Card", "Request Barang IN", "Request Barang OUT", "Request Retur", "Lihat Riwayat"
    ])
    if   user_menu == "Dashboard":          page_user_dashboard()
    elif user_menu == "Stock Card":         page_user_stock_card()
    elif user_menu == "Request Barang IN":  page_user_request_in()
    elif user_menu == "Request Barang OUT": page_user_request_out()
    elif user_menu == "Request Retur":      page_user_request_return()
    elif user_menu == "Lihat Riwayat":      page_user_riwayat()
