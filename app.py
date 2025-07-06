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
# Load the logo for the page icon
try:
    logo_file_path = Path(__file__).parent / "AWM Logo (002).png"
    page_icon_img = Image.open(logo_file_path)
except FileNotFoundError:
    page_icon_img = "📄" # Fallback to an emoji if the logo is not found

st.set_page_config(
    page_title="AWM Quote Generator",
    page_icon=page_icon_img,
    layout="wide"
)

# --- Modern, Pastel/Neutral App Styling ---
st.markdown("""
<style>
    /* --- Main App Styling --- */
    .stApp {
        background-color: #f8f9fa; /* Light grey background */
        font-family: 'Inter', sans-serif;
    }

    /* --- Container for each step in the workflow --- */
    .step-container {
        border: 1px solid #dee2e6; /* Softer border color */
        border-radius: 0.8rem;
        padding: 1.5rem 2rem;
        background-color: white;
        box-shadow: 0 4px 12px -1px rgb(0 0 0 / 0.05);
        margin-bottom: 2rem; /* Space between steps */
    }

    /* --- Title and Header Styling --- */
    h1, h2, h3 {
        color: #343a40; /* Darker grey for titles */
    }

    /* --- Pastel Button Styling --- */
    .stButton > button {
        background-color: #a0c4ff; /* Pastel Blue */
        color: #002b6e !important; /* Darker blue text for contrast */
        border: 1px solid #a0c4ff !important;
        border-radius: 0.375rem;
        font-weight: 600;
    }
    .stButton > button:hover {
        background-color: #8ab4f8; /* Slightly darker pastel blue on hover */
        border-color: #8ab4f8;
        color: #002b6e !important;
    }
    .stButton > button:disabled {
        background-color: #ced4da !important;
        color: #6c757d !important;
        border-color: #ced4da !important;
        opacity: 0.7;
    }

    /* --- Special styling for the final "Generate" button --- */
    .stButton > button[kind="primary"] {
        background-color: #a7d7c5; /* Pastel Green */
        border-color: #a7d7c5;
        color: #003e29 !important; /* Darker green text for contrast */
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #8abbac; /* Slightly darker pastel green on hover */
        border-color: #8abbac;
        color: #003e29 !important;
    }

    /* --- Styling for the file uploader --- */
    [data-testid="stFileUploader"] {
        padding: 1rem;
        background-color: #f1f3f5;
        border-radius: 0.5rem;
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
        st.error(f"Logo file not found: AWM Logo (002).png", icon="🚨")
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
        "name": "", "job_title": "Sales", "branch": "AWM Nunawading",
        "email": "", "phone": "03 8846 2500"
    }

if "quote_details" not in st.session_state:
    st.session_state.quote_details = {
        "customerName": "", "attention": "", "projectName": "",
        "quoteNumber": f"Q{pd.Timestamp.now().strftime('%Y%m%d%H%M')}",
        "date": pd.Timestamp.now().strftime('%d/%m/%Y')
    }

if "customer_logo_b64" not in st.session_state:
    st.session_state.customer_logo_b64 = None

if "company_logo_b64" not in st.session_state:
    st.session_state.company_logo_b64 = get_logo_base64(logo_file_path)

if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Type"


# --- Main Application UI ---

# --- Header with logo and title side-by-side ---
col1, col2 = st.columns([1, 4])
with col1:
    if st.session_state.company_logo_b64:
        st.image(f"data:image/png;base64,{st.session_state.company_logo_b64}", width=150)
with col2:
    st.title("AWM Quote Generator")
    st.caption(f"App created by Harry Leonhardt | Quote prepared by: **{st.session_state.user_details['name'] or 'Your Name'}**")

st.divider()

# --- STEP 1: Upload Supplier Quotes ---
with st.container():
    st.markdown('<div class="step-container">', unsafe_allow_html=True)
    st.header("Step 1: Upload Supplier Quotes")
    st.markdown("Upload one or more supplier quote documents (PDF or TXT). The system will extract the line items.")

    uploaded_files = st.file_uploader(
        "Upload PDF or TXT files",
        type=['pdf', 'txt'],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    process_button = st.button("Process Uploaded Files", use_container_width=True, disabled=not uploaded_files)
    st.markdown('</div>', unsafe_allow_html=True)

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
