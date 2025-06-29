# app.py

import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
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

def format_currency(num):
    """Formats a number as Australian currency."""
    if pd.isna(num) or num is None:
        return "$0.00"
    return f"${num:,.2f}"

# --- Gemini API Configuration ---
try:
    # Use st.secrets for secure API key storage in deployment
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    GEMINI_API_AVAILABLE = True
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found. Please add it to your Streamlit secrets.", icon="🚨")
    st.info("To get an API key, visit: https://makersuite.google.com/app/apikey")
    GEMINI_API_AVAILABLE = False
    
# --- Session State Initialization ---
if "quote_items" not in st.session_state:
    st.session_state.quote_items = pd.DataFrame(columns=[
        "TYPE", "QTY", "Supplier", "CAT_NO", "Description",
        "COST_PER_UNIT", "DISC", "MARGIN"
    ])

if "user_details" not in st.session_state:
    st.session_state.user_details = {
        "name": "Harry Leonhardt",
        "job_title": "Sales",
        "branch": "AWM Nunawading",
        "email": "harry.l@awm.mmem.com.au",
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
    uploaded_files = st.file_uploader(
        "Upload PDF or TXT files",
        type=['pdf', 'txt'],
        accept_multiple_files=True,
        help="Upload one or more supplier quote documents. The system will extract line items."
    )

    process_button = st.button("Process Uploaded Files", type="primary", use_container_width=True, disabled=not uploaded_files)

    st.divider()

    st.subheader("2. Global Settings")
    global_margin = st.number_input("Global Margin (%)", value=9.0, min_value=0.0, step=1.0, format="%.2f")
    if st.button("Apply Global Margin", use_container_width=True):
        if not st.session_state.quote_items.empty:
            st.session_state.quote_items['MARGIN'] = global_margin
            st.toast(f"Applied {global_margin}% margin to all items.")
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
    header_image = st.file_uploader("Upload Header Image", type=['png', 'jpg', 'jpeg'], help="Optional: Upload a banner image for the quote header.")
    if header_image:
        st.session_state.header_image_b64 = image_to_base64(header_image)
        st.image(header_image, caption="Header image preview")


    st.divider()
    
    st.subheader("4. AI Actions")
    if st.button("✨ Generate Project Summary", use_container_width=True, disabled=st.session_state.quote_items.empty):
        with st.spinner("🤖 Gemini is summarizing the project scope..."):
            try:
                # Same summary generation logic as before
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
    # This logic remains the same as the previous version
    with st.spinner(f"Processing {len(uploaded_files)} file(s) with Gemini... This may take a moment."):
        all_new_items = []
        failed_files = []
        extraction_prompt = (
            "From the provided document, extract all line items. For each item, extract: "
            "TYPE, QTY, Supplier, CAT_NO, Description, and COST_PER_UNIT. "
            "Return a JSON array of objects. Ensure QTY and COST_PER_UNIT are numbers."
        )
        json_schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"}, "CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]}}
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})

        for file in uploaded_files:
            try:
                st.write(f"Processing `{file.name}`...")
                part = file_to_generative_part(file)
                response = model.generate_content([extraction_prompt, part])
                extracted_data = json.loads(response.text)
                all_new_items.extend(extracted_data)
            except Exception as e:
                st.error(f"Error processing `{file.name}`: {e}")
                failed_files.append(file.name)
        
        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = global_margin
            st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            st.success(f"Successfully extracted {len(all_new_items)} items!")
        if failed_files:
            st.warning(f"Could not process the following files: {', '.join(failed_files)}")


# --- Main Content Area ---
if st.session_state.quote_items.empty:
    st.info("Upload supplier quotes using the sidebar to get started.")
else:
    # All content for the main area will be inside this container
    with st.container():
        # --- Display Project Summary if available ---
        if st.session_state.project_summary:
            st.subheader("✨ Project Scope Summary")
            st.markdown(st.session_state.project_summary)
            st.divider()

        # --- Editable Quote Table ---
        st.subheader("Quote Line Items")
        st.caption("You can edit values directly in the table below. Calculations will update automatically.")
        
        edited_df = st.data_editor(
            st.session_state.quote_items,
            column_config={
                "COST_PER_UNIT": st.column_config.NumberColumn("Cost/Unit", format="$%.2f"),
                "DISC": st.column_config.NumberColumn("Disc %", format="%.1f%%"),
                "MARGIN": st.column_config.NumberColumn("Margin %", format="%.1f%%"),
                "Description": st.column_config.TextColumn("Description", width="large"),
            },
            num_rows="dynamic",
            use_container_width=True,
            key="data_editor"
        )
        st.session_state.quote_items = edited_df

        # --- Real-time Calculations ---
        df = st.session_state.quote_items.copy()
        for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df['LINE_COST'] = df['QTY'] * df['COST_PER_UNIT']
        cost_after_disc = df['COST_PER_UNIT'] * (1 - df['DISC'] / 100)
        df['SELL_UNIT_EX_GST'] = cost_after_disc * (1 + df['MARGIN'] / 100)
        df['SELL_TOTAL_EX_GST'] = df['SELL_UNIT_EX_GST'] * df['QTY']
        gst_rate = 10
        df['GST_AMOUNT'] = df['SELL_TOTAL_EX_GST'] * (gst_rate / 100)
        df['SELL_TOTAL_INC_GST'] = df['SELL_TOTAL_EX_GST'] + df['GST_AMOUNT']

        st.divider()
        # --- Display Totals ---
        st.subheader("Quote Totals")
        col1, col2, col3 = st.columns(3)
        col1.metric("Sub-Total (ex. GST)", format_currency(df['SELL_TOTAL_EX_GST'].sum()))
        col2.metric("GST (10%)", format_currency(df['GST_AMOUNT'].sum()))
        col3.metric("Grand Total (inc. GST)", format_currency(df['SELL_TOTAL_INC_GST'].sum()))
        
        st.divider()
        # --- Finalize and Generate Quote ---
        st.header("Finalise and Generate Quote")

        with st.form("quote_details_form"):
            st.subheader("Quote Recipient & Project Details")
            q_details = st.session_state.quote_details
            
            c1, c2 = st.columns(2)
            q_details['customerName'] = c1.text_input("Customer Name", value=q_details['customerName'])
            q_details['attention'] = c2.text_input("Attention", value=q_details['attention'])
            q_details['projectName'] = c1.text_input("Project Name", value=q_details['projectName'])
            q_details['quoteNumber'] = c2.text_input("Quote Number", value=q_details['quoteNumber'])
            
            submitted = st.form_submit_button("Generate Final Quote HTML", type="primary", use_container_width=True)

        if submitted:
            # Generate the HTML content for the quote
            items_html = ""
            for i, row in df.iterrows():
                items_html += f"""
                <tr class="border-b border-gray-200">
                    <td class="p-3">{i + 1}</td>
                    <td class="p-3">{row['TYPE']}</td>
                    <td class="p-3">{row['QTY']}</td>
                    <td class="p-3">{row['Supplier']}</td>
                    <td class="p-3">{row['CAT_NO']}</td>
                    <td class="p-3 w-1/3">{row['Description']}</td>
                    <td class="p-3 text-right">{format_currency(row['SELL_UNIT_EX_GST'])}</td>
                    <td class="p-3 text-right">{format_currency(row['SELL_TOTAL_EX_GST'])}</td>
                </tr>
                """
            
            header_image_html = ""
            if st.session_state.header_image_b64:
                header_image_html = f'<img src="data:image/png;base64,{st.session_state.header_image_b64}" alt="Custom Header" class="max-h-24 object-contain">'

            quote_html = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Quote {q_details['quoteNumber']}</title>
                <script src="https://cdn.tailwindcss.com"></script>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
                <style> body {{ font-family: 'Inter', sans-serif; }} </style>
            </head>
            <body class="bg-gray-100 p-4 sm:p-8">
                <div class="max-w-4xl mx-auto bg-white p-6 sm:p-10 shadow-2xl rounded-xl">
                    <header class="flex justify-between items-start mb-8 border-b border-gray-300 pb-8">
                        <div>
                            <img src="https://i.imgur.com/nwCXdLa.png" alt="AWM Logo" class="h-16 mb-4">
                            <h1 class="text-2xl font-bold text-gray-800">{st.session_state.user_details['branch']}</h1>
                            <p class="text-sm text-gray-600">A Division of Metal Manufactures Limited (A.B.N. 13 003 762 641)</p>
                        </div>
                        <div class="text-right">
                            {header_image_html}
                            <h2 class="text-3xl font-bold text-gray-700 mt-4">QUOTATION</h2>
                        </div>
                    </header>
                    <section class="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                            <h2 class="font-bold text-gray-800 mb-2">QUOTE TO:</h2>
                            <p class="text-gray-700">{q_details['customerName']}</p>
                            <p class="text-gray-700">Attn: {q_details['attention'] or 'N/A'}</p>
                        </div>
                        <div class="bg-gray-50 p-4 rounded-lg border border-gray-200">
                             <p class="text-gray-700"><strong class="font-bold text-gray-800">PROJECT:</strong> {q_details['projectName']}</p>
                             <p class="text-gray-700"><strong class="font-bold text-gray-800">QUOTE #:</strong> {q_details['quoteNumber']}</p>
                             <p class="text-gray-700"><strong class="font-bold text-gray-800">DATE:</strong> {q_details['date']}</p>
                        </div>
                    </section>
                    {f'<section class="mb-8 p-4 bg-blue-50 border border-blue-200 rounded-lg"><h3 class="font-bold text-lg mb-2 text-blue-900">Project Summary</h3><p class="text-gray-700 whitespace-pre-wrap">{st.session_state.project_summary}</p></section>' if st.session_state.project_summary else ''}
                    <main>
                        <table class="w-full text-left text-sm">
                            <thead class="bg-slate-800 text-white">
                                <tr>
                                    <th class="p-3 rounded-tl-lg">ITEM</th><th class="p-3">TYPE</th><th class="p-3">QTY</th><th class="p-3">BRAND</th>
                                    <th class="p-3">CAT NO</th><th class="p-3 w-1/3">DESCRIPTION</th>
                                    <th class="p-3 text-right">UNIT EX GST</th><th class="p-3 text-right rounded-tr-lg">TOTAL EX GST</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-200">{items_html}</tbody>
                        </table>
                    </main>
                    <footer class="mt-8 flex justify-end">
                        <div class="w-full sm:w-1/2">
                            <div class="flex justify-between p-3 bg-gray-100 rounded-t-lg"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span class="text-gray-800">{format_currency(df['SELL_TOTAL_EX_GST'].sum())}</span></div>
                            <div class="flex justify-between p-3"><span class="font-bold text-gray-800">GST (10%):</span><span class="text-gray-800">{format_currency(df['GST_AMOUNT'].sum())}</span></div>
                            <div class="flex justify-between p-4 bg-slate-800 text-white font-bold text-lg rounded-b-lg"><span>Grand Total (Inc GST):</span><span>{format_currency(df['SELL_TOTAL_INC_GST'].sum())}</span></div>
                        </div>
                    </footer>
                    <div class="mt-12 pt-8 border-t-2 border-dashed border-gray-300">
                        <h3 class="font-bold text-gray-800">Prepared For You By:</h3>
                        <p class="text-gray-700 mt-2">{st.session_state.user_details['name']}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details['job_title']}</p>
                        <p class="text-gray-600 text-sm">{st.session_state.user_details['branch']}</p>
                        <p class="mt-2 text-sm"><strong>Email:</strong> {st.session_state.user_details['email']}</p>
                        <p class="text-sm"><strong>Phone:</strong> {st.session_state.user_details['phone']}</p>
                    </div>
                    <div class="mt-12 text-xs text-gray-500 border-t border-gray-300 pt-4">
                        <h3 class="font-bold mb-2">CONDITIONS:</h3>
                        <p>This offer is valid for 30 days. All goods are sold under MMEM's Terms and Conditions of Sale. Any changes in applicable taxes (GST) or tariffs which may occur will be to your account.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            st.download_button(
                label="✅ Download Final Quote",
                data=quote_html.encode('utf-8'),
                file_name=f"Quote_{q_details['quoteNumber']}_{q_details['customerName']}.html",
                mime='text/html',
                use_container_width=True
            )

