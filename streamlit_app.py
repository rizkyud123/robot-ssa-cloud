import streamlit as st
import pandas as pd
import requests
import io
import json
import os
from datetime import datetime
import re
import random
import time

# Page config
st.set_page_config(
    page_title="SSA Sedau Cloud Edition",
    page_icon="🏥",
    layout="wide"
)

# Load secrets
try:
    ID_APLIKASI = st.secrets["id_aplikasi"]
    ID_INSTITUSI = st.secrets["id_institusi"]
    MAPPING_FORMULIR = st.secrets["mapping_formulir"]
    DRIVE_LINKS = st.secrets["drive_links"]
    APP_PASSWORD = st.secrets["app_password"]
except KeyError as e:
    st.error(f"Secret tidak ditemukan: {e}. Silakan set secrets di Streamlit Cloud.")
    st.stop()

# Persistent log file
LOG_FILE = "upload_history.json"

def load_upload_history():
    """Load upload history from file"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_upload_history(history):
    """Save upload history to file"""
    with open(LOG_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def add_to_history(upload_data):
    """Add upload data to persistent history"""
    history = load_upload_history()
    history.append(upload_data)
    save_upload_history(history)

def get_today_history():
    """Get upload history for today"""
    history = load_upload_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_history = [h for h in history if h.get("Waktu_Upload", "").startswith(today)]
    return today_history

def check_app_password():
    """Check application password - no session persistence"""
    password = st.text_input("Masukkan Password Aplikasi:", type="password", key="app_password")
    if st.button("Login Aplikasi"):
        if password == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Password salah!")
    return st.session_state.get('authenticated', False)

def get_clean_date(text):
    bulan_map = {'Januari':'01','Februari':'02','Maret':'03','April':'04','Mei':'05','Juni':'06',
                 'Juli':'07','Agustus':'08','September':'09','Oktober':'10','November':'11','Desember':'12'}

    std_match = re.search(r'(\d{2})-(\d{2})-(\d{4})', text)
    if std_match:
        d, m, y = std_match.groups()
        return f"{y}-{m}-{d}"

    indo_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', text)
    if indo_match:
        d, m_name, y = indo_match.groups()
        m_num = bulan_map.get(m_name.capitalize(), '01')
        return f"{y}-{m_num}-{int(d):02d}"
    return None

def generate_new_filename(judul_laporan):
    puskesmas = "Puskesmas Sedau"
    aplikasi = "ePuskesmas"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return f"{puskesmas}_{aplikasi}_{judul_laporan}_{timestamp}.xlsx"

def process_uploaded_file(uploaded_file):
    """Process uploaded file and return DataFrame"""
    try:
        if uploaded_file.name.endswith('.xls'):
            # Read as HTML table
            content = uploaded_file.read().decode('utf-8', errors='ignore')
            df = pd.read_html(io.StringIO(content), flavor='html5lib')[0]
        else:
            # Read as Excel
            df = pd.read_excel(uploaded_file, header=None, engine='openpyxl')
        return df
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return pd.DataFrame()

def upload_single_file(df, file_name, username, password, progress_bar, status_text):
    """Upload single file to Portal Sehat"""
    try:
        # Login
        login_url = "https://admin-uploadsehat.lombokbaratkab.go.id/api/auth/local"
        login_payload = {"identifier": username, "password": password}
        headers_login = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        status_text.text("Login ke Portal Sehat...")
        response = requests.post(login_url, json=login_payload, headers=headers_login)
        if response.status_code != 200:
            return f"Login failed: {response.text}"

        jwt_token = response.json().get('jwt')
        if not jwt_token:
            return "No token received"

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Process file
        status_text.text(f"Memproses {file_name}...")
        if df.empty:
            return f"Could not read data from {file_name}"

        judul_file = str(df.iloc[0, 0]).strip()
        judul_bersih = judul_file.replace("Laporan Harian - ", "").strip()

        # Get date
        tgl_iso = None
        for i in range(1, 6):
            row_str = " ".join(df.iloc[i].astype(str))
            tgl_iso = get_clean_date(row_str)
            if tgl_iso: break
        if not tgl_iso:
            tgl_iso = datetime.now().strftime("%Y-%m-%d")

        # Check mapping
        if judul_bersih not in MAPPING_FORMULIR:
            return f"Judul '{judul_bersih}' tidak terdaftar di mapping"

        doc_id_form = MAPPING_FORMULIR[judul_bersih]

        # Generate new filename
        nama_file_baru = generate_new_filename(judul_bersih.replace("Pemeriksaan ", "").replace("Pelayanan ", ""))

        # Create Excel in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        # Upload
        url = "https://admin-uploadsehat.lombokbaratkab.go.id/api/upload-drive"
        payload = {
            "aplikasi": ID_APLIKASI,
            "formulir": doc_id_form,
            "institusi": ID_INSTITUSI,
            "TanggalAwal": tgl_iso,
            "TanggalAkhir": tgl_iso,
            "Nama": "",
            "NoHP": ""
        }

        files = {'file': (nama_file_baru, output, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}

        status_text.text(f"Mengupload {file_name}...")
        progress_bar.progress(0.7)

        response = requests.post(url, headers=headers, data=payload, files=files)

        if response.status_code == 200:
            res_json = response.json()
            server_id = res_json.get('data', {}).get('id', 'N/A')

            # Save to persistent history
            upload_data = {
                "Waktu_Upload": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Nama_File": file_name,
                "Jenis_Laporan": judul_file,
                "ID_Database_Server": server_id,
                "Status": "SUKSES",
                "Username": username,
                "Tanggal_Laporan": tgl_iso
            }
            add_to_history(upload_data)

            return f"✅ Berhasil! ID Server: {server_id}"
        else:
            return f"Gagal: {response.text}"

    except Exception as e:
        return f"Error: {str(e)}"

def dashboard_tab():
    """Dashboard tab to view upload history"""
    st.header("📊 Dashboard Upload History")

    # Load history
    history = load_upload_history()

    if not history:
        st.info("Belum ada riwayat upload. Lakukan upload pertama di tab Upload.")
        return

    # Convert to DataFrame
    df_history = pd.DataFrame(history)

    # Statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Upload", len(df_history))
    with col2:
        success_count = len(df_history[df_history['Status'] == 'SUKSES'])
        st.metric("Berhasil", success_count)
    with col3:
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = len(df_history[df_history['Waktu_Upload'].str.startswith(today)])
        st.metric("Upload Hari Ini", today_count)
    with col4:
        unique_users = df_history['Username'].nunique()
        st.metric("User Aktif", unique_users)

    # Filters
    st.subheader("🔍 Filter Data")
    col1, col2 = st.columns(2)
    with col1:
        date_filter = st.date_input("Pilih Tanggal", value=datetime.now().date())
    with col2:
        status_filter = st.selectbox("Status", ["Semua", "SUKSES"], index=0)

    # Apply filters
    filtered_df = df_history.copy()
    if date_filter:
        date_str = date_filter.strftime("%Y-%m-%d")
        filtered_df = filtered_df[filtered_df['Waktu_Upload'].str.startswith(date_str)]

    if status_filter != "Semua":
        filtered_df = filtered_df[filtered_df['Status'] == status_filter]

    # Display data
    st.subheader("📋 Riwayat Upload")
    st.dataframe(filtered_df, use_container_width=True)

    # Download filtered data
    if not filtered_df.empty:
        if st.button("📥 Download Data Terfilter"):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                filtered_df.to_excel(writer, index=False)
            output.seek(0)

            st.download_button(
                label="📥 Klik untuk Download",
                data=output,
                file_name=f"Riwayat_Upload_Sedau_{date_filter.strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

def check_drive_tab():
    """Check Drive tab for accessing Google Drive folders"""
    st.header("🔗 Cek Drive Laporan")

    st.markdown("Klik tombol di bawah untuk membuka folder Google Drive sesuai jenis laporan:")

    for jenis, url in DRIVE_LINKS.items():
        if st.button(f"📂 {jenis}", key=f"drive_{jenis}"):
            st.markdown(f'<a href="{url}" target="_blank">Buka Drive {jenis}</a>', unsafe_allow_html=True)
            st.info(f"Membuka {jenis} di tab baru...")

def upload_tab():
    """Upload tab for file processing"""
    # Portal Sehat credentials
    st.header("🔐 Login Portal Sehat")
    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Username Portal Sehat", key="username")
    with col2:
        password = st.text_input("Password Portal Sehat", type="password", key="password")

    # File upload
    st.header("📁 Upload File Laporan")
    uploaded_files = st.file_uploader(
        "Pilih file Excel (.xlsx) atau HTML (.xls) dari e-Puskesmas",
        type=['xlsx', 'xls'],
        accept_multiple_files=True
    )

    # Download Rekap Hari Ini
    st.header("📈 Rekap Upload Hari Ini")
    today_history = get_today_history()
    if today_history:
        df_today = pd.DataFrame({
            "Nama File": [h["Nama_File"] for h in today_history],
            "ID Server": [h["ID_Database_Server"] for h in today_history],
            "Timestamp": [h["Waktu_Upload"] for h in today_history]
        })
        st.dataframe(df_today)

        if st.button("📥 Download Rekap Hari Ini"):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_today.to_excel(writer, index=False)
            output.seek(0)

            st.download_button(
                label="📥 Klik untuk Download",
                data=output,
                file_name=f"Rekap_Upload_Sedau_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("Belum ada upload hari ini.")

    if st.button("🚀 Mulai Upload", type="primary"):
        if not username or not password or not uploaded_files:
            st.error("Lengkapi login dan pilih file!")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []

            total_files = len(uploaded_files)
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Memproses file {i+1}/{total_files}: {uploaded_file.name}")
                progress_bar.progress((i / total_files) * 0.5)

                # Process file
                df = process_uploaded_file(uploaded_file)
                if df.empty:
                    results.append(f"❌ {uploaded_file.name}: Gagal memproses file")
                    continue

                # Upload
                result = upload_single_file(df, uploaded_file.name, username, password, progress_bar, status_text)
                results.append(f"{uploaded_file.name}: {result}")

                # Random delay
                delay = random.uniform(3, 7)
                status_text.text(f"Menunggu {delay:.1f} detik...")
                time.sleep(delay)

            progress_bar.progress(1.0)
            status_text.text("✅ Proses selesai!")

            # Show results
            st.header("📊 Hasil Upload")
            for result in results:
                if "✅" in result:
                    st.success(result)
                else:
                    st.error(result)

def main():
    if not check_app_password():
        return

    st.title("🏥 Robot SSA - Puskesmas Sedau")
    st.markdown("**Automasi Upload Laporan Puskesmas Sedau ke Portal Sehat**")

    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📁 Upload", "🔗 Cek Drive"])

    with tab1:
        dashboard_tab()

    with tab2:
        upload_tab()

    with tab3:
        check_drive_tab()

if __name__ == "__main__":
    main()
