import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- 1. PDF Extraction Logic (Same as before) ---
def extract_info_vahan(file):
    text_content = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text_content += page.extract_text(layout=True) + "\n"

    # A. Chassis Number
    chassis_match = re.search(r"(?i)\b([A-HJ-NPR-Z0-9]{17})\b", text_content)
    chassis = chassis_match.group(1).upper() if chassis_match else "UNKNOWN"

    # B. Registration/Receipt Date
    date_match = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4})", text_content)
    reg_date = date_match.group(1) if date_match else "N/A"

    # C. Vehicle Number
    if re.search(r"\bNEW\b", text_content):
        vehicle_no = "NEW"
    else:
        veh_match = re.search(r"\b([A-Z]{2}\d{2}[A-Z]{0,3}\d{4})\b", text_content)
        vehicle_no = veh_match.group(1) if veh_match else "NEW"

    # D. Customer Name
    name = "Unknown"
    lines = text_content.split('\n')
    for i, line in enumerate(lines):
        if "Received From" in line:
            clean_line = line.replace("Received From", "").replace(":", "").strip()
            if len(clean_line) > 2: 
                name = clean_line
                break
            elif i + 1 < len(lines):
                next_line = lines[i+1].strip()
                if next_line and "Receipt" not in next_line and "Vehicle" not in next_line:
                    name = next_line
                    break
    
    name = re.sub(r"[^a-zA-Z\s\.]", "", name).strip()

    return {
        "extracted_chassis": chassis,
        "extracted_name": name,
        "extracted_reg_no": vehicle_no,
        "extracted_date": reg_date,
        "filename": file.name 
    }

# --- 2. Logic & Validation ---
def generate_remarks(extracted, master_row):
    ex_chassis = str(extracted['extracted_chassis']).strip().upper()
    ms_chassis = str(master_row['chassis number']).strip().upper()
    ex_name = str(extracted['extracted_name']).upper().replace(".", "").strip()
    ms_name = str(master_row['customer name']).upper().replace(".", "").strip()
    ex_reg = str(extracted['extracted_reg_no']).upper().strip()

    is_perm = re.match(r'^[A-Z]{2}\d{2}[A-Z]{0,3}\d{4}$', ex_reg.replace(" ", "")) or \
              re.match(r'^\d{2}BH\d{4}[A-Z]{2}$', ex_reg.replace(" ", ""))
    
    reg_type = "Temporary" if (ex_reg == "NEW" or not is_perm) else "Permanent"

    status = "Hold"
    remark = ""

    if ex_chassis == ms_chassis:
        if ex_name == ms_name:
            if reg_type == "Permanent":
                status = "Approve"
                remark = "Approved"
            else:
                status = "Hold"
                remark = "Uploaded document is temporary registration. Kindly upload VAHAN screenshot/Permanent Registration copy/Tax paid receipt."
        elif reg_type == "Permanent" and ex_name != ms_name:
            status = "Hold"
            remark = "Customer name on DCP doesn't match with customer name on receipt. Please provide relationship proof between them."
        else:
            status = "Hold"
            remark = f"Review Required. Name Mismatch ({ex_name}) & Temp Reg."
    else:
        status = "Reject"
        remark = f"Chassis Mismatch. PDF: {ex_chassis}"

    return status, remark, reg_type

# --- 3. Streamlit Interface ---
st.title("Vehicle Registration Checker")
st.caption("Output strictly follows the order of the uploaded Excel file.")

# Uploaders
excel_file = st.file_uploader("1. Upload Excel File", type=['xlsx', 'xls'])
pdf_files = st.file_uploader("2. Upload PDFs (Unlimited)", type=['pdf'], accept_multiple_files=True)

if excel_file and pdf_files and st.button("Generate Ordered Report"):
    
    # 1. Read Excel
    df_master = pd.read_excel(excel_file)
    df_master.columns = [c.strip().lower() for c in df_master.columns]
    
    if 'chassis number' not in df_master.columns:
        st.error("Excel must have 'Chassis Number' column.")
    else:
        # 2. Pre-process PDFs into a Dictionary
        # Structure: { 'MEX...123': { extracted_data... } }
        scanned_data = {}
        progress_bar = st.progress(0)
        
        st.write("Scanning PDFs...")
        for i, file in enumerate(pdf_files):
            data = extract_info_vahan(file)
            # Store by Chassis Number (Key)
            scanned_data[data['extracted_chassis']] = data
            progress_bar.progress((i + 1) / len(pdf_files))
            
        # 3. Iterate Excel Rows (Preserving Order)
        results = []
        st.write("Matching with Excel rows...")
        
        for index, row in df_master.iterrows():
            master_chassis = str(row.get('chassis number', '')).strip().upper()
            
            # Lookup this chassis in our scanned PDF data
            pdf_info = scanned_data.get(master_chassis)
            
            output_row = {
                "Chassis number": row.get('chassis number'),
                "Customer name": row.get('customer name'),
                "Dealer code": row.get('dealer code'),
                "Dealer name": row.get('dealer name'),
                "Model": row.get('model'),
                "Variant description": row.get('variant description'),
                "Vehicle status": row.get('vehicle status'),
                "MY": row.get('my'),
                "VY": row.get('vy'),
            }

            if pdf_info:
                # PDF Found -> Run Logic
                status, remark, reg_type = generate_remarks(pdf_info, row)
                output_row.update({
                    "Registration date": pdf_info['extracted_date'],
                    "Permanent / Temporary": reg_type,
                    "Certificate Attached": "Yes",
                    "RTO status": status,
                    "Remarks": remark
                })
            else:
                # PDF Not Found -> Leave Empty or Mark Missing
                output_row.update({
                    "Registration date": "",
                    "Permanent / Temporary": "",
                    "Certificate Attached": "No",
                    "RTO status": "Pending",
                    "Remarks": "Document not uploaded"
                })
            
            results.append(output_row)

        # 4. Display Final Table
        final_df = pd.DataFrame(results)
        st.success("Processing Complete!")
        st.dataframe(final_df)

        st.info("Row order matches your Excel file exactly. Copy-paste safely.")
