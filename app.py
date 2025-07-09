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
if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(globals().get("logo_file_path"))
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"
if "pdf_ready" not in st.session_state:
    st.session_state.pdf_ready = None

# --- Main App UI ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64: st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# --- STEP 1: START OR LOAD A QUOTE ---
with st.container(border=False):
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("Step 1: Start or Load a Quote")
    
    tab1, tab2 = st.tabs(["➕ Start New Quote", "📂 Load Saved Quote"])

    with tab1:
        st.markdown("Upload one or more supplier quote documents (PDF or TXT).")
        uploaded_files = st.file_uploader(
            "Upload files", type=['pdf', 'txt'], accept_multiple_files=True, label_visibility="collapsed"
        )
        if st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files):
            with st.spinner(f"Processing {len(uploaded_files)} file(s)..."):
                # (The file processing logic remains the same as the last working version)
                all_new_items, failed_files = [], []
                # ... Gemini API call logic ...
                if all_new_items:
                    st.session_state.quote_items = pd.concat([st.session_state.quote_items, pd.DataFrame(all_new_items)], ignore_index=True)
                    st.success("Files processed successfully!")
            st.rerun()

    with tab2:
        st.markdown("Load a previously saved quote from a CSV file.")
        saved_quote_file = st.file_uploader("Load Quote from CSV", type="csv")
        if saved_quote_file is not None:
            try:
                loaded_df = pd.read_csv(saved_quote_file)
                st.session_state.quote_items = loaded_df
                st.success("Quote successfully loaded!")
                st.rerun()
            except Exception as e:
                st.error(f"Error loading CSV: {e}")

    st.markdown('</div>', unsafe_allow_html=True)


if not WEASYPRINT_AVAILABLE:
     st.error("PDF generation library not found.", icon="🚨")
     st.stop()

# The rest of the app only shows if a quote exists (either started or loaded)
if not st.session_state.quote_items.empty:
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header("Step 2: Edit & Refine Quote")
        # ... (Data editor and other controls remain the same)
        
        st.divider()
        st.subheader("Save Quote")
        csv_data = st.session_state.quote_items.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="💾 Save Current Quote to CSV", data=csv_data, file_name=f"Saved_Quote_{st.session_state.quote_details['quoteNumber']}.csv",
            mime='text/csv', use_container_width=True, help="Download the current quote table to a CSV file."
        )

        # ... (Row operations, AI summarizer, etc. remain the same)
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- STEP 3 & 4: Details and PDF Generation ---
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        
        st.header("Step 3: Project & Customer Details")

        # --- Your Details ---
        with st.expander("Edit Your Details"):
            st.subheader("Load Staff Profile (Optional)")
            staff_profile_zip = st.file_uploader("Upload Staff Profile (.zip)", type="zip", key="staff_zip")
            if staff_profile_zip:
                try:
                    with zipfile.ZipFile(staff_profile_zip, 'r') as zip_ref:
                        json_file_name = next((f for f in zip_ref.namelist() if f.lower().endswith('.json')), None)
                        if json_file_name:
                            with zip_ref.open(json_file_name) as json_file:
                                details = json.load(json_file)
                                st.session_state.user_details['name'] = details.get('name', '')
                                st.session_state.user_details['job_title'] = details.get('job_title', '')
                                st.session_state.user_details['email'] = details.get('email', '')
                                st.session_state.user_details['phone'] = details.get('phone', '')
                    st.success("Staff Profile loaded!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error reading staff profile: {e}")
            
            # Manual entry fields for user details
            st.session_state.user_details['name'] = st.text_input("Your Name", value=st.session_state.user_details['name'])
            # ... other user detail inputs ...
        
        # --- Customer Details ---
        with st.form("quote_details_form"):
            st.subheader("Load Customer Profile (Optional)")
            customer_profile_zip = st.file_uploader("Upload Customer Profile (.zip)", type="zip", key="customer_zip")
            if customer_profile_zip:
                try:
                    with zipfile.ZipFile(customer_profile_zip, 'r') as zip_ref:
                        json_file_name = next((f for f in zip_ref.namelist() if f.lower().endswith('.json')), None)
                        # ... logic to process customer zip ...
                    st.success("Customer Profile loaded!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error reading customer profile: {e}")
            
            # Manual entry for customer details
            # ... customer detail inputs ...

            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        # --- PDF Generation Logic (Fix Applied) ---
        if submitted and not st.session_state.pdf_ready:
            # When form is submitted, calculate everything and store it in session state
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            # ... calculate totals ...
            html_content = "..." # Your HTML generation logic
            css_content = "..."  # Your CSS
            
            # Store the generated PDF bytes in session state
            st.session_state.pdf_ready = HTML(string=html_content).write_pdf(stylesheets=[CSS(string=css_content)])
            st.rerun() # Rerun to display the download button

        if st.session_state.pdf_ready:
            st.success("✅ Your PDF is ready for download!")
            st.download_button(
                label="⬇️ Download Final Quote PDF",
                data=st.session_state.pdf_ready,
                file_name=f"Quote_{st.session_state.quote_details['quoteNumber']}.pdf",
                mime='application/pdf',
                use_container_width=True
            )
            # Add a button to clear the generated PDF and start over
            if st.button("New PDF"):
                st.session_state.pdf_ready = None
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)
