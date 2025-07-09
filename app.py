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
    /* CSS styles remain the same */
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


# --- Helper Functions ---

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
    """Applies the global margin from the number_input to all items."""
    global_margin_value = st.session_state.get("global_margin_input", 9.0)
    st.session_state.quote_items['MARGIN'] = global_margin_value
    st.toast(f"Applied {global_margin_value}% margin to all items.")


# --- Gemini API Configuration ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except (FileNotFoundError, KeyError):
    st.error("🚨 Gemini API Key not found. Please add it to your Streamlit secrets.", icon="🚨")
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
if "sub_total_for_pdf" not in st.session_state:
    st.session_state.sub_total_for_pdf = 0
if "gst_total_for_pdf" not in st.session_state:
    st.session_state.gst_total_for_pdf = 0
if "grand_total_for_pdf" not in st.session_state:
    st.session_state.grand_total_for_pdf = 0
if "user_details" not in st.session_state:
    st.session_state.user_details = {"name": "", "job_title": "Sales", "branch": "AWM Nunawading", "email": "", "phone": "03 8846 2500"}
if "quote_details" not in st.session_state:
    st.session_state.quote_details = {"customerName": "", "attention": "", "projectName": "", "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}", "date": pd.Timestamp.now().strftime('%d/%m/%Y')}
if "customer_logo_b64" not in st.session_state:
    st.session_state.customer_logo_b64 = None
if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(globals().get("logo_file_path"))
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"

# --- Main Application UI ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64:
        st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")
st.divider()

# --- STEP 1: Upload Supplier Quotes ---
with st.container(border=False):
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("Step 1: Upload Supplier Quotes")
    st.markdown("Upload one or more supplier quote documents (PDF or TXT).")
    uploaded_files = st.file_uploader("Upload files", type=['pdf', 'txt'], accept_multiple_files=True, label_visibility="collapsed")
    process_button = st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files)
    st.markdown('</div>', unsafe_allow_html=True)

if process_button and uploaded_files:
    # ... (File processing logic remains the same)
    with st.spinner(f"Processing {len(uploaded_files)} file(s)..."):
        all_new_items, failed_files = [], []
        extraction_prompt = "..." # Prompt is unchanged
        json_schema = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"TYPE": {"type": "STRING"}, "QTY": {"type": "NUMBER"}, "Supplier": {"type": "STRING"}, "CAT_NO": {"type": "STRING"}, "Description": {"type": "STRING"}, "COST_PER_UNIT": {"type": "NUMBER"}}, "required": ["TYPE", "QTY", "Supplier", "CAT_NO", "Description", "COST_PER_UNIT"]}}
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json", "response_schema": json_schema})
        for i, file in enumerate(uploaded_files):
            try:
                st.write(f"Processing `{file.name}`...")
                part = file_to_generative_part(file)
                response = model.generate_content([extraction_prompt, part])
                extracted_data = json.loads(response.text)
                if extracted_data:
                    all_new_items.extend(extracted_data)
                if i < len(uploaded_files) - 1: time.sleep(2)
            except Exception as e:
                st.error(f"An error occurred processing `{file.name}`: {e}")
                failed_files.append(file.name)
        if all_new_items:
            new_df = pd.DataFrame(all_new_items)
            new_df['DISC'] = 0.0
            new_df['MARGIN'] = st.session_state.get("global_margin_input", 9.0)
            st.session_state.quote_items = pd.concat([st.session_state.quote_items, new_df], ignore_index=True)
            apply_sorting()
            st.success(f"Successfully extracted {len(all_new_items)} items!")
        if failed_files:
            st.warning(f"Could not process the following files: {', '.join(failed_files)}")
        st.rerun()

if not WEASYPRINT_AVAILABLE:
     st.error("PDF generation library not found.", icon="🚨")
     st.stop()

if not st.session_state.quote_items.empty:
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        st.header("Step 2: Edit & Refine Quote")
        st.caption("Edit values directly in the table. Calculations update automatically.")
        
        edited_df = st.data_editor(
            _calculate_sell_prices(st.session_state.quote_items),
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
        
        st.session_state.quote_items = edited_df.drop(columns=['SELL_UNIT_EX_GST', 'SELL_TOTAL_EX_GST']).reset_index(drop=True)
        
        st.divider()
        st.subheader("Table Controls")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Sorting**")
            st.radio("Sort items by:", ("Type", "Supplier"), horizontal=True, key="sort_by", label_visibility="collapsed", on_change=apply_sorting)
        with c2:
            st.write("**Global Margin**")
            st.number_input(
                "Global Margin (%)", value=9.0, min_value=0.0, max_value=99.9, step=1.0, format="%.2f",
                label_visibility="collapsed", key="global_margin_input", on_change=apply_global_margin
            )
            
        st.divider()
        st.subheader("Row Operations")
        # ... (Row operations logic remains the same)
        current_df_for_ops = st.session_state.quote_items
        row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in current_df_for_ops.iterrows()]
        selected_row_str = st.selectbox("Select a row to modify:", options=row_options, index=None, placeholder="Choose a row...")
        if selected_row_str:
            selected_index = row_options.index(selected_row_str)
            c1, c2, c3 = st.columns(3)
            if c1.button("Add Row Above", use_container_width=True):
                new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.get("global_margin_input", 9.0)}])
                updated_df = pd.concat([current_df_for_ops.iloc[:selected_index], new_row, current_df_for_ops.iloc[selected_index:]], ignore_index=True)
                st.session_state.quote_items = updated_df
                st.rerun()
            if c2.button("Add Row Below", use_container_width=True):
                new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.get("global_margin_input", 9.0)}])
                updated_df = pd.concat([current_df_for_ops.iloc[:selected_index+1], new_row, current_df_for_ops.iloc[selected_index+1:]], ignore_index=True)
                st.session_state.quote_items = updated_df
                st.rerun()
            if c3.button("Delete Selected Row", use_container_width=True):
                updated_df = current_df_for_ops.drop(current_df_for_ops.index[selected_index]).reset_index(drop=True)
                st.session_state.quote_items = updated_df
                st.rerun()
        
        st.divider()
        st.subheader("✍️ AI Description Summarizer")
        # ... (AI Summarizer logic remains the same)
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
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- STEP 3 & 4: Details and Final PDF Generation ---
    with st.container(border=False):
        st.markdown('<div class="step-container">', unsafe_allow_html=True)
        with st.form("quote_details_form"):
            # ... (Form logic remains the same)
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
            df_for_totals['GST_AMOUNT'] = df_for_totals['SELL_TOTAL_EX_GST'] * 0.10
            df_for_totals['SELL_TOTAL_INC_GST'] = df_for_totals['SELL_TOTAL_EX_GST'] + df_for_totals['GST_AMOUNT']
            st.session_state.sub_total_for_pdf = df_for_totals['SELL_TOTAL_EX_GST'].sum()
            st.session_state.gst_total_for_pdf = df_for_totals['GST_AMOUNT'].sum()
            st.session_state.grand_total_for_pdf = df_for_totals['SELL_TOTAL_INC_GST'].sum()
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Cost (Pre-Margin)", format_currency(total_cost_pre_margin))
            col2.metric("Sub-Total (ex. GST)", format_currency(st.session_state.sub_total_for_pdf))
            col3.metric("GST (10%)", format_currency(st.session_state.gst_total_for_pdf))
            col4.metric("Grand Total (inc. GST)", format_currency(st.session_state.grand_total_for_pdf))
            submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)

        if submitted:
            # --- PDF Generation Logic ---
            final_df = _calculate_sell_prices(st.session_state.quote_items)
            items_html = ""
            for i, row in final_df.iterrows():
                items_html += f"""...""" # Unchanged
            company_logo_html = f'<img src="data:image/png;base64,{st.session_state.company_logo_b64}" ...>' if st.session_state.company_logo_b64 else ''
            customer_logo_html = f'<img src="data:image/png;base64,{st.session_state.customer_logo_b64}" ...>' if st.session_state.customer_logo_b64 else ''
            # ... The rest of the HTML and PDF generation code is unchanged ...
            quote_html = f"""..."""
            pdf_css = """..."""
            combined_css = [CSS(string='@import url("https://cdnjs.cloudflare.com/ajax/libs/tailwindcss/2.2.19/tailwind.min.css");'), CSS(string=pdf_css)]
            pdf_bytes = HTML(string=quote_html).write_pdf(stylesheets=combined_css)
            st.download_button(
                label="✅ Download Final Quote as PDF",
                data=pdf_bytes,
                file_name=f"Quote_{q_details['quoteNumber']}_{q_details['customerName']}.pdf",
                mime='application/pdf',
                use_container_width=True
            )
        st.markdown('</div>', unsafe_allow_html=True)
