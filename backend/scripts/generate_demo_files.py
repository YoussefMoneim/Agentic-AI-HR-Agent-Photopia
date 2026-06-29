"""One-time script - generates demo PDF files for document library testing."""

import os
from fpdf import FPDF
from fpdf.enums import XPos, YPos

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'demo_files')


def generate_sensitive_employee_record():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # Header
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, 'WIN Holding Group', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

    pdf.set_font('Helvetica', 'I', 10)
    pdf.set_text_color(150, 30, 30)
    pdf.cell(0, 6, 'CONFIDENTIAL - Employee Record', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

    pdf.set_text_color(30, 30, 30)
    pdf.ln(8)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(8)

    # Fields
    fields = [
        ('Employee',            'Ahmed Hassan'),
        ('Employee Code',       'EMP-2024-0847'),
        ('National ID',         '29901011234567'),
        ('Basic Salary',        'EGP 45,000 per month'),
        ('Housing Allowance',   'EGP 5,000'),
        ('Transport Allowance', 'EGP 800'),
        ('Total Compensation',  'EGP 50,800'),
        ('Department',          'Engineering'),
        ('Manager',             'Nourhan Hosny'),
        ('Start Date',          'March 1, 2024'),
    ]

    for label, value in fields:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(60, 8, f'{label}:', new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 8, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5,
        'This document contains confidential compensation and personal identification data. '
        'Unauthorized disclosure is a violation of company policy and Egyptian PDPL regulations.')

    out_path = os.path.join(OUTPUT_DIR, 'sensitive_employee_record.pdf')
    pdf.output(out_path)
    print(f'Generated: {os.path.abspath(out_path)}')


if __name__ == '__main__':
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generate_sensitive_employee_record()
