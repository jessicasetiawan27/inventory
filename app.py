# app.py — Inventory app lengkap (Streamlit + Supabase)
# Fitur: Login (admin/approver/user), Dashboard, Lihat Stok, Stock Card,
# Tambah Master (manual + Excel), Request IN/OUT/RETURN, Approve/Reject,
# Riwayat & Export, Reset Pending/History
# Catatan: file upload (PDF DO) disimpan lokal (ephemeral) di Streamlit Cloud (untuk dev cepat).
#         Untuk produksi jangka panjang, sebaiknya pakai Supabase Storage (bisa ditambahkan belakangan).

import os
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ================== SETUP & HOTFIX ==================
st.set_page_config(page_title="Inventory System", page_icon="🧰", layout="wide")

# Hotfix agar kode lama 'st.experimental_rerun' jalan di Streamlit baru
try:
    if not hasattr(st, "experimental_rerun"):
        st.experimental_rerun = st.rerun
except Exception:
    pass

# Styling sederhana (mirip "before")
st.markdown("""
<style>
.main { background-color: #F8FAFC; }
h1, h2, h3 { color: #0F172A; }
.kpi-card {
  background: #ffffff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04); height:100%;
}
.kpi-title { font-size:12px; color:#64748B; letter-spacing:.06em; text-transform:uppercase; }
.kpi-value { font-size:24px; font-weight:700; color:#16A34A; margin-top:6px; }
.smallcap{ font-size:12px; color:#64748B; }
.card {
  background: #ffffff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04); height: 100%;
}
.stButton>button { background-color:#0EA5E9; color:white; border:none; border-radius:8px; }
.stButton>button:hover { background-color:#0284C7; }
</style>
""", unsafe_allow_html=True)

# Optional: Altair charts
try:
    import altair as alt
    _ALT = True
except Exception:
    _ALT = False

# ================== SUPABASE ==================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================== UTIL & CONSTANTS ==================
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

TRANS_TYPES = ["Support", "Penjualan"]  # untuk OUT

def now_iso():
    return datetime.now().isoformat()

def ts_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def to_int(x, default=0):
    try:
        v = int(pd.to_numeric(x, errors="coerce"))
        return v if pd.notna(v) else default
    except Exception:
        return default

def kpi(title, value, sub=None):
    st.markdown(f"""
    <div class="kpi-card">
      <div class="kpi-title">{title}</div>
      <div class="kpi-value">{value}</div>
      <div class="smallcap">{sub or ""}</div>
    </div>
    """, unsafe_allow_html=True)

def df_to_excel_bytes(df: pd.DataFrame, sheet="Sheet1") -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name=sheet)
    bio.seek(0)
    return bio.read()

# ================== LOADERS (CACHED) ==================
@st.cache_data(ttl=300)
def load_users_df():
    data = supabase.from_("users_gulavit").select("*").execute().data or []
    return pd.DataFrame(data)

@st.cache_data(ttl=300)
def load_inventory_df():
    data = supabase.from_("inventory_gulavit").select("*").execute().data or []
    df = pd.DataFrame(data)
    if df.empty:
        return df
    # Pastikan kolom standar
    for c in ["code", "item", "unit", "qty", "category"]:
        if c not in df.columns:
            df[c] = None
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0).astype(int)
    return df[["code", "item", "unit", "qty", "category"]]

@st.cache_data(ttl=180)
def load_pending_df():
    data = supabase.from_("pending_gulavit").select("*").execute().data or []
    return pd.DataFrame(data)

@st.cache_data(ttl=180)
def load_history_df():
    data = supabase.from_("history_gulavit").select("*").execute().data or []
    return pd.DataFrame(data)

def clear_cache():
    st.cache_data.clear()

# ================== WRITES ==================
def inv_insert(code, item, qty, unit="-", category="Uncategorized"):
    payload = {"code": code, "item": item, "qty": int(qty), "unit": unit or "-", "category": category or "Uncategorized"}
    supabase.from_("inventory_gulavit").insert(payload).execute()
    # history add item
    supabase.from_("history_gulavit").insert({
        "action": "ADD_ITEM",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "code": code, "item": item, "qty": int(qty), "stock": int(qty),
        "unit": unit or "-", "user": st.session_state.auth["username"],
        "event": "-", "timestamp": ts_text()
    }).execute()
    clear_cache()

def inv_update_qty(code, new_qty):
    supabase.from_("inventory_gulavit").update({"qty": int(new_qty)}).eq("code", code).execute()
    clear_cache()

def pending_add(rec: dict):
    supabase.from_("pending_gulavit").insert(rec).execute()
    clear_cache()

def pending_delete(id_: int):
    supabase.from_("pending_gulavit").delete().eq("id", id_).execute()
    clear_cache()

def history_add(rec: dict):
    supabase.from_("history_gulavit").insert(rec).execute()
    clear_cache()

# ================== SESSION & LOGIN ==================
if "auth" not in st.session_state:
    st.session_state.auth = {"ok": False, "username": "", "role": "user"}

def do_login(username, password):
    df_users = load_users_df()
    if df_users.empty:
        st.error("Tabel users_gulavit kosong. Jalankan SQL seed di Supabase.")
        return
    match = df_users[(df_users["username"] == username) & (df_users["password"] == password)]
    if not match.empty:
        role = match.iloc[0].get("role", "user")
        st.session_state.auth = {"ok": True, "username": username, "role": role}
        st.experimental_rerun()
    else:
        st.error("Username/password salah.")

def do_logout():
    st.session_state.auth = {"ok": False, "username": "", "role": "user"}
    st.experimental_rerun()

# ================== LOGIN UI ==================
if not st.session_state.auth["ok"]:
    st.title("Halaman Login Aplikasi Gudang Gulavit")
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        s = st.form_submit_button("Login")
    if s:
        do_login(u, p)
    st.stop()

# ================== LOAD ALL DATA ==================
df_inv = load_inventory_df()
df_pend = load_pending_df()
df_hist = load_history_df()

# ================== SIDEBAR ==================
st.sidebar.markdown(f"### 👋 {st.session_state.auth['username']}  \nRole: **{st.session_state.auth['role'].upper()}**")
if st.sidebar.button("🚪 Logout"):
    do_logout()
st.sidebar.divider()

role = st.session_state.auth["role"]

# ================== DASHBOARD ==================
def render_dashboard():
    st.markdown("## Dashboard")
    st.caption("Ringkasan cepat aktivitas & stok.")
    # KPI
    col1, col2, col3, col4 = st.columns(4)
    total_sku = int(len(df_inv)) if not df_inv.empty else 0
    total_qty = int(df_inv["qty"].sum()) if not df_inv.empty else 0
    total_pending = int(len(df_pend)) if not df_pend.empty else 0
    total_history = int(len(df_hist)) if not df_hist.empty else 0
    with col1: kpi("Total SKU", f"{total_sku:,}")
    with col2: kpi("Total Qty", f"{total_qty:,}")
    with col3: kpi("Pending", f"{total_pending:,}")
    with col4: kpi("Riwayat", f"{total_history:,}")

    st.divider()

    # Agregasi bulanan IN/OUT/RETURN (dari history)
    if df_hist.empty:
        st.info("Belum ada data riwayat.")
        return

    d = df_hist.copy()
    for c in ["action", "qty", "timestamp", "date"]:
        if c not in d.columns: d[c] = None
    d["qty"] = pd.to_numeric(d["qty"], errors="coerce").fillna(0).astype(int)

    # tanggal efektif: gunakan 'date' kalau ada, else dari 'timestamp'
    d["date_eff"] = pd.to_datetime(d["date"], errors="coerce")
    d["date_eff"] = d["date_eff"].fillna(pd.to_datetime(d["timestamp"], errors="coerce"))
    d = d.dropna(subset=["date_eff"]).copy()

    # type_norm dari action
    act = d["action"].astype(str).str.upper()
    d["type_norm"] = "-"
    d.loc[act.str.contains("ADD_ITEM"), "type_norm"] = "IN"
    d.loc[act.str.contains("APPROVE_IN"), "type_norm"] = "IN"
    d.loc[act.str.contains("APPROVE_OUT"), "type_norm"] = "OUT"
    d.loc[act.str.contains("APPROVE_RETURN"), "type_norm"] = "RETURN"
    d = d[d["type_norm"].isin(["IN", "OUT", "RETURN"])]

    def month_sum(df, tipe):
        x = df[df["type_norm"] == tipe].copy()
        if x.empty: 
            return pd.DataFrame({"Periode": [], "qty": [], "idx": []})
        x["month"] = x["date_eff"].dt.to_period("M").dt.to_timestamp()
        g = x.groupby("month", as_index=False)["qty"].sum().sort_values("month")
        g["Periode"] = g["month"].dt.strftime("%b %Y")
        g["idx"] = g["month"].dt.year.astype(int) * 12 + g["month"].dt.month.astype(int)
        return g[["Periode","qty","idx"]]

    g_in, g_out, g_ret = month_sum(d,"IN"), month_sum(d,"OUT"), month_sum(d,"RETURN")
    c1, c2, c3 = st.columns(3)

    def bar(container, dfm, title):
        with container:
            st.markdown(f'<div class="card"><div class="smallcap">{title}</div>', unsafe_allow_html=True)
            if _ALT and not dfm.empty:
                chart = alt.Chart(dfm).mark_bar(size=26).encode(
                    x=alt.X("Periode:O", sort=alt.SortField(field="idx", order="ascending")),
                    y=alt.Y("qty:Q", title="Qty"),
                    tooltip=["Periode","qty"]
                ).properties(height=280)
                st.altair_chart(chart, use_container_width=True)
            else:
                if dfm.empty: st.info("Belum ada data.") 
                else: st.bar_chart(dfm.set_index("Periode")["qty"])
            st.markdown("</div>", unsafe_allow_html=True)

    bar(c1, g_in,  "IN per Month")
    bar(c2, g_out, "OUT per Month")
    bar(c3, g_ret, "RETURN per Month")

# ================== LIHAT STOK ==================
def render_lihat_stok():
    st.markdown("## Lihat Stok Barang")
    if df_inv.empty:
        st.info("Belum ada data inventori.")
        return
    df = df_inv.rename(columns={"code":"Kode","item":"Nama Barang","unit":"Satuan","qty":"Qty","category":"Kategori"})
    col1, col2 = st.columns(2)
    kategori_list = ["Semua Kategori"] + sorted([x for x in df["Kategori"].dropna().unique()])
    kat = col1.selectbox("Filter Kategori", kategori_list)
    q = col2.text_input("Cari Nama/Kode")

    view = df.copy()
    if kat != "Semua Kategori":
        view = view[view["Kategori"] == kat]
    if q:
        view = view[ view["Nama Barang"].str.contains(q, case=False, na=False) | view["Kode"].str.contains(q, case=False, na=False) ]
    st.dataframe(view, use_container_width=True, hide_index=True)

# ================== STOCK CARD ==================
def render_stock_card():
    st.markdown("## Stock Card")
    if df_inv.empty:
        st.info("Belum ada master barang.")
        return
    items = sorted(df_inv["item"].dropna().unique().tolist())
    nama = st.selectbox("Pilih Barang", items)
    if not nama:
        return
    # ambil history terkait item
    h = df_hist.copy()
    if h.empty:
        st.info("Belum ada riwayat.")
        return
    h = h[h["item"] == nama].copy()
    h = h[h["action"].astype(str).str.upper().str.startswith(("ADD_ITEM", "APPROVE_"))]
    if h.empty:
        st.info("Belum ada transaksi disetujui untuk item ini.")
        return

    # urutkan waktu
    h["ts"] = pd.to_datetime(h["timestamp"], errors="coerce")
    h = h.sort_values("ts")
    saldo = 0
    rows = []
    for _, r in h.iterrows():
        act = str(r.get("action","")).upper()
        qty = to_int(r.get("qty"), 0)
        t_in = t_out = "-"
        ket = "N/A"
        if act == "ADD_ITEM":
            t_in = qty; saldo += qty; ket = "Initial Stock"
        elif act == "APPROVE_IN":
            t_in = qty; saldo += qty; 
            do = r.get("do_number","-"); ket = f"IN by {r.get('user','-')}" + (f" (DO: {do})" if do and do!='-' else "")
        elif act == "APPROVE_OUT":
            t_out = qty; saldo -= qty;
            ket = f"OUT ({r.get('trans_type','-')}) by {r.get('user','-')} — event: {r.get('event','-')}"
        elif act == "APPROVE_RETURN":
            t_in = qty; saldo += qty;
            ket = f"RETURN by {r.get('user','-')} — event: {r.get('event','-')}"
        rows.append({
            "Tanggal": r.get("date", r.get("timestamp","")),
            "Keterangan": ket,
            "Masuk (IN)": t_in, "Keluar (OUT)": t_out, "Saldo Akhir": saldo
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ================== TAMBAH MASTER BARANG ==================
def render_tambah_master():
    st.markdown("## Tambah Master Barang")
    tab1, tab2 = st.tabs(["Input Manual", "Upload Excel"])
    with tab1:
        code = st.text_input("Kode Barang (unik)", placeholder="ITM-0001")
        name = st.text_input("Nama Barang")
        unit = st.text_input("Satuan", placeholder="pcs/box/liter")
        qty  = st.number_input("Qty Awal", min_value=0, step=1)
        cat  = st.text_input("Kategori", placeholder="Umum/Minuman/Makanan...")
        if st.button("Tambah"):
            if not code.strip() or not name.strip():
                st.error("Kode & Nama wajib diisi.")
            elif (not df_inv.empty) and (code in df_inv["code"].tolist()):
                st.error(f"Kode '{code}' sudah ada.")
            else:
                inv_insert(code.strip(), name.strip(), int(qty), unit.strip() or "-", cat.strip() or "Uncategorized")
                st.success(f"Barang '{name}' ditambahkan.")
                st.experimental_rerun()
    with tab2:
        st.info("Format kolom Excel: Kode Barang | Nama Barang | Qty | Satuan | Kategori")
        tmpl = pd.DataFrame([{"Kode Barang":"ITM-0001","Nama Barang":"Contoh Produk","Qty":10,"Satuan":"pcs","Kategori":"Umum"}])
        data_xlsx = df_to_excel_bytes(tmpl, "Template Master")
        st.download_button("📥 Unduh Template", data=data_xlsx,
                           file_name="Template_Master.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        fu = st.file_uploader("Upload Excel Master", type=["xlsx"])
        if fu and st.button("Proses Upload"):
            try:
                df_new = pd.read_excel(fu, engine="openpyxl")
                req = ["Kode Barang","Nama Barang","Qty","Satuan","Kategori"]
                miss = [c for c in req if c not in df_new.columns]
                if miss:
                    st.error(f"Kolom kurang: {', '.join(miss)}"); return
                added = 0
                existing = set(df_inv["code"]) if not df_inv.empty else set()
                for i, r in df_new.iterrows():
                    code = str(r["Kode Barang"]).strip() if pd.notna(r["Kode Barang"]) else ""
                    name = str(r["Nama Barang"]).strip() if pd.notna(r["Nama Barang"]) else ""
                    if not code or not name: continue
                    if code in existing: continue
                    qty  = to_int(r["Qty"], 0)
                    unit = str(r["Satuan"]).strip() if pd.notna(r["Satuan"]) else "-"
                    cat  = str(r["Kategori"]).strip() if pd.notna(r["Kategori"]) else "Uncategorized"
                    inv_insert(code, name, qty, unit, cat)
                    added += 1
                st.success(f"Berhasil menambahkan {added} item.")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Gagal baca Excel: {e}")

# ================== REQUEST USER (IN/OUT/RETURN) ==================
def render_request_in():
    st.markdown("## Request Barang IN (Masuk)")

    mode = st.radio("Cara input item", ["Pilih dari master", "Input manual"], horizontal=True)

    if mode == "Pilih dari master":
        df = load_inventory_df()
        if df.empty:
            st.info("Belum ada master barang.")
            return
        items = df.to_dict(orient="records")
        c1, c2 = st.columns(2)
        idx = c1.selectbox(
            "Pilih Barang",
            range(len(items)),
            format_func=lambda i: f"{items[i]['item']} ({items[i]['qty']} {items[i]['unit']})"
        )
        qty = c2.number_input("Qty Masuk", min_value=1, step=1)
        do_number = st.text_input("Nomor Surat Jalan (wajib)")
        file_pdf = st.file_uploader("Upload PDF Surat Jalan (wajib)", type=["pdf"])

        if st.button("Ajukan Request IN"):
            if not do_number.strip():
                st.error("Nomor Surat Jalan wajib diisi."); return
            if not file_pdf:
                st.error("PDF Surat Jalan wajib diupload."); return
            # simpan file (ephemeral)
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            path = os.path.join(UPLOADS_DIR, f"DO_{st.session_state.auth['username']}_{ts}.pdf")
            with open(path, "wb") as f:
                f.write(file_pdf.getbuffer())

            rec = {
                "type": "IN",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "code": items[idx]["code"], "item": items[idx]["item"], "qty": int(qty),
                "unit": items[idx]["unit"], "trans_type": None, "event": "-",
                "do_number": do_number.strip(), "attachment": path,
                "user": st.session_state.auth["username"], "timestamp": ts_text()
            }
            pending_add(rec)
            st.success("Request IN diajukan, menunggu persetujuan.")
            st.experimental_rerun()

    else:  # Input manual
        c1, c2 = st.columns(2)
        code = c1.text_input("Kode Barang (baru/eksisting)", placeholder="ITM-0009")
        name = c2.text_input("Nama Barang", placeholder="Nama produk")
        c3, c4 = st.columns(2)
        unit = c3.text_input("Satuan", placeholder="pcs/box/liter", value="-")
        qty  = c4.number_input("Qty Masuk", min_value=1, step=1)
        do_number = st.text_input("Nomor Surat Jalan (wajib)")
        file_pdf  = st.file_uploader("Upload PDF Surat Jalan (wajib)", type=["pdf"])

        if st.button("Ajukan Request IN (Manual)"):
            if not code.strip() or not name.strip():
                st.error("Kode & Nama wajib diisi."); return
            if not do_number.strip():
                st.error("Nomor Surat Jalan wajib diisi."); return
            if not file_pdf:
                st.error("PDF Surat Jalan wajib diupload."); return

            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            path = os.path.join(UPLOADS_DIR, f"DO_{st.session_state.auth['username']}_{ts}.pdf")
            with open(path, "wb") as f:
                f.write(file_pdf.getbuffer())

            rec = {
                "type": "IN",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "code": code.strip(), "item": name.strip(), "qty": int(qty),
                "unit": unit.strip() or "-", "trans_type": None, "event": "-",
                "do_number": do_number.strip(), "attachment": path,
                "user": st.session_state.auth["username"], "timestamp": ts_text()
            }
            pending_add(rec)
            st.success("Request IN (manual) diajukan, menunggu persetujuan.")
            st.experimental_rerun()

def render_request_out():
    st.markdown("## Request Barang OUT (Keluar)")

    mode = st.radio("Cara input item", ["Pilih dari master", "Input manual"], horizontal=True)
    tipe = st.selectbox("Tipe Transaksi", TRANS_TYPES, index=0)
    event = st.text_input("Nama Event (wajib)")

    if mode == "Pilih dari master":
        df = load_inventory_df()
        if df.empty:
            st.info("Belum ada master barang.")
            return
        items = df.to_dict(orient="records")
        c1, c2 = st.columns(2)
        idx = c1.selectbox(
            "Pilih Barang",
            range(len(items)),
            format_func=lambda i: f"{items[i]['item']} (Stok: {items[i]['qty']} {items[i]['unit']})"
        )
        max_qty = int(items[idx]["qty"])
        qty = c2.number_input(
            "Qty Keluar",
            min_value=1,
            max_value=max_qty if max_qty > 0 else 1,
            step=1
        )

        if st.button("Ajukan Request OUT"):
            if not event.strip():
                st.error("Event wajib diisi."); return
            rec = {
                "type": "OUT",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "code": items[idx]["code"], "item": items[idx]["item"], "qty": int(qty),
                "unit": items[idx]["unit"], "trans_type": tipe, "event": event.strip(),
                "do_number": "-", "attachment": None,
                "user": st.session_state.auth["username"], "timestamp": ts_text()
            }
            pending_add(rec)
            st.success("Request OUT diajukan, menunggu persetujuan.")
            st.experimental_rerun()

    else:  # Input manual
        df = load_inventory_df()
        c1, c2 = st.columns(2)
        code = c1.text_input("Kode Barang (harus sudah terdaftar)", placeholder="ITM-0001")
        qty  = c2.number_input("Qty Keluar", min_value=1, step=1)

        if st.button("Ajukan Request OUT (Manual)"):
            if not event.strip():
                st.error("Event wajib diisi."); return
            if not code.strip():
                st.error("Kode barang wajib diisi."); return

            # cek keberadaan & stok
            if df.empty or code.strip() not in df["code"].tolist():
                st.error("Kode belum terdaftar di master. Tambahkan di 'Tambah Master' atau gunakan IN (manual) dulu.")
                return
            row = df[df["code"] == code.strip()].iloc[0]
            cur = int(row["qty"])
            if int(qty) > cur:
                st.error(f"Qty OUT melebihi stok tersedia ({cur})."); return

            rec = {
                "type": "OUT",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "code": code.strip(), "item": row["item"], "qty": int(qty),
                "unit": row.get("unit","-"), "trans_type": tipe, "event": event.strip(),
                "do_number": "-", "attachment": None,
                "user": st.session_state.auth["username"], "timestamp": ts_text()
            }
            pending_add(rec)
            st.success("Request OUT (manual) diajukan, menunggu persetujuan.")
            st.experimental_rerun()

def render_request_return():
    st.markdown("## Request Retur")
    if df_inv.empty:
        st.info("Belum ada master barang.")
        return
    items = df_inv.to_dict(orient="records")
    c1, c2 = st.columns(2)
    idx = c1.selectbox("Pilih Barang", range(len(items)),
                       format_func=lambda i: f"{items[i]['item']} (Stok: {items[i]['qty']} {items[i]['unit']})")
    qty = c2.number_input("Qty Retur", min_value=1, step=1)
    event = st.text_input("Keterangan Retur / Event")
    if st.button("Ajukan Request Retur"):
        rec = {
            "type": "RETURN",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "code": items[idx]["code"], "item": items[idx]["item"], "qty": int(qty),
            "unit": items[idx]["unit"], "trans_type": None, "event": event.strip() or "-",
            "do_number": "-", "attachment": None,
            "user": st.session_state.auth["username"], "timestamp": ts_text()
        }
        pending_add(rec)
        st.success("Request Retur diajukan, menunggu persetujuan.")
        st.experimental_rerun()

# ================== APPROVE (ADMIN/APPROVER) ==================
def render_approve():
    st.markdown("## Approve / Reject Request")
    if df_pend.empty:
        st.info("Tidak ada pending request.")
        return
    # pastikan kolom lengkap
    d = df_pend.copy()
    for c in ["id","type","date","code","item","qty","unit","trans_type","event","do_number","attachment","user","timestamp"]:
        if c not in d.columns: d[c] = None
    d["qty"] = pd.to_numeric(d["qty"], errors="coerce").fillna(0).astype(int)
    d = d.sort_values("timestamp", ascending=True)

    st.dataframe(d, use_container_width=True, hide_index=True)

    ids = d["id"].dropna().tolist() if "id" in d.columns else []
    if not ids:
        st.warning("Kolom 'id' tidak ada. Pastikan tabel pending_gulavit memiliki PK serial/bigserial.")
        return

    pick = st.multiselect("Pilih ID untuk diproses", ids)
    col1, col2 = st.columns(2)
    if col1.button("Approve Selected"):
        if not pick:
            st.warning("Pilih minimal satu ID."); return
        # muat inventory terbaru
        inv = load_inventory_df()
inv_by_code = {r["code"]: r for _, r in inv.iterrows()}
approved = 0
for id_ in pick:
    row = d[d["id"] == id_].iloc[0].to_dict()
    code, qty, rtype = row["code"], int(row["qty"]), str(row["type"]).upper()

    # Jika belum ada di master:
    if code not in inv_by_code:
        if rtype in ("IN", "RETURN"):
            # buat master item baru dengan qty 0, kemudian diproses normal
            inv_insert(
                code=code,
                item=row.get("item","-"),
                qty=0,
                unit=row.get("unit","-"),
                category="Uncategorized"
            )
            # refresh mapping lokal
            inv_by_code[code] = {"code": code, "item": row.get("item","-"), "unit": row.get("unit","-"), "qty": 0}
        else:  # OUT but item not found
            st.error(f"Code {code} tidak ditemukan di inventory. OUT tidak bisa diproses."); 
            continue

    cur = int(inv_by_code[code]["qty"])
    if rtype == "IN":
        new = cur + qty
    elif rtype == "OUT":
        if qty > cur:
            st.error(f"Qty OUT > stok untuk {code}. Lewati."); 
            continue
        new = cur - qty
    elif rtype == "RETURN":
        new = cur + qty
    else:
        st.error(f"Tipe tidak dikenal: {rtype}")
        continue

    # update inventory
    inv_update_qty(code, new)

    # catat history
    history_add({
        "action": f"APPROVE_{rtype}",
        "date": row.get("date"),
        "code": code, "item": row.get("item"),
        "qty": qty, "stock": new, "unit": row.get("unit"),
        "trans_type": row.get("trans_type"),
        "event": row.get("event"), "do_number": row.get("do_number"),
        "attachment": row.get("attachment"), "user": row.get("user"),
        "timestamp": ts_text()
    })

    # hapus pending
    pending_delete(id_)
    # update cache & map stok lokal
    inv_by_code[code]["qty"] = new
    approved += 1

st.success(f"Berhasil approve {approved} request.")
st.experimental_rerun()

# ================== RIWAYAT & EXPORT ==================
def render_riwayat():
    st.markdown("## Riwayat Transaksi")
    if df_hist.empty:
        st.info("Belum ada riwayat.")
        return
    d = df_hist.copy()
    for c in ["action","date","code","item","qty","stock","unit","trans_type","user","event","do_number","timestamp","attachment"]:
        if c not in d.columns: d[c] = None
    # Filter
    d["date_only"] = pd.to_datetime(d["date"].fillna(d["timestamp"]), errors="coerce").dt.date
    col1, col2 = st.columns(2)
    start = col1.date_input("Tanggal mulai", value=d["date_only"].min())
    end   = col2.date_input("Tanggal akhir", value=d["date_only"].max())
    col3, col4, col5 = st.columns(3)
    users = ["Semua"] + sorted(d["user"].dropna().astype(str).unique())
    acts  = ["Semua"] + sorted(d["action"].dropna().astype(str).unique())
    u_sel = col3.selectbox("Filter user", users)
    a_sel = col4.selectbox("Filter aksi", acts)
    q     = col5.text_input("Cari nama barang")

    view = d[(d["date_only"] >= start) & (d["date_only"] <= end)].copy()
    if u_sel != "Semua":
        view = view[view["user"].astype(str) == u_sel]
    if a_sel != "Semua":
        view = view[view["action"].astype(str) == a_sel]
    if q:
        view = view[view["item"].astype(str).str.contains(q, case=False, na=False)]

    show = ["action","date","code","item","qty","unit","stock","trans_type","user","event","do_number","timestamp"]
    show = [c for c in show if c in view.columns]
    st.dataframe(view[show].sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)

def render_export():
    st.markdown("## Export Laporan Inventori (Excel)")
    if df_inv.empty:
        st.info("Tidak ada data.")
        return
    df = df_inv.rename(columns={"code":"Kode","item":"Nama Barang","unit":"Satuan","qty":"Qty","category":"Kategori"})
    col1, col2 = st.columns(2)
    kategori_list = ["Semua Kategori"] + sorted([x for x in df["Kategori"].dropna().unique()])
    kat = col1.selectbox("Filter Kategori", kategori_list)
    q = col2.text_input("Cari Nama/Kode")
    view = df.copy()
    if kat != "Semua Kategori":
        view = view[view["Kategori"] == kat]
    if q:
        view = view[ view["Nama Barang"].str.contains(q, case=False, na=False) | view["Kode"].str.contains(q, case=False, na=False) ]
    st.dataframe(view, use_container_width=True, hide_index=True)
    if not view.empty:
        data = df_to_excel_bytes(view, "Inventori")
        st.download_button("Unduh Excel", data=data, file_name="Laporan_Inventori_Filter.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def render_reset():
    st.markdown("## Reset Data (Pending & History)")
    st.warning("Aksi ini tidak dapat dibatalkan. Inventori tidak dihapus.")
    confirm = st.text_input("Ketik: RESET")
    if st.button("Hapus Pending & History") and confirm == "RESET":
        # kosongkan pending & history
        supabase.from_("pending_gulavit").delete().neq("id", -1).execute()
        supabase.from_("history_gulavit").delete().neq("id", -1).execute()
        clear_cache()
        st.success("Pending & History sudah dikosongkan.")
        st.experimental_rerun()

# ================== NAVIGASI BERDASARKAN ROLE ==================
if role == "admin":
    menu = st.sidebar.radio("📌 Menu Admin", [
        "Dashboard", "Lihat Stok Barang", "Stock Card", "Tambah Master Barang",
        "Approve Request", "Riwayat", "Export Laporan", "Reset Data"
    ])
    if menu == "Dashboard": render_dashboard()
    elif menu == "Lihat Stok Barang": render_lihat_stok()
    elif menu == "Stock Card": render_stock_card()
    elif menu == "Tambah Master Barang": render_tambah_master()
    elif menu == "Approve Request": render_approve()
    elif menu == "Riwayat": render_riwayat()
    elif menu == "Export Laporan": render_export()
    elif menu == "Reset Data": render_reset()

elif role == "approver":
    menu = st.sidebar.radio("📌 Menu Approver", [
        "Dashboard", "Lihat Stok Barang", "Stock Card", "Approve Request", "Riwayat", "Export Laporan"
    ])
    if menu == "Dashboard": render_dashboard()
    elif menu == "Lihat Stok Barang": render_lihat_stok()
    elif menu == "Stock Card": render_stock_card()
    elif menu == "Approve Request": render_approve()
    elif menu == "Riwayat": render_riwayat()
    elif menu == "Export Laporan": render_export()

else:  # user
    menu = st.sidebar.radio("📌 Menu User", [
        "Dashboard", "Stock Card", "Request IN", "Request OUT", "Request Retur", "Lihat Riwayat"
    ])
    if menu == "Dashboard": render_dashboard()
    elif menu == "Stock Card": render_stock_card()
    elif menu == "Request IN": render_request_in()
    elif menu == "Request OUT": render_request_out()
    elif menu == "Request Retur": render_request_return()
    elif menu == "Lihat Riwayat": render_riwayat()
