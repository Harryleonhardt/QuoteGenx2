# app.py

import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import re
import time # Import the time library for handling rate limits
from io import BytesIO
from copy import deepcopy

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
    /* --- START: Sidebar Text Color Change --- */
    [data-testid="stSidebar"] p, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] .st-emotion-cache-1g8sf0w { /* Targets expander header */
        color: white !important;
    }
    /* --- END: Sidebar Text Color Change --- */

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

def format_currency(num):
    """Formats a number as Australian currency."""
    if pd.isna(num) or num is None:
        return "$0.00"
    return f"${num:,.2f}"

# --- Gemini API Configuration ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    GEMINI_API_AVAILABLE = True
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found. Please add it to your Streamlit secrets.", icon="🚨")
    st.info("To get an API key, visit: https://ai.google.dev/gemini-api/docs/rate-limits")
    GEMINI_API_AVAILABLE = False
    
# --- Session State Initialization ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "quote_items" not in st.session_state:
    st.session_state.quote_items = pd.DataFrame()
if "user_details" not in st.session_state:
    st.session_state.user_details = {
        "name": "", "job_title": "Sales", "branch": "AWM Nunawading",
        "email": "", "phone": "03 8846 2500"
    }
if "quote_details" not in st.session_state:
    st.session_state.quote_details = {
        "customerName": "", "attention": "", "projectName": "",
        "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}",
        "date": pd.Timestamp.now().strftime('%d/%m/%Y')
    }
if "project_summary" not in st.session_state:
    st.session_state.project_summary = ""
if "header_image_b64" not in st.session_state:
    st.session_state.header_image_b64 = None
if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = None

# --- Password Protection ---
def check_password():
    """Returns `True` if the user had a correct password."""
    if st.session_state.get("authenticated", False):
        return True

    def password_entered():
        if st.session_state["password"] == "AWM374":
            st.session_state["authenticated"] = True
            del st.session_state["password"]  
        else:
            st.session_state["authenticated"] = False

    st.text_input("Password", type="password", on_change=password_entered, key="password")
    if "authenticated" in st.session_state and not st.session_state.authenticated:
        st.error("😕 Password incorrect")
    return st.session_state.get("authenticated", False)

if not check_password():
    st.stop()


# --- Main Application UI ---

st.title("📄 AWM Quote Generator")
st.caption(f"App created by Harry Leonhardt | Quote prepared by: **{st.session_state.user_details['name']}**")

if not GEMINI_API_AVAILABLE:
    st.stop()


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
    supplier_files = st.file_uploader("Upload PDF or TXT files", type=['pdf', 'txt'], accept_multiple_files=True)
    process_button = st.button("Process Supplier Files", type="primary", use_container_width=True, disabled=not supplier_files)

    st.divider()
    
    st.subheader("2. Match to Customer Take-off (Optional)")
    takeoff_file = st.file_uploader("Upload Customer Take-off", type=['pdf', 'txt'])
    match_button = st.button("Match Quotes to Take-off", use_container_width=True, disabled=not takeoff_file or st.session_state.quote_items.empty)

    st.divider()

    st.subheader("3. Global & AI Settings")
    global_margin = st.number_input("Global Margin (%)", value=9.0, min_value=0.0, step=1.0, format="%.2f")
    if st.button("Apply Global Margin", use_container_width=True):
        if not st.session_state.quote_items.empty:
            st.session_state.quote_items['MARGIN'] = global_margin
            st.toast(f"Applied {global_margin}% margin to all items.")
    
    if st.button("✨ Generate Project Summary", use_container_width=True, disabled=st.session_state.quote_items.empty):
         with st.spinner("🤖 Gemini is summarizing the project scope..."):
            items_for_prompt = "\n".join([f"- {row['QTY']}x {row['Description']} (from {row['Supplier']})" for _, row in st.session_state.quote_items.iterrows()])
            prompt = f"Based on the following list of electrical components, write a 2-paragraph summary of this project's scope for a client proposal. Mention the key types of products being installed and the primary suppliers involved.\n\nItems:\n{items_for_prompt}"
            model = genai.GenerativeModel('gemini-1.5-pro')
            response = model.generate_content(prompt)
            st.session_state.project_summary = response.text
            st.toast("Project summary generated!", icon="✅")

    if st.button("Clear All Quote Items", use_container_width=True):
        st.session_state.quote_items = pd.DataFrame()
        st.session_state.project_summary = ""
        st.rerun()
        
    st.divider()
    
    st.subheader("4. Quote Customization")
    company_logo = st.file_uploader("Upload Company Logo", type=['png', 'jpg', 'jpeg'])
    if company_logo:
        st.session_state.company_logo_b64 = image_to_base64(company_logo)
        st.image(company_logo, caption="Company logo preview", width=200)

    header_image = st.file_uploader("Upload Custom Header Image (Optional)", type=['png', 'jpg', 'jpeg'])
    if header_image:
        st.session_state.header_image_b64 = image_to_base64(header_image)
        st.image(header_image, caption="Custom header preview")


# --- Main File Processing Logic ---
def robust_json_parser(response_text):
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```|(\{.*?\}|\[.*?\])', response_text, re.DOTALL)
        if match:
            json_str = match.group(1) if match.group(1) else match.group(2)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse cleaned JSON: {e}")
        else:
            raise ValueError("Could not find a valid JSON block in the API response.")

# --- START: Reverted to one-by-one file processing to avoid rate limit issues ---
if process_button and supplier_files:
    with st.spinner(f"Processing {len(supplier_files)} supplier file(s) one-by-one. This may take a moment..."):
        all_new_items = []
        progress_bar = st.progress(0, text="Initializing...")
        
        for i, file in enumerate(supplier_files):
            progress_bar.progress((i) / len(supplier_files), text=f"Processing file: {file.name}")
            try:
                prompt_parts = [
                    ("You are a data extraction specialist. From the following document, extract all line items. "
                     "Focus on tabular data. For each item, extract: "
                     "TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. "
                     "Return ONLY a valid JSON array of objects. Ensure QTY and COST_PER_UNIT are numbers. "
                     "**Crucially, all string values in the JSON must be properly formatted. Any special characters like newlines or double quotes within a string must be correctly escaped."),
                    file_to_generative_part(file)
                ]
                
                # Using a model that handles PDF/text extraction well
                model = genai.GenerativeModel('gemini-1.5-pro', generation_config={"response_mime_type": "application/json"})
                response = model.generate_content(prompt_parts)
                
                extracted_data = robust_json_parser(response.text)
                if extracted_data:
                    all_new_items.extend(extracted_data)
                
                # A 2-second delay between requests to stay within free-tier API rate limits
                time.sleep(2)

            except Exception as e:
                st.error(f"An error occurred while processing `{file.name}`: {e}")
                st.info("This might be due to API rate limits. The process will continue with the next file after a short delay.")
                time.sleep(5) # Longer sleep after an error before continuing

        progress_bar.progress(1.0, text="Processing complete!")

        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = global_margin
            
            if not st.session_state.quote_items.empty:
                 st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            else:
                 st.session_state.quote_items = new_df

            st.session_state.quote_items.drop_duplicates(subset=['CAT_NO', 'Description'], inplace=True, keep='last')
            st.success(f"Successfully processed {len(all_new_items)} items from {len(supplier_files)} file(s)!")
            st.rerun()
# --- END: Reverted file processing logic ---


if match_button and takeoff_file:
    with st.spinner("🤖 Matching supplier quotes to customer take-off... This is a complex task and may take a moment."):
        try:
            if takeoff_file.type == "application/pdf":
                takeoff_part = file_to_generative_part(takeoff_file)
                text_extraction_model = genai.GenerativeModel('gemini-1.5-pro')
                takeoff_response = text_extraction_model.generate_content(["Extract all text from this document.", takeoff_part])
                takeoff_content = takeoff_response.text
            else:
                takeoff_content = takeoff_file.read().decode('utf-8')

            supplier_json_str = st.session_state.quote_items.to_json(orient='records')
            
            matching_prompt = f"""
            You are an expert quote-matching assistant for an electrical wholesaler. Your task is to align a list of items from supplier quotes with a customer's take-off list.

            **RULES:**
            1.  **PRIORITIZE CUSTOMER LIST:** The final output structure, quantities, and descriptions MUST follow the customer take-off.
            2.  **MATCHING:** Match items from the supplier list to the customer list based on `CAT_NO`, `Description`, or `TYPE`. An exact `CAT_NO` is the best match.
            3.  **PRICING:** Use the `COST_PER_UNIT` from the matched supplier item.
            4.  **QUANTITY:** ALWAYS use the `QTY` from the customer's take-off list.
            5.  **UNMATCHED SUPPLIER ITEMS:** If an item from the supplier list does not match any item on the customer take-off, append it to the end of the final list.
            6.  **UNMATCHED CUSTOMER ITEMS:** If an item from the customer take-off cannot be matched to any supplier item, find the CLOSEST possible alternative from the supplier list. Use the supplier's `CAT_NO` and `COST_PER_UNIT`, but keep the customer's `QTY` and `Description`. In the `Description` for this item, add the note "(Supplier Recommendation)".
            7.  **OUTPUT:** Return a single, valid JSON array of objects representing the final, matched quote.

            **CUSTOMER TAKE-OFF (Plain Text):**
            ---
            {takeoff_content}
            ---

            **SUPPLIER QUOTE ITEMS (JSON):**
            ---
            {supplier_json_str}
            ---

            Now, generate the final matched JSON array.
            """
            model = genai.GenerativeModel('gemini-1.5-pro', generation_config={"response_mime_type": "application/json"})
            response = model.generate_content(matching_prompt)
            matched_data = robust_json_parser(response.text)
            
            if matched_data:
                matched_df = pd.DataFrame(matched_data)
                for col in ['DISC', 'MARGIN']:
                    if col not in matched_df.columns:
                        matched_df[col] = 0.0 if col == 'DISC' else global_margin
                st.session_state.quote_items = matched_df
                st.success("Successfully matched quote to customer take-off!")

        except Exception as e:
            st.error(f"Failed during matching process: {e}")


# --- Main Content Area ---
if st.session_state.quote_items.empty:
    st.info("Upload supplier quotes using the sidebar to get started.")
else:
    with st.container():
        if st.session_state.project_summary:
            st.subheader("✨ Project Scope Summary")
            st.markdown(st.session_state.project_summary)
            st.divider()

        st.subheader("Quote Line Items")
        
        df_for_editing = st.session_state.quote_items.copy()
        options = [f"Row {i+1}: {row.get('Description', 'N/A')[:70]}..." for i, row in df_for_editing.iterrows()]
        rows_to_summarize = st.multiselect("Select descriptions to summarize:", options)
        
        if st.button("✍️ Summarize Selected Descriptions", disabled=not rows_to_summarize):
            with st.spinner("🤖 Summarizing descriptions..."):
                indices_to_update = [int(s.split(':')[0].replace('Row ', '')) - 1 for s in rows_to_summarize]
                
                summarize_model = genai.GenerativeModel('gemini-1.5-pro')
                for idx in indices_to_update:
                    original_desc = st.session_state.quote_items.at[idx, 'Description']
                    prompt = f"Summarize the following technical product description into a concise, client-friendly phrase (around 5-10 words). Do not add any preamble.\n\nOriginal: \"{original_desc}\""
                    response = summarize_model.generate_content(prompt)
                    st.session_state.quote_items.at[idx, 'Description'] = response.text.strip()
                    time.sleep(1) # Small delay between summarization requests
                st.success("Descriptions summarized!")
                st.rerun()

        df = st.session_state.quote_items.copy()
        for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
            df[col] = pd.to_numeric(df.get(col), errors='coerce').fillna(0)
        cost_after_disc = df['COST_PER_UNIT'] * (1 - df['DISC'] / 100)
        df['SELL_UNIT_EX_GST'] = cost_after_disc * (1 + df['MARGIN'] / 100)
        df['Line Sell (Ex. GST)'] = df['SELL_UNIT_EX_GST'] * df['QTY']
        
        edited_df = st.data_editor(df, column_config={
            "COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),
            "DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
            "MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Line Sell (Ex. GST)": st.column_config.NumberColumn("Line Sell (Ex. GST)", format="$%.2f", disabled=True),
            "SELL_UNIT_EX_GST": st.column_config.NumberColumn(disabled=True)
        }, use_container_width=True, key="data_editor", hide_index=True)

        st.session_state.quote_items = edited_df.drop(columns=['Line Sell (Ex. GST)', 'SELL_UNIT_EX_GST'], errors='ignore')
        
        st.divider()
        st.subheader("Quote Totals")
        total_sell_ex_gst = (edited_df['Line Sell (Ex. GST)']).sum()
        total_gst = total_sell_ex_gst * 0.10
        total_sell_inc_gst = total_sell_ex_gst + total_gst
        col1, col2, col3 = st.columns(3)
        col1.metric("Sub-Total (ex. GST)", format_currency(total_sell_ex_gst))
        col2.metric("GST (10%)", format_currency(total_gst))
        col3.metric("Grand Total (inc. GST)", format_currency(total_sell_inc_gst))
        
        st.divider()
        st.header("Finalise and Generate Quote")

        with st.form("quote_details_form"):
            q_details = st.session_state.quote_details
            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details['customerName'])
            q_details['attention'] = c2.text_input("Attention", value=q_details['attention'])
            q_details['projectName'] = c1.text_input("Project Name", value=q_details['projectName'])
            q_details['quoteNumber'] = c2.text_input("Quote Number", value=q_details['quoteNumber'])
            submitted = st.form_submit_button("Generate Final Quote HTML", type="primary", use_container_width=True)

        if submitted:
            items_html = ""
            for i, row in edited_df.iterrows():
                items_html += f"""
                <tr class="border-b border-gray-200">
                    <td class="p-3 align-top">{i + 1}</td>
                    <td class="p-3 align-top">{row.get('TYPE', '')}</td>
                    <td class="p-3 align-top">{row.get('QTY', 0)}</td>
                    <td class="p-3 align-top">{row.get('Supplier', '')}</td>
                    <td class="p-3 align-top">
                        <strong class="text-xs text-gray-700 block">{row.get('CAT_NO', '')}</strong>
                        {row.get('Description', '')}
                    </td>
                    <td class="p-3 text-right align-top">{format_currency(row['SELL_UNIT_EX_GST'])}</td>
                    <td class="p-3 text-right align-top">{format_currency(row['Line Sell (Ex. GST)'])}</td>
                </tr>
                """
            
            company_logo_html = f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" alt="Company Logo" class="h-16 mb-4">' if st.session_state.company_logo_b64 else ''
            header_image_html = f'<img src="data:image/png;base64,{st.session_state.header_image_b64}" alt="Custom Header" class="max-h-24 object-contain">' if st.session_state.header_image_b64 else ''

            quote_html = f"""
            <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Quote {q_details['quoteNumber']}</title>
            <script src="https://cdn.tailwindcss.com"></script><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet"><style>body{{font-family:'Inter',sans-serif}}</style></head>
            <body class="bg-gray-100 p-4 sm:p-8"><div class="max-w-4xl mx-auto bg-white p-6 sm:p-10 shadow-2xl rounded-xl">
                <header class="flex justify-between items-start mb-8 border-b border-gray-300 pb-8">
                    <div>{company_logo_html}<h1 class="text-2xl font-bold text-gray-800">{st.session_state.user_details['branch']}</h1><p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p></div>
                    <div class="text-right">{header_image_html}<h2 class="text-3xl font-bold text-gray-700 mt-4">QUOTATION</h2></div>
                </header>
                <section class="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
                    <div class="bg-gray-50 p-4 rounded-lg border border-gray-200"><h2 class="font-bold text-gray-800 mb-2">QUOTE TO:</h2><p class="text-gray-700">{q_details['customerName']}</p><p class="text-gray-700">Attn: {q_details['attention'] or 'N/A'}</p></div>
                    <div class="bg-gray-50 p-4 rounded-lg border border-gray-200"><p class="text-gray-700"><strong class="font-bold text-gray-800">PROJECT:</strong> {q_details['projectName']}</p><p class="text-gray-700"><strong class="font-bold text-gray-800">QUOTE #:</strong> {q_details['quoteNumber']}</p><p class="text-gray-700"><strong class="font-bold text-gray-800">DATE:</strong> {q_details['date']}</p></div>
                </section>
                {f'<section class="mb-8 p-4 bg-blue-50 border border-blue-200 rounded-lg"><h3 class="font-bold text-lg mb-2 text-blue-900">Project Summary</h3><p class="text-gray-700 whitespace-pre-wrap">{st.session_state.project_summary}</p></section>' if st.session_state.project_summary else ''}
                <main><table class="w-full text-left text-sm">
                    <thead class="bg-slate-800 text-white"><tr>
                        <th class="p-3 rounded-tl-lg">ITEM</th><th class="p-3">TYPE</th><th class="p-3">QTY</th><th class="p-3">BRAND</th><th class="p-3 w-2/5">DESCRIPTION</th>
                        <th class="p-3 text-right">UNIT EX GST</th><th class="p-3 text-right rounded-tr-lg">TOTAL EX GST</th>
                    </tr></thead>
                    <tbody class="divide-y divide-gray-200">{items_html}</tbody>
                </table></main>
                <footer class="mt-8 flex justify-end">
                    <div class="w-full sm:w-1/2">
                        <div class="flex justify-between p-3 bg-gray-100 rounded-t-lg"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span>{format_currency(total_sell_ex_gst)}</span></div>
                        <div class="flex justify-between p-3"><span class="font-bold text-gray-800">GST (10%):</span><span>{format_currency(total_gst)}</span></div>
                        <div class="flex justify-between p-4 bg-slate-800 text-white font-bold text-lg rounded-b-lg"><span>Grand Total (Inc GST):</span><span>{format_currency(total_sell_inc_gst)}</span></div>
                    </div>
                </footer>
                <div class="mt-12 pt-8 border-t-2 border-dashed border-gray-300">
                    <h3 class="font-bold text-gray-800">Prepared For You By:</h3>
                    <p class="text-gray-700 mt-2">{st.session_state.user_details['name']}</p><p class="text-gray-600 text-sm">{st.session_state.user_details['job_title']}</p>
                    <p class="text-gray-600 text-sm">{st.session_state.user_details['branch']}</p><p class="mt-2 text-sm"><strong>Email:</strong> {st.session_state.user_details['email']}</p><p class="text-sm"><strong>Phone:</strong> {st.session_state.user_details['phone']}</p>
                </div>
                <div class="mt-12 text-xs text-gray-500 border-t border-gray-300 pt-4">
                    <h3 class="font-bold mb-2">CONDITIONS:</h3><p>This offer is valid for 30 days. All goods are sold under MMEM's Terms and Conditions of Sale. Any changes in applicable taxes (GST) or tariffs which may occur will be to your account.</p>
                </div>
            </div></body></html>
            """
            
            st.download_button(
                label="✅ Download Final Quote",
                data=quote_html.encode('utf-8'),
                file_name=f"Quote_{q_details['quoteNumber']}_{q_details['customerName']}.html",
                mime='text/html',
                use_container_width=True
            )
