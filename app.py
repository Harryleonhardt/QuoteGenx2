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
    # Ensure DataFrame is converted to list of dicts before saving
    if 'quote_items' in data and isinstance(data['quote_items'], pd.DataFrame):
        data['quote_items'] = data['quote_items'].to_dict('records')
    db.collection(collection).document(doc_id).set(data, merge=True)


def load_collection(collection_name):
    """Generic function to load all documents from a collection."""
    if db is None: return []
    docs_ref = db.collection(collection_name).stream()
    docs = []
    for doc in docs_ref:
        doc_data = doc.to_dict()
        doc_data['id'] = doc.id
        docs.append(doc_data)
    return docs


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
st.markdown("""<style>
    .stApp { background-color: #f8f9fa; font-family: 'Inter', sans-serif; }
    .step-container { border: 1px solid #dee2e6; border-radius: 0.8rem; padding: 1.5rem 2rem; background-color: white; box-shadow: 0 4px 12px -1px rgb(0 0 0 / 0.05); margin-bottom: 2rem; }
    h1, h2, h3 { color: #343a40; }
    .stButton > button { background-color: #a0c4ff; color: #002b6e !important; border: 1px solid #a0c4ff !important; border-radius: 0.375rem; font-weight: 600; }
    .stButton > button:hover { background-color: #8ab4f8; border-color: #8ab4f8; color: #002b6e !important; }
    .stButton > button:disabled { background-color: #ced4da !important; color: #6c757d !important; border-color: #ced4da !important; opacity: 0.7; }
    .stButton > button[kind="primary"] { background-color: #a7d7c5; border-color: #a7d7c5; color: #003e29 !important; }
    .stButton > button[kind="primary"]:hover { background-color: #8abbac; border-color: #8abbac; color: #003e29 !important; }
    [data-testid="stFileUploader"] { padding: 1rem; background-color: #f1f3f5; border-radius: 0.5rem; }
</style>""", unsafe_allow_html=True)

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
col1, col2 = st.columns([1, 4]);
if st.session_state.company_logo_b64:
    # FIXED: Explicitly create a data URI to prevent misinterpretation by st.image
    logo_data_uri = f"data:image/png;base64,{st.session_state.company_logo_b64}"
    col1.image(logo_data_uri, width=150)
col2.title("AWM Quote Generator")
col2.caption(f"App created by Harry Leonhardt | Prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**");
st.divider()

# --- CENTRALIZED QUOTE DASHBOARD ---
with st.container(border=True):
    st.header("☁️ Shared Quote Dashboard")
    if db is None:
        st.warning("Firestore is not connected. Dashboard is disabled.")
    else:
        c1, c2 = st.columns([0.7, 0.3])
        c1.info(f"Working on Quote ID: **{st.session_state.active_quote_id}**")
        if c2.button("✨ Start New Blank Quote", use_container_width=True):
            clear_current_quote()
            st.rerun()

        st.subheader("📖 All Quotes")
        
        search_term = st.text_input("Search Quotes (by #, Customer, or Project)", key="search_quotes", placeholder="Type here to search...")

        all_quotes = load_collection("quotes")
        
        if search_term:
            search_term_lower = search_term.lower()
            filtered_quotes = [
                q for q in all_quotes 
                if search_term_lower in q.get('quote_details', {}).get('quoteNumber', '').lower() or
                   search_term_lower in q.get('quote_details', {}).get('customerName', '').lower() or
                   search_term_lower in q.get('quote_details', {}).get('projectName', '').lower()
            ]
        else:
            filtered_quotes = all_quotes

        if not filtered_quotes:
            st.info("No quotes found matching your search.")
        else:
            sorted_quotes = sorted(filtered_quotes, key=lambda q: int(q.get('quote_details', {}).get('quoteNumber', 'Q0').replace('Q','')), reverse=True)

            for quote in sorted_quotes:
                details = quote.get('quote_details', {})
                status = quote.get('status', 'N/A')
                color = "green" if status == "Finalized" else "orange"
                with st.expander(f"**{details.get('quoteNumber', 'N/A')}** | Customer: **{details.get('customerName', 'N/A')}** | Status: :{color}[{status}]"):
                    st.write(f"**Project:** {details.get('projectName', 'N/A')}")
                    st.write(f"**Prepared By:** {quote.get('user_details', {}).get('name', 'N/A')}")
                    st.write(f"**Date:** {details.get('date', 'N/A')}")
                    
                    c1, c2, c3 = st.columns([1, 1, 1])
                    if c1.button("Load", key=f"load_{quote['id']}", use_container_width=True):
                        st.session_state.quote_details = quote['quote_details']
                        st.session_state.user_details = quote['user_details']
                        st.session_state.quote_items = pd.DataFrame.from_records(quote['quote_items'])
                        st.session_state.active_quote_id = quote['id']
                        st.rerun()
                    
                    if c2.button("Duplicate", key=f"dup_{quote['id']}", use_container_width=True):
                        new_quote_number = get_next_quote_number()
                        new_quote_data = {
                            "user_details": quote.get('user_details', {}),
                            "quote_items": pd.DataFrame.from_records(quote.get('quote_items', [])),
                            "quote_details": {
                                "customerName": details.get('customerName', ''),
                                "attention": details.get('attention', ''),
                                "projectName": f"{details.get('projectName', '')} (Copy)",
                                "quoteNumber": new_quote_number,
                                "date": pd.Timestamp.now().strftime('%d/%m/%Y')
                            }
                        }
                        save_document("quotes", new_quote_number, new_quote_data)
                        st.toast(f"Duplicated as new quote {new_quote_number}", icon="✨")
                        time.sleep(1); st.rerun()

                    if c3.button("Delete", key=f"del_{quote['id']}", use_container_width=True, type="secondary"):
                        delete_quote_from_firestore(quote['id'])
                        st.toast(f"Deleted {quote['id']}", icon="🗑️"); st.rerun()

# --- STEP 1: Upload ---
with st.container(border=True):
    st.header("Step 1: Upload Supplier Quotes to Current Quote")
    uploaded_files = st.file_uploader("Upload files", type=['pdf', 'txt'], accept_multiple_files=True, label_visibility="collapsed")
    if st.button("Process & Add to Current Quote", use_container_width=True, disabled=not uploaded_files):
        with st.spinner(f"Processing {len(uploaded_files)} file(s)..."):
            all_new_items = []
            extraction_prompt = ("From the provided document, extract all line items. For each item, extract: TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. Return ONLY a valid JSON array of objects. Ensure QTY and COST_PER_UNIT are numbers.")
            json_schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"}, "CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]}}
            model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})
            for file in uploaded_files:
                try:
                    part = file_to_generative_part(file)
                    response = model.generate_content([extraction_prompt, part])
                    extracted_data = json.loads(response.text)
                    if extracted_data: all_new_items.extend(extracted_data)
                except Exception as e: st.error(f"Error processing `{file.name}`: {e}")
            if all_new_items:
                new_df = pd.DataFrame(all_new_items)
                new_df['DISC'], new_df['MARGIN'] = 0.0, 9.0
                st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
                st.success(f"Successfully added {len(all_new_items)} items!"); st.rerun()

# --- Main Content Area (if items exist) ---
if not st.session_state.quote_items.empty:
    # --- STEP 2: Edit & Refine Quote ---
    with st.container(border=True):
        st.header(f"Step 2: Edit & Refine Quote ({st.session_state.active_quote_id})")
        df_to_edit = st.session_state.quote_items.copy()
        df_for_display = _calculate_sell_prices(df_to_edit)
        edited_df = st.data_editor(df_for_display, column_config={"COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),"DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),"MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%"),"Description": st.column_config.TextColumn("Description", width="large"),"SELL_UNIT_EX_GST": st.column_config.NumberColumn("Unit Price Ex GST", disabled=True),"SELL_TOTAL_EX_GST": st.column_config.NumberColumn("Line Price Ex GST", disabled=True)},column_order=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"],num_rows="dynamic",use_container_width=True,key="data_editor")
        if not df_to_edit.equals(edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST'])):
            st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
            st.rerun()

    # --- STEP 3: Details, Save, Finalize ---
    with st.container(border=True):
        st.header("Step 3: Details, Save, and Finalize")

        users = load_collection("users"); customers = load_collection("customers")
        user_names = ["<New User>"] + sorted([u['name'] for u in users])
        customer_names = ["<New Customer>"] + sorted([c['customerName'] for c in customers])
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("👤 Your Details")
            selected_user_name = st.selectbox("Select Your Name", options=user_names, index=0, key="user_selector")
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
            selected_customer_name = st.selectbox("Select Customer", options=customer_names, index=0, key="customer_selector")
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
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            sub_total = df_for_totals['SELL_TOTAL_EX_GST'].sum()
            gst_total = df_for_totals['GST_AMOUNT'].sum()
            items_html = ""
            for i, row in final_df.iterrows():
                items_html += f"""<tr class="border-b border-gray-200"><td class="p-2 align-top">{i + 1}</td><td class="p-2 align-top">{row['TYPE']}</td><td class="p-2 align-top">{row['QTY']}</td><td class="p-2 align-top">{row['Supplier']}</td><td class="p-2 w-1/3 align-top"><strong class="block text-xs font-bold">{row['CAT_NO']}</strong><span>{row['Description']}</span></td><td class="p-2 text-right align-top">{format_currency(row['SELL_UNIT_EX_GST'])}</td><td class="p-2 text-right align-top">{format_currency(row['SELL_TOTAL_EX_GST'])}</td></tr>"""
            company_logo_html = f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" alt="Company Logo" class="h-16 mb-4">' if st.session_state.company_logo_b64 else ''
            customer_logo_html = f'<img src="data:image/png;base64,{st.session_state.customer_logo_b64}" alt="Customer Logo" class="max-h-24 object-contain">' if st.session_state.customer_logo_b64 else ''
            branch_address_html = '<p class="text-sm text-gray-600">31-33 Rooks Road, Nunawading, 3131</p>' if st.session_state.user_details['branch'] == "AWM Nunawading" else ''
            attention_html = f'<p class="text-gray-700"><strong class="font-bold text-gray-800">Attn:</strong> {q_details["attention"] or "N/A"}</p>'
            quote_html = f"""
            <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Quote {q_details['quoteNumber']}</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"></head><body>
            <div class="bg-white"><header class="flex justify-between items-start mb-8 border-b border-gray-300 pb-8"><div>{company_logo_html}<h1 class="text-2xl font-bold text-gray-800">{st.session_state.user_details['branch']}</h1>{branch_address_html}<p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p></div><div class="text-right">{customer_logo_html}<h2 class="text-3xl font-bold text-gray-700 mt-4">QUOTATION</h2></div></header><section class="grid grid-cols-2 gap-6 mb-8"><div class="bg-gray-50 p-4 rounded-lg border border-gray-200"><h2 class="font-bold text-gray-800 mb-2">QUOTE TO:</h2><p class="text-gray-700">{q_details['customerName']}</p>{attention_html}</div><div class="bg-gray-50 p-4 rounded-lg border border-gray-200"><p class="text-gray-700"><strong class="font-bold text-gray-800">PROJECT:</strong> {q_details['projectName']}</p><p class="text-gray-700"><strong class="font-bold text-gray-800">QUOTE #:</strong> {q_details['quoteNumber']}</p><p class="text-gray-700"><strong class="font-bold text-gray-800">DATE:</strong> {q_details['date']}</p></div></section><main><table class="w-full text-left text-sm" style="table-layout: auto;"><thead class="bg-slate-800 text-white"><tr><th class="p-2 rounded-tl-lg">ITEM</th><th class="p-2">TYPE</th><th class="p-2">QTY</th><th class="p-2">BRAND</th><th class="p-2 w-1/3">PRODUCT DETAILS</th><th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right rounded-tr-lg">TOTAL EX GST</th></tr></thead><tbody class="divide-y divide-gray-200">{items_html}</tbody></table></main><footer class="mt-8 flex justify-end" style="page-break-inside: avoid;"><div class="w-2/5"><div class="flex justify-between p-2 bg-gray-100"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span class="text-gray-800">{format_currency(sub_total)}</span></div><div class="flex justify-between p-2"><span class="font-bold text-gray-800">GST (10%):</span><span class="text-gray-800">{format_currency(gst_total)}</span></div><div class="flex justify-between p-4 bg-slate-800 text-white font-bold text-lg rounded-b-lg"><span>Grand Total (Inc GST):</span><span>{format_currency(grand_total)}</span></div></div></footer><div class="mt-12 pt-8" style="page-break-inside: avoid;"><h3 class="font-bold text-gray-800">Prepared For You By:</h3><p class="text-gray-700 mt-2">{st.session_state.user_details['name']}</p><p class="text-gray-600 text-sm">{st.session_state.user_details['job_title']}</p><p class="text-gray-600 text-sm">{st.session_state.user_details['branch']}</p><p class="mt-2 text-sm"><strong>Email:</strong> {st.session_state.user_details['email']}</p><p class="text-sm"><strong>Phone:</strong> {st.session_state.user_details['phone']}</p></div><div class="mt-12 text-xs text-gray-500 border-t border-gray-300 pt-4" style="page-break-inside: avoid;"><h3 class="font-bold mb-2">CONDITIONS:</h3><p>This offer is valid for 30 days. All goods are sold under MMEM's Terms and Conditions of Sale. Any changes in applicable taxes (GST) or tariffs which may occur will be to your account.</p></div></div></body></html>
            """
            pdf_css = """@page { size: A4; margin: 1.5cm; } body { font-family: 'Inter', sans-serif; } thead { display: table-header-group; } tfoot { display: table-footer-group; } table { width: 100%; border-collapse: collapse; } tr { page-break-inside: avoid !important; } th, td { text-align: left; padding: 4px 6px; vertical-align: top; } th { background-color: #1e293b; color: white; } td.text-right, th.text-right { text-align: right; }"""
            combined_css = [CSS(string='@import url("https://cdnjs.cloudflare.com/ajax/libs/tailwindcss/2.2.19/tailwind.min.css");'), CSS(string=pdf_css)]
            pdf_bytes = HTML(string=quote_html).write_pdf(stylesheets=combined_css)
            st.download_button(label="✅ Download Final Quote as PDF",data=pdf_bytes,file_name=f"Quote_{q_details['quoteNumber']}.pdf",mime='application/pdf',use_container_width=True)
            
            clear_current_quote()
            time.sleep(1)
            st.rerun()
