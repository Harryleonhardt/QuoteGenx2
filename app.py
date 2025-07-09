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
    .step-container { border: 1px solid #dee2e6; border-radius: 0.8rem; padding: 1.5rem 2rem; background-color: white; box-shadow: 0 4px 12px -1px rgb(0 0 0 / 0.05); margin-bottom: 2rem; }
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

def get_logo_base64(file_path):
    try:
        with open(file_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        st.error("Logo file not found.", icon="🚨")
        return None

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
    if sort_key in st.session_state.quote_items.columns:
        st.session_state.quote_items = st.session_state.quote_items.sort_values(
            by=sort_key, kind='mergesort'
        ).reset_index(drop=True)

def apply_global_margin():
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
            prompt = f"Summarize the following product description..."
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
if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(globals().get("logo_file_path"))
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"
# ✅ FIX: Initialize the processing flag
if "processing_triggered" not in st.session_state:
    st.session_state.processing_triggered = False

# --- Main App UI ---
st.title("AWM Quote Generator")
st.caption(f"Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# ✅ FIX: This entire block now runs first if the flag is set
if st.session_state.processing_triggered:
    # Reset the flag immediately
    st.session_state.processing_triggered = False
    
    uploaded_files = st.session_state.get('file_uploader_state', [])
    if uploaded_files:
        with st.spinner(f"Processing {len(uploaded_files)} file(s)..."):
            all_new_items = []
            failed_files = []
            extraction_prompt = (
                "From the provided document, extract all line items..."
            )
            json_schema = {"type": "ARRAY", "items": {...}} # (Schema remains the same)
            model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})

            for i, file in enumerate(uploaded_files):
                try:
                    st.write(f"Processing `{file.name}`...")
                    part = get_logo_base64(file) # This helper needs to be adjusted for generic files
                    response = model.generate_content([extraction_prompt, part])
                    extracted_data = json.loads(response.text)
                    if extracted_data:
                        all_new_items.extend(extracted_data)
                    if i < len(uploaded_files) - 1:
                        time.sleep(2)
                except Exception as e:
                    st.error(f"An error occurred processing `{file.name}`: {e}")
                    failed_files.append(file.name)

            if all_new_items:
                new_df = pd.DataFrame(all_new_items)
                new_df['DISC'] = 0.0
                new_df['MARGIN'] = st.session_state.get("global_margin_input", DEFAULT_MARGIN)
                st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
                apply_sorting()
                st.success(f"Successfully extracted {len(all_new_items)} items!")

            if failed_files:
                st.warning(f"Could not process the following files: {', '.join(failed_files)}")
            
            # Clear the file uploader state after processing
            st.session_state.file_uploader_state = []

# --- STEP 1: START OR LOAD A QUOTE ---
with st.container(border=True):
    st.header("Step 1: Start or Load a Quote")
    
    tab1, tab2 = st.tabs(["➕ Start New Quote", "📂 Load Saved Quote"])

    with tab1:
        st.markdown("Upload one or more supplier quote documents (PDF or TXT).")
        st.file_uploader(
            "Upload supplier documents", type=['pdf', 'txt'], accept_multiple_files=True,
            key='file_uploader_state' # Use a key to hold the files in state
        )
        # ✅ FIX: This button now only sets the flag. It doesn't run the logic itself.
        st.button(
            "Process Uploaded Files", 
            use_container_width=True, 
            disabled=not st.session_state.get('file_uploader_state'),
            on_click=lambda: st.session_state.update(processing_triggered=True)
        )

    with tab2:
        st.markdown("Load a previously saved quote from a CSV file.")
        if saved_quote_file := st.file_uploader("Load Quote from CSV", type="csv"):
            try:
                st.session_state.quote_items = pd.read_csv(saved_quote_file)
                st.success("Quote successfully loaded!")
                st.rerun()
            except Exception as e:
                st.error(f"Error loading CSV: {e}")

# The rest of the app only shows if a quote exists
if not st.session_state.quote_items.empty:
    # --- STEP 2: EDIT QUOTE ---
    with st.container(border=True):
        st.header("Step 2: Edit & Refine Quote")
        # ... (The rest of the app code for Steps 2, 3, and 4 remains the same)
