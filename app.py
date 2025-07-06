import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import re
import time
from io import BytesIO
from pathlib import Path
from PIL import Image
from google.oauth2 import service_account
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import Transaction
from google.cloud.firestore_v1.base_query import FieldFilter

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

# --- FIRESTORE SETUP ---
def init_firestore_client():
    """Initializes and returns a Firestore client if credentials are valid."""
    try:
        key_dict = {
            "type": st.secrets["type"], "project_id": st.secrets["project_id"],
            "private_key_id": st.secrets["private_key_id"],
            "private_key": st.secrets["private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["client_email"], "client_id": st.secrets["client_id"],
            "auth_uri": st.secrets["auth_uri"], "token_uri": st.secrets["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["client_x509_cert_url"]
        }
        if "universe_domain" in st.secrets:
            key_dict["universe_domain"] = st.secrets["universe_domain"]
        creds = service_account.Credentials.from_service_account_info(key_dict)
        db = firestore.Client(credentials=creds)
        return db
    except Exception as e:
        st.error(f"🚨 Firestore connection failed. Please check your secrets. Error: {e}", icon="🚨")
        return None

db = init_firestore_client()

# --- Firestore Helper Functions ---

@firestore.transactional
def get_next_quote_number_transaction(transaction, counter_ref):
    """
    Atomically increments the quote number counter in a transaction.
    This prevents race conditions where two users might get the same number.
    """
    snapshot = counter_ref.get(transaction=transaction)
    current_number = snapshot.get("current_number")
    new_number = current_number + 1
    transaction.update(counter_ref, {"current_number": new_number})
    return f"Q{new_number}"

def get_next_quote_number():
    """Gets the next sequential quote number from Firestore."""
    if db is None: return f"Q-Error-{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}"
    counter_ref = db.collection("counters").document("quote_counter")
    transaction = db.transaction()
    return get_next_quote_number_transaction(transaction, counter_ref)

def save_document(collection, doc_id, data):
    """Generic function to save a document to a collection."""
    if db is None: return
    db.collection(collection).document(doc_id).set(data, merge=True)

def load_collection(collection_name):
    """Generic function to load all documents from a collection."""
    if db is None: return []
    docs_ref = db.collection(collection_name).stream()
    return [doc.to_dict() for doc in docs_ref]

def delete_quote_from_firestore(quote_id):
    if db is None: return
    db.collection("quotes").document(quote_id).delete()

# --- Page Configuration & Styling ---
try:
    logo_file_path = Path(__file__).parent / "AWM Logo (002).png"
    page_icon_img = Image.open(logo_file_path)
except FileNotFoundError:
    page_icon_img = "📄"
st.set_page_config(page_title="AWM Quote Generator", page_icon=page_icon_img, layout="wide")
st.markdown("""<style>... [CSS unchanged] ...</style>""", unsafe_allow_html=True) # Your CSS here

# --- Helper Functions (non-DB) ---
def file_to_generative_part(file):
    return {"mime_type": file.type, "data": BytesIO(file.getvalue()).read()}
def image_to_base64(image_file):
    if image_file is not None: return base64.b64encode(image_file.getvalue()).decode()
    return None
def get_logo_base64(file_path):
    try:
        with open(file_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError: return None
def format_currency(num):
    if pd.isna(num) or num is None: return "$0.00"
    return f"${num:,.2f}"
def check_password():
    if st.session_state.get("password_correct", False): return True
    st.header("Login")
    password = st.text_input("Enter Password", type="password")
    if password == "AWM374":
        st.session_state["password_correct"] = True; st.rerun()
    elif password: st.error("Password incorrect.")
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

# --- Gemini API & Password ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except Exception: st.error("🚨 Gemini API Key not found."); st.stop()
if not check_password(): st.stop()

# --- Session State Initialization ---
def clear_current_quote():
    new_quote_number = get_next_quote_number()
    st.session_state.quote_items = pd.DataFrame(columns=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN"])
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "quoteNumber": new_quote_number, "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
    st.session_state.customer_logo_b64 = None
    st.session_state.active_quote_id = new_quote_number

if 'active_quote_id' not in st.session_state: clear_current_quote()
if 'user_details' not in st.session_state: st.session_state.user_details = {"name": "", "job_title": "Sales", "branch": "AWM Nunawading", "email": "", "phone": "03 8846 2500"}
if 'company_logo_b64' not in st.session_state: st.session_state.company_logo_b64 = get_logo_base64(logo_file_path)
if 'sort_by' not in st.session_state: st.session_state.sort_by = "Type"

# --- Main Application UI ---
col1, col2 = st.columns([1, 4]); col1.image(st.session_state.company_logo_b64, width=150) if st.session_state.company_logo_b64 else None; col2.title("AWM Quote Generator"); col2.caption(f"App created by Harry Leonhardt | Prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**"); st.divider()

# --- CENTRALIZED QUOTE DASHBOARD ---
with st.container(border=True):
    st.header("☁️ Shared Quote Dashboard")
    if db is None: st.warning("Firestore is not connected. Dashboard is disabled.")
    else:
        c1, c2 = st.columns([0.7, 0.3]); c1.info(f"Working on Quote ID: **{st.session_state.active_quote_id}**");
        if c2.button("✨ Start New Blank Quote", use_container_width=True): clear_current_quote(); st.rerun()
        st.subheader("📖 All Quotes"); all_quotes = load_collection("quotes")
        if not all_quotes: st.info("No quotes found.")
        else:
            for quote in sorted(all_quotes, key=lambda q: q.get('quote_details', {}).get('quoteNumber', '0'), reverse=True):
                details = quote.get('quote_details', {}); status = quote.get('status', 'N/A'); color = "green" if status == "Finalized" else "orange"
                with st.expander(f"**{details.get('quoteNumber', 'N/A')}** | Customer: **{details.get('customerName', 'N/A')}** | Status: :{color}[{status}]"):
                    st.write(f"**Project:** {details.get('projectName', 'N/A')}"); st.write(f"**Prepared By:** {quote.get('user_details', {}).get('name', 'N/A')}"); st.write(f"**Date:** {details.get('date', 'N/A')}")
                    c1, _, c3 = st.columns([1, 1, 1])
                    if c1.button("Load", key=f"load_{quote['id']}", use_container_width=True):
                        st.session_state.quote_details = quote['quote_details']; st.session_state.user_details = quote['user_details']; st.session_state.quote_items = pd.DataFrame.from_records(quote['quote_items']); st.session_state.active_quote_id = quote['id']; st.rerun()
                    if c3.button("Delete", key=f"del_{quote['id']}", use_container_width=True, type="secondary"):
                        delete_quote_from_firestore(quote['id']); st.toast(f"Deleted {quote['id']}", icon="🗑️"); st.rerun()

# --- STEP 1: Upload ---
with st.container(border=True):
    st.header("Step 1: Upload Supplier Quotes to Current Quote")
    uploaded_files = st.file_uploader("Upload files", type=['pdf', 'txt'], accept_multiple_files=True, label_visibility="collapsed")
    if st.button("Process & Add to Current Quote", use_container_width=True, disabled=not uploaded_files):
        # ... [File processing logic is unchanged] ...
        pass

# --- Main Content Area (if items exist) ---
if not st.session_state.quote_items.empty:
    # --- STEP 2: Edit & Refine Quote ---
    with st.container(border=True):
        # ... [Data editor and table controls are unchanged] ...
        pass

    # --- STEP 3: Details, Save, Finalize ---
    with st.container(border=True):
        st.header("Step 3: Details, Save, and Finalize")

        # --- NEW: User and Customer Details Management ---
        users = load_collection("users"); customers = load_collection("customers")
        user_names = ["<New User>"] + [u['name'] for u in users]
        customer_names = ["<New Customer>"] + [c['customerName'] for c in customers]
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("👤 Your Details")
            selected_user_name = st.selectbox("Select Your Name", options=user_names, index=0)
            if selected_user_name == "<New User>":
                st.session_state.user_details['name'] = st.text_input("Your Name", key="new_user_name")
                st.session_state.user_details['job_title'] = st.text_input("Job Title", "Sales", key="new_user_title")
                st.session_state.user_details['branch'] = st.text_input("Branch", "AWM Nunawading", key="new_user_branch")
                st.session_state.user_details['email'] = st.text_input("Your Email", key="new_user_email")
                st.session_state.user_details['phone'] = st.text_input("Your Phone", "03 8846 2500", key="new_user_phone")
                if st.button("Save New User"):
                    save_document("users", st.session_state.user_details['name'], st.session_state.user_details)
                    st.toast("User saved!"); time.sleep(1); st.rerun()
            else:
                user_data = next((u for u in users if u['name'] == selected_user_name), None)
                if user_data: st.session_state.user_details = user_data
        
        with c2:
            st.subheader("🏢 Customer Details")
            q_details = st.session_state.quote_details
            selected_customer_name = st.selectbox("Select Customer", options=customer_names, index=0)
            if selected_customer_name == "<New Customer>":
                q_details['customerName'] = st.text_input("Customer Name", key="new_cust_name")
                customer_logo_file = st.file_uploader("Upload Customer Logo", type=['png', 'jpg', 'jpeg'])
                if customer_logo_file: st.session_state.customer_logo_b64 = image_to_base64(customer_logo_file)
                if st.button("Save New Customer"):
                    new_customer_data = {'customerName': q_details['customerName'], 'logo_b64': st.session_state.customer_logo_b64}
                    save_document("customers", q_details['customerName'], new_customer_data)
                    st.toast("Customer saved!"); time.sleep(1); st.rerun()
            else:
                customer_data = next((c for c in customers if c['customerName'] == selected_customer_name), None)
                if customer_data:
                    q_details['customerName'] = customer_data['customerName']
                    st.session_state.customer_logo_b64 = customer_data.get('logo_b64')
            
            q_details['attention'] = st.text_input("Attention", value=q_details.get('attention', ''))
            q_details['projectName'] = st.text_input("Project Name", value=q_details.get('projectName', ''))
            st.text_input("Quote Number", value=q_details['quoteNumber'], disabled=True)
            if st.session_state.customer_logo_b64: st.image(f"data:image/png;base64,{st.session_state.customer_logo_b64}", width=150)

        st.divider()

        # --- Save or Finalize Actions ---
        if db is not None:
            if st.button("💾 Save as 'In Progress' to Dashboard", use_container_width=True):
                current_quote_data = {"quote_details": st.session_state.quote_details, "user_details": st.session_state.user_details, "quote_items": st.session_state.quote_items}
                save_document("quotes", st.session_state.active_quote_id, current_quote_data)
                st.toast("✅ Quote progress saved!", icon="☁️"); time.sleep(1); st.rerun()
        
        with st.form("finalize_form"):
            st.header("Finalize & Generate PDF")
            df_for_totals = _calculate_sell_prices(st.session_state.quote_items)
            df_for_totals['GST_AMOUNT'] = df_for_totals['SELL_TOTAL_EX_GST'] * 0.10
            df_for_totals['SELL_TOTAL_INC_GST'] = df_for_totals['SELL_TOTAL_EX_GST'] + df_for_totals['GST_AMOUNT']
            grand_total = df_for_totals['SELL_TOTAL_INC_GST'].sum()
            st.metric("Grand Total (inc. GST)", format_currency(grand_total))
            submitted = st.form_submit_button("Generate PDF & Save as Finalized", type="primary", use_container_width=True)

        if submitted:
            if db is not None:
                final_quote_data = {"quote_details": st.session_state.quote_details, "user_details": st.session_state.user_details, "quote_items": st.session_state.quote_items, "grand_total": grand_total}
                save_document("quotes", st.session_state.active_quote_id, final_quote_data)
                st.toast("✅ Quote finalized!", icon="🎉")
            
            # --- PDF Generation Logic ---
            # ... [Unchanged PDF generation logic] ...
            clear_current_quote()
            time.sleep(1)
            st.rerun()
