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
    """Converts an uploaded file into the format Gemini API expects."""
    file.seek(0)
    return {"mime_type": file.type, "data": file.getvalue()}

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
    st.session_state.quote_items = pd.DataFrame(columns=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"])
if "user_details" not in st.session_state:
    st.session_state.user_details = {"name": "", "job_title": "Sales", "branch": "AWM Nunawading", "email": "", "phone": "03 8846 2500"}
if "quote_details" not in st.session_state:
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "address": "", "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}", "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"
if "company_logo_img" not in st.session_state:
    try:
        logo_path = Path(__file__).parent / "AWM Logo (002).png"
        st.session_state.company_logo_img = Image.open(logo_path)
    except FileNotFoundError:
        st.session_state.company_logo_img = None


# --- Main App UI ---
col1, col2 = st.columns([1, 4], vertical_alignment="center")
if st.session_state.company_logo_img:
    col1.image(st.session_state.company_logo_img, width=150)
col2.title("AWM Quote Generator")
st.caption("App created by Harry Leonhardt")
st.divider()

# --- STEP 1: START OR LOAD A QUOTE ---
with st.container(border=True):
    st.header("Step 1: Start or Load a Quote")

    tab1, tab2 = st.tabs(["➕ Start New Quote", "📂 Load Saved Quote"])

    with tab1:
        st.markdown("##### Upload PDFs")
        st.file_uploader(
            "Upload supplier documents", type=['pdf'], accept_multiple_files=True,
            key='file_uploader_state', label_visibility="collapsed"
        )
        
        st.markdown("##### Or Paste Text")
        st.text_area(
            "Paste quote text here",
            key="pasted_text_input",
            placeholder="Copy and paste line items from an email or document...",
            height=150, label_visibility="collapsed"
        )
        
        st.text_area(
            "Special Instructions for AI (Optional)",
            key="custom_prompt_instructions",
            placeholder="e.g., Ignore headers and footers. For 'Supplier X', the part number is always 7 digits.",
            help="Provide specific instructions to improve extraction accuracy for complex or unusual layouts."
        )

        st.divider()
        uploaded_files = st.session_state.get('file_uploader_state', [])
        pasted_text = st.session_state.get('pasted_text_input', '')

        if st.button("Process All Inputs", use_container_width=True, disabled=not (uploaded_files or pasted_text)):
            with st.spinner("Processing all inputs..."):
                all_new_items, failed_inputs = [], []
                
                base_prompt = """
                Your task is to accurately extract all line items from the provided content. Analyze it to understand its structure. Return ONLY a valid JSON array of objects.
                Follow these specific rules for each field:
                1.  **Supplier**: Identify the supplier's company name. If not present, use 'N/A'. Apply this supplier name to all extracted line items.
                2.  **TYPE**: This is a short code (e.g., 'A', 'B', 'C1').
                3.  **CAT_NO (Catalog Number)**: This is a unique product identifier (e.g., 'argo1200em'), not a sentence. It may be under a column named "Part Number" or "Item Code".
                4.  **Description**: This is the descriptive text for the product.
                5.  **QTY (Quantity)**: This is the numerical quantity.
                6.  **COST_PER_UNIT**: This is the price for a single unit.
                """
                
                custom_instructions = st.session_state.get("custom_prompt_instructions", "")
                full_extraction_prompt = f"{base_prompt}\n\nAdditional Instructions:\n{custom_instructions}" if custom_instructions else base_prompt

                json_schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"},"CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]}}
                model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})
                
                # --- Process Uploaded PDF Files ---
                for file in uploaded_files:
                    try:
                        st.write(f"Processing PDF: `{file.name}`...")
                        part = file_to_generative_part(file)
                        response = model.generate_content([full_extraction_prompt, part])
                        extracted_data = json.loads(response.text)
                        if extracted_data:
                            all_new_items.extend(extracted_data)
                    except Exception as e:
                        st.error(f"An error occurred processing `{file.name}`: {e}")
                        failed_inputs.append(f"PDF: {file.name}")
                
                # --- Process Pasted Text ---
                if pasted_text.strip():
                    try:
                        st.write("Processing pasted text...")
                        response = model.generate_content([full_extraction_prompt, pasted_text])
                        extracted_data = json.loads(response.text)
                        if extracted_data:
                            all_new_items.extend(extracted_data)
                    except Exception as e:
                        st.error(f"An error occurred processing the pasted text: {e}")
                        failed_inputs.append("Pasted Text")

                # --- Combine and Finalize ---
                if all_new_items:
                    new_df = pd.DataFrame(all_new_items)
                    new_df['DISC'] = 0.0
                    new_df['MARGIN'] = st.session_state.get("global_margin_input", DEFAULT_MARGIN)
                    st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
                    apply_sorting()
                    st.success(f"Successfully extracted {len(all_new_items)} items!")
                
                if failed_inputs:
                    st.warning(f"Could not process the following inputs: {', '.join(failed_inputs)}")
            
            st.rerun()

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
if "quote_items" in st.session_state and not st.session_state.quote_items.empty:
    with st.container(border=True):
        st.header("Step 2: Edit & Refine Quote")
        st.caption("Edit values directly in the table. Calculations update automatically when you click away.")
        
        st.session_state.quote_items = _calculate_sell_prices(st.session_state.quote_items)

        edited_df = st.data_editor(
            st.session_state.quote_items,
            column_config={
                "COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),
                "DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
                "MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%", min_value=0, max_value=99.9),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "SELL_UNIT_EX_GST": st.column_config.NumberColumn("Unit Price Ex GST", disabled=True, format="$%.2f"),
                "SELL_TOTAL_EX_GST": st.column_config.NumberColumn("Line Price Ex GST", disabled=True, format="$%.2f"),
            },
            column_order=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"],
            num_rows="dynamic", use_container_width=True, key="data_editor"
        )
        st.session_state.quote_items = edited_df
        
        st.divider()
        st.subheader("Table Controls")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Sorting**")
            st.radio("Sort items by:", ("Type", "Supplier"), horizontal=True, key="sort_by", label_visibility="collapsed", on_change=apply_sorting)
        with c2:
            st.write("**Global Margin**")
            sub_c1, sub_c2 = st.columns([0.6, 0.4])
            sub_c1.number_input("Global Margin (%)", value=DEFAULT_MARGIN, min_value=0.0, max_value=99.9, step=1.0, format="%.2f", label_visibility="collapsed", key="global_margin_input")
            sub_c2.button("Apply Margin", use_container_width=True, on_click=apply_global_margin)
        st.divider()
        st.subheader("Row Operations")
        row_options = [f"Row {i+1}: {str(row.get('Description', 'No Description'))[:50]}..." for i, row in st.session_state.quote_items.iterrows()]
        selected_row_str = st.selectbox("Select a row to modify:", options=row_options, index=None, placeholder="Choose a row...")
        if selected_row_str:
            st.session_state.selected_row_index = row_options.index(selected_row_str)
        c1, c2, c3 = st.columns(3)
        c1.button("Add Row Above", use_container_width=True, on_click=add_row, args=(0,), disabled=not selected_row_str)
        c2.button("Add Row Below", use_container_width=True, on_click=add_row, args=(1,), disabled=not selected_row_str)
        c3.button("Delete Selected Row", use_container_width=True, on_click=delete_row, disabled=not selected_row_str)
        
    # --- STEP 3: DETAILS AND PDF ---
    with st.container(border=True):
        st.header("Step 3: Enter Details & Generate PDF")
        with st.expander("Your Details (Prepared By)"):
            st.subheader("Load Staff Profile (Optional)")
            staff_profile_zip = st.file_uploader("Upload Staff Profile (.zip)", type="zip", key="staff_zip", help="Upload a .zip with a .json file containing your details.")
            if staff_profile_zip:
                try:
                    with zipfile.ZipFile(staff_profile_zip, 'r') as zip_ref:
                        json_file_name = next((f for f in zip_ref.namelist() if f and f.lower().endswith('.json')), None)
                        if json_file_name:
                            with zip_ref.open(json_file_name) as json_file:
                                details = json.load(json_file)
                                st.session_state.user_details['name'] = details.get('name', '')
                                st.session_state.user_details['job_title'] = details.get('job_title', '')
                                st.session_state.user_details['email'] = details.get('email', '')
                                st.session_state.user_details['phone'] = details.get('phone', '')
                    st.success("Staff Profile loaded!")
                except Exception as e:
                    st.error(f"Error reading staff profile: {e}")
            c1, c2 = st.columns(2)
            st.session_state.user_details['name'] = c1.text_input("Your Name", value=st.session_state.user_details.get('name', ''))
            st.session_state.user_details['job_title'] = c2.text_input("Job Title", value=st.session_state.user_details.get('job_title', ''))
            st.session_state.user_details['email'] = c1.text_input("Your Email", value=st.session_state.user_details.get('email', ''))
            st.session_state.user_details['phone'] = c2.text_input("Your Phone", value=st.session_state.user_details.get('phone', ''))
            st.session_state.user_details['branch'] = c1.text_input("Branch", value=st.session_state.user_details.get('branch', ''))
        st.divider()
        st.header("Customer & Project Details")
        st.subheader("Load Customer Profile (Optional)")
        customer_profile_zip = st.file_uploader("Upload Customer Profile (.zip)", type="zip", key="customer_zip", help="Upload a .zip with customer details and logo.")
        if customer_profile_zip:
            try:
                with zipfile.ZipFile(customer_profile_zip, 'r') as zip_ref:
                    json_file_name = next((f for f in zip_ref.namelist() if f and f.lower().endswith('.json')), None)
                    if json_file_name:
                        with zip_ref.open(json_file_name) as json_file:
                            details = json.load(json_file)
                            st.session_state.quote_details['customerName'] = details.get('customerName', '')
                            st.session_state.quote_details['attention'] = details.get('attention', '')
                            st.session_state.quote_details['address'] = details.get('address', '')
                    logo_file_name = next((f for f in zip_ref.namelist() if f and f.lower().endswith(('.png', '.jpg', '.jpeg'))), None)
                    if logo_file_name:
                        with zip_ref.open(logo_file_name) as logo_file:
                            st.session_state.customer_logo_b64 = base64.b64encode(logo_file.read()).decode()
                st.success("Customer Profile loaded!")
            except Exception as e:
                st.error(f"Error reading .zip file: {e}")
        with st.form("quote_details_form"):
            st.subheader("Enter Details Manually")
            q_details = st.session_state.quote_details
            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details.get('customerName', ''))
            q_details['attention'] = c2.text_input("Attention", value=q_details.get('attention', ''))
            q_details['address'] = st.text_area("Customer Address", value=q_details.get('address', ''), height=100)
            q_details['projectName'] = st.text_input("Project Name", value=q_details.get('projectName', ''))
            q_details['quoteNumber'] = st.text_input("Quote Number", value=q_details.get('quoteNumber', ''))
            if st.session_state.get("customer_logo_b64"):
                st.write("Customer Logo Preview:")
                st.image(f"data:image/png;base64,{st.session_state.get('customer_logo_b64')}", width=150)
            st.divider()
            st.header("Review Totals & Generate PDF")
            df_for_totals = _calculate_sell_prices(st.session_state.quote_items)
            sub_total = df_for_totals['SELL_TOTAL_EX_GST'].sum()
            gst_total = sub_total * 0.10
            grand_total = sub_total + gst_total
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Cost (Pre-Margin)", format_currency((df_for_totals['COST_PER_UNIT'] * (1 - df_for_totals['DISC'] / 100) * df_for_totals['QTY']).sum()))
            c2.metric("Sub-Total (ex. GST)", format_currency(sub_total))
            c3.metric("GST (10%)", format_currency(gst_total))
            c4.metric("Grand Total (inc. GST)", format_currency(grand_total))
            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)
        if submitted:
            st.info("Generating PDF...")
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            items_html = ""
            for i, row in final_df.iterrows():
                items_html += f"""
                <tr class="border-b border-gray-200">
                    <td class="p-2 align-top">{i + 1}</td><td class="p-2 align-top">{row.get('TYPE','')}</td>
                    <td class="p-2 align-top">{row.get('QTY','')}</td><td class="p-2 align-top">{row.get('Supplier','')}</td>
                    <td class="p-2 w-1/3 align-top"><strong class="block text-xs font-bold">{row.get('CAT_NO','')}</strong><span>{row.get('Description','')}</span></td>
                    <td class="p-2 text-right align-top">{format_currency(row.get('SELL_UNIT_EX_GST'))}</td>
                    <td class="p-2 text-right align-top">{format_currency(row.get('SELL_TOTAL_EX_GST'))}</td>
                </tr>"""
            company_logo_html = ""
            if st.session_state.get("company_logo_img"):
                buffered = BytesIO()
                st.session_state.company_logo_img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                company_logo_html = f'<img src="data:image/png;base64,{img_str}" alt="Company Logo" class="h-16 mb-4">'
            customer_logo_html = f'<img src="data:image/png;base64,{st.session_state.get("customer_logo_b64")}" alt="Customer Logo" class="max-h-24 object-contain">' if st.session_state.get("customer_logo_b64") else ''
            address_html = q_details.get('address', '').replace('\n', '<br>')
            quote_to_html = f"""
                <h2 class="font-bold text-gray-800 mb-2">QUOTE TO:</h2>
                <p class="text-gray-700">{q_details.get('customerName','')}</p><p class="text-gray-700">{address_html}</p>
                <p class="text-gray-700 mt-2"><strong class="font-bold text-gray-800">Attn:</strong> {q_details.get("attention", "N/A")}</p>"""
            quote_html = f"""
            <!DOCTYPE html><html lang="en">
            <head><meta charset="UTF-8"><title>Quote {q_details.get('quoteNumber')}</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"></head>
            <body>
                <div class="bg-white">
                    <header class="flex justify-between items-start mb-8 border-b border-gray-300 pb-8">
                        <div>{company_logo_html}<h1 class="text-2xl font-bold text-gray-800">{st.session_state.user_details.get('branch','')}</h1>
                            <p class="text-sm text-gray-600">31-33 Rooks Road, Nunawading, 3131</p>
                            <p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p></div>
                        <div class="text-right">{customer_logo_html}<h2 class="text-3xl font-bold text-gray-700 mt-4">QUOTATION</h2></div>
                    </header>
                    <section class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">{quote_to_html}</div>
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">PROJECT:</strong> {q_details.get('projectName')}</p>
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">QUOTE #:</strong> {q_details.get('quoteNumber')}</p>
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">DATE:</strong> {q_details.get('date')}</p></div>
                    </section>
                    <main><table class="w-full text-left text-sm" style="table-layout: auto;">
                            <thead class="bg-slate-800 text-white"><tr>
                                <th class="p-2 rounded-tl-lg">ITEM</th><th class="p-2">TYPE</th><th class="p-2">QTY</th><th class="p-2">BRAND</th>
                                <th class="p-2 w-1/3">PRODUCT DETAILS</th><th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right rounded-tr-lg">TOTAL EX GST</th>
                            </tr></thead><tbody class="divide-y divide-gray-200">{items_html}</tbody></table></main>
                    <footer class="mt-8 flex justify-end" style="page-break-inside: avoid;"><div class="w-2/5">
                            <div class="flex justify-between p-2 bg-gray-100 border-b border-gray-200"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span class="text-gray-800">{format_currency(sub_total)}</span></div>
                            <div class="flex justify-between p-2 bg-gray-100 border-b border-gray-200"><span class="font-bold text-gray-800">GST (10%):</span><span class="text-gray-800">{format_currency(gst_total)}</span></div>
                            <div class="flex justify-between p-3 bg-gray-200 rounded-b-lg"><span class="font-bold text-gray-900 text-lg">Grand Total (Inc GST):</span><span class="font-bold text-gray-900 text-lg">{format_currency(grand_total)}</span></div>
                    </div></footer>
                    <div class="mt-12 pt-8" style="page-break-inside: avoid;">
                        <h3 class="font-bold text-gray-800">Prepared For You By:</h3>
                        <p class="text-gray-700 mt-2">{st.session_state.user_details.get('name')}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details.get('job_title')}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details.get('branch')}</p>
                        <p class="mt-2 text-sm"><strong>Email:</strong> {st.session_state.user_details.get('email')}</p>
                        <p class="text-sm"><strong>Phone:</strong> {st.session_state.user_details.get('phone')}</p></div>
                    <div class="mt-12 text-xs text-gray-500 border-t border-gray-300 pt-4" style="page-break-inside: avoid;">
                        <h3 class="font-bold mb-2">CONDITIONS:</h3>
                        <p>This offer is valid for 30 days. All goods are sold under MMEM's Terms and Conditions of Sale. Any changes in applicable taxes (GST) or tariffs which may occur will be to your account.</p></div></div></body></html>"""
            pdf_css = """@page { size: A4; margin: 1.5cm; } body { font-family: 'Inter', sans-serif; } thead { display: table-header-group; } tfoot { display: table-footer-group; } table { width: 100%; border-collapse: collapse; } tr { page-break-inside: avoid !important; } th, td { text-align: left; padding: 4px 6px; vertical-align: top; } th { background-color: #1e2b3b; color: white; } td.text-right, th.text-right { text-align: right; }"""
            combined_css = [CSS(string='@import url("https://cdnjs.cloudflare.com/ajax/libs/tailwindcss/2.2.19/tailwind.min.css");'), CSS(string=pdf_css)]
            try:
                pdf_bytes = HTML(string=quote_html).write_pdf(stylesheets=combined_css)
                st.download_button(
                    label="✅ Download Final Quote as PDF", data=pdf_bytes, file_name=f"Quote_{q_details.get('quoteNumber', 'quote')}.pdf",
                    mime='application/pdf', use_container_width=True
                )
            except Exception as e:
                st.error(f"Failed to generate PDF: {e}")
