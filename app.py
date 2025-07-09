import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import time
import zipfile
from io import BytesIO
from pathlib import Path
from PIL import Image

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

# --- App Configuration ---
DEFAULT_MARGIN = 5.0

# --- Page Configuration & Logo ---
try:
    logo_file_path = Path(__file__).parent / "AWM Logo (002).png"
    page_icon_img = Image.open(logo_file_path)
except FileNotFoundError:
    page_icon_img = "📄"

st.set_page_config(
    page_title="AWM Quote Generator",
    page_icon=page_icon_img,
    layout="wide"
)

# --- App Styling ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; font-family: 'Inter', sans-serif; }
    .st-emotion-cache-1y4p8pa { padding-top: 2rem; }
    h1, h2, h3 { color: #343a40; }
    .stButton > button { background-color: #a0c4ff; color: #002b6e !important; border: 1px solid #a0c4ff !important; border-radius: 0.375rem; font-weight: 600; }
    .stButton > button:hover { background-color: #8ab4f8; border-color: #8ab4f8; color: #002b6e !important; }
    .stButton > button:disabled { background-color: #ced4da !important; color: #6c757d !important; border-color: #ced4da !important; opacity: 0.7; }
    .stButton > button[kind="primary"] { background-color: #a7d7c5; border-color: #a7d7c5; color: #003e29 !important; }
    .stButton > button[kind="primary"]:hover { background-color: #8abbac; border-color: #8abbac; color: #003e29 !important; }
    [data-testid="stFileUploader"] { padding: 1rem; background-color: #f1f3f5; border-radius: 0.5rem; }
</style>
""", unsafe_allow_html=True)


# --- Helper & Callback Functions ---
def file_to_generative_part(file):
    bytes_io = BytesIO(file.getvalue())
    return {"mime_type": file.type, "data": bytes_io.read()}

def format_currency(num):
    if pd.isna(num) or num is None: return "$0.00"
    return f"${num:,.2f}"

def check_password():
    if st.session_state.get("password_correct", False): return True
    st.header("Login")
    password = st.text_input("Enter Password", type="password")
    if password == "AWM374":
        st.session_state["password_correct"] = True
        st.rerun()
    elif password:
        st.error("Password incorrect. Please try again.")
    return False

def _calculate_sell_prices(df: pd.DataFrame) -> pd.DataFrame:
    df_calc = df.copy()
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        df_calc[col] = pd.to_numeric(df_calc[col], errors='coerce').fillna(0)
    cost_after_disc = df_calc['COST_PER_UNIT'] * (1 - df_calc['DISC'] / 100)
    margin_divisor = (1 - df_calc['MARGIN'] / 100)
    margin_divisor[margin_divisor <= 0] = 0.01
    df_calc['SELL_UNIT_EX_GST'] = cost_after_disc / margin_divisor
    df_calc['SELL_TOTAL_EX_GST'] = df_calc['SELL_UNIT_EX_GST'] * df_calc['QTY']
    return df_calc

def apply_sorting():
    sort_key = st.session_state.sort_by
    if "quote_items" in st.session_state and not st.session_state.quote_items.empty:
        if sort_key in st.session_state.quote_items.columns:
            st.session_state.quote_items = st.session_state.quote_items.sort_values(
                by=sort_key, kind='mergesort'
            ).reset_index(drop=True)

def apply_global_margin():
    if "quote_items" in st.session_state and not st.session_state.quote_items.empty:
        global_margin_value = st.session_state.get("global_margin_input", DEFAULT_MARGIN)
        st.session_state.quote_items['MARGIN'] = global_margin_value
        st.toast(f"Applied {global_margin_value}% margin to all items.")

def add_row(index_offset):
    if st.session_state.get("selected_row_index") is None: return
    idx = st.session_state.selected_row_index
    new_idx = idx + index_offset
    current_df = st.session_state.quote_items
    new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.get("global_margin_input", DEFAULT_MARGIN)}])
    st.session_state.quote_items = pd.concat([current_df.iloc[:new_idx], new_row, current_df.iloc[new_idx:]], ignore_index=True)

def delete_row():
    if st.session_state.get("selected_row_index") is None: return
    idx = st.session_state.selected_row_index
    current_df = st.session_state.quote_items
    st.session_state.quote_items = current_df.drop(current_df.index[idx]).reset_index(drop=True)

def summarize_description():
    if st.session_state.get("summary_selectbox_index") is None: return
    try:
        idx = st.session_state.summary_selectbox_index
        original_description = st.session_state.quote_items.at[idx, 'Description']
        with st.spinner("🤖 Gemini is summarizing..."):
            prompt = f"Summarize the following product description in one clear, concise sentence for a customer quote. Be professional and easy to understand.\n\nOriginal Description: '{original_description}'"
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            st.session_state.quote_items.at[idx, 'Description'] = response.text.strip()
            st.toast("Description summarized!", icon="✅")
    except Exception as e:
        st.error(f"Failed to summarize: {e}")

# --- Gemini API & Password ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found.", icon="🚨")
    st.stop()

if not check_password():
    st.stop()

# --- Session State Initialization ---
if "quote_items" not in st.session_state:
    st.session_state.quote_items = pd.DataFrame(columns=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN"])
if "user_details" not in st.session_state:
    st.session_state.user_details = {"name": "", "job_title": "Sales", "branch": "AWM Nunawading", "email": "", "phone": "03 8846 2500"}
if "quote_details" not in st.session_state:
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "address": "", "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}", "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"
if "processing_triggered" not in st.session_state:
    st.session_state.processing_triggered = False

# ✅ FIX: Load the logo as a Pillow Image object, not a base64 string
if "company_logo_img" not in st.session_state:
    try:
        logo_path = Path(__file__).parent / "AWM Logo (002).png"
        st.session_state.company_logo_img = Image.open(logo_path)
    except FileNotFoundError:
        st.session_state.company_logo_img = None


# --- Main App UI ---
col1, col2 = st.columns([1, 4], vertical_alignment="center")
# ✅ FIX: Display the image object directly
if st.session_state.company_logo_img:
    col1.image(st.session_state.company_logo_img, width=150)
col2.title("AWM Quote Generator")
st.caption("App created by Harry Leonhardt")
st.divider()

# --- Main Processing Block ---
if st.session_state.processing_triggered:
    st.session_state.processing_triggered = False
    uploaded_files = st.session_state.get('file_uploader_state', [])
    if uploaded_files:
        # ... (Processing logic remains the same) ...
        pass

# --- STEP 1: START OR LOAD A QUOTE ---
with st.container(border=True):
    # ... (Step 1 code remains the same) ...
    pass

# The rest of the app only shows if a quote exists
if "quote_items" in st.session_state and not st.session_state.quote_items.empty:
    with st.container(border=True):
        # ... (Step 2 code remains the same) ...
        pass
        
    # --- STEP 3: DETAILS AND PDF ---
    with st.container(border=True):
        st.header("Step 3: Enter Details & Generate PDF")
        
        # ... (Staff and Customer profile uploaders remain the same) ...
        
        with st.form("quote_details_form"):
            # ... (Form contents remain the same) ...
            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        if submitted:
            st.info("PDF Generation triggered. This might take a moment...")
            
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            items_html = ""
            for i, row in final_df.iterrows():
                items_html += f"""...""" # Unchanged

            # ✅ FIX: Convert company logo from Image object to base64 string on the fly for PDF
            company_logo_html = ""
            if st.session_state.get("company_logo_img"):
                buffered = BytesIO()
                st.session_state.company_logo_img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                company_logo_html = f'<img src="data:image/png;base64,{img_str}" alt="Company Logo" class="h-16 mb-4">'

            customer_logo_html = f'<img src="data:image/png;base64,{st.session_state.get("customer_logo_b64")}" alt="Customer Logo" class="max-h-24 object-contain">' if st.session_state.get("customer_logo_b64") else ''
            
            # ... (The rest of the HTML generation and WeasyPrint logic remains the same) ...
            
            try:
                # ... (WeasyPrint call) ...
                pass
            except Exception as e:
                st.error(f"Failed to generate PDF: {e}")
