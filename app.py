# ... [keep the imports and all your helper functions as before] ...

# [ ... session state and all code above the main table unchanged ... ]

    # --- Main Table, Editing, and Actions ---
    # ... [code above unchanged] ...

    st.divider()
    st.subheader("Row Operations & Reordering")
    row_options = [f"Row {i+1}: {row['Description'][:50]}..." for i, row in st.session_state.quote_items.iterrows()]
    selected_row_str = st.selectbox("Select a row to modify or move:", options=row_options, index=None, placeholder="Choose a row...")

    if selected_row_str:
        selected_index = row_options.index(selected_row_str)
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
        if c1.button("Add Row Above", use_container_width=True, key="add_above"):
            new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.global_margin}])
            updated_df = pd.concat([st.session_state.quote_items.iloc[:selected_index], new_row, st.session_state.quote_items.iloc[selected_index:]], ignore_index=True)
            st.session_state.quote_items = updated_df
            st.rerun()
        if c2.button("Add Row Below", use_container_width=True, key="add_below"):
            new_row = pd.DataFrame([{"TYPE": "", "QTY": 1, "Supplier": "", "CAT_NO": "", "Description": "", "COST_PER_UNIT": 0.0, "DISC": 0.0, "MARGIN": st.session_state.global_margin}])
            updated_df = pd.concat([st.session_state.quote_items.iloc[:selected_index+1], new_row, st.session_state.quote_items.iloc[selected_index+1:]], ignore_index=True)
            st.session_state.quote_items = updated_df
            st.rerun()
        if c3.button("Delete Selected Row", use_container_width=True, key="delete_row"):
            updated_df = st.session_state.quote_items.drop(st.session_state.quote_items.index[selected_index]).reset_index(drop=True)
            st.session_state.quote_items = updated_df
            st.rerun()
        if c4.button("Move Up", use_container_width=True, key="move_up"):
            if selected_index > 0:
                df = st.session_state.quote_items.copy()
                df.iloc[selected_index-1], df.iloc[selected_index] = df.iloc[selected_index].copy(), df.iloc[selected_index-1].copy()
                st.session_state.quote_items = df.reset_index(drop=True)
                st.rerun()
        if c5.button("Move Down", use_container_width=True, key="move_down"):
            if selected_index < len(st.session_state.quote_items)-1:
                df = st.session_state.quote_items.copy()
                df.iloc[selected_index+1], df.iloc[selected_index] = df.iloc[selected_index].copy(), df.iloc[selected_index+1].copy()
                st.session_state.quote_items = df.reset_index(drop=True)
                st.rerun()

    # ... [rest of code unchanged until the PDF generation section] ...

    st.divider()
    st.header("Finalise and Generate Quote")
    with st.form("quote_details_form"):
        st.subheader("Review Details (edit above if needed)")
        submitted = st.form_submit_button("Generate Final Quote PDF", type="primary", use_container_width=True)
    if submitted:
        final_df = st.session_state.quote_items.copy()
        # Keep row order as-is (do not sort)
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
                                <th class="p-2 text-right">UNIT EX GST</th><th class="p-2 text-right rounded-tr-lg">TOTAL EX GST</th>
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
