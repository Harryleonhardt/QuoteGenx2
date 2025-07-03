# app.py

import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import re
import time 
from io import BytesIO
from pathlib import Path
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


# --- Page Configuration ---
st.set_page_config(
    page_title="AWM Quote Generator",
    page_icon="📄",
    layout="wide"
)

# --- App Styling ---
st.markdown("""
<style>
    /* Main app background */
    .stApp {
        background-color: #f0f2f6;
    }
    /* Style for containers */
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
        border: 1px solid #e6e6e6;
        border-radius: 0.5rem;
        padding: 1rem;
        background-color: white;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    }
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #0f172a; /* Slate 900 */
    }
    /* --- Sidebar text color for better contrast --- */
    [data-testid="stSidebar"] .st-emotion-cache-1gulkj5,
    [data-testid="stSidebar"] .st-emotion-cache-taue2i,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] .st-slider label {
        color: white !important;
    }
    /* --- Direct styling for sidebar buttons for guaranteed visibility --- */
    [data-testid="stSidebar"] button {
        background-color: #0284c7 !important; /* A bright blue */
        color: white !important;
        border: 1px solid #0284c7 !important;
    }
    [data-testid="stSidebar"] button:hover {
        background-color: #0369a1 !important; /* A darker blue for hover */
        border-color: #0369a1 !important;
        color: white !important;
    }
    [data-testid="stSidebar"] button:disabled {
        background-color: #334155 !important;
        color: #94a3b8 !important;
        border-color: #334155 !important;
    }
    /* Make titles more prominent */
    h1, h2, h3 {
        color: #1e293b; /* Slate 800 */
    }
</style>
""", unsafe_allow_html=True)


# --- Helper Functions ---

def file_to_generative_part(file):
    """Converts an uploaded file to a GenAI Part."""
    bytes_io = BytesIO(file.getvalue())
    return {
        "mime_type": file.type,
        "data": bytes_io.read()
    }

def image_to_base64(image_file):
    """Converts an image file to a base64 string."""
    if image_file is not None:
        bytes_data = image_file.getvalue()
        return base64.b64encode(bytes_data).decode()
    return None

def get_logo_base64(file_path):
    """Reads a local image file and returns its base64 representation."""
    try:
        with open(file_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        st.error(
            f"Logo file not found. Please ensure 'AWM Logo (002).png' is in the root of your GitHub repository alongside 'app.py' and that you have rebooted the Streamlit app.",
            icon="🚨"
        )
        return None

def format_currency(num):
    """Formats a number as Australian currency."""
    if pd.isna(num) or num is None:
        return "$0.00"
    return f"${num:,.2f}"

def check_password():
    """Returns `True` if the user has entered the correct password."""
    if st.session_state.get("password_correct", False):
        return True

    st.header("Login")
    password = st.text_input("Enter Password", type="password")

    if password == "AWM374":
        st.session_state["password_correct"] = True
        st.rerun()
    elif password:
        st.error("Password incorrect. Please try again.")

    return False

# --- NEW: Centralized Calculation Function ---
def _calculate_sell_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Takes a dataframe and returns it with calculated sell prices."""
    df_calc = df.copy()
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        df_calc[col] = pd.to_numeric(df_calc[col], errors='coerce').fillna(0)
    
    cost_after_disc = df_calc['COST_PER_UNIT'] * (1 - df_calc['DISC'] / 100)
    margin_divisor = (1 - df_calc['MARGIN'] / 100)
    margin_divisor[margin_divisor <= 0] = 0.01 
    
    df_calc['SELL_UNIT_EX_GST'] = cost_after_disc / margin_divisor
    df_calc['SELL_TOTAL_EX_GST'] = df_calc['SELL_UNIT_EX_GST'] * df_calc['QTY']
    
    return df_calc

# --- Gemini API Configuration ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    GEMINI_API_AVAILABLE = True
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found. Please add it to your Streamlit secrets.", icon="🚨")
    st.info("To get an API key, visit: https://makersuite.google.com/app/apikey")
    GEMINI_API_AVAILABLE = False
    st.stop()

# --- Password Wall ---
if not check_password():
    st.stop()


# --- Session State Initialization ---
if "quote_items" not in st.session_state:
    st.session_state.quote_items = pd.DataFrame(columns=[
        "TYPE", "QTY", "Supplier", "CAT_NO", "Description",
        "COST_PER_UNIT", "DISC", "MARGIN"
    ])

if "user_details" not in st.session_state:
    st.session_state.user_details = {
        "name": "",
        "job_title": "Sales",
        "branch": "AWM Nunawading",
        "email": "",
        "phone": "03 8846 2500"
    }

if "quote_details" not in st.session_state:
    st.session_state.quote_details = {
        "customerName": "",
        "attention": "",
        "projectName": "",
        "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}",
        "date": pd.Timestamp.now().strftime('%d/%m/%Y')
    }

if "project_summary" not in st.session_state:
    st.session_state.project_summary = ""

if "header_image_b64" not in st.session_state:
    st.session_state.header_image_b64 = None

if "company_logo_b64" not in st.session_state:
    logo_file_path = Path(__file__).parent / "AWM Logo (002).png"
    st.session_state.company_logo_b64 = get_logo_base64(logo_file_path)

if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"


# --- Main Application UI ---

st.title("📄 AWM Quote Generator")
st.caption(f"App created by Harry Leonhardt | Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")

# --- Sidebar for Controls and Actions ---
with st.sidebar:
    st.header("Controls & Settings")

    with st.expander("👤 **Your Details**", expanded=True):
        st.session_state.user_details['name'] = st.text_input("Your Name", value=st.session_state.user_details['name'])
        st.session_state.user_details['job_title'] = st.text_input("Job Title", value=st.session_state.user_details['job_title'])
        st.session_state.user_details['branch'] = st.text_input("Branch", value=st.session_state.user_details['branch'])
        st.session_state.user_details['email'] = st.text_input("Your Email", value=st.session_state.user_details['email'])
        st.session_state.user_details['phone'] = st.text_input("Your Phone", value=st.session_state.user_details['phone'])

    st.subheader("1. Upload Supplier Quotes")
    uploaded_files = st.file_uploader(
        "Upload PDF or TXT files",
        type=['pdf', 'txt'],
        accept_multiple_files=True,
        help="Upload one or more supplier quote documents. The system will extract line items."
    )

    process_button = st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files)

    st.divider()

    st.subheader("2. Global Settings")
    global_margin = st.number_input("Global Margin (%)", value=9.0, min_value=0.0, max_value=99.9, step=1.0, format="%.2f")
    
    if st.button("Apply Global Margin", use_container_width=True):
        if not st.session_state.quote_items.empty:
            st.session_state.quote_items['MARGIN'] = global_margin
            st.toast(f"Applied {global_margin}% margin to all items.")
            st.rerun()
        else:
            st.warning("No items in the quote to apply margin to.")
    
    if st.button("Clear All Quote Items", use_container_width=True):
        st.session_state.quote_items = pd.DataFrame(columns=[
            "TYPE", "QTY", "Supplier", "CAT_NO", "Description",
            "COST_PER_UNIT", "DISC", "MARGIN"
        ])
        st.session_state.project_summary = ""
        st.rerun()

    st.divider()

    st.subheader("3. Quote Customization")
    if st.session_state.company_logo_b64:
        st.write("Company Logo:")
        st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=200)

    header_image = st.file_uploader("Upload Custom Header Image (Optional)", type=['png', 'jpg', 'jpeg'], help="Optional: Upload a banner image for the quote header.")
    if header_image:
        st.session_state.header_image_b64 = image_to_base64(header_image)
        st.image(header_image, caption="Custom header preview")

    st.divider()

    st.subheader("4. AI Actions")
    if st.button("✨ Generate Project Summary", use_container_width=True, disabled=st.session_state.quote_items.empty):
        with st.spinner("🤖 Gemini is summarizing the project scope..."):
            try:
                items_for_prompt = "\n".join(
                    [f"- {row['QTY']}x {row['Description']} (from {row['Supplier']})"
                     for index, row in st.session_state.quote_items.iterrows()]
                )
                prompt = (
                    "Based on the following list of electrical components, write a 2-paragraph summary of this project's "
                    "scope for a client proposal. Mention the key types of products being installed (e.g., "
                    "emergency lighting, architectural downlights, weatherproof battens) and the primary suppliers involved."
                    f"\n\nItems:\n{items_for_prompt}"
                )
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(prompt)
                st.session_state.project_summary = response.text
                st.toast("Project summary generated!", icon="✅")
            except Exception as e:
                st.error(f"Failed to generate summary: {e}")


# --- File Processing Logic ---
if process_button and uploaded_files:
    spinner_text = f"Processing {len(uploaded_files)} file(s)... (Pausing between files to respect API limits)"
    with st.spinner(spinner_text):
        all_new_items = []
        failed_files = []
        extraction_prompt = (
            "From the provided document, extract all line items. For each item, extract: "
            "TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. "
            "Return ONLY a valid JSON array of objects. "
            "Ensure QTY and COST_PER_UNIT are numbers. "
            "**Crucially, all string values in the JSON must be properly formatted. Any special characters like newlines or double quotes within a string must be correctly escaped (e.g., '\\n' for newlines, '\\\"' for quotes).**"
        )

        json_schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"}, "CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]}}
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})

        for i, file in enumerate(uploaded_files):
            try:
                st.write(f"Processing `{file.name}`...")
                part = file_to_generative_part(file)
                response = model.generate_content([extraction_prompt, part])
                response_text = response.text
                extracted_data = None

                try:
                    extracted_data = json.loads(response_text)
                except json.JSONDecodeError:
                    st.write(f"Initial JSON parse failed for `{file.name}`. Attempting to clean response...")
                    match = re.search(r'```json\s*(.*)\s*```', response_text, re.DOTALL)
                    if match:
                        json_str = match.group(1).strip()
                        try:
                            extracted_data = json.loads(json_str)
                            st.write(f"Successfully cleaned and parsed JSON for `{file.name}`.")
                        except json.JSONDecodeError as final_e:
                            st.error(f"Failed to parse cleaned JSON for `{file.name}`. Error: {final_e}")
                            failed_files.append(file.name)
                            continue
                    else:
                        st.error(f"Error processing `{file.name}`: Could not find a valid JSON block in the API response.")
                        failed_files.append(file.name)
                        continue

                if extracted_data:
                    all_new_items.extend(extracted_data)
                
                if i < len(uploaded_files) - 1:
                    time.sleep(2)

            except Exception as e:
                st.error(f"An unexpected error occurred processing `{file.name}`: {e}")
                failed_files.append(file.name)

        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = global_margin
            st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            st.success(f"Successfully extracted {len(all_new_items)} items!")
        if failed_files:
            st.warning(f"Could not process the following files: {', '.join(failed_files)}")
        st.rerun()


# --- Main Content Area ---
if not WEASYPRINT_AVAILABLE:
     st.error("PDF generation library not found. Please ensure `weasyprint` is in your requirements.txt and the system packages are in `packages.txt`.", icon="🚨")
     st.stop()

if st.session_state.quote_items.empty:
    st.info("Upload your supplier quotes using the sidebar to get started. The company logo is pre-loaded.")
else:
    with st.container():
        if st.session_state.project_summary:
            st.subheader("✨ Project Scope Summary")
            st.markdown(st.session_state.project_summary)
            st.divider()

        st.subheader("Quote Line Items")
        
        sort_option = st.radio(
            "Sort items by:",
            ("Type", "Supplier"),
            horizontal=True,
            key="sort_by"
        )
        
        df_to_edit = st.session_state.quote_items.copy()
        if sort_option == 'Type':
            df_to_edit = df_to_edit.sort_values(by='TYPE', kind='mergesort').reset_index(drop=True)
        elif sort_option == 'Supplier':
            df_to_edit = df_to_edit.sort_values(by='Supplier', kind='mergesort').reset_index(drop=True)
        
        st.caption("You can edit values directly in the table below. Calculations will update automatically.")
        
        # --- FIX: Use the centralized calculation function ---
        df_for_display = _calculate_sell_prices(df_to_edit)
        
        edited_df = st.data_editor(
            df_for_display,
            column_config={
                "COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),
                "DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
                "MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%", min_value=0, max_value=99.9),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "SELL_UNIT_EX_GST": st.column_config.NumberColumn("Unit Price Ex GST", help="= (Cost * (1-Disc)) / (1-Margin)", format="$%.2f", disabled=True),
                "SELL_TOTAL_EX_GST": st.column_config.NumberColumn("Line Price Ex GST", help="= Unit Price Ex GST * QTY", format="$%.2f", disabled=True),
            },
            column_order=["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", "DISC", "MARGIN", "SELL_UNIT_EX_GST", "SELL_TOTAL_EX_GST"],
            num_rows="dynamic",
            use_container_width=True,
            key="data_editor"
        )
        
        if not df_to_edit.equals(edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST'])):
            st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
            st.rerun()

        st.divider()
        st.subheader("Row Operations")
        
        row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in df_to_edit.iterrows()]
        
        selected_row_str = st.selectbox("Select a row to modify:", options=row_options, index=None, placeholder="Choose a row...")

        if selected_row_str:
            selected_index = row_options.index(selected_row_str)
            
            c1, c2, c3 = st.columns(3)
            
            if c1.button("Add Row Above", use_container_width=True):
                new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": global_margin}])
                updated_df = pd.concat([df_to_edit.iloc[:selected_index], new_row, df_to_edit.iloc[selected_index:]], ignore_index=True)
                st.session_state.quote_items = updated_df
                st.rerun()

            if c2.button("Add Row Below", use_container_width=True):
                new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": global_margin}])
                updated_df = pd.concat([df_to_edit.iloc[:selected_index+1], new_row, df_to_edit.iloc[selected_index+1:]], ignore_index=True)
                st.session_state.quote_items = updated_df
                st.rerun()

            if c3.button("Delete Selected Row", use_container_width=True):
                updated_df = df_to_edit.drop(df_to_edit.index[selected_index]).reset_index(drop=True)
                st.session_state.quote_items = updated_df
                st.rerun()

        st.divider()
        st.subheader("✍️ AI Description Summarizer")
        st.caption("Select an item to generate a shorter, more client-friendly description.")
        
        selected_item_str_for_summary = st.selectbox("Select Item to Summarize", options=row_options, index=None, placeholder="Choose an item...", key="summary_selectbox")
        
        if st.button("Summarize Description", use_container_width=True, disabled=not selected_item_str_for_summary):
            selected_index = row_options.index(selected_item_str_for_summary)
            original_description = st.session_state.quote_items.at[selected_index, 'Description']
            
            with st.spinner("🤖 Gemini is summarizing..."):
                try:
                    prompt = f"Summarize the following product description in one clear, concise sentence for a customer quote. Be professional and easy to understand.\n\nOriginal Description: '{original_description}'"
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    response = model.generate_content(prompt)
                    
                    st.session_state.quote_items.at[selected_index, 'Description'] = response.text.strip()
                    st.toast("Description summarized!", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to summarize: {e}")

        # --- FIX: Use the centralized calculation function for totals ---
        df_for_totals = _calculate_sell_prices(st.session_state.quote_items)
        
        cost_after_disc_total = df_for_totals['COST_PER_UNIT'] * (1 - df_for_totals['DISC'] / 100)
        total_cost_pre_margin = (cost_after_disc_total * df_for_totals['QTY']).sum()
        
        gst_rate = 10
        df_for_totals['GST_AMOUNT'] = df_for_totals['SELL_TOTAL_EX_GST'] * (gst_rate / 100)
        df_for_totals['SELL_TOTAL_INC_GST'] = df_for_totals['SELL_TOTAL_EX_GST'] + df_for_totals['GST_AMOUNT']

        st.divider()
        st.subheader("Quote Totals")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Cost (Pre-Margin)", format_currency(total_cost_pre_margin))
        col2.metric("Sub-Total (ex. GST)", format_currency(df_for_totals['SELL_TOTAL_EX_GST'].sum()))
        col3.metric("GST (10%)", format_currency(df_for_totals['GST_AMOUNT'].sum()))
        col4.metric("Grand Total (inc. GST)", format_currency(df_for_totals['SELL_TOTAL_INC_GST'].sum()))

        st.divider()
        st.header("Finalise and Generate Quote")

        with st.form("quote_details_form"):
            st.subheader("Quote Recipient & Project Details")
            q_details = st.session_state.quote_details

            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details['customerName'])
            q_details['attention'] = c2.text_input("Attention", value=q_details['attention'])
            q_details['projectName'] = c1.text_input("Project Name", value=q_details['projectName'])
            q_details['quoteNumber'] = c2.text_input("Quote Number", value=q_details['quoteNumber'])

            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        if submitted:
            # --- FIX: Use the centralized calculation function for the final PDF data ---
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            
            if st.session_state.sort_by == 'Type':
                final_df = final_df.sort_values(by='TYPE', kind='mergesort').reset_index(drop=True)
            elif st.session_state.sort_by == 'Supplier':
                final_df = final_df.sort_values(by='Supplier', kind='mergesort').reset_index(drop=True)

            items_html = ""
            for i, row in final_df.iterrows():
                product_details_html = f"""
                <td class="p-2 w-1/3 align-top">
                    <strong class="block text-xs font-bold">{row['CAT_NO']}</strong>
                    <span>{row['Description']}</span>
                </td>
                """
                items_html += f"""
                <tr class="border-b border-gray-200">
                    <td class="p-2 align-top">{i + 1}</td>
                    <td class="p-2 align-top">{row['TYPE']}</td>
                    <td class="p-2 align-top">{row['QTY']}</td>
                    <td class="p-2 align-top">{row['Supplier']}</td>
                    {product_details_html}
                    <td class="p-2 text-right align-top">{format_currency(row['SELL_UNIT_EX_GST'])}</td>
                    <td class="p-2 text-right align-top">{format_currency(row['SELL_TOTAL_EX_GST'])}</td>
                </tr>
                """

            company_logo_html = ""
            if st.session_state.company_logo_b64:
                company_logo_html = f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" alt="Company Logo" class="h-16 mb-4">'
            else:
                company_logo_html = '<h1 class="text-3xl font-bold text-gray-800">Company Name</h1>'

            header_image_html = ""
            if st.session_state.header_image_b64:
                header_image_html = f'<img src="data:image/png;base64,{st.session_state.header_image_b64}" alt="Custom Header" class="max-h-24 object-contain">'
            
            branch_address_html = ""
            if st.session_state.user_details['branch'] == "AWM Nunawading":
                branch_address_html = '<p class="text-sm text-gray-600">31-33 Rooks Road, Nunawading, 3131</p>'

            attention_html = f'<p class="text-gray-700"><strong class="font-bold text-gray-800">Attn:</strong> {q_details["attention"] or "N/A"}</p>'

            quote_html = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Quote {q_details['quoteNumber']}</title>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
            </head>
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
                            {header_image_html}
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
                    {f'<section class="mb-8 p-4 bg-blue-50 border border-blue-200 rounded-lg"><h3 class="font-bold text-lg mb-2 text-blue-900">Project Summary</h3><p class="text-gray-700 whitespace-pre-wrap">{st.session_state.project_summary}</p></section>' if st.session_state.project_summary else ''}
                    <main>
                        <table class="w-full text-left text-sm" style="table-layout: auto;">
                            <thead class="bg-slate-800 text-white">
                                <tr>
                                    <th class="p-2 rounded-tl-lg">ITEM</th><th class="p-2">TYPE</th><th class="p-2">QTY</th><th class="p-2">BRAND</th>
                                    <th class="p-2 w-1/3">PRODUCT DETAILS</th>
                                    <th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right rounded-tr-lg">TOTAL EX GST</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-200">{items_html}</tbody>
                        </table>
                    </main>
                    <footer class="mt-8 flex justify-end" style="page-break-inside: avoid;">
                        <div class="w-2/5">
                            <div class="flex justify-between p-2 bg-gray-100 rounded-t-lg"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span class="text-gray-800">{format_currency(final_df['SELL_TOTAL_EX_GST'].sum())}</span></div>
                            <div class="flex justify-between p-2"><span class="font-bold text-gray-800">GST (10%):</span><span class="text-gray-800">{format_currency(final_df['GST_AMOUNT'].sum())}</span></div>
                            <div class="flex justify-between p-4 bg-slate-800 text-white font-bold text-lg rounded-b-lg"><span>Grand Total (Inc GST):</span><span>{format_currency(final_df['SELL_TOTAL_INC_GST'].sum())}</span></div>
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
            </body>
            </html>
            """
            
            pdf_css = """
                @page {
                    size: A4;
                    margin: 1.5cm;
                }
                body {
                    font-family: 'Inter', sans-serif;
                }
                thead { 
                    display: table-header-group; 
                }
                tfoot {
                    display: table-footer-group;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                }
                tr {
                    page-break-inside: avoid !important;
                }
                th, td {
                    text-align: left;
                    padding: 4px 6px;
                    vertical-align: top;
                }
                th {
                    background-color: #1e293b;
                    color: white;
                }
                td.text-right, th.text-right {
                    text-align: right;
                }
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
