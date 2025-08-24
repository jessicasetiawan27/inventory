# app.py — MVP: login + baca tabel dari Supabase
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime

# --- Hotfix: agar kode lama "st.experimental_rerun" tetap jalan di Streamlit baru
try:
    if not hasattr(st, "experimental_rerun"):
        st.experimental_rerun = st.rerun
except Exception:
    pass

st.set_page_config(page_title="Gudang Gulavit", page_icon="🧰", layout="wide")

# ====== Baca secrets (akan kita isi nanti) ======
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# ====== Init Supabase ======
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@st.cache_data(ttl=300)
def load_all():
    users = supabase.from_("users_gulavit").select("*").execute().data or []
    inv   = supabase.from_("inventory_gulavit").select("*").execute().data or []
    pend  = supabase.from_("pending_gulavit").select("*").execute().data or []
    hist  = supabase.from_("history_gulavit").select("*").execute().data or []
    return pd.DataFrame(users), pd.DataFrame(inv), pd.DataFrame(pend), pd.DataFrame(hist)

# ------ LOGIN STATE ------
if "auth" not in st.session_state:
    st.session_state.auth = {"ok": False, "username": "", "role": "user"}

def do_login(u, p):
    df_users, *_ = load_all()
    if df_users.empty:
        st.error("Tabel users_gulavit kosong atau belum dibuat.")
        return
    ok = df_users[(df_users["username"] == u) & (df_users["password"] == p)]
    if not ok.empty:
        st.session_state.auth = {"ok": True, "username": u, "role": ok.iloc[0].get("role", "user")}
        st.experimental_rerun()
    else:
        st.error("Username/password salah.")

# ------ UI LOGIN ------
if not st.session_state.auth["ok"]:
    st.title("Halaman Login Aplikasi Gudang Gulavit")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        s = st.form_submit_button("Login")
    if s:
        do_login(u, p)
    st.stop()

# ------ MAIN ------
st.header(f"Halo, {st.session_state.auth['username']} ({st.session_state.auth['role']})")
df_users, df_inv, df_pend, df_hist = load_all()

tab1, tab2, tab3 = st.tabs(["Dashboard", "Inventori", "Pending"])
with tab1:
    st.write("Ringkasan cepat")
    st.metric("Total SKU", int(len(df_inv)))
    st.metric("Pending Request", int(len(df_pend)))

with tab2:
    st.subheader("Daftar Inventori")
    st.dataframe(df_inv if not df_inv.empty else pd.DataFrame(), use_container_width=True)

with tab3:
    st.subheader("Pending Request")
    st.dataframe(df_pend if not df_pend.empty else pd.DataFrame(), use_container_width=True)

st.divider()
if st.button("Logout"):
    st.session_state.auth = {"ok": False, "username": "", "role": "user"}
    st.experimental_rerun()
