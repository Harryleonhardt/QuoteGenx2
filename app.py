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

# --- AMENDED: Callback for st.data_editor ---
def update_quote_items_from_editor():
    """Callback function to update session state from the data editor."""
    # The data editor's state is accessed via its key in st.session_state
    edited_data = st.session_state["data_editor"]
    df = pd.DataFrame(edited_data)
    
    # Define the columns that should be persisted in the state
    original_cols = ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN"]
    
    # Filter to only include columns that exist in the edited dataframe
    cols_to_keep = [col for col in original_cols if col in df.columns]
    
    # Update the session state, ensuring index is reset
    st.session_state.quote_items = df[cols_to_keep].reset_index(drop=True)


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

# --- Main App UI ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64: st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# --- STEP 1: Upload Supplier Quotes ---
with st.container(border=False):
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("Step 1: Upload Supplier Quotes")
    st.markdown("Upload one or more supplier quote documents (PDF or TXT).")

    uploaded_files = st.file_uploader(
        "Upload files",
        type=['pdf', 'txt'],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files):
        with st.spinner(f"Processing {len(uploaded_files)} file(s)... (Pausing between files)"):
            all_new_items = []
            failed_files = []
            extraction_prompt = (
                "From the provided document, extract all line items. For each item, extract: "
                "TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. "
                "Return ONLY a valid JSON array of objects. "
                "Ensure QTY and COST_PER_UNIT are numbers. "
                "**Crucially, all string values in the JSON must be properly formatted. Any special characters like newlines or double quotes within a string must be correctly escaped (e.g., '\\n' for newlines, '\\\"' for quotes).**"
            )
            json_schema = {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "TYPE": {"type": "STRING"},
                        "QTY": {"type": "NUMBER"},
                        "Supplier": {"type": "STRING"},
                        "CAT_NO": {"type": "STRING"},
                        "Description": {"type": "STRING"},
                        "COST_PER_UNIT": {"type": "NUMBER"}
                    },
                    "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]
                }
            }
            model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})

            for i, file in enumerate(uploaded_files):
                try:
                    st.write(f"Processing `{file.name}`...")
                    part = file_to_generative_part(file)
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
                new_df['MARGIN'] = st.session_state.get("global_margin_input", 9.0)
                current_items = st.session_state.quote_items
                st.session_state.quote_items = pd.concat([current_items, new_df], ignore_index=True)
                apply_sorting()
                st.success(f"Successfully extracted {len(all_new_items)} items!")

            if failed_files:
                st.warning(f"Could not process the following files: {', '.join(failed_files)}")
        
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


if not WEASYPRINT_AVAILABLE:
     st.error("PDF generation library not found.", icon="🚨")
     st.stop()

if not st.session_state.quote_items.empty:
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header("Step 2: Edit & Refine Quote")
        st.caption("Edit values directly in the table. Calculations update automatically.")
        
        # --- AMENDED: Using the on_change callback for stability ---
        st.data_editor(
            _calculate_sell_prices(st.session_state.quote_items),
            column_config={
                "COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),
                "DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
                "MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%", min_value=0, max_value=99.9),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "SELL_UNIT_EX_GST": st.column_config.NumberColumn("Unit Price Ex GST", disabled=True, format="$%.2f", help="= (Cost * (1-Disc)) / (1-Margin)"),
                "SELL_TOTAL_EX_GST": st.column_config.NumberColumn("Line Price Ex GST", disabled=True, format="$%.2f", help="= Unit Price Ex GST * QTY"),
            },
            column_order=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"],
            num_rows="dynamic",
            use_container_width=True,
            key="data_editor",
            on_change=update_quote_items_from_editor
        )
        
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
            sub_c2.button("Apply Margin", use_container_width=True, on_click=apply_global_margin)

        st.divider()
        st.subheader("Row Operations")
        
        # --- AMENDED: Handles non-string data in 'Description' column ---
        row_options = [f"Row {i+1}: {(str(row['Description'] or ''))[:50]}..." for i, row in st.session_state.quote_items.iterrows()]
        selected_row_str = st.selectbox("Select a row to modify:", options=row_options, index=None, placeholder="Choose a row...")
        
        if selected_row_str:
            st.session_state.selected_row_index = row_options.index(selected_row_str)
        
        c1, c2, c3 = st.columns(3)
        c1.button("Add Row Above", use_container_width=True, on_click=add_row, args=(0,), disabled=not selected_row_str)
        c2.button("Add Row Below", use_container_width=True, on_click=add_row, args=(1,), disabled=not selected_row_str)
        c3.button("Delete Selected Row", use_container_width=True, on_click=delete_row, disabled=not selected_row_str)

        st.divider()
        st.subheader("✍️ AI Description Summarizer")
        
        # --- AMENDED: Handles non-string data in 'Description' column ---
        summary_row_options = [f"Row {i+1}: {(str(row['Description'] or ''))[:50]}..." for i, row in st.session_state.quote_items.iterrows()]
        selected_item_str_for_summary = st.selectbox("Select Item to Summarize", options=summary_row_options, index=None, placeholder="Choose an item...", key="summary_selectbox")

        if selected_item_str_for_summary:
            st.session_state.summary_selectbox_index = summary_row_options.index(selected_item_str_for_summary)
        
        st.button("Summarize Description", use_container_width=True, on_click=summarize_description, disabled=not selected_item_str_for_summary)
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- STEP 3 & 4: Details and PDF Generation ---
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        with st.form("quote_details_form"):
            st.header("Step 3: Project & Customer Details")
            st.subheader("Your Details")
            with st.expander("Edit Your Details", expanded=False):
                st.session_state.user_details['name'] = st.text_input("Your Name", value=st.session_state.user_details['name'])
                st.session_state.user_details['job_title'] = st.text_input("Job Title", value=st.session_state.user_details['job_title'])
                st.session_state.user_details['branch'] = st.text_input("Branch", value=st.session_state.user_details['branch'])
                st.session_state.user_details['email'] = st.text_input("Your Email", value=st.session_state.user_details['email'])
                st.session_state.user_details['phone'] = st.text_input("Your Phone", value=st.session_state.user_details['phone'])
            
            st.subheader("Customer & Project Details")
            q_details = st.session_state.quote_details
            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details['customerName'])
            q_details['attention'] = c2.text_input("Attention", value=q_details['attention'])
            q_details['projectName'] = c1.text_input("Project Name", value=q_details['projectName'])
            q_details['quoteNumber'] = c2.text_input("Quote Number", value=q_details['quoteNumber'])
            
            customer_logo = st.file_uploader("Upload Customer Logo (Optional)", type=['png', 'jpg', 'jpeg'])
            if customer_logo:
                st.session_state.customer_logo_b64 = image_to_base64(customer_logo)
                st.image(customer_logo, caption="Customer logo preview", width=150)
            
            st.divider()
            st.header("Step 4: Review Totals & Generate PDF")
            df_for_totals = _calculate_sell_prices(st.session_state.quote_items)
            total_cost_pre_margin = (df_for_totals['COST_PER_UNIT'] * (1 - df_for_totals['DISC'] / 100) * df_for_totals['QTY']).sum()
            
            sub_total = df_for_totals['SELL_TOTAL_EX_GST'].sum()
            gst_total = sub_total * 0.10
            grand_total = sub_total + gst_total
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Cost (Pre-Margin)", format_currency(total_cost_pre_margin))
            col2.metric("Sub-Total (ex. GST)", format_currency(sub_total))
            col3.metric("GST (10%)", format_currency(gst_total))
            col4.metric("Grand Total (inc. GST)", format_currency(grand_total))
            
            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        if submitted:
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            items_html = ""
            for i, row in final_df.iterrows():
                items_html += f"""
                <tr class="border-b border-gray-200">
                    <td class="p-2 align-top">{i + 1}</td>
                    <td class="p-2 align-top">{row['TYPE']}</td>
                    <td class="p-2 align-top">{row['QTY']}</td>
                    <td class="p-2 align-top">{row['Supplier']}</td>
                    <td class="p-2 w-1/3 align-top">
                        <strong class="block text-xs font-bold">{row['CAT_NO']}</strong>
                        <span>{row['Description']}</span>
                    </td>
                    <td class="p-2 text-right align-top">{format_currency(row['SELL_UNIT_EX_GST'])}</td>
                    <td class="p-2 text-right align-top">{format_currency(row['SELL_TOTAL_EX_GST'])}</td>
                </tr>"""

            company_logo_html = f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" alt="Company Logo" class="h-16 mb-4">' if st.session_state.get("company_logo_b64") else ''
            customer_logo_html = f'<img src="data:image/png;base64,{st.session_state.customer_logo_b64}" alt="Customer Logo" class="max-h-24 object-contain">' if st.session_state.get("customer_logo_b64") else ''
            branch_address_html = '<p class="text-sm text-gray-600">31-33 Rooks Road, Nunawading, 3131</p>' if st.session_state.user_details['branch'] == "AWM Nunawading" else ''
            attention_html = f'<p class="text-gray-700"><strong class="font-bold text-gray-800">Attn:</strong> {q_details["attention"] or "N/A"}</p>'

            quote_html = f"""
            <!DOCTYPE html><html lang="en">
            <head><meta charset="UTF-8"><title>Quote {q_details['quoteNumber']}</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"></head>
            <body>
                <div class="bg-white">
                    <header class="flex justify-between items-start mb-8 border-b border-gray-300 pb-8">
                        <div>
                            {company_logo_html}
                            <h1 class="text-2xl font-bold text-gray-800">{st.session_state.user_details['branch']}</h1>
                            {branch_address_html}
                            <p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p>
                        </div>
                        <div class="text-right">
                            {customer_logo_html}
                            <h2 class="text-3xl font-bold text-gray-700 mt-4">QUOTATION</h2>
                        </div>
                    </header>
                    <section class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                            <h2 class="font-bold text-gray-800 mb-2">QUOTE TO:</h2>
                            <p class="text-gray-700">{q_details['customerName']}</p>
                            {attention_html}
                        </div>
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">PROJECT:</strong> {q_details['projectName']}</p>
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">QUOTE #:</strong> {q_details['quoteNumber']}</p>
                            <p class="text-gray-700"><strong class="font-bold text-gray-800">DATE:</strong> {q_details['date']}</p>
                        </div>
                    </section>
                    <main>
                        <table class="w-full text-left text-sm" style="table-layout: auto;">
                            <thead class="bg-slate-800 text-white"><tr>
                                <th class="p-2 rounded-tl-lg">ITEM</th><th class="p-2">TYPE</th><th class="p-2">QTY</th><th class="p-2">BRAND</th>
                                <th class="p-2 w-1/3">PRODUCT DETAILS</th>
                                <th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right rounded-tr-lg">TOTAL EX GST</th>
                            </tr></thead>
                            <tbody class="divide-y divide-gray-200">{items_html}</tbody>
                        </table>
                    </main>
                    
                    <footer class="mt-8 flex justify-end" style="page-break-inside: avoid;">
                        <div class="w-2/5">
                            <div class="flex justify-between p-2 bg-gray-100 border-b border-gray-200">
                                <span class="font-bold text-gray-800">Sub-Total (Ex GST):</span>
                                <span class="text-gray-800">{format_currency(sub_total)}</span>
                            </div>
                            <div class="flex justify-between p-2 bg-gray-100 border-b border-gray-200">
                                <span class="font-bold text-gray-800">GST (10%):</span>
                                <span class="text-gray-800">{format_currency(gst_total)}</span>
                            </div>
                            <div class="flex justify-between p-3 bg-gray-200 rounded-b-lg">
                                <span class="font-bold text-gray-900 text-lg">Grand Total (Inc GST):</span>
                                <span class="font-bold text-gray-900 text-lg">{format_currency(grand_total)}</span>
                            </div>
                        </div>
                    </footer>

                    <div class="mt-12 pt-8" style="page-break-inside: avoid;">
                        <h3 class="font-bold text-gray-800">Prepared For You By:</h3>
                        <p class="text-gray-700 mt-2">{st.session_state.user_details['name']}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details['job_title']}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details['branch']}</p>
                        <p class="mt-2 text-sm"><strong>Email:</strong> {st.session_state.user_details['email']}</p>
                        <p class="text-sm"><strong>Phone:</strong> {st.session_state.user_details['phone']}</p>
                    </div>
                    <div class="mt-12 text-xs text-gray-500 border-t border-gray-300 pt-4" style="page-break-inside: avoid;">
                        <h3 class="font-bold mb-2">CONDITIONS:</h3>
                        <p>This offer is valid for 30 days. All goods are sold under MMEM's Terms and Conditions of Sale. Any changes in applicable taxes (GST) or tariffs which may occur will be to your account.</p>
                    </div>
                </div>
            </body></html>
            """

            pdf_css = """
            @page { size: A4; margin: 1.5cm; }
            body { font-family: 'Inter', sans-serif; }
            thead { display: table-header-group; }
            tfoot { display: table-footer-group; }
            table { width: 100%; border-collapse: collapse; }
            tr { page-break-inside: avoid !important; }
            th, td { text-align: left; padding: 4px 6px; vertical-align: top; }
            th { background-color: #1e293b; color: white; }
            td.text-right, th.text-right { text-align: right; }
            """
            combined_css = [
                CSS(string='@import url("https://cdnjs.cloudflare.com/ajax/libs/tailwindcss/2.2.19/tailwind.min.css");'),
                CSS(string=pdf_css)
            ]

            pdf_bytes = HTML(string=quote_html).write_pdf(stylesheets=combined_css)

            st.download_button(
                label="✅ Download Final Quote as PDF",
                data=pdf_bytes,
                file_name=f"Quote_{q_details['quoteNumber']}_{q_details['customerName']}.pdf",
                mime='application/pdf',
                use_container_width=True
            )
        
        st.markdown('</div>', unsafe_allow_html=True)
