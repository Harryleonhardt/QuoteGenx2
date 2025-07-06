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

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

# --- FIRESTORE SETUP ---
# MODIFIED: This function now builds the credentials from individual secrets.
# This is a more robust method that avoids TOML parsing issues.
def init_firestore_client():
    """Initializes and returns a Firestore client if credentials are valid."""
    try:
        # Construct the credentials dictionary from individual secrets
        key_dict = {
            "type": st.secrets["type"],
            "project_id": st.secrets["project_id"],
            "private_key_id": st.secrets["private_key_id"],
            # The private_key is a multi-line string; it must be handled carefully.
            # We replace the literal '\n' characters from the secret with actual newlines.
            "private_key": st.secrets["private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["client_email"],
            "client_id": st.secrets["client_id"],
            "auth_uri": st.secrets["auth_uri"],
            "token_uri": st.secrets["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["client_x509_cert_url"]
        }
        # The 'universe_domain' key was added in later gcloud versions, so we add it if it exists.
        if "universe_domain" in st.secrets:
            key_dict["universe_domain"] = st.secrets["universe_domain"]

        creds = service_account.Credentials.from_service_account_info(key_dict)
        db = firestore.Client(credentials=creds)
        return db
    except KeyError as e:
        # This error now specifically means one of the individual keys is missing.
        st.error(f"🚨 A required Firestore secret is missing: '{e.args[0]}'. Please check your Streamlit secrets.", icon="🚨")
        return None
    except Exception as e:
        st.error(f"🚨 An unexpected error occurred while connecting to Firestore: {e}", icon="🚨")
        return None


db = init_firestore_client()

# --- Firestore Helper Functions ---
def save_quote_to_firestore(quote_id, quote_data, status):
    """Saves or updates a quote document in the 'quotes' collection in Firestore."""
    if db is None: return
    quote_data['status'] = status
    # Firestore doesn't accept DataFrames, so we convert it to a list of dictionaries.
    quote_data['quote_items'] = quote_data['quote_items'].to_dict('records')
    db.collection("quotes").document(quote_id).set(quote_data)

def load_all_quotes_from_firestore():
    """Loads all quotes from Firestore, ordered by the most recent date."""
    if db is None: return []
    # Queries the database to get all documents from the 'quotes' collection.
    quotes_ref = db.collection("quotes").order_by("quote_details.date", direction=firestore.Query.DESCENDING).stream()
    quotes = []
    for quote in quotes_ref:
        quote_data = quote.to_dict()
        quote_data['id'] = quote.id # The document ID is the unique quote ID.
        quotes.append(quote_data)
    return quotes

def delete_quote_from_firestore(quote_id):
    """Deletes a specific quote document from Firestore using its ID."""
    if db is None: return
    db.collection("quotes").document(quote_id).delete()

# --- Page Configuration & Logo ---
try:
    logo_file_path = Path(__file__).parent / "AWM Logo (002).png"
    page_icon_img = Image.open(logo_file_path)
except FileNotFoundError:
    page_icon_img = "📄"

st.set_page_config(page_title="AWM Quote Generator", page_icon=page_icon_img, layout="wide")

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

# --- Helper Functions (non-DB) ---
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
        st.error(f"Logo file not found: AWM Logo (002).png", icon="🚨")
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

# --- Gemini API & Password ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found.", icon="🚨")
    st.stop()
if not check_password(): st.stop()


# --- Session State Initialization ---
def clear_current_quote():
    """Resets the session state to a blank quote, assigning a new unique ID."""
    new_quote_number = f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}"
    st.session_state.quote_items = pd.DataFrame(columns=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN"])
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "quoteNumber": new_quote_number, "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
    st.session_state.customer_logo_b64 = None
    st.session_state.active_quote_id = new_quote_number # The active ID is the quote number.

if 'active_quote_id' not in st.session_state:
    clear_current_quote()
if 'user_details' not in st.session_state:
    st.session_state.user_details = {"name": "", "job_title": "Sales", "branch": "AWM Nunawading", "email": "", "phone": "03 8846 2500"}
if 'company_logo_b64' not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(logo_file_path)
if 'sort_by' not in st.session_state:
    st.session_state.sort_by = "Type"

# --- Main Application UI ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64:
        st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"App created by Harry Leonhardt | Prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# --- CENTRALIZED QUOTE DASHBOARD ---
with st.container():
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("☁️ Shared Quote Dashboard")

    if db is None:
        st.warning("Firestore is not connected. The dashboard is disabled.")
    else:
        c1, c2 = st.columns([0.7, 0.3])
        with c1:
            st.info(f"You are currently working on Quote ID: **{st.session_state.active_quote_id}**")
        with c2:
            if st.button("✨ Start a New Blank Quote", use_container_width=True):
                clear_current_quote()
                st.rerun()

        st.subheader("📖 All Quotes")
        all_quotes = load_all_quotes_from_firestore()

        if not all_quotes:
            st.info("No quotes found in the database. Finalize a quote to see it here.")
        else:
            for quote in all_quotes:
                quote_details = quote.get('quote_details', {})
                status = quote.get('status', 'N/A')
                status_color = "green" if status == "Finalized" else "orange"
                
                with st.expander(f"**{quote_details.get('quoteNumber', 'N/A')}** | Customer: **{quote_details.get('customerName', 'N/A')}** | Status: :{status_color}[{status}]"):
                    st.write(f"**Project:** {quote_details.get('projectName', 'N/A')}")
                    st.write(f"**Prepared By:** {quote.get('user_details', {}).get('name', 'N/A')}")
                    st.write(f"**Date:** {quote_details.get('date', 'N/A')}")
                    
                    c1, c2, c3 = st.columns([1, 1, 1])
                    if c1.button("Load this Quote", key=f"load_{quote['id']}", use_container_width=True):
                        st.session_state.quote_details = quote['quote_details']
                        st.session_state.user_details = quote['user_details']
                        st.session_state.quote_items = pd.DataFrame.from_records(quote['quote_items'])
                        st.session_state.active_quote_id = quote['id']
                        st.rerun()
                    
                    if c3.button("❌ Delete this Quote", key=f"del_{quote['id']}", use_container_width=True, type="secondary"):
                        delete_quote_from_firestore(quote['id'])
                        st.toast(f"Deleted quote {quote['id']}", icon="🗑️")
                        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# --- STEP 1: Upload ---
with st.container():
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
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
                except Exception as e:
                    st.error(f"Error processing `{file.name}`: {e}")
            if all_new_items:
                new_df = pd.DataFrame(all_new_items)
                new_df['DISC'], new_df['MARGIN'] = 0.0, 9.0
                st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
                st.success(f"Successfully added {len(all_new_items)} items!")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- Main Content Area (if items exist) ---
if not st.session_state.quote_items.empty:
    # --- STEP 2: Edit & Refine Quote ---
    with st.container():
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header(f"Step 2: Edit & Refine Quote ({st.session_state.active_quote_id})")
        df_to_edit = st.session_state.quote_items.copy()
        df_for_display = _calculate_sell_prices(df_to_edit)
        edited_df = st.data_editor(df_for_display, column_config={"COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),"DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),"MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%"),"Description": st.column_config.TextColumn("Description", width="large"),"SELL_UNIT_EX_GST": st.column_config.NumberColumn("Unit Price Ex GST", disabled=True),"SELL_TOTAL_EX_GST": st.column_config.NumberColumn("Line Price Ex GST", disabled=True)},column_order=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"],num_rows="dynamic",use_container_width=True,key="data_editor")
        if not df_to_edit.equals(edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST'])):
            st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # --- STEP 3: Save or Finalize ---
    with st.container():
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header("Step 3: Save Progress or Finalize Quote")
        if db is not None:
            if st.button("💾 Save as 'In Progress' to Dashboard", use_container_width=True):
                current_quote_data = {"quote_details": st.session_state.quote_details, "user_details": st.session_state.user_details, "quote_items": st.session_state.quote_items}
                save_quote_to_firestore(st.session_state.active_quote_id, current_quote_data, "In Progress")
                st.toast("✅ Quote progress saved to the cloud!", icon="☁️")
                time.sleep(1)
                st.rerun()
        st.divider()
        with st.form("quote_details_form"):
            st.header("Finalize & Generate PDF")
            st.subheader("Customer & Project Details")
            q_details = st.session_state.quote_details
            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details['customerName'])
            q_details['attention'] = c2.text_input("Attention", value=q_details['attention'])
            q_details['projectName'] = c1.text_input("Project Name", value=q_details['projectName'])
            q_details['quoteNumber'] = c2.text_input("Quote Number", value=q_details['quoteNumber'], disabled=True)
            df_for_totals = _calculate_sell_prices(st.session_state.quote_items)
            df_for_totals['GST_AMOUNT'] = df_for_totals['SELL_TOTAL_EX_GST'] * (10 / 100)
            df_for_totals['SELL_TOTAL_INC_GST'] = df_for_totals['SELL_TOTAL_EX_GST'] + df_for_totals['GST_AMOUNT']
            sub_total = df_for_totals['SELL_TOTAL_EX_GST'].sum()
            gst_total = df_for_totals['GST_AMOUNT'].sum()
            grand_total = df_for_totals['SELL_TOTAL_INC_GST'].sum()
            st.metric("Grand Total (inc. GST)", format_currency(grand_total))
            submitted = st.form_submit_button("Generate Final PDF & Save to Dashboard", type="primary", use_container_width=True)

        if submitted:
            if db is not None:
                final_quote_data = {"quote_details": st.session_state.quote_details, "user_details": st.session_state.user_details, "quote_items": st.session_state.quote_items, "grand_total": grand_total}
                save_quote_to_firestore(st.session_state.active_quote_id, final_quote_data, "Finalized")
                st.toast("✅ Quote finalized and saved to dashboard!", icon="🎉")
            
            # PDF Generation Logic
            final_df = _calculate_sell_prices(st.session_state.quote_items)
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

        st.markdown('</div>', unsafe_allow_html=True)
