# app.py
import streamlit as st
import pandas as pd
import fitz  # pymupdf
import requests
import json
from datetime import datetime
import base64

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
        response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)
        result = response.json()

        if "candidates" in result and result["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text"):
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            st.error("API response is missing the expected content.")
            st.json(result) # Show the malformed response for debugging
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        # Try to show more detailed error from response body
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
    
    # Generate table rows from the dataframe
    rows_html = ""
    for index, row in df.iterrows():
        rows_html += f"""
        <tr class="border-b {'bg-white' if index % 2 == 0 else 'bg-gray-50'}">
            <td class="p-2">{index + 1}</td>
            <td class="p-2">{row.get('TYPE', '')}</td>
            <td class="p-2">{row.get('QTY', 0)}</td>
            <td class="p-2">{row.get('Supplier', '')}</td>
            <td class="p-2">{row.get('CAT_NO', '')}</td>
            <td class="p-2">{row.get('Description', '')}</td>
            <td class="p-2 text-right">{format_currency(row.get('UNIT_SELL_EX_GST', 0))}</td>
            <td class="p-2 text-right">{format_currency(row.get('TOTAL_SELL_EX_GST', 0))}</td>
            <td class="p-2 text-right">{format_currency(row.get('TOTAL_SELL_INC_GST', 0))}</td>
        </tr>
        """
        
    gst_total = totals['total_inc_gst'] - totals['total_ex_gst']

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Quote {details['quote_number']}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style> body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }} </style>
    </head>
    <body class="bg-gray-100 p-8">
        <div class="max-w-4xl mx-auto bg-white p-10 shadow-lg">
            <header class="flex justify-between items-start mb-8 border-b pb-8">
                <div>
                    <img src="https://www.mmem.com.au/gfx/MMEM-logo.svg" alt="AWM Logo" class="h-16 mb-4">
                    <h1 class="text-2xl font-bold text-gray-800">AWM NUNAWADING</h1>
                    <p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p>
                    <address class="mt-2 not-italic text-sm text-gray-600">
                        31-33 Rooks Road<br>
                        Nunawading, VIC 3131
                    </address>
                     <div class="mt-2 text-sm text-gray-600">
                        <p><strong>P:</strong> 03 8846 2500</p>
                        <p><strong>F:</strong> 03 8846 2501</p>
                        <p><strong>E:</strong> heath.judd@mmem.com.au</p>
                    </div>
                </div>
                <div></div>
            </header>
            <section class="grid grid-cols-2 gap-8 mb-8">
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h2 class="font-bold text-gray-700 mb-2">QUOTE TO:</h2>
                    <p>{details['customer_name']}</p>
                    <p>Attn: {details.get('attention', 'N/A')}</p>
                </div>
                <div class="bg-gray-50 p-4 rounded-lg">
                    <h2 class="font-bold text-gray-700 mb-2">PROJECT DETAILS:</h2>
                    <p><strong>PROJECT:</strong> {details['project_name']}</p>
                    <p><strong>QUOTE NO:</strong> {details['quote_number']}</p>
                    <p><strong>DATE:</strong> {details['date']}</p>
                    <p><strong>PREPARED BY:</strong> {details['prepared_by']}</p>
                </div>
            </section>
            <main>
                <table class="w-full text-left text-sm">
                    <thead class="bg-gray-800 text-white">
                        <tr>
                            <th class="p-2">ITEM</th><th class="p-2">TYPE</th><th class="p-2">QTY</th><th class="p-2">BRAND</th>
                            <th class="p-2">CAT NO</th><th class="p-2 w-1/3">DESCRIPTION</th>
                            <th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right">TOTAL EX GST</th>
                            <th class="p-2 text-right">TOTAL INC GST</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </main>
            <footer class="mt-8 flex justify-end">
                <div class="w-1/2">
                    <div class="flex justify-between p-2 bg-gray-100 rounded-t-lg"><span class="font-bold">Sub-Total (Ex GST):</span><span>{format_currency(totals['total_ex_gst'])}</span></div>
                    <div class="flex justify-between p-2"><span class="font-bold">GST:</span><span>{format_currency(gst_total)}</span></div>
                    <div class="flex justify-between p-4 bg-gray-800 text-white font-bold text-lg rounded-b-lg"><span class="">Grand Total (Inc GST):</span><span>{format_currency(totals['total_inc_gst'])}</span></div>
                </div>
            </footer>
            <div class="mt-12 text-xs text-gray-500 border-t pt-4">
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

# --- Main App UI ---
st.title("📄 Quote Generator Pro")
st.write("Upload supplier quotes (PDF or TXT) to automatically extract line items, then edit and generate a final customer quote.")

# --- Sidebar for Controls & API Key ---
with st.sidebar:
    st.header("⚙️ Controls & Settings")
    
    st.text_input(
        "Gemini API Key",
        type="password",
        key="api_key",
        help="Your Google AI Studio API key. This is stored securely for your session."
    )

    st.info("💡 Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey).")

    global_margin = st.number_input(
        "Global Margin (%)", 
        min_value=0.0, 
        value=9.0, 
        step=1.0, 
        key="global_margin"
    )
    
    gst_rate = st.number_input(
        "GST Rate (%)",
        min_value=0.0,
        value=10.0,
        step=0.5,
        key="gst_rate"
    )

    if st.button("Apply Global Margin to All Items"):
        df = st.session_state.quote_items_df
        if not df.empty:
            df['MARGIN'] = global_margin
            st.session_state.quote_items_df = df
            st.success(f"Global margin of {global_margin}% applied.")
            st.rerun()

# --- File Uploader and Processing ---
st.header("1. Upload Supplier Quotes")
uploaded_files = st.file_uploader(
    "Choose PDF or TXT files",
    type=["pdf", "txt"],
    accept_multiple_files=True
)

if uploaded_files:
    if st.button("✨ Extract Items from Uploaded Files", type="primary"):
        with st.spinner("Processing documents with Gemini... This may take a moment."):
            all_new_items = []
            failed_files = []

            # Define the JSON schema for Gemini
            json_schema = {
                "type": "ARRAY", "items": { "type": "OBJECT", "properties": {
                    "TYPE": { "type": "STRING" }, "QTY": { "type": "NUMBER" }, "Supplier": { "type": "STRING" },
                    "CAT_NO": { "type": "STRING" }, "Description": { "type": "STRING" }, "COST_PER_UNIT": { "type": "NUMBER" }
                }, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"] }
            }

            for uploaded_file in uploaded_files:
                try:
                    file_bytes = uploaded_file.getvalue()
                    
                    if uploaded_file.type == "application/pdf":
                        # For PDFs, extract text first
                        doc = fitz.open(stream=file_bytes, filetype="pdf")
                        file_text = "".join(page.get_text() for page in doc)
                        prompt_text = f"From the provided text extracted from a PDF, extract all line items. Document Text: \n\n{file_text}"
                        payload = {
                            "contents": [{"parts": [{"text": prompt_text}]}],
                            "generationConfig": {"responseMimeType": "application/json", "responseSchema": json_schema}
                        }
                    else: # Assumes text/plain
                        base64_data = base64.b64encode(file_bytes).decode('utf-8')
                        prompt_text = "From the provided document, extract all line items. For each item, extract: TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. Return a JSON array of objects."
                        payload = {
                            "contents": [{"parts": [{"text": prompt_text}, {"inlineData": {"mimeType": uploaded_file.type, "data": base64_data}}]}],
                            "generationConfig": {"responseMimeType": "application/json", "responseSchema": json_schema}
                        }

                    json_text = call_gemini_api(payload)
                    
                    if json_text:
                        parsed_items = json.loads(json_text)
                        all_new_items.extend(parsed_items)
                    else:
                        failed_files.append(uploaded_file.name)

                except Exception as e:
                    st.error(f"Error processing {uploaded_file.name}: {e}")
                    failed_files.append(uploaded_file.name)

            if all_new_items:
                new_df = pd.DataFrame(all_new_items)
                new_df['DISC'] = 0.0
                new_df['MARGIN'] = st.session_state.global_margin
                new_df['ENHANCE'] = False
                st.session_state.quote_items_df = pd.concat([st.session_state.quote_items_df, new_df], ignore_index=True)
                st.success(f"Successfully extracted {len(all_new_items)} items!")
            
            if failed_files:
                st.warning(f"Could not process the following files: {', '.join(failed_files)}")


# --- Display and Edit Quote Items ---
if not st.session_state.quote_items_df.empty:
    st.header("2. Review and Edit Quote Items")

    edited_df = st.session_state.quote_items_df.copy()

    # Ensure numeric columns are of a numeric type for calculations
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        edited_df[col] = pd.to_numeric(edited_df[col], errors='coerce').fillna(0)

    # --- Calculations ---
    edited_df['LINE_COST'] = edited_df['QTY'] * edited_df['COST_PER_UNIT']
    cost_after_disc = edited_df['COST_PER_UNIT'] * (1 - edited_df['DISC'] / 100)
    edited_df['UNIT_SELL_EX_GST'] = cost_after_disc * (1 + edited_df['MARGIN'] / 100)
    edited_df['TOTAL_SELL_EX_GST'] = edited_df['UNIT_SELL_EX_GST'] * edited_df['QTY']
    gst_multiplier = 1 + st.session_state.gst_rate / 100
    edited_df['TOTAL_SELL_INC_GST'] = edited_df['TOTAL_SELL_EX_GST'] * gst_multiplier

    # --- Totals ---
    totals = {
        'total_ex_gst': edited_df['TOTAL_SELL_EX_GST'].sum(),
        'total_inc_gst': edited_df['TOTAL_SELL_INC_GST'].sum()
    }
    
    st.markdown("Use the table below to adjust quantities, costs, discounts, and margins. All financial columns will update automatically.")

    # --- Data Editor ---
    edited_df_from_editor = st.data_editor(
        edited_df,
        column_config={
            "Description": st.column_config.TextColumn(width="large"),
            "COST_PER_UNIT": st.column_config.NumberColumn(format="$%.2f"),
            "DISC": st.column_config.NumberColumn(label="Disc %"),
            "MARGIN": st.column_config.NumberColumn(label="Margin %"),
            "ENHANCE": st.column_config.CheckboxColumn(label="Enhance? ✨"),
            # Calculated columns should not be editable
            "LINE_COST": st.column_config.NumberColumn(label="Line Cost", format="$%.2f", disabled=True),
            "UNIT_SELL_EX_GST": st.column_config.NumberColumn(label="Unit Sell (ex GST)", format="$%.2f", disabled=True),
            "TOTAL_SELL_EX_GST": st.column_config.NumberColumn(label="Total Sell (ex GST)", format="$%.2f", disabled=True),
            "TOTAL_SELL_INC_GST": st.column_config.NumberColumn(label="Total Sell (inc GST)", format="$%.2f", disabled=True),
        },
        num_rows="dynamic",
        key="data_editor"
    )

    # Update session state with the edited dataframe from the editor
    st.session_state.quote_items_df = edited_df_from_editor

    # --- Action Buttons ---
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✍️ Enhance Selected Descriptions"):
            with st.spinner("Enhancing descriptions with Gemini..."):
                df = st.session_state.quote_items_df.copy()
                enhanced_count = 0
                indices_to_enhance = df[df['ENHANCE']].index
                
                for index in indices_to_enhance:
                    prompt = f"Rewrite the following technical product description into a clear, client-friendly sentence (do not add any preamble like 'here is the rewritten description'):\n\n\"{df.at[index, 'Description']}\""
                    payload = {"contents": [{"parts": [{"text": prompt}]}]}
                    enhanced_text = call_gemini_api(payload)
                    if enhanced_text:
                        df.at[index, 'Description'] = enhanced_text.strip().replace('"', '')
                        df.at[index, 'ENHANCE'] = False
                        enhanced_count += 1
                
                st.session_state.quote_items_df = df
                st.success(f"Successfully enhanced {enhanced_count} descriptions.")
                st.rerun()

    with col3:
        if st.button("🗑️ Clear All Items", type="secondary"):
            st.session_state.quote_items_df = pd.DataFrame(columns=st.session_state.quote_items_df.columns)
            st.session_state.project_summary = ""
            st.rerun()

    # --- Final Quote Section ---
    st.header("3. Generate Final Quote")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 Generate Project Summary"):
            if not st.session_state.quote_items_df.empty:
                with st.spinner("Generating summary..."):
                    items_for_prompt = "\n".join(
                        f"- {row['QTY']}x {row['Description']} (from {row['Supplier']})"
                        for _, row in st.session_state.quote_items_df.iterrows()
                    )
                    prompt = f"""Based on the following list of electrical components, write a 2-paragraph summary of this project's scope for a client proposal. Mention the key types of products being installed (e.g., emergency lighting, architectural downlights, weatherproof battens) and the primary suppliers involved.\n\nItems:\n{items_for_prompt}"""
                    payload = {"contents": [{"parts": [{"text": prompt}]}]}
                    summary = call_gemini_api(payload)
                    if summary:
                        st.session_state.project_summary = summary
            else:
                st.warning("Please add items to the quote first.")

    if st.session_state.project_summary:
        st.subheader("Generated Project Summary")
        st.text_area("You can edit the summary below before finalizing the quote.", value=st.session_state.project_summary, height=200, key="summary_text_area")

    with st.expander("Enter Final Quote Details", expanded=True):
        with st.form("quote_details_form"):
            c1, c2 = st.columns(2)
            with c1:
                customer_name = st.text_input("Customer Name", value="Elon Electrics")
                attention = st.text_input("Attention")
                project_name = st.text_input("Project Name", value="Nazareth College Student Hub")
            with c2:
                quote_number = st.text_input("Quote Number", value=f"Q{datetime.now().strftime('%Y%m%d%H%M')}")
                prepared_by = st.text_input("Prepared By", value="Harry L")
                date = st.date_input("Date", value=datetime.now())

            submitted = st.form_submit_button("✓ Generate & Download Quote HTML", type="primary")
            if submitted:
                # Use the most up-to-date dataframe for the final HTML
                final_df = st.session_state.quote_items_df
                
                # Recalculate totals just before generating HTML to be safe
                for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
                    final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)
                final_df['LINE_COST'] = final_df['QTY'] * final_df['COST_PER_UNIT']
                cost_after_disc = final_df['COST_PER_UNIT'] * (1 - final_df['DISC'] / 100)
                final_df['UNIT_SELL_EX_GST'] = cost_after_disc * (1 + final_df['MARGIN'] / 100)
                final_df['TOTAL_SELL_EX_GST'] = final_df['UNIT_SELL_EX_GST'] * final_df['QTY']
                gst_multiplier = 1 + st.session_state.gst_rate / 100
                final_df['TOTAL_SELL_INC_GST'] = final_df['TOTAL_SELL_EX_GST'] * gst_multiplier
                final_totals = {
                    'total_ex_gst': final_df['TOTAL_SELL_EX_GST'].sum(),
                    'total_inc_gst': final_df['TOTAL_SELL_INC_GST'].sum()
                }

                quote_details = {
                    "customer_name": customer_name, "attention": attention,
                    "project_name": project_name, "quote_number": quote_number,
                    "prepared_by": prepared_by, "date": date.strftime('%d/%m/%Y')
                }
                
                final_html = generate_quote_html(final_df, quote_details, final_totals)
                
                st.download_button(
                    label="📥 Download Quote File",
                    data=final_html,
                    file_name=f"Quote_{quote_details['quote_number']}_{quote_details['customer_name']}.html",
                    mime="text/html"
                )
                st.success("Quote generated! Use the download button above.")
