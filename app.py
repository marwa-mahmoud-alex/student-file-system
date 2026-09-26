# -*- coding: utf-8 -*-
"""
نظام استعلام ملفات الطلاب - كلية التمريض - جامعة الإسكندرية
--------------------------------------------------------------
تطبيق Streamlit لاستعلام الطلاب عن حالة ملفاتهم، ولوحة تحكم للموظفين
لتعديل الحالات ومتابعة الجدول الكامل مع إمكانية التصدير.

البيانات تُقرأ وتُحدَّث في Google Sheets:
- تبويب الطالب: قراءة سريعة عامة عبر رابط تصدير CSV (لا يحتاج مصادقة).
- تبويب الموظف: قراءة/كتابة عبر Google Sheets API (يحتاج حساب خدمة Service Account)
  حتى يمكن حفظ التعديلات فعلياً في الشيت (رابط CSV للقراءة فقط ولا يسمح بالكتابة).
"""

import html
import io
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

# ============================================================
# 1) الإعدادات الأساسية - عدّل القيم التالية حسب مشروعك
# ============================================================
st.set_page_config(
    page_title="نظام استعلام ملفات الطلاب - كلية التمريض",
    page_icon="📁",
    layout="wide",
)

# ضع هنا رابط ملف Google Sheets الخاص بك (رابط المشاركة العادي كافٍ)
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1KW46MhPH8uU75BOYh8FmH_sGRX6iLxfz4YfFicbf-D8/edit?usp=sharing"
WORKSHEET_NAME = "Sheet1"  # اسم الورقة (Tab) داخل الملف

REQUIRED_COLUMNS = ["الرقم_القومي", "رقم_الجلوس", "اسم_الطالب", "حالة_الملف", "ملاحظات"]

STATUS_COLORS = {
    "تم التسليم": "#16a34a",      # أخضر
    "قيد المراجعة": "#f59e0b",    # برتقالي
    "لم يتم التسليم": "#dc2626",  # أحمر
}
DEFAULT_STATUS_COLOR = "#6b7280"  # رمادي لأي حالة غير معروفة


def extract_sheet_id(url: str):
    """يستخرج معرف الشيت (Sheet ID) من رابط جوجل شيت العادي."""
    try:
        return url.split("/d/")[1].split("/")[0]
    except (IndexError, AttributeError):
        return None


SHEET_ID = extract_sheet_id(GOOGLE_SHEET_URL)
# رابط تصدير CSV مع تحديد اسم الورقة (أدق من /export?format=csv عند وجود أكثر من ورقة)
CSV_EXPORT_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={WORKSHEET_NAME}"
    if SHEET_ID
    else None
)


# ============================================================
# 2) قراءة البيانات (تبويب الطالب) - عامة، سريعة، مع Cache
# ============================================================
@st.cache_data(ttl=60, show_spinner=False)
def load_public_data() -> pd.DataFrame:
    if not CSV_EXPORT_URL:
        raise ValueError("رابط Google Sheets غير صالح. تأكد من ضبط GOOGLE_SHEET_URL بشكل صحيح.")

    response = requests.get(CSV_EXPORT_URL, timeout=10)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text), dtype=str)
    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"الأعمدة التالية مفقودة من الشيت: {', '.join(missing)}")

    return df.fillna("")


# ============================================================
# 3) الاتصال بـ Google Sheets API (تبويب الموظف) - قراءة وكتابة
# ============================================================
def get_admin_credentials():
    """يقرأ بيانات دخول الأدمن من secrets.toml، ويرجع بيانات افتراضية إن لم تكن موجودة."""
    try:
        email = st.secrets["admin_credentials"]["email"]
        password = st.secrets["admin_credentials"]["password"]
        return email, password, True
    except Exception:
        return "admin@app.com", "admin123", False


@st.cache_resource(show_spinner=False)
def get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.worksheet(WORKSHEET_NAME)


@st.cache_data(ttl=30, show_spinner=False)
def load_admin_records():
    ws = get_worksheet()
    records = ws.get_all_records()
    for i, record in enumerate(records):
        record["_row"] = i + 2  # +1 لصف العناوين، +1 لأن الفهرسة في الشيت تبدأ من 1
    return records


def render_rtl_table(df: pd.DataFrame) -> str:
    """يبني جدول HTML مخصص بحيث يظهر بالكامل من اليمين لليسار (العناوين والصفوف)."""
    headers_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in df.columns)
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{html.escape(str(row[col]))}</td>" for col in df.columns)
        rows_html += f"<tr>{cells}</tr>"
    return f"""
    <div class="rtl-table-wrapper">
        <table class="rtl-table">
            <thead><tr>{headers_html}</tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """


def update_student_record(row_number: int, new_status: str, new_notes: str):
    ws = get_worksheet()
    header = ws.row_values(1)
    status_col = header.index("حالة_الملف") + 1
    notes_col = header.index("ملاحظات") + 1
    ws.update_cell(row_number, status_col, new_status)
    ws.update_cell(row_number, notes_col, new_notes)


# ============================================================
# 4) التنسيقات (CSS) - دعم RTL + هيدر متدرج + أزرار وبطاقات
# ============================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');

html, body, [class*="css"], [class*="st-"], * {
        font-family: 'Cairo', sans-serif !important;
    }
    
    html, body, [class*="css"] {
        direction: rtl;
        font-weight: 600;
        text-align: right;
        font-size: 17px;
    }

    .main-header {
        background: linear-gradient(135deg, #3b82f6 0%, #1e3a8a 100%);
        padding: 2rem 1.5rem;
        border-radius: 16px;
        text-align: center;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 16px rgba(30, 58, 138, 0.25);
    }
    .main-header h1 { margin: 0; font-size: 1.9rem; font-weight: 700; }
    .main-header p { margin: 0.3rem 0 0; font-size: 1.05rem; opacity: 0.9; }
    
    div.stButton > button,
    div.stFormSubmitButton > button,
    div.stDownloadButton > button,
    div.stButton > button *,
    div.stFormSubmitButton > button *,
    div.stDownloadButton > button * {
        font-family: 'Cairo', sans-serif !important;
    }
    
    div.stButton > button, div.stFormSubmitButton > button {
        width: 100%;
        border-radius: 10px;
        padding: 0.95rem 1.5rem;
        font-weight: 700 !important;
        font-size: 1.2rem !important;
        border: none;
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        color: white;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover, div.stFormSubmitButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(37, 99, 235, 0.35);
    }

    .result-card {
        border-radius: 14px;
        padding: 1.2rem 1.5rem;
        background: #ffffff;
        border-right: 6px solid var(--status-color, #6b7280);
        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        margin-top: 1rem;
    }
    .result-card h3 { margin: 0 0 0.4rem; }
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.8rem;
        border-radius: 999px;
        color: white;
        font-weight: 700;
        font-size: 0.9rem;
    }
        .rtl-table-wrapper {
        overflow-x: auto;
        margin-top: 0.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    }
    .rtl-table {
        width: 100%;
        border-collapse: collapse;
        direction: rtl;
        text-align: right;
        font-size: 0.95rem;
        background: white;
    }
    .rtl-table th, .rtl-table td {
        padding: 0.55rem 0.9rem;
        border-bottom: 1px solid #e5e7eb;
        white-space: nowrap;
    }
    .rtl-table thead th {
        background: linear-gradient(135deg, #3b82f6, #1e3a8a);
        color: white;
        font-weight: 700;
    }
    .rtl-table tbody tr:nth-child(even) {
        background: #f8fafc;
    }
    .rtl-table tbody tr:hover {
        background: #eef2ff;
    }
    
    .app-footer {
        text-align: center;
        color: #6b7280;
        font-size: 0.95rem;
        margin-top: 3rem;
        padding-top: 1.2rem;
        border-top: 1px solid #e5e7eb;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 5) الهيدر والتبويبات
# ============================================================
st.markdown(
    """
    <div class="main-header">
        <h1>📁 نظام استعلام ملفات الطلاب</h1>
        <p>كلية التمريض – جامعة الإسكندرية</p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2 = st.tabs(["🔍 استعلام طالب", "📝 دخول الموظفين"])

# ============================================================
# 6) تبويب: استعلام طالب
# ============================================================
with tab1:
    st.subheader("🔍 أدخل رقمك القومي أو رقم جلوس الثانوية العامة")
    query = st.text_input(
        "الرقم",
        placeholder="أدخل الرقم القومي (14 رقم) أو رقم الجلوس",
        label_visibility="collapsed",
    )
    search_clicked = st.button("🔍 عرض بياناتي", key="search_btn")

    if search_clicked:
        query_clean = query.strip()
        if not query_clean:
            st.warning("يرجى إدخال الرقم القومي أو رقم الجلوس أولاً.")
        else:
            try:
                df = load_public_data()
                match = df[
                    (df["الرقم_القومي"].str.strip() == query_clean)
                    | (df["رقم_الجلوس"].str.strip() == query_clean)
                ]
                if match.empty:
                    st.error("⚠️ لم يتم العثور على بيانات مرتبطة بهذا الرقم، يرجى التأكد وإعادة المحاولة.")
                else:
                    row = match.iloc[0]
                    status = str(row["حالة_الملف"]).strip()
                    color = STATUS_COLORS.get(status, DEFAULT_STATUS_COLOR)
                    notes = row["ملاحظات"] or "لا توجد ملاحظات"
                    st.markdown(
                        f"""
                        <div class="result-card" style="--status-color: {color};">
                            <h3>👤 {row['اسم_الطالب']}</h3>
                            <p><span class="status-badge" style="background:{color};">{status}</span></p>
                            <p>📝 <b>ملاحظات:</b> {notes}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            except Exception as e:
                st.error(
                    "⚠️ تعذّر الاتصال بقاعدة البيانات حالياً، يرجى المحاولة لاحقاً.\n\n"
                    f"تفاصيل تقنية: {e}"
                )

# ============================================================
# 7) تبويب: دخول الموظفين
# ============================================================
with tab2:
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.subheader("📝 تسجيل دخول الموظفين")
        admin_email, admin_password, has_secrets = get_admin_credentials()
        if not has_secrets:
            st.info(
                "ℹ️ يتم حالياً استخدام بيانات دخول افتراضية للتجربة فقط "
                "(admin@app.com / admin123). أضف بيانات آمنة في ملف secrets.toml قبل النشر الفعلي."
            )

        with st.form("login_form"):
            email_input = st.text_input("البريد الإلكتروني")
            password_input = st.text_input("كلمة المرور", type="password")
            login_clicked = st.form_submit_button("🔒 دخول")

        if login_clicked:
            if email_input == admin_email and password_input == admin_password:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("البريد الإلكتروني أو كلمة المرور غير صحيحة.")

    else:
        st.success("✅ أهلاً بك في لوحة تحكم الموظفين")
        _, logout_col = st.columns([5, 1])
        with logout_col:
            if st.button("🚪 تسجيل الخروج"):
                st.session_state.logged_in = False
                st.rerun()

        try:
            records = load_admin_records()
        except Exception as e:
            st.error(
                "⚠️ تعذّر الاتصال بـ Google Sheets عبر حساب الخدمة.\n\n"
                "تأكد من:\n"
                "1) إضافة بيانات حساب الخدمة (gcp_service_account) في secrets.toml.\n"
                "2) مشاركة ملف Google Sheets مع بريد حساب الخدمة (Editor).\n\n"
                f"تفاصيل تقنية: {e}"
            )
            st.stop()

        st.markdown("### 🔎 بحث وتعديل حالة طالب")
        admin_query = st.text_input("ابحث بالرقم القومي أو رقم الجلوس", key="admin_query").strip()

        if admin_query:
            found = [
                r
                for r in records
                if str(r.get("الرقم_القومي", "")).strip() == admin_query
                or str(r.get("رقم_الجلوس", "")).strip() == admin_query
            ]
            if not found:
                st.warning("لا يوجد طالب بهذا الرقم.")
            else:
                student = found[0]
                st.write(f"**الاسم:** {student.get('اسم_الطالب', '')}")

                status_options = list(STATUS_COLORS.keys())
                current_status = str(student.get("حالة_الملف", "")).strip()
                default_index = (
                    status_options.index(current_status) if current_status in status_options else 0
                )
                new_status = st.selectbox("حالة الملف", options=status_options, index=default_index)
                new_notes = st.text_area("ملاحظات", value=student.get("ملاحظات", ""))

                if st.button("💾 حفظ التعديلات"):
                    try:
                        update_student_record(student["_row"], new_status, new_notes)
                        load_admin_records.clear()
                        st.success("تم حفظ التعديلات بنجاح ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ حدث خطأ أثناء الحفظ: {e}")

        st.markdown("### 📋 جدول جميع الطلاب")
        full_df = pd.DataFrame(records).drop(columns=["_row"], errors="ignore")
        st.dataframe(full_df, use_container_width=True)

        col_csv, col_xlsx = st.columns(2)
        with col_csv:
            st.download_button(
                "⬇️ تنزيل CSV",
                data=full_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"طلاب_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
        with col_xlsx:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                full_df.to_excel(writer, index=False, sheet_name="الطلاب")
            st.download_button(
                "⬇️ تنزيل Excel",
                data=excel_buffer.getvalue(),
                file_name=f"طلاب_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
          
# ============================================================
# 8) الفوتر (يظهر أسفل الصفحة في كل التبويبات)
# ============================================================
st.markdown("---")
st.markdown("<p style='text-align: center; color: gray;'>جميع الحقوق محفوظة © كلية التمريض -جامعة الاسكندرية</p>", unsafe_allow_html=True)
