# app.py — Supabase Inventory (multi-brand) dengan UX Sidebar Accordion (collapsed default)
# - IN/OUT/RETURN: multi-item (manual + Excel), staging → Ajukan
# - Approve IN: auto-create item baru jika belum ada (menggunakan KODE yang user isi bila tersedia & unik)
# - Stock Card running balance (urut date->timestamp)
# - Riwayat: status PENDING/APPROVED/REJECTED
# - Sidebar baru (collapsed), tombol Refresh, Reset Database disembunyikan
# Prasyarat: tabel per brand (inventory_*, pending_*, history_*), users_gulavit
# Secrets: SUPABASE_URL, SUPABASE_KEY

import os
import base64
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client, Client

# -------------------- CONFIG --------------------
BANNER_URL = "https://media.licdn.com/dms/image/v2/D563DAQFDri8xlKNIvg/image-scale_191_1128/image-scale_191_1128/0/1678337293506/pesona_inti_rasa_cover?e=2147483647&v=beta&t=vHi0xtyAZsT9clHb0yBYPE8M9IaO2dNY6Cb_Vs3Ddlo"
ICON_URL   = "https://i.ibb.co/7C96T9y/favicon.png"
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

BRANDS = ["gulavit","takokak"]
TABLES = {
    "gulavit": {"inv":"inventory_gulavit","pend":"pending_gulavit","hist":"history_gulavit"},
    "takokak": {"inv":"inventory_takokak","pend":"pending_takokak","hist":"history_takokak"},
}
USERS_TABLE = "users_gulavit"

TRANS_TYPES = ["Support", "Penjualan"]
STD_REQ_COLS = ["date","code","item","qty","unit","event","trans_type","do_number","attachment","user","timestamp"]

st.set_page_config(page_title="Inventory System", page_icon=ICON_URL, layout="wide")

# streamlit forward-compat alias
try:
    if not hasattr(st, "experimental_rerun"):
        st.experimental_rerun = st.rerun
except Exception:
    pass

# -------------------- STYLE --------------------
st.markdown("""
<style>
:root { --sidebar-bg:#0f9aa9; --chip:#0EA5E9; }
.main { background-color: #F8FAFC; }
h1, h2, h3 { color: #0F172A; }
.kpi-card { background:#fff;border:1px solid #E2E8F0;border-radius:14px;padding:18px 18px 12px;box-shadow:0 1px 2px rgba(0,0,0,.04); }
.kpi-title { font-size:12px;color:#64748B;letter-spacing:.06em;text-transform:uppercase; }
.kpi-value { font-size:26px;font-weight:700;color:#16A34A;margin-top:6px; }
.kpi-sub { font-size:12px;color:#64748B;margin-top:2px; }
.stButton>button { background-color:#0EA5E9;color:#fff;border-radius:8px;height:2.6em;width:100%;border:none; }
.stButton>button:hover { background-color:#0284C7;color:#fff; }
.smallcap{ font-size:12px;color:#64748B; }
.card { background:#fff;border:1px solid #E2E8F0;border-radius:14px;padding:14px;box-shadow:0 1px 2px rgba(0,0,0,.04);height:100%; }
.badge { display:inline-block; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.badge.blue { background:#E0F2FE; color:#075985; }
</style>
""", unsafe_allow_html=True)

# Optional Altair
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
def ts_text(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _to_date_str(val):
    if val is None or str(val).strip()=="":
        return datetime.now().strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(val, errors="coerce").strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def _norm_event(s): return str(s).strip() if s is not None else "-"

def _norm_trans_type(s):
    s = "" if s is None else str(s).strip().lower()
    if s == "support": return "Support"
    if s == "penjualan": return "Penjualan"
    return None

def normalize_out_record(base: dict) -> dict:
    rec = {k: None for k in STD_REQ_COLS}
    rec.update({
        "date": _to_date_str(base.get("date")),
        "code": base.get("code","-") or "-",
        "item": base.get("item","-") or "-",
        "qty": int(pd.to_numeric(base.get("qty",0), errors="coerce") or 0),
        "unit": base.get("unit","-") or "-",
        "event": _norm_event(base.get("event","-")),
        "trans_type": _norm_trans_type(base.get("trans_type")),
        "do_number": base.get("do_number","-") or "-",
        "attachment": base.get("attachment"),
        "user": base.get("user", st.session_state.get("username","-")),
        "timestamp": base.get("timestamp", ts_text()),
    })
    return rec

def normalize_return_record(base: dict) -> dict:
    rec = {k: None for k in STD_REQ_COLS}
    rec.update({
        "date": _to_date_str(base.get("date")),
        "code": base.get("code","-") or "-",
        "item": base.get("item","-") or "-",
        "qty": int(pd.to_numeric(base.get("qty",0), errors="coerce") or 0),
        "unit": base.get("unit","-") or "-",
        "event": _norm_event(base.get("event","-")),
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
    bio.seek(0); return bio.read()

def make_master_template_bytes() -> bytes:
    cols = ["Kode Barang", "Nama Barang", "Qty", "Satuan", "Kategori"]
    df_tmpl = pd.DataFrame([{"Kode Barang":"ITM-0001","Nama Barang":"Contoh Produk","Qty":10,"Satuan":"PCS","Kategori":"Umum"}], columns=cols)
    return dataframe_to_excel_bytes(df_tmpl, "Template Master")

def make_out_template_bytes(inv_records: list) -> bytes:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cols = ["Tanggal","Kode Barang","Nama Barang","Qty","Event","Tipe"]
    rows=[]
    if inv_records:
        for r in inv_records[:2]:
            rows.append({"Tanggal":today,"Kode Barang":r["code"],"Nama Barang":r["name"],"Qty":1,"Event":"Contoh event","Tipe":"Support"})
    else:
        rows.append({"Tanggal":today,"Kode Barang":"ITM-0001","Nama Barang":"Contoh Produk","Qty":1,"Event":"Contoh event","Tipe":"Support"})
    return dataframe_to_excel_bytes(pd.DataFrame(rows, columns=cols), "Template OUT")

def make_in_template_bytes(inv_records: list) -> bytes:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cols = ["Tanggal","Kode Barang","Nama Barang","Qty","Unit (opsional)","Event (opsional)"]
    rows=[]
    if inv_records:
        for r in inv_records[:2]:
            rows.append({"Tanggal":today,"Kode Barang":r["code"],"Nama Barang":r["name"],"Qty":5,"Unit (opsional)":"PCS","Event (opsional)":""})
    else:
        rows.append({"Tanggal":today,"Kode Barang":"ITM-0001","Nama Barang":"Contoh Produk","Qty":10,"Unit (opsional)":"PCS","Event (opsional)":""})
    return dataframe_to_excel_bytes(pd.DataFrame(rows, columns=cols), "Template IN")

def make_return_template_bytes(inv_records: list) -> bytes:
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cols = ["Tanggal","Kode Barang","Nama Barang","Qty","Event"]
    rows=[]
    if inv_records:
        for r in inv_records[:2]:
            rows.append({"Tanggal":today,"Kode Barang":r["code"],"Nama Barang":r["name"],"Qty":1,"Event":"Contoh event dari OUT"})
    else:
        rows.append({"Tanggal":today,"Kode Barang":"ITM-0001","Nama Barang":"Contoh Produk","Qty":1,"Event":"Contoh event"})
    return dataframe_to_excel_bytes(pd.DataFrame(rows, columns=cols), "Template Retur")

# -------------------- READS --------------------
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
                "admin":{"password":st.secrets.get("passwords",{}).get("admin","admin"),"role":"admin"},
                "user":{"password":st.secrets.get("passwords",{}).get("user","user"),"role":"user"},
            }
        return users
    except Exception:
        return {
            "admin":{"password":st.secrets.get("passwords",{}).get("admin","admin"),"role":"admin"},
            "user":{"password":st.secrets.get("passwords",{}).get("user","user"),"role":"user"},
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
    df_inv  = _safe_select(t["inv"])
    df_pend = _safe_select(t["pend"])
    df_hist = _safe_select(t["hist"])

    inv = {}
    if not df_inv.empty:
        for _, r in df_inv.iterrows():
            inv[str(r.get("code","-"))] = {
                "name": str(r.get("item","-")),
                "qty": int(pd.to_numeric(r.get("qty",0), errors="coerce") or 0),
                "unit": str(r.get("unit","-")) if pd.notna(r.get("unit")) else "-",
                "category": str(r.get("category","Uncategorized")) if pd.notna(r.get("category")) else "Uncategorized",
            }

    pend=[]
    if not df_pend.empty:
        for _, r in df_pend.iterrows():
            base = {k: r.get(k) for k in STD_REQ_COLS}
            base.update({"type": r.get("type"), "id": r.get("id")})
            rec = normalize_return_record(base) if base["type"]=="RETURN" else normalize_out_record(base)
            rec["type"]=base["type"]; rec["id"]=base["id"]
            pend.append(rec)

    hist = df_hist.to_dict(orient="records") if not df_hist.empty else []
    return {"users": _load_users(), "inventory": inv, "pending_requests": pend, "history": hist}

def invalidate_cache(): st.cache_data.clear()

# -------------------- WRITES --------------------
def inv_insert_raw(brand, payload: dict):
    t = TABLES[brand]
    supabase.from_(t["inv"]).insert(payload).execute()
    invalidate_cache()

def inv_update_qty(brand, code, new_qty):
    t = TABLES[brand]
    supabase.from_(t["inv"]).update({"qty": int(new_qty)}).eq("code", code).execute()
    invalidate_cache()

def pending_add_many(brand, records: list):
    if not records: return
    t = TABLES[brand]
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
    df = pd.DataFrame(data.get("history", []))
    if df.empty: return df
    df["qty"] = pd.to_numeric(df.get("qty",0), errors="coerce").fillna(0).astype(int)
    s_date = pd.to_datetime(df["date"], errors="coerce") if "date" in df.columns else pd.Series(pd.NaT, index=df.index)
    s_ts   = pd.to_datetime(df["timestamp"], errors="coerce") if "timestamp" in df.columns else pd.Series(pd.NaT, index=df.index)
    df["date_eff"] = s_date.fillna(s_ts).dt.floor("D")
    act = df.get("action","").astype(str).str.upper()
    df["type_norm"]="-"
    df.loc[act.str.contains("APPROVE_IN"),"type_norm"]="IN"
    df.loc[act.str.contains("APPROVE_OUT"),"type_norm"]="OUT"
    df.loc[act.str.contains("APPROVE_RETURN"),"type_norm"]="RETURN"
    for c in ["item","event","trans_type","unit"]:
        if c not in df.columns: df[c]=None
    df["event"]=df["event"].fillna("-").astype(str)
    df["trans_type"]=df["trans_type"].fillna("-").astype(str)
    df = df[df["type_norm"].isin(["IN","OUT","RETURN"])].copy()
    df = df.dropna(subset=["date_eff"])
    return df

def _kpi_card(title, value, sub=None):
    st.markdown(f"""<div class="kpi-card"><div class="kpi-title">{title}</div>
                    <div class="kpi-value">{value}</div>
                    <div class="kpi-sub">{sub or ""}</div></div>""", unsafe_allow_html=True)

def render_dashboard_pro(data: dict, brand_label: str, allow_download=True):
    try:
        df_hist = _prepare_history_df(data)
        inv_records = [{"Kode":c,"Nama Barang":it.get("name","-"),"Current Stock":int(it.get("qty",0)),"Unit":it.get("unit","-")}
                       for c,it in data.get("inventory",{}).items()]
        df_inv = pd.DataFrame(inv_records)
        st.markdown(f"## Dashboard — {brand_label}")
        st.caption("Metrik berbasis qty. *Sales* = OUT tipe **Penjualan**.")
        st.divider()

        today = pd.Timestamp.today().normalize()
        default_start = (today - pd.DateOffset(months=11)).replace(day=1)
        F1, F2 = st.columns(2)
        start_date = F1.date_input("Tanggal mulai", value=default_start.date())
        end_date   = F2.date_input("Tanggal akhir", value=today.date())

        if not df_hist.empty:
            mask = (df_hist["date_eff"]>=pd.Timestamp(start_date))&(df_hist["date_eff"]<=pd.Timestamp(end_date))
            df_range=df_hist.loc[mask].copy()
        else:
            df_range=pd.DataFrame(columns=["date_eff","type_norm","qty","item","event","trans_type"])

        total_sku = int(len(df_inv)) if not df_inv.empty else 0
        total_qty = int(df_inv["Current Stock"].sum()) if not df_inv.empty else 0
        tot_in  = int(df_range.loc[df_range["type_norm"]=="IN","qty"].sum()) if not df_range.empty else 0
        tot_out = int(df_range.loc[df_range["type_norm"]=="OUT","qty"].sum()) if not df_range.empty else 0
        tot_ret = int(df_range.loc[df_range["type_norm"]=="RETURN","qty"].sum()) if not df_range.empty else 0

        c1,c2,c3,c4 = st.columns(4)
        _kpi_card("Total SKU", f"{total_sku:,}", f"Brand {brand_label}")
        _kpi_card("Total Qty (Stock)", f"{total_qty:,}", f"Per {pd.Timestamp(end_date).strftime('%d %b %Y')}")
        _kpi_card("Total IN (periode)", f"{tot_in:,}")
        _kpi_card("Total OUT / Retur", f"{tot_out:,} / {tot_ret:,}")

        st.divider()

        def month_agg(df, tipe):
            d = df[df["type_norm"]==tipe].copy()
            if d.empty: return pd.DataFrame({"month":[], "qty":[], "Periode":[], "idx":[]})
            d["month"]=d["date_eff"].dt.to_period("M").dt.to_timestamp()
            g=d.groupby("month", as_index=False)["qty"].sum().sort_values("month")
            g["Periode"]=g["month"].dt.strftime("%b %Y")
            g["idx"]=g["month"].dt.year.astype(int)*12+g["month"].dt.month.astype(int)
            return g

        g_in, g_out, g_ret = month_agg(df_range,"IN"), month_agg(df_range,"OUT"), month_agg(df_range,"RETURN")

        def _month_bar(container, dfm, title, color="#0EA5E9"):
            with container:
                st.markdown(f'<div class="card"><div class="smallcap">{title}</div>', unsafe_allow_html=True)
                if _ALT_OK and not dfm.empty:
                    chart=(alt.Chart(dfm).mark_bar(size=28)
                           .encode(x=alt.X("Periode:O", sort=alt.SortField(field="idx", order="ascending"), title="Periode"),
                                   y=alt.Y("qty:Q", title="Qty"),
                                   tooltip=[alt.Tooltip("month:T", title="Periode", format="%b %Y"), "qty:Q"],
                                   color=alt.value(color)).properties(height=320))
                    st.altair_chart(chart, use_container_width=True)
                else:
                    if dfm.empty: st.info("Belum ada data.")
                    else: st.bar_chart(dfm.set_index("Periode")["qty"])
                st.markdown("</div>", unsafe_allow_html=True)

        A,B,C = st.columns(3)
        _month_bar(A, g_in,  "IN per Month",    "#22C55E")
        _month_bar(B, g_out, "OUT per Month",   "#EF4444")
        _month_bar(C, g_ret, "RETUR per Month", "#0EA5E9")

        st.divider()

        t1,t2 = st.columns([1,1])
        with t1:
            st.markdown('<div class="card"><div class="smallcap">Top 10 Items (Current Stock)</div>', unsafe_allow_html=True)
            if _ALT_OK and not df_inv.empty:
                top10=df_inv.sort_values("Current Stock", ascending=False).head(10)
                chart=(alt.Chart(top10).mark_bar(size=22)
                       .encode(y=alt.Y("Nama Barang:N", sort="-x", title=None),
                               x=alt.X("Current Stock:Q", title="Qty"),
                               tooltip=["Nama Barang","Current Stock"]).properties(height=360))
                st.altair_chart(chart, use_container_width=True)
            else:
                st.dataframe(df_inv.sort_values("Current Stock", ascending=False).head(10), use_container_width=True, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with t2:
            st.markdown('<div class="card"><div class="smallcap">Top 5 Event by OUT Qty</div>', unsafe_allow_html=True)
            df_ev=df_range[(df_range["type_norm"]=="OUT") & (df_range["event"].notna())].copy()
            df_ev=df_ev[df_ev["event"].astype(str).str.trim().ne("-")]
            if "event" not in df_ev.columns: df_ev["event"]="-"
            ev_top=(df_ev.groupby("event", as_index=False)["qty"].sum().sort_values("qty", ascending=False).head(5))
            if _ALT_OK and not ev_top.empty:
                chart=(alt.Chart(ev_top).mark_bar(size=22)
                       .encode(y=alt.Y("event:N", sort="-x", title="Event"),
                               x=alt.X("qty:Q", title="Qty"),
                               tooltip=["event","qty"]).properties(height=360))
                st.altair_chart(chart, use_container_width=True)
            else:
                if ev_top.empty: st.info("Belum ada OUT pada rentang ini.")
                else: st.dataframe(ev_top.rename(columns={"event":"Event","qty":"Qty"}), use_container_width=True, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()

        st.subheader("Reorder Insight (berdasarkan OUT 3 bulan terakhir)")
        st.caption("Days of Cover = stok saat ini / rata-rata OUT harian (3 bulan).")
        tgt_days = st.slider("Target Days of Cover", min_value=30, max_value=120, step=15, value=60)

        if df_inv.empty:
            st.info("Inventory kosong."); 
            return
        ref_end = pd.Timestamp(end_date)
        last3_start = (ref_end - pd.DateOffset(months=3)).normalize() + pd.Timedelta(days=1)
        out3 = df_hist[(df_hist["type_norm"]=="OUT") & (df_hist["date_eff"]>=last3_start) & (df_hist["date_eff"]<=ref_end)]
        out3_item = out3.groupby("item")["qty"].sum().to_dict()

        rows=[]
        for _, r in df_inv.iterrows():
            name=r["Nama Barang"]; stock=int(r["Current Stock"]); unit=r.get("Unit","-")
            last3=int(out3_item.get(name,0)); avg_m=last3/3.0; avg_daily=(avg_m/30.0) if avg_m>0 else 0.0
            doc = (stock/avg_daily) if avg_daily>0 else float("inf")
            if doc==float("inf"): reco,urg="OK (tidak ada pemakaian)",5
            elif doc<15: reco,urg="Order NOW (Urgent)",1
            elif doc<30: reco,urg="Order bulan ini",2
            elif doc<60: reco,urg="Order bulan depan",3
            elif doc<90: reco,urg="Order 2 bulan lagi",4
            else: reco,urg="OK (stok aman)",5
            target_qty=int(max(0,(avg_daily*tgt_days)-stock)) if avg_daily>0 else 0
            rows.append({"Nama Barang":name,"Unit":unit,"Current Stock":stock,"OUT 3 Bulan":last3,
                         "Avg OUT / Bulan":round(avg_m,1),"Days of Cover":("∞" if doc==float("inf") else int(round(doc))),
                         "Rekomendasi":reco,"Saran Order (Qty)":target_qty,"_urgency":urg})
        df_reorder=pd.DataFrame(rows).sort_values(["_urgency","Days of Cover"], ascending=[True, True]).drop(columns=["_urgency"])
        st.dataframe(df_reorder, use_container_width=True, hide_index=True)
        if allow_download and not df_reorder.empty:
            data = dataframe_to_excel_bytes(df_reorder, "Reorder Insight")
            st.download_button("Unduh Excel Reorder Insight", data=data,
                               file_name=f"Reorder_{brand_label.replace(' ','_')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        st.error(f"Dashboard error: {e}")

# -------------------- SESSION --------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in=False
    st.session_state.username=""
    st.session_state.role=""
    st.session_state.current_brand="gulavit"

for k in ["req_in_items","req_out_items","req_ret_items",
          "in_select_flags","out_select_flags","ret_select_flags"]:
    if k not in st.session_state:
        st.session_state[k]=[] if "flags" not in k else []

if "notification" not in st.session_state: st.session_state.notification=None
if "menu" not in st.session_state: st.session_state.menu = "Dashboard"

# -------------------- LOGIN --------------------
if not st.session_state.logged_in:
    st.image(BANNER_URL, use_container_width=True)
    st.markdown("<div style='text-align:center;'><h1 style='margin-top:10px;'>Inventory Management System</h1></div>", unsafe_allow_html=True)
    st.subheader("Silakan Login untuk Mengakses Sistem")
    username = st.text_input("Username", placeholder="Masukkan username")
    password = st.text_input("Password", type="password", placeholder="Masukkan password")
    if st.button("Login"):
        users=_load_users(); user=users.get(username)
        if user and user["password"]==password:
            st.session_state.logged_in=True
            st.session_state.username=username
            st.session_state.role=user["role"]
            st.success(f"Login berhasil sebagai {user['role'].upper()}")
            st.rerun()
        else:
            st.error("❌ Username atau password salah.")
    st.stop()

role = st.session_state.role

# -------------------- TOP TOOLBAR --------------------
def global_toolbar():
    st.image(BANNER_URL, use_container_width=True)
    c1, c2, c3 = st.columns([1.2, 2, 1])
    with c1:
        brand_sel = st.selectbox(
            "Brand", BRANDS,
            index=BRANDS.index(st.session_state.current_brand),
            key="toolbar_brand"
        )
        if brand_sel != st.session_state.current_brand:
            st.session_state.current_brand = brand_sel
            st.rerun()
    with c2:
        st.text_input("Cari Kode/Nama/Event…", key="global_search", placeholder="Cari cepat…")
    with c3:
        st.markdown(
            f"<div style='text-align:right;margin-top:6px;'>"
            f"<span class='badge blue'>{st.session_state.role.title()}</span>&nbsp;"
            f"{st.session_state.current_brand.capitalize()}</div>",
            unsafe_allow_html=True
        )
    st.divider()

global_toolbar()
DATA = load_brand_data(st.session_state.current_brand)

# -------------------- NOTIF --------------------
if st.session_state.notification:
    nt=st.session_state.notification
    (st.success if nt["type"]=="success" else st.warning if nt["type"]=="warning" else st.error)(nt["message"])
    st.session_state.notification=None

# -------------------- ADMIN PAGES (dari script lama) --------------------
def page_admin_dashboard(): render_dashboard_pro(DATA, st.session_state.current_brand.capitalize(), allow_download=False)

def page_admin_lihat_stok():
    st.markdown(f"## Stok Barang - {st.session_state.current_brand.capitalize()}"); st.divider()
    inv = DATA["inventory"]
    if not inv: st.info("Belum ada barang."); return
    df = pd.DataFrame([{"Kode":c,"Nama Barang":it["name"],"Qty":it["qty"],"Satuan":it.get("unit","-"),"Kategori":it.get("category","Uncategorized")}
                       for c,it in inv.items()])
    cats=["Semua Kategori"]+sorted(df["Kategori"].dropna().unique().tolist())
    c1,c2 = st.columns(2)
    cat=c1.selectbox("Pilih Kategori", cats)
    q=c2.text_input("Cari Nama/Kode")
    view=df.copy()
    if cat!="Semua Kategori": view=view[view["Kategori"]==cat]
    if q: view=view[ view["Nama Barang"].str.contains(q, case=False) | view["Kode"].str.contains(q, case=False) ]
    st.dataframe(view, use_container_width=True, hide_index=True)

def page_admin_stock_card():
    st.markdown(f"## Stock Card - {st.session_state.current_brand.capitalize()}"); st.divider()
    hist=DATA["history"]
    if not hist: st.info("Belum ada riwayat."); return
    item_names=sorted({it["name"] for it in DATA["inventory"].values()})
    if not item_names: st.info("Belum ada master barang."); return
    sel = st.selectbox("Pilih Barang", item_names)
    if not sel: return
    filtered=[h for h in hist if h.get("item")==sel and (str(h.get("action","")).startswith("APPROVE") or str(h.get("action","")).startswith("ADD"))]
    if not filtered: st.info("Belum ada transaksi disetujui untuk barang ini."); return
    df=pd.DataFrame(filtered)
    df["date_eff"]=pd.to_datetime(df["date"], errors="coerce")
    df["ts"]=pd.to_datetime(df["timestamp"], errors="coerce")
    df["sort_key"]=df["date_eff"].fillna(df["ts"])
    df=df.sort_values(["sort_key","ts"]).reset_index(drop=True)
    rows=[]; saldo=0
    for _,h in df.iterrows():
        act=str(h.get("action","")).upper()
        qty=int(pd.to_numeric(h.get("qty",0), errors="coerce") or 0)
        t_in=t_out="-"; ket="N/A"
        if act=="ADD_ITEM":
            t_in=qty; saldo+=qty; ket="Initial Stock"
        elif act=="APPROVE_IN":
            t_in=qty; saldo+=qty
            do=h.get("do_number","-"); ket=f"Request IN by {h.get('user','-')}" + (f" (DO: {do})" if do and do!='- ' else "")
        elif act=="APPROVE_OUT":
            t_out=qty; saldo-=qty
            ket=f"Request OUT ({h.get('trans_type','-')}) by {h.get('user','-')} — Event: {h.get('event','-')}"
        elif act=="APPROVE_RETURN":
            t_in=qty; saldo+=qty
            ket=f"Retur by {h.get('user','-')} — Event: {h.get('event','-')}"
        rows.append({"Tanggal": h.get("date", h.get("timestamp","")), "Keterangan":ket,
                     "Masuk (IN)": t_in if t_in!="-" else "-", "Keluar (OUT)": t_out if t_out!="-" else "-", "Saldo Akhir": saldo})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def page_admin_tambah_master():
    st.markdown(f"## Tambah Master Barang - {st.session_state.current_brand.capitalize()}"); st.divider()
    tab1, tab2 = st.tabs(["Input Manual","Upload Excel"])
    with tab1:
        code=st.text_input("Kode Barang (unik & wajib)", placeholder="ITM-0001")
        name=st.text_input("Nama Barang")
        unit=st.text_input("Satuan (PCS/BOX/LITER)", value="PCS")
        qty=st.number_input("Jumlah Stok Awal", min_value=0, step=1)
        cat=st.text_input("Kategori", placeholder="Umum/Minuman/Makanan", value="Umum")
        if st.button("Tambah Barang Manual"):
            inv=DATA["inventory"]
            if not code.strip(): st.error("Kode wajib."); return
            if code in inv: st.error(f"Kode '{code}' sudah ada."); return
            if not name.strip(): st.error("Nama barang wajib."); return
            inv_insert_raw(st.session_state.current_brand, {"code":code.strip(),"item":name.strip(),"qty":int(qty),
                                                            "unit":unit.strip() or "-","category":cat.strip() or "Uncategorized"})
            history_add(st.session_state.current_brand, {"action":"ADD_ITEM","item":name.strip(),"qty":int(qty),"stock":int(qty),
                                                         "unit":unit.strip() or "-","user":st.session_state.username,"event":"-",
                                                         "timestamp":ts_text(),"date":datetime.now().strftime("%Y-%m-%d"),
                                                         "code":code.strip(),"trans_type":None,"do_number":"-","attachment":None})
            st.success(f"Barang '{name}' ditambahkan.")
            st.experimental_rerun()
    with tab2:
        st.info("Format: **Kode Barang | Nama Barang | Qty | Satuan | Kategori**")
        st.download_button("📥 Unduh Template Master Excel", data=make_master_template_bytes(),
                           file_name=f"Template_Master_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu=st.file_uploader("Upload File Excel Master", type=["xlsx"])
        if fu and st.button("Tambah dari Excel (Master)"):
            try:
                df_new=pd.read_excel(fu, engine="openpyxl")
                req=["Kode Barang","Nama Barang","Qty","Satuan","Kategori"]
                miss=[c for c in req if c not in df_new.columns]
                if miss: st.error(f"Kolom kurang: {', '.join(miss)}"); return
                added, errors = 0, []
                existing=set(DATA["inventory"].keys())
                for i,r in df_new.iterrows():
                    code=str(r["Kode Barang"]).strip() if pd.notna(r["Kode Barang"]) else ""
                    name=str(r["Nama Barang"]).strip() if pd.notna(r["Nama Barang"]) else ""
                    if not code or not name: errors.append(f"Baris {i+2}: Kode/Nama wajib."); continue
                    if code in existing: errors.append(f"Baris {i+2}: Kode '{code}' sudah ada."); continue
                    qty=int(pd.to_numeric(r["Qty"], errors="coerce") or 0)
                    unit=str(r["Satuan"]).strip() if pd.notna(r["Satuan"]) else "-"
                    cat=str(r["Kategori"]).strip() if pd.notna(r["Kategori"]) else "Uncategorized"
                    inv_insert_raw(st.session_state.current_brand, {"code":code,"item":name,"qty":qty,"unit":unit,"category":cat})
                    history_add(st.session_state.current_brand, {"action":"ADD_ITEM","item":name,"qty":qty,"stock":qty,"unit":unit,
                                                                 "user":st.session_state.username,"event":"-","timestamp":ts_text(),
                                                                 "date":datetime.now().strftime("%Y-%m-%d"),
                                                                 "code":code,"trans_type":None,"do_number":"-","attachment":None})
                    added+=1
                if added: st.success(f"{added} item master ditambahkan.")
                if errors: st.warning("Beberapa baris dilewati:\n- " + "\n- ".join(errors))
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Gagal membaca Excel: {e}")

def page_admin_approve():
    st.markdown(f"## Approve / Reject Request - {st.session_state.current_brand.capitalize()}"); st.divider()
    pend=DATA["pending_requests"]
    if not pend: st.info("Tidak ada pending request."); return
    df=pd.DataFrame(pend)
    df["Lampiran"]=df["attachment"].apply(lambda x: "Ada" if x else "Tidak Ada")

    if "approve_select_flags" not in st.session_state or len(st.session_state.approve_select_flags)!=len(df):
        st.session_state.approve_select_flags=[False]*len(df)

    csel1,csel2=st.columns([1,1])
    if csel1.button("Pilih semua"): st.session_state.approve_select_flags=[True]*len(df)
    if csel2.button("Kosongkan pilihan"): st.session_state.approve_select_flags=[False]*len(df)

    df["Pilih"]=st.session_state.approve_select_flags
    cfg={"Pilih": st.column_config.CheckboxColumn("Pilih", default=False)}
    for c in df.columns:
        if c!="Pilih": cfg[c]=st.column_config.TextColumn(c, disabled=True)
    edited=st.data_editor(df, key="editor_admin_approve", use_container_width=True, hide_index=True, column_config=cfg)
    st.session_state.approve_select_flags=edited["Pilih"].fillna(False).tolist()
    selected_idx=[i for i,v in enumerate(st.session_state.approve_select_flags) if v]

    col1,col2=st.columns(2)
    if col1.button("Approve Selected"):
        if not selected_idx:
            st.session_state.notification={"type":"warning","message":"Pilih setidaknya satu item."}; st.rerun()
        brand=st.session_state.current_brand
        t=TABLES[brand]
        inv_map = load_brand_data(brand)["inventory"]  # fresh
        approved_ids=[]
        for i in selected_idx:
            req=pend[i]
            qty=int(pd.to_numeric(req["qty"], errors="coerce") or 0)
            ttype=str(req["type"]).upper()

            # cari by name
            found_code=None
            for code,it in inv_map.items():
                if it.get("name")==req["item"]:
                    found_code=code; break

            # IN: buat item baru kalau tidak ada. Jika user isi code & unik → pakai code tsb.
            if ttype=="IN" and found_code is None:
                req_code = (req.get("code") or "").strip()
                req_name = req.get("item")
                if req_code and req_code not in inv_map and req_code!="-":
                    inv_insert_raw(brand, {"code":req_code, "item":req_name, "qty":0,
                                           "unit":req.get("unit","-"), "category":"Uncategorized"})
                    inv_map[req_code]={"name":req_name,"qty":0,"unit":req.get("unit","-"),"category":"Uncategorized"}
                    found_code=req_code
                else:
                    # fallback auto
                    code_candidate = f"NEW-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    inv_insert_raw(brand, {"code":code_candidate, "item":req_name, "qty":0,
                                           "unit":req.get("unit","-"), "category":"Uncategorized"})
                    inv_map[code_candidate]={"name":req_name,"qty":0,"unit":req.get("unit","-"),"category":"Uncategorized"}
                    found_code=code_candidate

            if found_code is None:
                st.warning(f"Item '{req['item']}' tidak ditemukan; lewati.")
                continue

            cur=int(inv_map[found_code]["qty"])
            if ttype=="IN":      new_qty=cur+qty
            elif ttype=="OUT":   new_qty=cur-qty
            elif ttype=="RETURN":new_qty=cur+qty
            else:
                st.warning(f"Tipe tidak dikenali: {ttype}"); continue

            inv_update_qty(brand, found_code, new_qty)
            inv_map[found_code]["qty"]=new_qty

            history_add(brand, {"action":f"APPROVE_{ttype}","item":req["item"],"qty":qty,"stock":new_qty,
                                "unit":req.get("unit","-"),"user":req.get("user", st.session_state.username),
                                "event":req.get("event","-"),"do_number":req.get("do_number","-"),
                                "attachment":req.get("attachment"),"timestamp":ts_text(),"date":req.get("date"),
                                "code":found_code,"trans_type":req.get("trans_type")})
            approved_ids.append(req.get("id"))

        if approved_ids:
            pending_delete_by_ids(brand, approved_ids)
            st.session_state.notification={"type":"success","message":f"{len(approved_ids)} request di-approve."}
        else:
            st.session_state.notification={"type":"warning","message":"Tidak ada request valid yang diproses."}
        st.rerun()

    if col2.button("Reject Selected"):
        if not selected_idx:
            st.session_state.notification={"type":"warning","message":"Pilih setidaknya satu item."}; st.rerun()
        brand=st.session_state.current_brand
        rejected_ids=[]
        for i in selected_idx:
            req=pend[i]
            history_add(brand, {"action":f"REJECT_{str(req.get('type','-')).upper()}","item":req.get("item","-"),
                                "qty":int(pd.to_numeric(req.get("qty",0), errors="coerce") or 0),
                                "stock":None,"unit":req.get("unit","-"),"user":req.get("user", st.session_state.username),
                                "event":req.get("event","-"),"do_number":req.get("do_number","-"),
                                "attachment":req.get("attachment"),"timestamp":ts_text(),
                                "date":req.get("date"),"code":req.get("code"),"trans_type":req.get("trans_type")})
            rejected_ids.append(req.get("id"))
        if rejected_ids:
            pending_delete_by_ids(brand, rejected_ids)
            st.session_state.notification={"type":"success","message":f"{len(rejected_ids)} request di-reject."}
        st.rerun()

def page_admin_riwayat():
    st.markdown(f"## Riwayat Lengkap - {st.session_state.current_brand.capitalize()}"); st.divider()
    hist=DATA["history"]
    if not hist: st.info("Belum ada riwayat."); return
    keys=["action","item","qty","stock","unit","user","event","do_number","attachment","timestamp","date","code","trans_type"]
    rows=[]
    for h in hist:
        e={k:h.get(k) for k in keys}
        for k, d in [("do_number","-"),("event","-"),("unit","-")]:
            if e.get(k) is None: e[k]=d
        rows.append(e)
    df=pd.DataFrame(rows)
    df["date_only"]=pd.to_datetime(df["date"].fillna(df["timestamp"]), errors="coerce").dt.date

    def dl(path):
        if path and os.path.exists(str(path)):
            with open(path,"rb") as f: b=base64.b64encode(f.read()).decode()
            name=os.path.basename(path)
            return f'<a href="data:application/pdf;base64,{b}" download="{name}">Unduh</a>'
        return "Tidak Ada"
    df["Lampiran"]=df["attachment"].apply(dl)

    c1,c2=st.columns(2)
    start=c1.date_input("Tanggal Mulai", value=df["date_only"].min())
    end  =c2.date_input("Tanggal Akhir", value=df["date_only"].max())
    c3,c4,c5=st.columns(3)
    users=["Semua Pengguna"]+sorted(df["user"].dropna().unique().tolist())
    acts=["Semua Tipe"]+sorted(df["action"].dropna().unique().tolist())
    u=c3.selectbox("Filter Pengguna", users)
    a=c4.selectbox("Filter Tipe Aksi", acts)
    q=c5.text_input("Cari Nama Barang")

    view=df[(df["date_only"]>=start)&(df["date_only"]<=end)].copy()
    if u!="Semua Pengguna": view=view[view["user"]==u]
    if a!="Semua Tipe": view=view[view["action"]==a]
    if q: view=view[view["item"].str.contains(q, case=False, na=False)]
    cols=["action","date","code","item","qty","unit","stock","trans_type","user","event","do_number","timestamp","Lampiran"]
    cols=[c for c in cols if c in view.columns]
    st.markdown(view[cols].to_html(escape=False, index=False), unsafe_allow_html=True)

def page_admin_export():
    st.markdown(f"## Export Laporan - {st.session_state.current_brand.capitalize()}"); st.divider()
    inv=DATA["inventory"]
    if not inv: st.info("Tidak ada data."); return
    df=pd.DataFrame([{"Kode":c,"Nama Barang":it["name"],"Qty":it["qty"],"Satuan":it.get("unit","-"),"Kategori":it.get("category","Uncategorized")}
                     for c,it in inv.items()])
    cats=["Semua Kategori"]+sorted(df["Kategori"].unique())
    c1,c2=st.columns(2)
    cat=c1.selectbox("Pilih Kategori", cats)
    q=c2.text_input("Cari Nama/Kode")
    view=df.copy()
    if cat!="Semua Kategori": view=view[view["Kategori"]==cat]
    if q: view=view[view["Nama Barang"].str.contains(q, case=False)|view["Kode"].str.contains(q, case=False)]
    st.markdown("### Preview")
    st.dataframe(view, use_container_width=True, hide_index=True)
    if not view.empty:
        data=dataframe_to_excel_bytes(view, "Stok Barang Filtered")
        st.download_button("Unduh Laporan Excel", data=data,
                           file_name=f"Laporan_Inventori_{st.session_state.current_brand.capitalize()}_Filter.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.warning("Tidak ada data sesuai filter.")

# -------------------- USER PAGES (dari script lama) --------------------
def _existing_events_for_out(brand: str) -> list:
    data = load_brand_data(brand)
    events=set()
    for h in data.get("history", []):
        if str(h.get("action","")).upper()=="APPROVE_OUT":
            ev=str(h.get("event","-")).strip()
            if ev and ev!="-": events.add(ev)
    for p in data.get("pending_requests", []):
        if str(p.get("type","")).upper()=="OUT":
            ev=str(p.get("event","-")).strip()
            if ev and ev!="-": events.add(ev)
    return sorted(events)

def _ensure_flags(flag_key, target_len):
    cur = st.session_state.get(flag_key, [])
    if len(cur)!=target_len:
        st.session_state[flag_key] = [False]*target_len

def _render_staged_table(df, flag_key, editor_key):
    _ensure_flags(flag_key, len(df))
    df = df.copy()
    df["Pilih"] = st.session_state[flag_key]
    cfg = {"Pilih": st.column_config.CheckboxColumn("Pilih", default=False)}
    for c in df.columns:
        if c!="Pilih": cfg[c]=st.column_config.TextColumn(c, disabled=True)
    edited = st.data_editor(df, key=editor_key, use_container_width=True, hide_index=True, column_config=cfg)
    st.session_state[flag_key] = edited["Pilih"].fillna(False).tolist()
    return [i for i,v in enumerate(st.session_state[flag_key]) if v]

def page_user_dashboard(): render_dashboard_pro(DATA, st.session_state.current_brand.capitalize(), allow_download=True)
def page_user_stock_card(): page_admin_stock_card()

# ---------- IN: MULTI-ITEM (manual + excel) ----------
def page_user_request_in():
    st.markdown(f"## Request Barang IN (Multi-item) - {st.session_state.current_brand.capitalize()}"); st.divider()
    items=list(DATA["inventory"].values())
    tab1, tab2 = st.tabs(["Tambah Manual","Tambah dari Excel"])

    with tab1:
        mode = st.radio("Sumber Item", ["Pilih dari Inventory", "Tambah Item Baru"])
        if mode=="Pilih dari Inventory":
            if not items:
                st.info("Inventory kosong. Gunakan 'Tambah Item Baru'.")
            else:
                c1,c2 = st.columns(2)
                idx=c1.selectbox("Pilih Barang", range(len(items)),
                                 format_func=lambda x: f"{items[x]['name']} (Stok: {items[x]['qty']} {items[x].get('unit','-')})")
                qty=c2.number_input("Jumlah", min_value=1, step=1)
                if st.button("Tambah ke Daftar IN (Existing)"):
                    brand=st.session_state.current_brand
                    inv_by_name={it["name"]:(code,it.get("unit","-")) for code,it in load_brand_data(brand)["inventory"].items()}
                    name=items[idx]["name"]; code,unit=inv_by_name.get(name, ("-", items[idx].get("unit","-")))
                    base={"date": datetime.now().strftime("%Y-%m-%d"), "code":code, "item":name, "qty":int(qty),
                          "unit":unit, "event":"-", "trans_type":None, "do_number":"-", "attachment":None,
                          "user": st.session_state.username, "timestamp": ts_text()}
                    st.session_state.req_in_items.append(normalize_out_record(base))
                    st.success("Ditambahkan ke daftar IN.")
        else:
            c1,c2 = st.columns(2)
            code_new = c1.text_input("Kode Barang (opsional)")
            name_new = c2.text_input("Nama Barang (wajib)")
            unit_new = st.text_input("Satuan (mis: PCS/BOX/LITER)", value="PCS")
            qty=st.number_input("Jumlah", min_value=1, step=1, key="in_new_qty")
            if st.button("Tambah ke Daftar IN (Item Baru)"):
                if not name_new.strip(): st.error("Nama wajib."); return
                base={"date": datetime.now().strftime("%Y-%m-%d"),
                      "code": (code_new.strip() if code_new.strip() else "-"),
                      "item": name_new.strip(), "qty": int(qty),
                      "unit": unit_new.strip() or "-", "event":"-", "trans_type":None,
                      "do_number":"-", "attachment":None,
                      "user": st.session_state.username, "timestamp": ts_text()}
                st.session_state.req_in_items.append(normalize_out_record(base))
                st.success("Ditambahkan ke daftar IN.")

    with tab2:
        st.info("Format Excel: **Tanggal | Kode Barang | Nama Barang | Qty | Unit (opsional) | Event (opsional)**")
        inv_records=[{"code":c,"name":it.get("name","-")} for c,it in DATA["inventory"].items()]
        st.download_button("📥 Unduh Template Excel IN",
                           data=make_in_template_bytes(inv_records),
                           file_name=f"Template_IN_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu=st.file_uploader("Upload File Excel IN", type=["xlsx"], key="in_excel_uploader")
        if fu and st.button("Tambah dari Excel → Daftar IN"):
            try:
                df_new=pd.read_excel(fu, engine="openpyxl")
            except Exception as e:
                st.error(f"Gagal membaca Excel: {e}"); return
            req_cols=["Tanggal","Kode Barang","Nama Barang","Qty"]
            miss=[c for c in req_cols if c not in df_new.columns]
            if miss: st.error(f"Kolom berikut wajib: {', '.join(req_cols)}"); return
            brand=st.session_state.current_brand
            inv = load_brand_data(brand)["inventory"]
            by_code={code:(it.get("name"), it.get("unit","-")) for code,it in inv.items()}
            by_name={it.get("name"):(code, it.get("unit","-")) for code,it in inv.items()}
            added, errors = 0, []
            for ridx,row in df_new.iterrows():
                try:
                    dt=pd.to_datetime(row["Tanggal"], errors="coerce")
                    date_str=dt.strftime("%Y-%m-%d") if pd.notna(dt) else datetime.now().strftime("%Y-%m-%d")
                    code_x=str(row["Kode Barang"]).strip() if pd.notna(row["Kode Barang"]) else ""
                    name_x=str(row["Nama Barang"]).strip() if pd.notna(row["Nama Barang"]) else ""
                    qty_x=int(pd.to_numeric(row["Qty"], errors="coerce") or 0)
                    unit_x=str(row["Unit (opsional)"]).strip() if "Unit (opsional)" in df_new.columns and pd.notna(row.get("Unit (opsional)")) else None
                    event_x=str(row["Event (opsional)"]).strip() if "Event (opsional)" in df_new.columns and pd.notna(row.get("Event (opsional)")) else "-"
                    if not name_x: errors.append(f"Baris {ridx+2}: Nama wajib."); continue
                    if qty_x<=0: errors.append(f"Baris {ridx+2}: Qty harus > 0."); continue
                    inv_name, inv_unit = (None, None); inv_code=None
                    if code_x and code_x in by_code:
                        inv_name, inv_unit = by_code[code_x]; inv_code=code_x
                        if not unit_x: unit_x = inv_unit
                    elif name_x and name_x in by_name:
                        inv_code, inv_unit = by_name[name_x]; inv_name = name_x
                        if not unit_x: unit_x = inv_unit
                    base={"date": date_str, "code": (inv_code if inv_code else (code_x if code_x else "-")),
                          "item": (inv_name if inv_name else name_x), "qty": qty_x, "unit": (unit_x if unit_x else "-"),
                          "event": (event_x if event_x else "-"), "trans_type": None,
                          "do_number": "-", "attachment": None,
                          "user": st.session_state.username, "timestamp": ts_text()}
                    st.session_state.req_in_items.append(normalize_out_record(base))
                    added+=1
                except Exception as e:
                    errors.append(f"Baris {ridx+2}: {e}")
            if added: st.success(f"{added} baris ditambahkan ke daftar IN.")
            if errors: st.warning("Beberapa baris dilewati:\n- " + "\n- ".join(errors))

    if st.session_state.req_in_items:
        st.divider()
        st.subheader("Daftar Item Request IN (Staged)")
        df_in = pd.DataFrame(st.session_state.req_in_items)
        pref_cols=[c for c in ["date","code","item","qty","unit","event"] if c in df_in.columns]
        df_in=df_in[pref_cols]
        cA,cB = st.columns([1,1])
        if cA.button("Pilih semua", key="in_sel_all"): st.session_state.in_select_flags=[True]*len(df_in)
        if cB.button("Kosongkan pilihan", key="in_sel_none"): st.session_state.in_select_flags=[False]*len(df_in)
        selected_idx = _render_staged_table(df_in, "in_select_flags", "editor_in_staged")

        if st.button("Hapus Item Terpilih", key="delete_in"):
            if selected_idx:
                keep=[i for i in range(len(st.session_state.req_in_items)) if i not in selected_idx]
                st.session_state.req_in_items = [st.session_state.req_in_items[i] for i in keep]
                st.session_state.in_select_flags=[False]*len(st.session_state.req_in_items)
                st.rerun()
            else:
                st.info("Tidak ada baris dipilih.")

        st.markdown("#### Informasi Wajib untuk Ajukan (berlaku untuk baris terpilih)")
        c1,c2 = st.columns(2)
        do_number = c1.text_input("Nomor Surat Jalan (wajib)")
        pdf = c2.file_uploader("Upload PDF DO (wajib, 1 file untuk semua baris terpilih)", type=["pdf"], key="in_pdf_submit")

        if st.button("Ajukan Request IN Terpilih"):
            if not selected_idx:
                st.warning("Pilih setidaknya satu item."); return
            if not do_number.strip():
                st.error("Nomor DO wajib."); return
            if not pdf:
                st.error("PDF DO wajib."); return
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            path=os.path.join(UPLOADS_DIR, f"{st.session_state.username}_{ts}.pdf")
            with open(path,"wb") as f: f.write(pdf.getbuffer())

            to_insert=[]
            for i,rec in enumerate(st.session_state.req_in_items):
                if i in selected_idx:
                    r=rec.copy()
                    r["do_number"]=do_number.strip()
                    r["attachment"]=path
                    r["type"]="IN"
                    to_insert.append(r)
            if to_insert:
                pending_add_many(st.session_state.current_brand, to_insert)
                keep=[i for i in range(len(st.session_state.req_in_items)) if i not in selected_idx]
                st.session_state.req_in_items=[st.session_state.req_in_items[i] for i in keep]
                st.session_state.in_select_flags=[False]*len(st.session_state.req_in_items)
                st.success(f"{len(to_insert)} request IN diajukan & menunggu approval.")
                st.rerun()

# ---------- OUT ----------
def page_user_request_out():
    st.markdown(f"## Request Barang OUT (Multi-item) - {st.session_state.current_brand.capitalize()}"); st.divider()
    items=list(DATA["inventory"].values())
    if not items: st.info("Belum ada master barang."); return
    tab1, tab2 = st.tabs(["Tambah Manual","Tambah dari Excel"])

    with tab1:
        c1,c2 = st.columns(2)
        idx=c1.selectbox("Pilih Barang", range(len(items)),
                         format_func=lambda x: f"{items[x]['name']} (Stok: {items[x]['qty']} {items[x].get('unit','-')})")
        max_qty=int(pd.to_numeric(items[idx].get("qty",0), errors="coerce") or 0)
        if max_qty<1:
            c2.number_input("Jumlah", min_value=0, max_value=0, step=1, value=0, disabled=True)
            st.warning("Stok item ini 0. Tidak bisa request OUT.")
        else:
            qty=c2.number_input("Jumlah", min_value=1, max_value=max_qty, step=1)
        tipe=st.selectbox("Tipe Transaksi", TRANS_TYPES, index=0)

        existing_events = _existing_events_for_out(st.session_state.current_brand)
        use_new = st.checkbox("Tambah Event Baru?")
        if use_new:
            event_value = st.text_input("Nama Event Baru", placeholder="Masukkan nama event")
        else:
            if not existing_events:
                st.info("Belum ada event. Centang 'Tambah Event Baru?' untuk mengetik event.")
                event_value = st.text_input("Nama Event", placeholder="Masukkan nama event")
            else:
                event_value = st.selectbox("Pilih Event", existing_events)

        if st.button("Tambah ke Daftar OUT"):
            if max_qty<1: st.error("Stok 0."); return
            if not str(event_value).strip(): st.error("Event wajib."); return
            selected_name=items[idx]["name"]
            brand=st.session_state.current_brand
            inv_map=load_brand_data(brand)["inventory"]
            found_code=next((c for c,it in inv_map.items() if it.get("name")==selected_name), None)
            base={"date": datetime.now().strftime("%Y-%m-%d"), "code": found_code if found_code else "-",
                  "item": selected_name, "qty": int(qty), "unit": items[idx].get("unit","-"),
                  "event": str(event_value).strip(), "trans_type": tipe, "user": st.session_state.username}
            st.session_state.req_out_items.append(normalize_out_record(base))
            st.success("Ditambahkan ke daftar OUT.")

    with tab2:
        st.info("Format: **Tanggal | Kode Barang | Nama Barang | Qty | Event | Tipe**  (Tipe = Support/Penjualan)")
        inv_records=[{"code":c,"name":it.get("name","-")} for c,it in DATA["inventory"].items()]
        st.download_button("📥 Unduh Template Excel OUT",
                           data=make_out_template_bytes(inv_records),
                           file_name=f"Template_OUT_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu=st.file_uploader("Upload File Excel OUT", type=["xlsx"], key="out_excel_uploader")
        if fu and st.button("Tambah dari Excel → Daftar OUT"):
            try:
                df_new=pd.read_excel(fu, engine="openpyxl")
            except Exception as e:
                st.error(f"Gagal membaca Excel: {e}"); return
            req=["Tanggal","Kode Barang","Nama Barang","Qty","Event","Tipe"]
            miss=[c for c in req if c not in df_new.columns]
            if miss: st.error(f"Kolom kurang: {', '.join(miss)}"); return

            brand=st.session_state.current_brand
            inv=load_brand_data(brand)["inventory"]
            by_code={code:(it.get("name"), it.get("unit","-"), it.get("qty",0)) for code,it in inv.items()}
            by_name={it.get("name"):(code, it.get("unit","-"), it.get("qty",0)) for code,it in inv.items()}

            added, errors = 0, []
            for ridx,row in df_new.iterrows():
                try:
                    dt=pd.to_datetime(row["Tanggal"], errors="coerce")
                    date_str=dt.strftime("%Y-%m-%d") if pd.notna(dt) else datetime.now().strftime("%Y-%m-%d")
                    code_x=str(row["Kode Barang"]).strip() if pd.notna(row["Kode Barang"]) else ""
                    name_x=str(row["Nama Barang"]).strip() if pd.notna(row["Nama Barang"]) else ""
                    qty_x=int(pd.to_numeric(row["Qty"], errors="coerce") or 0)
                    event_x=str(row["Event"]).strip() if pd.notna(row["Event"]) else ""
                    tipe_x=str(row["Tipe"]).strip().lower() if pd.notna(row["Tipe"]) else ""
                    if not event_x: errors.append(f"Baris {ridx+2}: Event wajib."); continue
                    if tipe_x not in ["support","penjualan"]: errors.append(f"Baris {ridx+2}: Tipe harus Support/Penjualan."); continue
                    tipe_norm="Support" if tipe_x=="support" else "Penjualan"
                    inv_name, inv_unit, inv_stock=(None,None,None); inv_code=None
                    if code_x and code_x in by_code:
                        inv_name,inv_unit,inv_stock=by_code[code_x]; inv_code=code_x
                    elif name_x and name_x in by_name:
                        inv_code,inv_unit,inv_stock=by_name[name_x]; inv_name=name_x
                    else:
                        errors.append(f"Baris {ridx+2}: Item tidak ada di inventory (OUT hanya untuk existing)."); continue
                    if qty_x<=0: errors.append(f"Baris {ridx+2}: Qty harus > 0."); continue
                    if inv_stock is not None and qty_x>inv_stock: errors.append(f"Baris {ridx+2}: Qty ({qty_x}) > stok ({inv_stock})."); continue
                    base={"date": date_str, "code": inv_code, "item": inv_name, "qty": qty_x, "unit": inv_unit or "-",
                          "event": event_x, "trans_type": tipe_norm, "user": st.session_state.username}
                    st.session_state.req_out_items.append(normalize_out_record(base)); added+=1
                except Exception as e:
                    errors.append(f"Baris {ridx+2}: {e}")
            if added: st.success(f"{added} baris ditambahkan ke daftar OUT.")
            if errors: st.warning("Beberapa baris dilewati:\n- " + "\n- ".join(errors))

    if st.session_state.req_out_items:
        st.divider()
        st.subheader("Daftar Item Request OUT (Staged)")
        df_out=pd.DataFrame(st.session_state.req_out_items)
        pref_cols=[c for c in ["date","code","item","qty","unit","event","trans_type"] if c in df_out.columns]
        df_out=df_out[pref_cols]
        c1,c2=st.columns([1,1])
        if c1.button("Pilih semua", key="out_sel_all"): st.session_state.out_select_flags=[True]*len(df_out)
        if c2.button("Kosongkan pilihan", key="out_sel_none"): st.session_state.out_select_flags=[False]*len(df_out)
        selected_idx=_render_staged_table(df_out, "out_select_flags", "editor_out_staged")

        if st.button("Hapus Item Terpilih", key="delete_out"):
            if selected_idx:
                keep=[i for i in range(len(st.session_state.req_out_items)) if i not in selected_idx]
                st.session_state.req_out_items=[st.session_state.req_out_items[i] for i in keep]
                st.session_state.out_select_flags=[False]*len(st.session_state.req_out_items)
                st.rerun()
            else:
                st.info("Tidak ada baris dipilih.")

        if st.button("Ajukan Request OUT Terpilih"):
            if not selected_idx:
                st.warning("Pilih setidaknya satu item."); return
            to_insert=[]
            for i,rec in enumerate(st.session_state.req_out_items):
                if i in selected_idx:
                    r=rec.copy(); r["type"]="OUT"; to_insert.append(r)
            if to_insert:
                pending_add_many(st.session_state.current_brand, to_insert)
                keep=[i for i in range(len(st.session_state.req_out_items)) if i not in selected_idx]
                st.session_state.req_out_items=[st.session_state.req_out_items[i] for i in keep]
                st.session_state.out_select_flags=[False]*len(st.session_state.req_out_items)
                st.success(f"{len(to_insert)} request OUT diajukan & menunggu approval.")
                st.rerun()

# ---------- RETURN ----------
def page_user_request_return():
    st.markdown(f"## Request Retur (Multi-item) - {st.session_state.current_brand.capitalize()}"); st.divider()
    items=list(DATA["inventory"].values())
    if not items: st.info("Belum ada master barang."); return

    hist=DATA.get("history", [])
    approved_out_map={}
    for h in hist:
        if h.get("action")=="APPROVE_OUT":
            it=h.get("item"); ev=h.get("event")
            if it and ev and ev not in ["-",None,""]:
                approved_out_map.setdefault(it, set()).add(ev)

    tab1,tab2=st.tabs(["Tambah Manual","Tambah dari Excel"])
    with tab1:
        c1,c2=st.columns(2)
        idx=c1.selectbox("Pilih Barang", range(len(items)),
                         format_func=lambda x: f"{items[x]['name']} (Stok Gudang: {items[x]['qty']} {items[x].get('unit','-')})")
        qty=c2.number_input("Jumlah Retur", min_value=1, step=1)
        name=items[idx]["name"]; unit=items[idx].get("unit","-")
        events=sorted(list(approved_out_map.get(name,set())))
        if not events:
            st.warning("Belum ada event OUT disetujui untuk item ini."); ev_choice=None
        else:
            ev_choice=st.selectbox("Pilih Event (dari OUT yang disetujui)", events)
        if st.button("Tambah ke Daftar Retur"):
            if not ev_choice: st.error("Pilih event terlebih dahulu."); return
            brand=st.session_state.current_brand
            inv=load_brand_data(brand)["inventory"]
            code=next((c for c,it in inv.items() if it.get("name")==name), "-")
            base={"date": datetime.now().strftime("%Y-%m-%d"), "code": code, "item": name, "qty": int(qty),
                  "unit": unit, "event": ev_choice, "user": st.session_state.username}
            st.session_state.req_ret_items.append(normalize_return_record(base))
            st.success("Ditambahkan ke daftar Retur.")

    with tab2:
        st.info("Format: **Tanggal | Kode Barang | Nama Barang | Qty | Event**")
        inv_records=[{"code":c,"name":it.get("name","-")} for c,it in DATA["inventory"].items()]
        st.download_button("📥 Unduh Template Excel Retur",
                           data=make_return_template_bytes(inv_records),
                           file_name=f"Template_Retur_{st.session_state.current_brand.capitalize()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu=st.file_uploader("Upload File Excel Retur", type=["xlsx"], key="ret_excel_uploader")
        if fu and st.button("Tambah dari Excel → Daftar Retur"):
            try:
                df_new=pd.read_excel(fu, engine="openpyxl")
            except Exception as e:
                st.error(f"Gagal membaca Excel: {e}"); return
            req=["Tanggal","Kode Barang","Nama Barang","Qty","Event"]
            miss=[c for c in req if c not in df_new.columns]
            if miss: st.error(f"Kolom kurang: {', '.join(miss)}"); return

            brand=st.session_state.current_brand
            inv=load_brand_data(brand)["inventory"]
            by_code={code:(it.get("name"), it.get("unit","-")) for code,it in inv.items()}
            by_name={it.get("name"):(code, it.get("unit","-")) for code,it in inv.items()}

            approved_out_map={}
            for h in load_brand_data(brand)["history"]:
                if h.get("action")=="APPROVE_OUT":
                    it=h.get("item"); ev=h.get("event")
                    if it and ev and ev not in ["-",None,""]:
                        approved_out_map.setdefault(it, set()).add(ev)

            added, errors = 0, []
            for ridx,row in df_new.iterrows():
                try:
                    dt=pd.to_datetime(row["Tanggal"], errors="coerce")
                    date_str=dt.strftime("%Y-%m-%d") if pd.notna(dt) else datetime.now().strftime("%Y-%m-%d")
                    code_x=str(row["Kode Barang"]).strip() if pd.notna(row["Kode Barang"]) else ""
                    name_x=str(row["Nama Barang"]).strip() if pd.notna(row["Nama Barang"]) else ""
                    qty_x=int(pd.to_numeric(row["Qty"], errors="coerce") or 0)
                    event_x=str(row["Event"]).strip() if pd.notna(row["Event"]) else ""
                    if qty_x<=0: errors.append(f"Baris {ridx+2}: Qty harus > 0."); continue
                    if not event_x: errors.append(f"Baris {ridx+2}: Event wajib."); continue
                    inv_name,inv_unit=(None,None); inv_code=None
                    if code_x and code_x in by_code: inv_name,inv_unit=by_code[code_x]; inv_code=code_x
                    elif name_x and name_x in by_name: inv_code,inv_unit=by_name[name_x]; inv_name=name_x
                    else: errors.append(f"Baris {ridx+2}: Item tidak ditemukan."); continue
                    valid=approved_out_map.get(inv_name,set())
                    exists=any(e.strip().lower()==event_x.strip().lower() for e in valid)
                    if not exists:
                        if not valid: errors.append(f"Baris {ridx+2}: Belum ada OUT approved untuk '{inv_name}'."); continue
                        else: errors.append(f"Baris {ridx+2}: Event '{event_x}' tidak cocok. Tersedia: {', '.join(sorted(valid))}."); continue
                    base={"date": date_str, "code": inv_code if inv_code else "-", "item": inv_name,
                          "qty": qty_x, "unit": inv_unit if inv_unit else "-", "event": event_x,
                          "user": st.session_state.username}
                    st.session_state.req_ret_items.append(normalize_return_record(base)); added+=1
                except Exception as e:
                    errors.append(f"Baris {ridx+2}: {e}")
            if added: st.success(f"{added} baris ditambahkan ke daftar Retur.")
            if errors: st.warning("Beberapa baris gagal:\n- " + "\n- ".join(errors))

    if st.session_state.req_ret_items:
        st.divider()
        st.subheader("Daftar Item Request Retur (Staged)")
        df_ret=pd.DataFrame(st.session_state.req_ret_items)
        pref_cols=[c for c in ["date","code","item","qty","unit","event"] if c in df_ret.columns]
        df_ret=df_ret[pref_cols]
        r1,r2=st.columns([1,1])
        if r1.button("Pilih semua", key="ret_sel_all"): st.session_state.ret_select_flags=[True]*len(df_ret)
        if r2.button("Kosongkan pilihan", key="ret_sel_none"): st.session_state.ret_select_flags=[False]*len(df_ret)
        selected_idx=_render_staged_table(df_ret, "ret_select_flags", "editor_ret_staged")

        if st.button("Hapus Item Terpilih", key="delete_ret"):
            if selected_idx:
                keep=[i for i in range(len(st.session_state.req_ret_items)) if i not in selected_idx]
                st.session_state.req_ret_items=[st.session_state.req_ret_items[i] for i in keep]
                st.session_state.ret_select_flags=[False]*len(st.session_state.req_ret_items)
                st.rerun()
            else:
                st.info("Tidak ada baris dipilih.")

        if st.button("Ajukan Request Retur Terpilih"):
            if not selected_idx:
                st.warning("Pilih setidaknya satu item."); return
            to_insert=[]
            for i,rec in enumerate(st.session_state.req_ret_items):
                if i in selected_idx:
                    r=rec.copy(); r["type"]="RETURN"; to_insert.append(r)
            if to_insert:
                pending_add_many(st.session_state.current_brand, to_insert)
                keep=[i for i in range(len(st.session_state.req_ret_items)) if i not in selected_idx]
                st.session_state.req_ret_items=[st.session_state.req_ret_items[i] for i in keep]
                st.session_state.ret_select_flags=[False]*len(st.session_state.req_ret_items)
                st.success(f"{len(to_insert)} request RETUR diajukan & menunggu approval.")
                st.rerun()

def page_user_riwayat():
    st.markdown(f"## Riwayat Saya - {st.session_state.current_brand.capitalize()}"); st.divider()
    hist=DATA.get("history", [])
    rows=[]
    for h in hist:
        if h.get("user")!=st.session_state.username: continue
        act=str(h.get("action","")).upper()
        if act.startswith("APPROVE_"): status="APPROVED"; ttype=act.split("_",1)[-1]
        elif act.startswith("REJECT_"): status="REJECTED"; ttype=act.split("_",1)[-1]
        elif act.startswith("ADD_"): status="-"; ttype="ADD"
        else: status="-"; ttype="-"
        rows.append({"Status":status,"Type":ttype,"Date":h.get("date"),"Code":h.get("code","-"),
                     "Item":h.get("item","-"),"Qty":h.get("qty","-"),"Unit":h.get("unit","-"),
                     "Trans. Tipe":h.get("trans_type","-"),"Event":h.get("event","-"),
                     "DO":h.get("do_number","-"),"Timestamp":h.get("timestamp","-")})
    pend=DATA.get("pending_requests", [])
    for p in pend:
        if p.get("user")!=st.session_state.username: continue
        rows.append({"Status":"PENDING","Type":p.get("type","-"),"Date":p.get("date"),"Code":p.get("code","-"),
                    "Item":p.get("item","-"),"Qty":p.get("qty","-"),"Unit":p.get("unit","-"),
                    "Trans. Tipe":p.get("trans_type","-"),"Event":p.get("event","-"),
                    "DO":p.get("do_number","-"),"Timestamp":p.get("timestamp","-")})
    if rows:
        df=pd.DataFrame(rows)
        try:
            df["ts"]=pd.to_datetime(df["Timestamp"], errors="coerce")
            df=df.sort_values("ts", ascending=False).drop(columns=["ts"])
        except Exception: pass
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Anda belum memiliki riwayat transaksi.")

# -------------------- SIDEBAR (Accordion collapsed) --------------------
with st.sidebar:
    st.markdown(f"### 👋 Halo, {st.session_state.username}")
  

    if st.button("🔄 Refresh data", use_container_width=True):
        invalidate_cache()
        st.session_state.notification = {"type":"success","message":"Data di-refresh."}
        st.rerun()

    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in=False
        st.session_state.username=""
        st.session_state.role=""
        st.session_state.current_brand="gulavit"
        st.rerun()

    st.divider()

    # Dashboard (single)
    active = (st.session_state.menu == "Dashboard")
    if st.button(("📊 " if active else "") + "Dashboard",
                 type=("primary" if active else "secondary"),
                 use_container_width=True):
        st.session_state.menu = "Dashboard"; st.rerun()

    # Inventory
    def nav(label, icon=""):
        act = (st.session_state.menu == label)
        if st.button((icon+" " if icon else "") + label,
                     type=("primary" if act else "secondary"),
                     use_container_width=True):
            st.session_state.menu = label; st.rerun()

    with st.expander("📦 Inventory", expanded=False):
        nav("Lihat Stok Barang", "📦")
        nav("Stock Card", "🧾")
        if role != "admin":
            nav("Request Barang IN", "⬇️")
            nav("Request Barang OUT", "⬆️")
            nav("Request Retur", "↩️")
            nav("Lihat Riwayat", "🕘")

    if role == "admin":
        with st.expander("✅ Approval", expanded=False):
            nav("Approve Request", "✅")
            nav("Riwayat Lengkap", "📜")

    if role == "admin":
        with st.expander("🗂 Master", expanded=False):
            nav("Tambah Master Barang", "➕")
            # Reset Database disembunyikan

    with st.expander("📑 Report", expanded=False):
        nav("Export Laporan ke Excel", "📤")

# -------------------- ROUTER --------------------
def route(menu, role):
    if role == "admin":
        if   menu=="Dashboard":                page_admin_dashboard()
        elif menu=="Lihat Stok Barang":        page_admin_lihat_stok()
        elif menu=="Stock Card":               page_admin_stock_card()
        elif menu=="Tambah Master Barang":     page_admin_tambah_master()
        elif menu=="Approve Request":          page_admin_approve()
        elif menu=="Riwayat Lengkap":          page_admin_riwayat()
        elif menu=="Export Laporan ke Excel":  page_admin_export()
        else:                                  page_admin_dashboard()
    else:
        if   menu=="Dashboard":          page_user_dashboard()
        elif menu=="Stock Card":         page_user_stock_card()
        elif menu=="Request Barang IN":  page_user_request_in()
        elif menu=="Request Barang OUT": page_user_request_out()
        elif menu=="Request Retur":      page_user_request_return()
        elif menu=="Lihat Riwayat":      page_user_riwayat()
        elif menu=="Export Laporan ke Excel": page_admin_export()
        else: page_user_dashboard()

route(st.session_state.menu, role)
