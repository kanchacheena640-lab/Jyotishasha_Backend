import os
from dotenv import load_dotenv
from openai import OpenAI
from email_utils import send_email as send_email_with_attachment
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report

#from pdf_generator import generate_pdf_report

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_openai_response(prompt):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a senior Vedic astrologer writing detailed reports."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

def generate_pdf_and_email(name, email, product, report_text, kundali, language="en"):
    # Create reports folder if needed
    reports_dir = "/home/Jyotishasha/reports"
    os.makedirs(reports_dir, exist_ok=True)

    # Create filename
    safe_name = name.replace(" ", "_")
    safe_product = product.replace(" ", "_")
    pdf_path = f"{reports_dir}/{safe_name}_{safe_product}.pdf"

    # Extract fields
    dob = kundali.get("dob", "NA")
    tob = kundali.get("tob", "NA")
    pob = kundali.get("pob", "NA")
    moon_sign = kundali.get("moon_traits", {}).get("title", "NA")
    lagna_sign = kundali.get("lagna_sign", "NA")
    dasha_summary = kundali.get("grah_dasha_block", {}).get("grah_dasha_text", "")
    transit_summary = kundali.get("transit_summary", "")  # must be injected into kundali before calling this

    # Call ReportLab PDF builder
    generate_pdf_report(
        output_path=pdf_path,
        client_name=name,
        dob=dob,
        tob=tob,
        pob=pob,
        moon_sign=moon_sign,
        lagna_sign=lagna_sign,
        dasha_summary=dasha_summary,
        transit_summary=transit_summary,
        gpt_report=report_text,
        kundali_chart_path="/tmp/kundali_chart.png"  # or change path if needed
    )

    # Email PDF
    send_email_with_attachment(
        email,
        f"Your {product} Report",
        "Please find attached your personalized astrology report.",
        pdf_path
    )

    return pdf_path
