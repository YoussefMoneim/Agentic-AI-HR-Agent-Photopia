import uuid
from datetime import date
from pathlib import Path

from fpdf import FPDF

import config
from data.base import DataSource
from tools.base import Tool, ToolContext, ToolResult, ToolSpec


# ── Shared PDF helpers ────────────────────────────────────────────────────────
# Used by all three builders below to keep the visual style consistent.

def _section_header(pdf: FPDF, W: float, text: str, navy: bool = False) -> None:
    pdf.set_fill_color(45, 53, 97) if navy else pdf.set_fill_color(26, 26, 46)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(W, 7, f"  {text}", fill=True, ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _table_row(pdf: FPDF, W: float, label: str, value: str, shaded: bool) -> None:
    hw = W / 2
    if shaded:
        pdf.set_fill_color(248, 248, 251)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(85, 85, 85)
    pdf.cell(hw, 7, f"  {label}", fill=True, border="B", ln=False)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(hw, 7, f"  {value}", fill=True, border="B", ln=True)


def _total_row(pdf: FPDF, W: float, label: str, value: str) -> None:
    hw = W / 2
    pdf.set_fill_color(220, 224, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(hw, 9, f"  {label}", fill=True, ln=False)
    pdf.cell(hw, 9, f"  {value}", fill=True, ln=True)


# ── PDF builders ──────────────────────────────────────────────────────────────

def _build_pdf(employee: dict, tenant: dict, doc_id: str,
               issue_date: str, employment_start: str, total_salary: float) -> bytes:

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()
    W = pdf.epw
    ref = doc_id[:8].upper()
    currency = employee.get("currency", "EGP")

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W * 0.65, 9, tenant["company_name"], ln=False)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.35, 9, f"REF: SC-{ref}", align="R", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.65, 5, tenant["address"], ln=False)
    pdf.cell(W * 0.35, 5, f"DATE: {issue_date}", align="R", ln=True)

    pdf.cell(W * 0.65, 5, f"{tenant['phone']}  |  {tenant['website']}", ln=False)
    pdf.cell(W * 0.35, 5, "TYPE: Salary Certificate", align="R", ln=True)

    pdf.ln(3)
    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.8)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(8)

    # ── Title ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W, 8, "SALARY CERTIFICATE", align="C", ln=True)
    pdf.ln(7)

    # ── Body text ────────────────────────────────────────────────────────────
    name = employee.get("full_name", "")
    position = employee.get("position", "N/A")
    department = employee.get("department", "N/A")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(
        W, 6,
        f"To Whom It May Concern,\n\n"
        f"This is to certify that {name} is currently employed at "
        f"{tenant['company_name']} in the position of {position} "
        f"within the {department} department, effective from {employment_start}.",
    )
    pdf.ln(7)

    # ── Employment table ─────────────────────────────────────────────────────
    _section_header(pdf, W, "Employment Details")
    _table_row(pdf, W, "Employee Code", employee.get("employee_code", ""), False)
    _table_row(pdf, W, "Full Name", name, True)
    _table_row(pdf, W, "Position", position, False)
    _table_row(pdf, W, "Department", department, True)
    _table_row(pdf, W, "Employment Type", employee.get("employment_type", ""), False)
    _table_row(pdf, W, "Start Date", employment_start, True)
    pdf.ln(5)

    # ── Salary table ─────────────────────────────────────────────────────────
    _section_header(pdf, W, f"Remuneration Details ({currency})", navy=True)
    _table_row(pdf, W, "Basic Salary", f"{float(employee.get('basic_salary') or 0):,.2f} {currency}", False)
    _table_row(pdf, W, "Housing Allowance", f"{float(employee.get('housing_allowance') or 0):,.2f} {currency}", True)
    _table_row(pdf, W, "Transport Allowance", f"{float(employee.get('transport_allowance') or 0):,.2f} {currency}", False)
    _total_row(pdf, W, "Total Monthly Salary", f"{total_salary:,.2f} {currency}")
    pdf.ln(8)

    # ── Closing ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(
        W, 6,
        f"This certificate is issued upon the employee's request for official purposes only "
        f"and carries no further commitment or guarantee on the part of {tenant['company_name']}.",
    )

    # ── Signature ────────────────────────────────────────────────────────────
    pdf.ln(12)
    sig_start = 20 + W * 0.55
    sig_w = 190 - sig_start

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.55, 5, f"Issued: {issue_date}", ln=False)
    pdf.cell(W * 0.45, 5, "", ln=True)

    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.5)
    sig_y = pdf.get_y() + 8
    pdf.line(sig_start, sig_y, 190, sig_y)
    pdf.ln(11)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(sig_w, 5, tenant["signatory_name"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(sig_w, 5, tenant["signatory_title"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.cell(sig_w, 5, tenant["company_name"], align="C", ln=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_y(-18)  # negative = measure from bottom of page
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(W / 2, 4, tenant["company_name"], ln=False)
    pdf.cell(W / 2, 4, f"Generated by Fotopia HR Agent  ·  {issue_date}", align="R", ln=True)

    return bytes(pdf.output())


def _build_twimc_pdf(employee: dict, tenant: dict, doc_id: str,
                     issue_date: str, employment_start: str,
                     addressed_to: str, purpose: str) -> bytes:
    # Same structure as _build_pdf but NO salary section — intentional.
    # TWIMC letters confirm employment only; salary is disclosed separately via salary certificate.

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()
    W = pdf.epw
    ref = doc_id[:8].upper()

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W * 0.65, 9, tenant["company_name"], ln=False)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.35, 9, f"REF: TW-{ref}", align="R", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.65, 5, tenant["address"], ln=False)
    pdf.cell(W * 0.35, 5, f"DATE: {issue_date}", align="R", ln=True)

    pdf.cell(W * 0.65, 5, f"{tenant['phone']}  |  {tenant['website']}", ln=False)
    pdf.cell(W * 0.35, 5, "TYPE: Employment Letter", align="R", ln=True)

    pdf.ln(3)
    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.8)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(8)

    # ── Title ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W, 8, "TO WHOM IT MAY CONCERN", align="C", ln=True)
    pdf.ln(7)

    # ── Addressed to ─────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.cell(W, 6, addressed_to + ",", ln=True)
    pdf.ln(4)

    # ── Body ─────────────────────────────────────────────────────────────────
    name = employee.get("full_name", "")
    position = employee.get("position", "N/A")
    department = employee.get("department", "N/A")

    pdf.multi_cell(
        W, 6,
        f"This is to certify that {name} is currently employed at "
        f"{tenant['company_name']} in the position of {position} "
        f"within the {department} department, effective from {employment_start}.\n\n"
        f"This letter is issued upon the employee's request for {purpose}.",
    )
    pdf.ln(7)

    # ── Employment table ─────────────────────────────────────────────────────
    _section_header(pdf, W, "Employment Details")
    _table_row(pdf, W, "Employee Code", employee.get("employee_code", ""), False)
    _table_row(pdf, W, "Full Name", name, True)
    _table_row(pdf, W, "Position", position, False)
    _table_row(pdf, W, "Department", department, True)
    _table_row(pdf, W, "Employment Type", employee.get("employment_type", ""), False)
    _table_row(pdf, W, "Start Date", employment_start, True)
    pdf.ln(8)

    # ── Closing ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(
        W, 6,
        f"This letter is issued at the employee's request and is valid as of the date above. "
        f"It carries no further commitment or guarantee on the part of {tenant['company_name']}.",
    )

    # ── Signature ────────────────────────────────────────────────────────────
    pdf.ln(12)
    sig_start = 20 + W * 0.55
    sig_w = 190 - sig_start

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.55, 5, f"Issued: {issue_date}", ln=False)
    pdf.cell(W * 0.45, 5, "", ln=True)

    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.5)
    sig_y = pdf.get_y() + 8
    pdf.line(sig_start, sig_y, 190, sig_y)
    pdf.ln(11)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(sig_w, 5, tenant["signatory_name"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(sig_w, 5, tenant["signatory_title"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.cell(sig_w, 5, tenant["company_name"], align="C", ln=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_y(-18)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(W / 2, 4, tenant["company_name"], ln=False)
    pdf.cell(W / 2, 4, f"Generated by Fotopia HR Agent  ·  {issue_date}", align="R", ln=True)

    return bytes(pdf.output())


def _build_experience_pdf(employee: dict, tenant: dict, doc_id: str,
                           issue_date: str, employment_start: str,
                           last_working_day: str) -> bytes:
    # Past tense throughout ("was employed") + last working day row — key differences from the other two builders.

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()
    W = pdf.epw
    ref = doc_id[:8].upper()

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W * 0.65, 9, tenant["company_name"], ln=False)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.35, 9, f"REF: EC-{ref}", align="R", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.65, 5, tenant["address"], ln=False)
    pdf.cell(W * 0.35, 5, f"DATE: {issue_date}", align="R", ln=True)

    pdf.cell(W * 0.65, 5, f"{tenant['phone']}  |  {tenant['website']}", ln=False)
    pdf.cell(W * 0.35, 5, "TYPE: Experience Certificate", align="R", ln=True)

    pdf.ln(3)
    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.8)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(8)

    # ── Title ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(W, 8, "EXPERIENCE CERTIFICATE", align="C", ln=True)
    pdf.ln(7)

    # ── Body ─────────────────────────────────────────────────────────────────
    name = employee.get("full_name", "")
    position = employee.get("position", "N/A")
    department = employee.get("department", "N/A")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(
        W, 6,
        f"To Whom It May Concern,\n\n"
        f"This is to certify that {name} was employed at "
        f"{tenant['company_name']} in the position of {position} "
        f"within the {department} department from {employment_start} "
        f"to {last_working_day}.\n\n"
        f"During their tenure, {name} demonstrated professionalism and "
        f"dedication in their role as {position}.",
    )
    pdf.ln(7)

    # ── Employment table ─────────────────────────────────────────────────────
    _section_header(pdf, W, "Employment Details")
    _table_row(pdf, W, "Employee Code", employee.get("employee_code", ""), False)
    _table_row(pdf, W, "Full Name", name, True)
    _table_row(pdf, W, "Position", position, False)
    _table_row(pdf, W, "Department", department, True)
    _table_row(pdf, W, "Employment Type", employee.get("employment_type", ""), False)
    _table_row(pdf, W, "Date Joined", employment_start, True)
    _table_row(pdf, W, "Last Working Day", last_working_day, False)
    pdf.ln(8)

    # ── Closing ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(
        W, 6,
        f"We wish {name} all the best in their future endeavours. "
        f"This certificate is issued upon request and carries no further commitment "
        f"on the part of {tenant['company_name']}.",
    )

    # ── Signature ────────────────────────────────────────────────────────────
    pdf.ln(12)
    sig_start = 20 + W * 0.55
    sig_w = 190 - sig_start

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(W * 0.55, 5, f"Issued: {issue_date}", ln=False)
    pdf.cell(W * 0.45, 5, "", ln=True)

    pdf.set_draw_color(26, 26, 46)
    pdf.set_line_width(0.5)
    sig_y = pdf.get_y() + 8
    pdf.line(sig_start, sig_y, 190, sig_y)
    pdf.ln(11)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 26, 46)
    pdf.cell(sig_w, 5, tenant["signatory_name"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(sig_w, 5, tenant["signatory_title"], align="C", ln=True)

    pdf.set_x(sig_start)
    pdf.cell(sig_w, 5, tenant["company_name"], align="C", ln=True)

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_y(-18)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(W / 2, 4, tenant["company_name"], ln=False)
    pdf.cell(W / 2, 4, f"Generated by Fotopia HR Agent  ·  {issue_date}", align="R", ln=True)

    return bytes(pdf.output())


# ── Tools ─────────────────────────────────────────────────────────────────────

class GenerateSalaryCertificateTool(Tool):
    spec = ToolSpec(
        name="generate_salary_certificate",
        description=(
            "Generate an official salary certificate PDF for an employee. "
            "Requires an employee_code obtained via search_employees first. "
            "Returns a document_id that can be used to download the PDF. "
            "Only HR managers and admins may generate certificates."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The employee_code (e.g. EMP001) from search_employees.",
                }
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        # Compute in Python — never let the LLM do financial arithmetic
        total_salary = (
            float(employee.get("basic_salary") or 0)
            + float(employee.get("housing_allowance") or 0)
            + float(employee.get("transport_allowance") or 0)
        )

        doc_id = str(uuid.uuid4())
        issue_date = date.today().strftime("%d %B %Y")

        start_raw = employee.get("start_date", "")
        try:
            employment_start = date.fromisoformat(start_raw).strftime("%d %B %Y") if start_raw else "N/A"
        except ValueError:
            employment_start = start_raw or "N/A"

        pdf_bytes = _build_pdf(
            employee=employee,
            tenant=config.TENANT_CONFIG,
            doc_id=doc_id,
            issue_date=issue_date,
            employment_start=employment_start,
            total_salary=total_salary,
        )

        output_path = Path(config.DOCUMENTS_DIR) / f"{doc_id}.pdf"
        output_path.write_bytes(pdf_bytes)  # file is served later via GET /documents/{doc_id}

        return ToolResult(
            success=True,
            document_id=doc_id,
            document_type="salary_certificate",
            data={
                "document_id": doc_id,
                "employee_name": employee["full_name"],
                "employee_code": code,
                "total_salary": total_salary,
                "currency": config.TENANT_CONFIG["currency"],
                "issue_date": issue_date,
                "message": f"Salary certificate generated for {employee['full_name']}",
            },
            action_type="data_write",
        )


class GenerateTwimcLetterTool(Tool):
    spec = ToolSpec(
        name="generate_twimc_letter",
        description=(
            "Generate a 'To Whom It May Concern' employment letter for an employee. "
            "Confirms employment, position, department, and start date — does NOT include salary. "
            "Used for bank, embassy, or government requests. "
            "Requires an employee_code obtained via search_employees first. "
            "Returns a document_id that can be used to download the PDF."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The employee_code (e.g. EMP001) from search_employees.",
                },
                "addressed_to": {
                    "type": "string",
                    "description": "Who the letter is addressed to, e.g. 'The Egyptian Embassy'. Defaults to 'To Whom It May Concern'.",
                },
                "purpose": {
                    "type": "string",
                    "description": "The purpose of the letter, e.g. 'visa application', 'bank account opening'. Defaults to 'official purposes'.",
                },
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        addressed_to = input.get("addressed_to", "").strip() or "To Whom It May Concern"
        purpose = input.get("purpose", "").strip() or "official purposes"

        doc_id = str(uuid.uuid4())
        issue_date = date.today().strftime("%d %B %Y")

        start_raw = employee.get("start_date", "")
        try:
            employment_start = date.fromisoformat(start_raw).strftime("%d %B %Y") if start_raw else "N/A"
        except ValueError:
            employment_start = start_raw or "N/A"

        pdf_bytes = _build_twimc_pdf(
            employee=employee,
            tenant=config.TENANT_CONFIG,
            doc_id=doc_id,
            issue_date=issue_date,
            employment_start=employment_start,
            addressed_to=addressed_to,
            purpose=purpose,
        )

        output_path = Path(config.DOCUMENTS_DIR) / f"{doc_id}.pdf"
        output_path.write_bytes(pdf_bytes)

        return ToolResult(
            success=True,
            document_id=doc_id,
            document_type="twimc_letter",
            data={
                "document_id": doc_id,
                "employee_name": employee["full_name"],
                "employee_code": code,
                "addressed_to": addressed_to,
                "purpose": purpose,
                "issue_date": issue_date,
                "message": f"Employment letter generated for {employee['full_name']}",
            },
            action_type="data_write",
        )


class GenerateExperienceCertificateTool(Tool):
    spec = ToolSpec(
        name="generate_experience_certificate",
        description=(
            "Generate an experience certificate PDF for an employee confirming their employment history. "
            "Includes position, department, start date, and last working day. "
            "Used for job applications and visa applications when an employee is leaving or has left. "
            "Requires an employee_code obtained via search_employees first. "
            "Returns a document_id that can be used to download the PDF."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "employee_code": {
                    "type": "string",
                    "description": "The employee_code (e.g. EMP001) from search_employees.",
                },
                "last_working_day": {
                    "type": "string",
                    "description": "The employee's last working day as ISO date (YYYY-MM-DD). Defaults to today if not provided.",
                },
            },
            "required": ["employee_code"],
        },
        allowed_roles=["hr_staff", "hr_manager", "admin"],
    )

    def __init__(self, data_source: DataSource) -> None:
        self._ds = data_source

    def execute(self, input: dict, ctx: ToolContext) -> ToolResult:
        code = input.get("employee_code", "").strip()
        if not code:
            return ToolResult(success=False, error="employee_code is required")

        employee = self._ds.get_employee_by_code(ctx.tenant_id, code)
        if employee is None:
            return ToolResult(success=False, error=f"Employee '{code}' not found")

        doc_id = str(uuid.uuid4())
        today = date.today()
        issue_date = today.strftime("%d %B %Y")

        start_raw = employee.get("start_date", "")
        try:
            employment_start = date.fromisoformat(start_raw).strftime("%d %B %Y") if start_raw else "N/A"
        except ValueError:
            employment_start = start_raw or "N/A"

        lwd_raw = input.get("last_working_day", "").strip()
        try:
            last_working_day = date.fromisoformat(lwd_raw).strftime("%d %B %Y") if lwd_raw else today.strftime("%d %B %Y")
        except ValueError:
            return ToolResult(success=False, error=f"Invalid last_working_day '{lwd_raw}'. Use YYYY-MM-DD format.")

        pdf_bytes = _build_experience_pdf(
            employee=employee,
            tenant=config.TENANT_CONFIG,
            doc_id=doc_id,
            issue_date=issue_date,
            employment_start=employment_start,
            last_working_day=last_working_day,
        )

        output_path = Path(config.DOCUMENTS_DIR) / f"{doc_id}.pdf"
        output_path.write_bytes(pdf_bytes)

        return ToolResult(
            success=True,
            document_id=doc_id,
            document_type="experience_certificate",
            data={
                "document_id": doc_id,
                "employee_name": employee["full_name"],
                "employee_code": code,
                "employment_start": employment_start,
                "last_working_day": last_working_day,
                "issue_date": issue_date,
                "message": f"Experience certificate generated for {employee['full_name']}",
            },
            action_type="data_write",
        )
