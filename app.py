import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import time
from io import BytesIO
from pathlib import Path
from PIL import Image

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

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
    /* CSS styles remain the same */
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

def image_to_base64(image_file):
    if image_file is not None:
        return base64.b64encode(image_file.getvalue()).decode()
    return None

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
        st.rerun() # This rerun is SAFE and necessary for login
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

# ✅ FIX: All state modifications are now wrapped in callback functions
def apply_sorting():
    sort_key = st.session_state.sort_by
    if sort_key in st.session_state.quote_items.columns:
        st.session_state.quote_items = st.session_state.quote_items.sort_values(
            by=sort_key, kind='mergesort'
        ).reset_index(drop=True)

def apply_global_margin():
    global_margin_value = st.session_state.get("global_margin_input", 9.0)
    st.session_state.quote_items['MARGIN'] = global_margin_value
    st.toast(f"Applied {global_margin_value}% margin to all items.")

def add_row(index_offset):
    if st.session_state.get("selected_row_index") is None: return
    idx = st.session_state.selected_row_index
    new_idx = idx + index_offset
    current_df = st.session_state.quote_items
    new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.get("global_margin_input", 9.0)}])
    st.session_state.quote_items = pd.concat([current_df.iloc[:new_idx], new_row, current_df.iloc[new_idx:]], ignore_index=True)

def delete_row():
    if st.session_state.get("selected_row_index") is None: return
    idx = st.session_state.selected_row_index
    current_df = st.session_state.quote_items
    st.session_state.quote_items = current_df.drop(current_df.index[idx]).reset_index(drop=True)

def summarize_description():
    if st.session_state.get("summary_selectbox") is None: return
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
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}", "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(globals().get("logo_file_path"))
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"
# ... other initializations ...

# --- Main App UI ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64: st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# --- STEP 1: Upload ---
with st.container(border=False):
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("Step 1: Upload Supplier Quotes")
    uploaded_files = st.file_uploader("Upload files", type=['pdf', 'txt'], accept_multiple_files=True, label_visibility="collapsed")
    if st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files):
        with st.spinner(f"Processing {len(uploaded_files)} file(s)..."):
            # ... File processing logic is fine ...
            st.rerun() # This rerun is SAFE and necessary after a long process
    st.markdown('</div>', unsafe_allow_html=True)

if not WEASYPRINT_AVAILABLE:
     st.error("PDF generation library not found.", icon="🚨")
     st.stop()

if not st.session_state.quote_items.empty:
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header("Step 2: Edit & Refine Quote")
        
        edited_df = st.data_editor(
            _calculate_sell_prices(st.session_state.quote_items),
            #... column_config is the same ...
            num_rows="dynamic", use_container_width=True, key="data_editor"
        )
        st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
        
        st.divider()
        st.subheader("Table Controls")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Sorting**")
            st.radio("Sort items by:", ("Type", "Supplier"), horizontal=True, key="sort_by", label_visibility="collapsed", on_change=apply_sorting)
        with c2:
            st.write("**Global Margin**")
            sub_c1, sub_c2 = st.columns([0.6, 0.4])
            sub_c1.number_input("Global Margin (%)", value=9.0, min_value=0.0, max_value=99.9, step=1.0, format="%.2f", label_visibility="collapsed", key="global_margin_input")
            # ✅ FIX: Button uses on_click, no rerun needed.
            sub_c2.button("Apply Margin", use_container_width=True, on_click=apply_global_margin)

        st.divider()
        st.subheader("Row Operations")
        row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in st.session_state.quote_items.iterrows()]
        selected_row_str = st.selectbox("Select a row to modify:", options=row_options, index=None, placeholder="Choose a row...", key="selected_row_str")
        
        # Store the selected index in session state so callbacks can access it
        if selected_row_str:
            st.session_state.selected_row_index = row_options.index(selected_row_str)
        
        c1, c2, c3 = st.columns(3)
        # ✅ FIX: All buttons use on_click callbacks and pass arguments if needed. No reruns.
        c1.button("Add Row Above", use_container_width=True, on_click=add_row, args=(0,), disabled=not selected_row_str)
        c2.button("Add Row Below", use_container_width=True, on_click=add_row, args=(1,), disabled=not selected_row_str)
        c3.button("Delete Selected Row", use_container_width=True, on_click=delete_row, disabled=not selected_row_str)

        st.divider()
        st.subheader("✍️ AI Description Summarizer")
        summary_row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in st.session_state.quote_items.iterrows()]
        selected_item_str_for_summary = st.selectbox("Select Item to Summarize", options=summary_row_options, index=None, placeholder="Choose an item...", key="summary_selectbox")

        # Store index for the callback
        if selected_item_str_for_summary:
            st.session_state.summary_selectbox_index = summary_row_options.index(selected_item_str_for_summary)
        
        # ✅ FIX: Button uses on_click, no rerun needed.
        st.button("Summarize Description", use_container_width=True, on_click=summarize_description, disabled=not selected_item_str_for_summary)
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- STEP 3 & 4: Details and PDF ---
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        with st.form("quote_details_form"):
            # ... The form logic remains the same ...
            st.header("Step 3: Project & Customer Details")
            # ...
            st.header("Step 4: Review Totals & Generate PDF")
            # ...
            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        if submitted:
            # ... The PDF generation logic remains the same ...
            pass # Placeholder for your existing PDF logic
        st.markdown('</div>', unsafe_allow_html=True)
