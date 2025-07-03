import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import base64
import re
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

# Maintain row order and sort state in session
if "quote_items" not in st.session_state:
    st.session_state.quote_items = pd.DataFrame(columns=[
        "TYPE", "QTY", "Supplier", "CAT_NO", "Description",
        "COST_PER_UNIT", "DISC", "MARGIN"
    ])
if "row_order" not in st.session_state:
    st.session_state.row_order = []
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
    st.session_state.sort_by = "Order"  # New default: always keep manual order unless user sorts

def update_row_order():
    # Reset or set row order to match quote_items if not set
    if len(st.session_state.row_order) != len(st.session_state.quote_items):
        st.session_state.row_order = list(range(len(st.session_state.quote_items)))

def reorder_df(df, row_order):
    return df.iloc[row_order].reset_index(drop=True)

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
        st.session_state.row_order = []
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

        # Process each file separately
        if uploaded_files:
            for file in uploaded_files:
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
                except Exception as e:
                    st.error(f"An unexpected error occurred processing `{file.name}`: {e}")
                    failed_files.append(file.name)

        # Process pasted text separately
        if pasted_text.strip():
            try:
                st.write("Processing pasted text...")
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

        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = st.session_state.global_margin
            st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            # update row order to append new rows at end
            update_row_order()
            st.session_state.row_order.extend(list(range(len(st.session_state.row_order), len(st.session_state.quote_items))))
            st.success(f"Successfully extracted {len(all_new_items)} items!")
        if failed_files:
            st.warning(f"Could not process the following: {', '.join(failed_files)}")
        st.rerun()

if not WEASYPRINT_AVAILABLE:
    st.error("PDF generation library not found. Please ensure `weasyprint` is in your requirements.txt and the system packages are in `packages.txt`.", icon="🚨")
    st.stop()

if st.session_state.quote_items.empty:
    st.info("Upload your supplier quotes above to get started.")
else:
    st.markdown("---")
    if st.session_state.project_summary:
        st.subheader("✨ Project Scope Summary")
        st.markdown(st.session_state.project_summary)

    st.subheader("Quote Line Items")
    sort_option = st.radio(
        "Sort items by:",
        ("Manual Order", "Type", "Supplier"),
        horizontal=True,
        key="sort_by"
    )

    update_row_order()

    # Apply sorting for table display, but preserve row order if "Manual Order"
    if sort_option == "Manual Order":
        display_df = reorder_df(st.session_state.quote_items, st.session_state.row_order)
    elif sort_option == "Type":
        display_df = st.session_state.quote_items.sort_values(by='TYPE', kind="stable").reset_index(drop=True)
    elif sort_option == "Supplier":
        display_df = st.session_state.quote_items.sort_values(by='Supplier', kind="stable").reset_index(drop=True)
    else:
        display_df = reorder_df(st.session_state.quote_items, st.session_state.row_order)

    st.caption("You can edit values directly in the table below. Calculations will update automatically.")
    df_for_display = display_df.copy()
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        df_for_display[col] = pd.to_numeric(df_for_display[col], errors='coerce').fillna(0)
    cost_after_disc = df_for_display['COST_PER_UNIT'] * (1 - df_for_display['DISC'] / 100)
    margin_divisor = (1 - df_for_display['MARGIN'] / 100)
    margin_divisor[margin_divisor <= 0] = 0.01
    df_for_display['SELL_UNIT_EX_GST'] = cost_after_disc / margin_divisor
    df_for_display['SELL_TOTAL_EX_GST'] = df_for_display['SELL_UNIT_EX_GST'] * df_for_display['QTY']
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

    # Update the underlying data and row order if table changes
    if not display_df.equals(edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST'])):
        # To keep row order correct after sorting or editing, always update quote_items to match the edited display
        st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
        if sort_option == "Manual Order":
            # Keep the row_order as is
            pass
        else:
            # If sorted by Type or Supplier, update row_order to match this new order
            st.session_state.row_order = list(range(len(st.session_state.quote_items)))
        st.rerun()

    st.divider()
    st.subheader("Row Operations & Reordering")
    row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in reorder_df(st.session_state.quote_items, st.session_state.row_order).iterrows()]
    selected_row_str = st.selectbox("Select a row to modify or move:", options=row_options, index=None, placeholder="Choose a row...")

    if selected_row_str:
        selected_index = row_options.index(selected_row_str)
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
        if c1.button("Add Row Above", use_container_width=True, key="add_above"):
            new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.global_margin}])
            idx = st.session_state.row_order[selected_index]
            updated_df = pd.concat([st.session_state.quote_items.iloc[:idx], new_row, st.session_state.quote_items.iloc[idx:]], ignore_index=True)
            st.session_state.quote_items = updated_df
            st.session_state.row_order.insert(selected_index, len(updated_df)-1)
            st.rerun()
        if c2.button("Add Row Below", use_container_width=True, key="add_below"):
            new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.global_margin}])
            idx = st.session_state.row_order[selected_index]
            updated_df = pd.concat([st.session_state.quote_items.iloc[:idx+1], new_row, st.session_state.quote_items.iloc[idx+1:]], ignore_index=True)
            st.session_state.quote_items = updated_df
            st.session_state.row_order.insert(selected_index+1, len(updated_df)-1)
            st.rerun()
        if c3.button("Delete Selected Row", use_container_width=True, key="delete_row"):
            idx = st.session_state.row_order[selected_index]
            updated_df = st.session_state.quote_items.drop(idx).reset_index(drop=True)
            st.session_state.quote_items = updated_df
            st.session_state.row_order.pop(selected_index)
            # Re-map row_order to new df index (since drop resets index)
            st.session_state.row_order = [i if i < idx else i-1 for i in st.session_state.row_order]
            st.rerun()
        if c4.button("Move Up", use_container_width=True, key="move_up"):
            if selected_index > 0:
                st.session_state.row_order[selected_index-1], st.session_state.row_order[selected_index] = st.session_state.row_order[selected_index], st.session_state.row_order[selected_index-1]
                st.rerun()
        if c5.button("Move Down", use_container_width=True, key="move_down"):
            if selected_index < len(st.session_state.row_order)-1:
                st.session_state.row_order[selected_index+1], st.session_state.row_order[selected_index] = st.session_state.row_order[selected_index], st.session_state.row_order[selected_index+1]
                st.rerun()

    st.divider()
    st.subheader("✍️ AI Description Summarizer")
    st.caption("Select an item to generate a shorter, more client-friendly description.")
    summary_row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in reorder_df(st.session_state.quote_items, st.session_state.row_order).iterrows()]
    selected_item_str_for_summary = st.selectbox("Select Item to Summarize", options=summary_row_options, index=None, placeholder="Choose an item...", key="summary_selectbox")
    if st.button("Summarize Description", use_container_width=True, disabled=not selected_item_str_for_summary):
        selected_index = summary_row_options.index(selected_item_str_for_summary)
        idx = st.session_state.row_order[selected_index]
        original_description = st.session_state.quote_items.at[idx, 'Description']
        with st.spinner("🤖 Gemini is summarizing..."):
            try:
                prompt = f"Summarize the following product description in one clear, concise sentence for a customer quote. Be professional and easy to understand.\n\nOriginal Description: '{original_description}'"
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(prompt)
                st.session_state.quote_items.at[idx, 'Description'] = response.text.strip()
                st.toast("Description summarized!", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to summarize: {e}")

    # Totals for display, always based on actual manual row order
    df_for_totals = reorder_df(st.session_state.quote_items, st.session_state.row_order).copy()
    for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
        df_for_totals[col] = pd.to_numeric(df_for_totals[col], errors='coerce').fillna(0)
    cost_after_disc = df_for_totals['COST_PER_UNIT'] * (1 - df_for_totals['DISC'] / 100)
    margin_divisor = (1 - df_for_totals['MARGIN'] / 100)
    margin_divisor[margin_divisor <= 0] = 0.01
    df_for_totals['SELL_UNIT_EX_GST'] = cost_after_disc / margin_divisor
    df_for_totals['SELL_TOTAL_EX_GST'] = df_for_totals['SELL_UNIT_EX_GST'] * df_for_totals['QTY']
    total_cost_pre_margin = (cost_after_disc * df_for_totals['QTY']).sum()
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
        st.subheader("Review Details (edit above if needed)")
        submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)
    if submitted:
        # Always use manual order for PDF regardless of display sort
        final_df = reorder_df(st.session_state.quote_items, st.session_state.row_order).copy()
        for col in ['QTY', 'COST_PER_UNIT', 'DISC', 'MARGIN']:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)
        final_cost_after_disc = final_df['COST_PER_UNIT'] * (1 - final_df['DISC'] / 100)
        final_margin_divisor = (1 - final_df['MARGIN'] / 100)
        final_margin_divisor[final_margin_divisor <= 0] = 0.01
        final_df['SELL_UNIT_EX_GST'] = final_cost_after_disc / final_margin_divisor
        final_df['SELL_TOTAL_EX_GST'] = final_df['SELL_UNIT_EX_GST'] * final_df['QTY']
        gst_rate = 10
        final_df['GST_AMOUNT'] = final_df['SELL_TOTAL_EX_GST'] * (gst_rate / 100)
        final_df['SELL_TOTAL_INC_GST'] = final_df['SELL_TOTAL_EX_GST'] + final_df['GST_AMOUNT']

        pdf_subtotal = format_currency(final_df['SELL_TOTAL_EX_GST'].sum())
        pdf_gst = format_currency(final_df['GST_AMOUNT'].sum())
        pdf_grand_total = format_currency(final_df['SELL_TOTAL_INC_GST'].sum())

        items_html = ""
        for i, row in final_df.iterrows():
            # Only include fields that are for the client, never price, margin or discount
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
            </tr>
            """
        q_details = st.session_state.quote_details
        company_logo_html = (
            f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" alt="Company Logo" class="h-16 mb-4">'
            if st.session_state.company_logo_b64
            else '<h1 class="text-3xl font-bold text-gray-800">Company Name</h1>'
        )
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
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-200">{items_html}</tbody>
                    </table>
                </main>
                <footer class="mt-8 flex justify-end" style="page-break-inside: avoid;">
                    <div class="w-2/5">
                        <div class="flex justify-between p-2 bg-gray-100 rounded-t-lg"><span class="font-bold text-gray-800">Sub-Total (Ex GST):</span><span class="text-gray-800">{pdf_subtotal}</span></div>
                        <div class="flex justify-between p-2"><span class="font-bold text-gray-800">GST (10%):</span><span class="text-gray-800">{pdf_gst}</span></div>
                        <div class="flex justify-between p-4 bg-slate-800 text-white font-bold text-lg rounded-b-lg"><span>Grand Total (Inc GST):</span><span>{pdf_grand_total}</span></div>
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
            thead { display: table-header-group; }
            tfoot { display: table-footer-group; }
            table {
                width: 100%;
                border-collapse: collapse;
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
