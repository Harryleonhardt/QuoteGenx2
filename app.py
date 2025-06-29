# app.py
import streamlit as st
import pandas as pd
import fitz  # pymupdf
import requests
import json
from datetime import datetime
import base64
import re

# --- Page Configuration ---
st.set_page_config(
    page_title="Quote Generator Pro",
    page_icon="📄",
    layout="wide"
)

# --- Helper Functions ---

def format_currency(value):
    """Formats a number as a currency string."""
    if pd.isna(value):
        return "$0.00"
    return f"${value:,.2f}"

def clean_and_parse_json(json_string):
    """
    Attempts to clean and parse a potentially malformed JSON string from the API.
    """
    # Remove any markdown backticks and the word 'json'
    cleaned_string = re.sub(r'```json\s*|\s*```', '', json_string.strip())

    # Try to find the start of the JSON array '[' and the end ']'
    try:
        start_index = cleaned_string.find('[')
        end_index = cleaned_string.rfind(']')
        if start_index != -1 and end_index != -1:
            # Extract the content between the first '[' and last ']'
            potential_json = cleaned_string[start_index : end_index + 1]
            return json.loads(potential_json)
        else:
            # Fallback for single object responses
            start_index = cleaned_string.find('{')
            end_index = cleaned_string.rfind('}')
            if start_index != -1 and end_index != -1:
                potential_json = cleaned_string[start_index : end_index + 1]
                return json.loads(potential_json)
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse cleaned JSON. Error: {e}")
        st.text_area("Problematic API Response:", cleaned_string, height=200)
        return None
    
    st.error("Could not find a valid JSON array or object in the API response.")
    st.text_area("Raw API Response:", json_string, height=200)
    return None


def call_gemini_api(payload):
    """
    Calls the Gemini API with the provided payload.
    Requires the API key to be set in st.session_state.
    """
    api_key = st.session_state.get("api_key", "")
    if not api_key:
        st.error("Gemini API Key is not set. Please enter it in the sidebar.")
        return None

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=120)
        response.raise_for_status()
        result = response.json()

        if "candidates" in result and result["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text"):
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            st.error("API response is missing the expected content.")
            st.json(result)
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        try:
            st.json(response.json())
        except:
            st.text(response.text)
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during API call: {e}")
        return None

def generate_quote_html(df, details, totals):
    """Generates the final quote HTML from the dataframe and details."""
    
    # --- Dynamic Details ---
    prepared_by_name = details.get('prepared_by', '')
    job_title = details.get('job_title', '')
    branch = details.get('branch', 'AWM Branch')
    logo_url = details.get('logo_url', 'https://www.mmem.com.au/gfx/MMEM-logo.svg') # Fallback logo
    
    email_name = prepared_by_name.lower().replace(" ", ".")
    dynamic_email = f"{email_name}@mmem.com.au"

    # Generate table rows
    rows_html = "".join(
        f"""
        <tr class="border-b {'bg-white' if index % 2 == 0 else 'bg-gray-50'}">
            <td class="p-3">{index + 1}</td>
            <td class="p-3">{row.get('TYPE', '')}</td>
            <td class="p-3">{row.get('QTY', 0)}</td>
            <td class="p-3">{row.get('Supplier', '')}</td>
            <td class="p-3">{row.get('CAT_NO', '')}</td>
            <td class="p-3">{row.get('Description', '')}</td>
            <td class="p-3 text-right">{format_currency(row.get('UNIT_SELL_EX_GST', 0))}</td>
            <td class="p-3 text-right">{format_currency(row.get('TOTAL_SELL_EX_GST', 0))}</td>
            <td class="p-3 text-right">{format_currency(row.get('TOTAL_SELL_INC_GST', 0))}</td>
        </tr>
        """
        for index, row in df.iterrows()
    )
        
    gst_total = totals['total_inc_gst'] - totals['total_ex_gst']

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Quote {details['quote_number']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap" rel="stylesheet">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ font-family: 'Roboto', sans-serif; }}
            .details-label {{ font-weight: 700; color: #374151; }}
        </style>
    </head>
    <body class="bg-gray-100 p-8">
        <div class="max-w-4xl mx-auto bg-white p-12 shadow-2xl rounded-lg">
            <header class="flex justify-between items-start mb-10 border-b-2 border-gray-200 pb-8">
                <div>
                    <img src="{logo_url}" alt="Company Logo" class="h-20 mb-4">
                    <h1 class="text-3xl font-bold text-gray-800">{branch}</h1>
                    <p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p>
                </div>
                <div class="text-right text-sm text-gray-600">
                    <p><span class="details-label">Phone:</span> 03 8846 2500</p>
                    <p><span class="details-label">Fax:</span> 03 8846 2501</p>
                    <p><span class="details-label">Email:</span> {dynamic_email}</p>
                </div>
            </header>
            <section class="grid grid-cols-2 gap-8 mb-10">
                <div class="bg-gray-50 p-6 rounded-lg border border-gray-200">
                    <h2 class="text-lg font-bold text-gray-700 mb-3">QUOTE TO:</h2>
                    <p>{details['customer_name']}</p>
                    <p>Attn: {details.get('attention', 'N/A')}</p>
                </div>
                <div class="bg-gray-50 p-6 rounded-lg border border-gray-200">
                    <h2 class="text-lg font-bold text-gray-700 mb-3">PROJECT DETAILS:</h2>
                    <p><span class="details-label">Project:</span> {details['project_name']}</p>
                    <p><span class="details-label">Quote No:</span> {details['quote_number']}</p>
                    <p><span class="details-label">Date:</span> {details['date']}</p>
                    <p><span class="details-label">Prepared By:</span> {prepared_by_name}</p>
                </div>
            </section>
            <main>
                <table class="w-full text-left text-sm">
                    <thead class="bg-gray-800 text-white">
                        <tr>
                            <th class="p-3">ITEM</th><th class="p-3">TYPE</th><th class="p-3">QTY</th><th class="p-3">BRAND</th>
                            <th class="p-3">CAT NO</th><th class="p-3 w-1/3">DESCRIPTION</th>
                            <th class="p-3 text-right">UNIT EX GST</th><th class="p-3 text-right">TOTAL EX GST</th>
                            <th class="p-3 text-right">TOTAL INC GST</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </main>
            <footer class="mt-10 pt-8 border-t-2 border-gray-200 flex justify-between items-end">
                <div>
                    <h3 class="font-bold text-gray-800 text-lg">Kind Regards,</h3>
                    <p class="mt-6 text-gray-700">{prepared_by_name}</p>
                    <p class="text-sm text-gray-600">{job_title}</p>
                </div>
                <div class="w-1/2">
                    <div class="flex justify-between p-3 bg-gray-100 rounded-t-lg"><span class="font-bold">Sub-Total (Ex GST):</span><span>{format_currency(totals['total_ex_gst'])}</span></div>
                    <div class="flex justify-between p-3"><span class="font-bold">GST:</span><span>{format_currency(gst_total)}</span></div>
                    <div class="flex justify-between p-4 bg-gray-800 text-white font-bold text-xl rounded-b-lg"><span class="">Grand Total (Inc GST):</span><span>{format_currency(totals['total_inc_gst'])}</span></div>
                </div>
            </footer>
            <div class="mt-12 text-xs text-gray-500 border-t pt-6">
                <h3 class="font-bold mb-2">CONDITIONS OF SALE:</h3>
                <p>The Products and Services appearing on this document are sold under the current MMEM Terms and Conditions of Sale applying at the date of order acceptance. A copy of these conditions is available upon request.</p>
                <p class="mt-2"><strong>THIS OFFER IS VALID FOR ACCEPTANCE 30 DAYS.</strong> ANY CHANGES IN APPLICABLE GOODS AND SERVICES TAXES, (GST) ,VAT OR TARIFFS, WHICH MAY OCCUR DURING THE AGREEMENT PERIOD WILL BE TO YOUR ACCOUNT.</p>
            </div>
        </div>
    </body>
    </html>
    """

# --- Initialize Session State ---
if "quote_items_df" not in st.session_state:
    st.session_state.quote_items_df = pd.DataFrame(columns=[
        "TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT", 
        "DISC", "MARGIN", "ENHANCE"
    ])
if "project_summary" not in st.session_state:
    st.session_state.project_summary = ""
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "final_html" not in st.session_state:
    st.session_state.final_html = None
if "quote_details" not in st.session_state:
    st.session_state.quote_details = {}

# --- Custom Styling ---
st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    .gradient-text {
        background: -webkit-linear-gradient(45deg, #0072ff, #00c6ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
        font-size: 2.5rem;
    }
    h1, h2, h3 { color: #2c3e50; }
    .stButton>button {
        border-radius: 8px;
        border: 1px solid transparent;
        transition: all 0.3s ease-in-out;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 8px rgba(0,0,0,0.15);
    }
    .stFileUploader {
        background-color: #ffffff;
        border-radius: 0.5rem;
        padding: 1.5rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
</style>
""", unsafe_allow_html=True)

# --- Main App UI ---
st.markdown('<p class="gradient-text">Quote Generator Pro</p>', unsafe_allow_html=True)
st.markdown("##### Created by Harry Leonhardt")
st.write("Upload supplier quotes (PDF or TXT) to automatically extract line items, then edit and generate a final customer quote.")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Controls & Settings")
    st.text_input("Gemini API Key", type="password", key="api_key", help="Your Google AI Studio API key.")
    st.info("💡 Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey).")
    st.number_input("Global Margin (%)", min_value=0.0, value=9.0, step=1.0, key="global_margin")
    st.number_input("GST Rate (%)", min_value=0.0, value=10.0, step=0.5, key="gst_rate")
    if st.button("Apply Global Margin"):
        if not st.session_state.quote_items_df.empty:
            st.session_state.quote_items_df['MARGIN'] = st.session_state.global_margin
            st.success(f"Global margin of {st.session_state.global_margin}% applied.")
            st.rerun()

# --- File Uploader ---
st.header("1. Upload Supplier Quotes")
uploaded_files = st.file_uploader("Choose PDF or TXT files", type=["pdf", "txt"], accept_multiple_files=True)

if uploaded_files:
    if st.button("✨ Extract Items from Files", type="primary"):
        with st.spinner("Processing documents with Gemini..."):
            all_items = []
            for file in uploaded_files:
                try:
                    bytes_data = file.getvalue()
                    schema = { "type": "ARRAY", "items": { "type": "OBJECT", "properties": { "TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"}, "CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}}}
                    
                    if file.type == "application/pdf":
                        # ** REVERTED LOGIC STARTS HERE **
                        # Use the simpler, more direct text extraction method
                        doc = fitz.open(stream=bytes_data, filetype="pdf")
                        text = "".join(page.get_text() for page in doc)
                        prompt = f"From the provided text extracted from a PDF, extract all line items. Document Text: \n\n{text}"
                        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema}}
                        # ** REVERTED LOGIC ENDS HERE **
                    else: # Handle TXT files
                        b64 = base64.b64encode(bytes_data).decode('utf-8')
                        prompt = "From the provided document, extract all line items. For each item, extract: TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. Return a JSON array of objects."
                        payload = {"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": file.type, "data": b64}}]}], "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema}}

                    json_text = call_gemini_api(payload)
                    if json_text:
                        # Use the robust parser to handle potentially messy API responses
                        parsed_data = clean_and_parse_json(json_text)
                        if parsed_data:
                            all_items.extend(parsed_data)
                except Exception as e:
                    st.error(f"Error processing {file.name}: {e}")
            
            if all_items:
                new_df = pd.DataFrame(all_items)
                new_df.fillna({'QTY': 1, 'COST_PER_UNIT': 0}, inplace=True)
                new_df['DISC'] = 0.0
                new_df['MARGIN'] = st.session_state.global_margin
                new_df['ENHANCE'] = False
                st.session_state.quote_items_df = pd.concat([st.session_state.quote_items_df, new_df], ignore_index=True)
                st.session_state.final_html = None
                st.success(f"Successfully extracted {len(all_items)} items!")

# --- Data Editor ---
if not st.session_state.quote_items_df.empty:
    st.header("2. Review and Edit Quote Items")
    
    df = st.session_state.quote_items_df.copy()
    # Ensure numeric types
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    st.session_state.quote_items_df = st.data_editor(
        df,
        column_config={
            "Description": st.column_config.TextColumn(width="large"),
            "COST_PER_UNIT": st.column_config.NumberColumn(format="$%.2f"),
            "ENHANCE": st.column_config.CheckboxColumn("Enhance? ✨")
        }, num_rows="dynamic", key="data_editor"
    )
    st.session_state.final_html = None

    # --- Action Buttons ---
    b_col1, b_col2, b_col3 = st.columns(3)
    if b_col1.button("✍️ Enhance Descriptions"):
        with st.spinner("Enhancing..."):
            df = st.session_state.quote_items_df.copy()
            for i, row in df[df['ENHANCE']].iterrows():
                prompt = f"Rewrite for a client proposal: \"{row['Description']}\""
                text = call_gemini_api({"contents": [{"parts": [{"text": prompt}]}]})
                if text:
                    df.at[i, 'Description'] = text.strip().strip('"')
                    df.at[i, 'ENHANCE'] = False
            st.session_state.quote_items_df = df
            st.rerun()

    if b_col3.button("🗑️ Clear All Items", type="secondary"):
        st.session_state.quote_items_df = pd.DataFrame(columns=df.columns)
        st.session_state.project_summary = ""
        st.session_state.final_html = None
        st.rerun()

    # --- Final Quote ---
    st.header("3. Generate Final Quote")
    if st.button("📝 Generate Project Summary"):
        # Summary generation logic...
        pass
    if st.session_state.project_summary:
        st.text_area("Project Summary", value=st.session_state.project_summary, height=150)

    with st.expander("Enter Final Quote Details", expanded=True):
        with st.form("quote_details_form"):
            c1, c2 = st.columns(2)
            logo_url = c1.text_input("Company Logo URL", value="https://i.imgur.com/3zWXg1E.png")
            branch = c1.text_input("Branch Name", value="AWM Nunawading")
            customer_name = c1.text_input("Customer Name")
            attention = c1.text_input("Attention")
            
            project_name = c2.text_input("Project Name")
            quote_number = c2.text_input("Quote Number", value=f"Q{datetime.now().strftime('%Y%m%d%H%M')}")
            prepared_by = c2.text_input("Prepared By")
            job_title = c2.text_input("Job Title")
            date = c2.date_input("Date", value=datetime.now())

            if st.form_submit_button("✓ Prepare Quote for Download", type="primary"):
                final_df = st.session_state.quote_items_df.copy()
                # Recalculate totals
                final_df['LINE_COST'] = final_df['QTY'] * final_df['COST_PER_UNIT']
                cost_after_disc = final_df['COST_PER_UNIT'] * (1 - final_df['DISC'] / 100)
                final_df['UNIT_SELL_EX_GST'] = cost_after_disc * (1 + final_df['MARGIN'] / 100)
                final_df['TOTAL_SELL_EX_GST'] = final_df['UNIT_SELL_EX_GST'] * final_df['QTY']
                final_df['TOTAL_SELL_INC_GST'] = final_df['TOTAL_SELL_EX_GST'] * (1 + st.session_state.gst_rate / 100)
                final_totals = {
                    'total_ex_gst': final_df['TOTAL_SELL_EX_GST'].sum(),
                    'total_inc_gst': final_df['TOTAL_SELL_INC_GST'].sum()
                }

                st.session_state.quote_details = {
                    "customer_name": customer_name, "attention": attention, "project_name": project_name, 
                    "quote_number": quote_number, "prepared_by": prepared_by, "job_title": job_title, 
                    "date": date.strftime('%d/%m/%Y'), "branch": branch, "logo_url": logo_url
                }
                
                st.session_state.final_html = generate_quote_html(final_df, st.session_state.quote_details, final_totals)
                st.success("Quote prepared! Download button below.")

    if st.session_state.final_html:
        details = st.session_state.quote_details
        file_name = f"Quote_{details.get('quote_number')}_{details.get('customer_name')}.html".replace(" ", "_")
        st.download_button("📥 Download Quote File", data=st.session_state.final_html, file_name=file_name, mime="text/html")
