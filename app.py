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

logo_path = Path(__file__).parent / "AWM Logo (002).png"

def get_logo_base64(file_path):
    try:
        with open(file_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        return None

company_logo_b64 = get_logo_base64(logo_path)
page_icon = f"data:image/png;base64,{company_logo_b64}" if company_logo_b64 else "📄"

st.set_page_config(
    page_title="AWM Quote Generator",
    page_icon=page_icon,
    layout="wide"
)

st.markdown("""
<style>
    body, .stApp {
        background-color: #f7fafc !important;
        font-family: 'Inter', sans-serif !important;
    }
    .stContainer {
        max-width: 1100px !important;
        margin: auto;
    }
    .stTitle, h1, h2, h3 {
        color: #1e293b;
    }
    .stTextInput>div>div>input,
    .stNumberInput input,
    .stTextArea textarea {
        background-color: #f4f6fa !important;
        border-radius: 4px !important;
        border: 1px solid #cbd5e1 !important;
    }
    .stButton>button {
        background-color: #1e293b !important;
        color: white !important;
        border-radius: 5px !important;
        border: none !important;
        font-weight: 500 !important;
        transition: background 0.2s;
    }
    .stButton>button:hover {
        background-color: #0f172a !important;
    }
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        background: #fff;
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(30,41,59,0.10), 0 1.5px 6px rgba(0,0,0,0.04);
        margin-bottom: 2rem;
    }
    .drag-drop-box {
        border: 2px dashed #64748b;
        border-radius: 8px;
        background: #f1f5f9;
        padding: 2rem;
        text-align: center;
        color: #334155;
        margin-bottom: 2rem;
    }
    .awm-logo-header {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 0;
    }
    .awm-logo-header img {
        height: 50px;
    }
    .awm-logo-header h1 {
        font-size: 2.5rem;
        margin-bottom: 0;
        color: #1e293b;
        font-weight: 700;
        letter-spacing: 0.02em;
    }
</style>
""", unsafe_allow_html=True)

def file_to_generative_part(file):
    bytes_io = BytesIO(file.getvalue())
    return {"mime_type": file.type, "data": bytes_io.read()}

def image_to_base64(image_file):
    if image_file is not None:
        bytes_data = image_file.getvalue()
        return base64.b64encode(bytes_data).decode()
    return None

def format_currency(num):
    if pd.isna(num) or num is None:
        return "$0.00"
    return f"${num:,.2f}"

def check_password():
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

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    GEMINI_API_AVAILABLE = True
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found. Please add it to your Streamlit secrets.", icon="🚨")
    st.info("To get an API key, visit: https://makersuite.google.com/app/apikey")
    GEMINI_API_AVAILABLE = False
    st.stop()

if not check_password():
    st.stop()

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
    st.session_state.company_logo_b64 = company_logo_b64
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"

with st.container():
    st.markdown(
        f'<div class="awm-logo-header">'
        f'<img src="data:image/png;base64,{company_logo_b64}" alt="AWM Logo" />'
        f'<h1>AWM Quote Generator</h1></div>',
        unsafe_allow_html=True
    )
    st.caption(
        f"App created by Harry Leonhardt | Quote prepared by: "
        f"**{st.session_state.user_details['name'] or 'Your Name'}**"
    )

    with st.form("details_form"):
        st.markdown("#### Your Details & Customer Details")
        c1, c2, c3 = st.columns([1.2, 1.2, 1])
        with c1:
            st.text_input("Your Name", value=st.session_state.user_details['name'], key="name")
            st.text_input("Job Title", value=st.session_state.user_details['job_title'], key="job_title")
            st.text_input("Branch", value=st.session_state.user_details['branch'], key="branch")
            st.text_input("Your Email", value=st.session_state.user_details['email'], key="email")
            st.text_input("Your Phone", value=st.session_state.user_details['phone'], key="phone")
        with c2:
            st.text_input("Customer Name", value=st.session_state.quote_details['customerName'], key="customerName")
            st.text_input("Attention", value=st.session_state.quote_details['attention'], key="attention")
            st.text_input("Project Name", value=st.session_state.quote_details['projectName'], key="projectName")
            st.text_input("Quote Number", value=st.session_state.quote_details['quoteNumber'], key="quoteNumber")
        with c3:
            global_margin = st.number_input("Global Margin (%)", value=9.0, min_value=0.0, max_value=99.9, step=1.0, format="%.2f", key="global_margin")
        col_apply, col_clear = st.columns(2)
        apply_margin = col_apply.form_submit_button("Apply Margin")
        clear_all = col_clear.form_submit_button("Clear All Items")
        for field in ["name", "job_title", "branch", "email", "phone"]:
            st.session_state.user_details[field] = st.session_state[field]
        for field in ["customerName", "attention", "projectName", "quoteNumber"]:
            st.session_state.quote_details[field] = st.session_state[field]

    if apply_margin:
        if not st.session_state.quote_items.empty:
            st.session_state.quote_items['MARGIN'] = global_margin
            st.toast(f"Applied {global_margin}% margin to all items.")
            st.rerun()
        else:
            st.warning("No items in the quote to apply margin to.")

    if clear_all:
        st.session_state.quote_items = st.session_state.quote_items.iloc[0:0]
        st.session_state.project_summary = ""
        st.rerun()

    st.markdown("---")

    st.markdown('<div class="drag-drop-box">', unsafe_allow_html=True)
    up_col1, up_col2 = st.columns(2)
    with up_col1:
        uploaded_files = st.file_uploader(
            "Drag & drop PDF or TXT files here, or click to browse",
            type=['pdf', 'txt'],
            accept_multiple_files=True,
            key="uploader"
        )
    with up_col2:
        pasted_text = st.text_area(
            "Or paste supplier quote text here (one document at a time):",
            height=180,
            key="pasted_text"
        )
    st.markdown('</div>', unsafe_allow_html=True)
    process_button = st.button("Process Uploaded/Pasted Files", use_container_width=True, disabled=not (uploaded_files or pasted_text.strip()))

    c_logo, c_head = st.columns([1, 2])
    with c_logo:
        if st.session_state.company_logo_b64:
            st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=170)
    with c_head:
        header_image = st.file_uploader("Upload Custom Header (Optional)", type=['png', 'jpg', 'jpeg'], key="header_img")
        if header_image:
            st.session_state.header_image_b64 = image_to_base64(header_image)
            st.image(header_image, caption="Custom header preview", width=200)

    st.markdown("---")
    c_sum, c_ai = st.columns([2, 1])
    with c_sum:
        if st.button("✨ Generate Project Summary", use_container_width=True, disabled=st.session_state.quote_items.empty):
            with st.spinner("🤖 Gemini is summarizing the project scope..."):
                try:
                    items_for_prompt = "\n".join(
                        [f"- {row['QTY']}x {row['Description']} (from {row['Supplier']})"
                         for _, row in st.session_state.quote_items.iterrows()]
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

if process_button and (uploaded_files or pasted_text.strip()):
    with st.spinner(f"Processing {len(uploaded_files) if uploaded_files else 0} file(s) and pasted text with Gemini..."):
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

        # Process each file separately, with 2s delay
        if uploaded_files:
            for idx, file in enumerate(uploaded_files):
                st.info(f"Processing file {idx+1} of {len(uploaded_files)}: `{file.name}`")
                try:
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
                except Exception as e:
                    st.error(f"An unexpected error occurred processing `{file.name}`: {e}")
                    failed_files.append(file.name)
                st.info("Waiting 2 seconds before next file...")
                time.sleep(2)  # Wait 2 seconds after each file

        # Process pasted text separately, with delay
        if pasted_text.strip():
            st.info("Processing pasted text...")
            try:
                response = model.generate_content([extraction_prompt, pasted_text])
                response_text = response.text
                extracted_data = None
                try:
                    extracted_data = json.loads(response_text)
                except json.JSONDecodeError:
                    st.write(f"Initial JSON parse failed. Attempting to clean response...")
                    match = re.search(r'```json\s*(.*)\s*```', response_text, re.DOTALL)
                    if match:
                        json_str = match.group(1).strip()
                        try:
                            extracted_data = json.loads(json_str)
                            st.write(f"Successfully cleaned and parsed JSON for pasted text.")
                        except json.JSONDecodeError as final_e:
                            st.error(f"Failed to parse cleaned JSON for pasted text. Error: {final_e}")
                            failed_files.append("Pasted Text")
                    else:
                        st.error("Error processing pasted text: Could not find a valid JSON block in the API response.")
                        failed_files.append("Pasted Text")
                if extracted_data:
                    all_new_items.extend(extracted_data)
            except Exception as e:
                st.error(f"An unexpected error occurred processing pasted text: {e}")
                failed_files.append("Pasted Text")
            st.info("Waiting 2 seconds before continuing...")
            time.sleep(2)  # Wait 2 seconds after pasted text

        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = st.session_state.global_margin
            st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            st.success(f"Successfully extracted {len(all_new_items)} items!")
        if failed_files:
            st.warning(f"Could not process the following: {', '.join(failed_files)}")
        st.rerun()

# ... rest of the app (table, row ops, PDF, etc.) unchanged ...
