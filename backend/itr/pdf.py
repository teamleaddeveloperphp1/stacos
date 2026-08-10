"""PDF exports (§9 "Export computation sheet", §10.2 "Preview", §10.4
"Validation report export"). Built with reportlab -- the only PDF dependency
this project takes on; no other module imports it, so the engine stays
dependency-light.
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from itr.rules.registry import RULE_SET_VERSION
from itr.serialize.json_schema_validator import SCHEMA_VERSION
from itr.util.num import format_indian

_STYLES = getSampleStyleSheet()
_H1 = ParagraphStyle('H1', parent=_STYLES['Heading1'], fontSize=16, spaceAfter=6)
_H2 = ParagraphStyle('H2', parent=_STYLES['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=4)
_BODY = _STYLES['BodyText']
_SMALL = ParagraphStyle('Small', parent=_BODY, fontSize=8, textColor=colors.grey)
_GREEN = ParagraphStyle('Green', parent=_BODY, textColor=colors.HexColor('#146c2e'), fontSize=13)
_RED = ParagraphStyle('Red', parent=_BODY, textColor=colors.HexColor('#b3261e'))
_AMBER = ParagraphStyle('Amber', parent=_BODY, textColor=colors.HexColor('#9a6a00'))


def _doc(buffer, title):
    return SimpleDocTemplate(
        buffer, pagesize=A4, title=title,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )


def _money_table(rows, col_widths=(110 * mm, 40 * mm)):
    """`rows`: list of (label, amount-already-formatted-or-None) pairs."""
    data = [[Paragraph(label, _BODY), Paragraph(amount or '', _BODY)] for label, amount in rows]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d6dbe0')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f7f8fa')),
    ]))
    return t


def _rupee(v):
    return f'₹{format_indian(v)}'


def _header_block(tax_return, computed):
    pi = tax_return.data['personalInfo']
    name = ' '.join(x for x in (pi['firstName'], pi['middleName'], pi['lastName']) if x).strip() or '—'
    return [
        Paragraph(f'ITR-1 (Sahaj) — {name}', _H1),
        Paragraph(
            f"PAN {pi['pan'] or '—'} &middot; AY {tax_return.data['ay']} &middot; "
            f"Regime: {computed.get('regime', '—')} &middot; Generated {_now_str()}",
            _SMALL,
        ),
        Spacer(1, 6 * mm),
    ]


def _now_str():
    from django.utils import timezone
    return timezone.now().strftime('%Y-%m-%d %H:%M')


# ---------------------------------------------------------------------------
# §9 — computation sheet (Screen 6 "Export computation sheet (PDF)")
# ---------------------------------------------------------------------------

def render_computation_sheet_pdf(tax_return, computed):
    buffer = io.BytesIO()
    doc = _doc(buffer, 'ITR-1 Computation Sheet')
    story = _header_block(tax_return, computed)

    story.append(Paragraph('A. Gross Total Income', _H2))
    story.append(_money_table([
        ('Income from Salary', _rupee(computed['salary']['incomeFromSalary'])),
        ('Income from House Property', _rupee(computed['houseProperty']['incomeForGti'])),
        ('Income from Other Sources', _rupee(computed['otherSources']['netIncomeOthSrc'])),
        ('Long-Term Capital Gains u/s 112A', _rupee(computed['ltcg112A'])),
        ('Gross Total Income', _rupee(computed['grossTotalIncomeInclLtcg'])),
    ]))

    story.append(Paragraph('B. Total Deductions (Chapter VI-A)', _H2))
    deduction_rows = [
        (section, _rupee(info['eligible']))
        for section, info in computed['deductions']['bySection'].items()
    ]
    deduction_rows.append(('Total Deductions', _rupee(computed['totalDeductions'])))
    story.append(_money_table(deduction_rows))

    story.append(Paragraph('C. Total Taxable Income', _H2))
    story.append(_money_table([('Total Taxable Income (A − B)', _rupee(computed['totalIncome']))]))

    story.append(Paragraph('D. Total Tax, Fee and Interest', _H2))
    tax = computed['tax']
    interest = computed['interest']
    story.append(_money_table([
        ('D1. Tax payable on total income', _rupee(tax['taxPayableOnTotalIncome'])),
        ('D2. Rebate u/s 87A', _rupee(tax['rebate87A'])),
        ('D3. Tax payable after rebate', _rupee(tax['taxPayableAfterRebate'])),
        ('D4. Health & education cess', _rupee(tax['educationCess'])),
        ('D5. Total tax and cess', _rupee(tax['totalTaxAndCess'])),
        ('D6. Relief u/s 89', _rupee(tax['relief89'])),
        ('D7. Interest u/s 234A', _rupee(interest['interest234A'])),
        ('D8. Interest u/s 234B', _rupee(interest['interest234B'])),
        ('D9. Interest u/s 234C', _rupee(interest['interest234C'])),
        ('D10. Fee u/s 234F', _rupee(interest['fee234F'])),
        ('D10a. Fee u/s 234-I', _rupee(interest['fee234I'])),
        ('D11. Total Tax, Fee and Interest', _rupee(computed['totalTaxFeeAndInterest'])),
    ]))

    story.append(Paragraph('E. Total Taxes Paid', _H2))
    paid = computed['taxesPaid']
    story.append(_money_table([
        ('TDS on salary (TDS1)', _rupee(paid['tds1'])),
        ('TDS other than salary (TDS2)', _rupee(paid['tds2'])),
        ('TDS on sale of immovable property etc. (TDS3)', _rupee(paid['tds3'])),
        ('Tax Collected at Source (TCS)', _rupee(paid['tcs'])),
        ('Advance Tax', _rupee(paid['advanceTax'])),
        ('Self-Assessment Tax', _rupee(paid['selfAssessmentTax'])),
        ('Total Taxes Paid', _rupee(paid['total'])),
    ]))

    story.append(Paragraph('Amount Payable / Refund', _H2))
    if computed['refundDue'] > 0:
        story.append(Paragraph(f"Refund due: {_rupee(computed['refundDue'])}", _GREEN))
    elif computed['balanceTaxPayable'] > 0:
        story.append(Paragraph(f"Tax payable: {_rupee(computed['balanceTaxPayable'])}", _AMBER))
    else:
        story.append(Paragraph('No tax payable and no refund due.', _BODY))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        f'Rule set {RULE_SET_VERSION} &middot; Schema {SCHEMA_VERSION} &middot; '
        f"Constants {computed.get('constantsVersion', '')}",
        _SMALL,
    ))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# §10.4 — validation report export (PDF)
# ---------------------------------------------------------------------------

def render_validation_report_pdf(tax_return, report):
    buffer = io.BytesIO()
    doc = _doc(buffer, 'ITR-1 Validation Report')
    story = [
        Paragraph('ITR-1 Validation Report', _H1),
        Paragraph(
            f"PAN {tax_return.data['personalInfo']['pan'] or '—'} &middot; "
            f"AY {tax_return.data['ay']} &middot; Generated {_now_str()}",
            _SMALL,
        ),
        Spacer(1, 6 * mm),
    ]

    if report.ok:
        story.append(Paragraph('✓ Validation successful — no errors were found.', _GREEN))
    else:
        story.append(Paragraph(
            f'✗ Validation failed — {len(report.errors)} error(s), {len(report.advisories)} advisory(ies).',
            _RED,
        ))

    def _finding_table(findings, style):
        if not findings:
            return
        rows = [[Paragraph(f'[{f.ruleId}]', _BODY), Paragraph(f.message, style)] for f in findings]
        t = Table(rows, colWidths=(22 * mm, 128 * mm))
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d6dbe0')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(t)

    if report.errors:
        story.append(Paragraph('Errors', _H2))
        _finding_table(report.errors, _RED)
    if report.advisories:
        story.append(Paragraph('Advisories', _H2))
        _finding_table(report.advisories, _AMBER)
    if report.documentAdvisories:
        story.append(Paragraph('Document advisories', _H2))
        _finding_table(report.documentAdvisories, _BODY)
    if report.ruleErrors:
        story.append(Paragraph('Rule engine errors', _H2))
        rows = [[Paragraph(f"[{e['ruleId']}]", _BODY), Paragraph(e['error'], _RED)] for e in report.ruleErrors]
        story.append(Table(rows, colWidths=(22 * mm, 128 * mm)))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        f'Rule set {report.ruleSetVersion} &middot; Constants {report.constantsVersion} &middot; '
        f'Evaluated {report.rulesEvaluated} &middot; Skipped {report.rulesSkipped}',
        _SMALL,
    ))

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# §10.2 — "Preview" (full ITR-1 form as a PDF for review)
# ---------------------------------------------------------------------------

def render_return_preview_pdf(tax_return, computed):
    """A section-by-section preview of everything that will be filed --
    not a pixel copy of the portal's own layout, but every figure and entry
    a preparer would want to double-check before generating the JSON."""
    model = tax_return.data
    buffer = io.BytesIO()
    doc = _doc(buffer, 'ITR-1 Preview')
    story = _header_block(tax_return, computed)

    pi = model['personalInfo']
    story.append(Paragraph('Personal Information', _H2))
    story.append(_money_table([
        ('Date of birth', pi['dob'] or '—'),
        ('Aadhaar', pi['aadhaar'] or '—'),
        ('Employer category', pi['employerCategory'] or '—'),
        ('Filing section', str(model['filingStatus']['returnFileSec'])),
    ], col_widths=(60 * mm, 90 * mm)))

    story.append(Paragraph('Gross Total Income', _H2))
    story.append(_money_table([
        ('Income from Salary', _rupee(computed['salary']['incomeFromSalary'])),
        ('Income from House Property', _rupee(computed['houseProperty']['incomeForGti'])),
        ('Income from Other Sources', _rupee(computed['otherSources']['netIncomeOthSrc'])),
        ('Gross Total Income', _rupee(computed['grossTotalIncomeInclLtcg'])),
    ]))

    story.append(Paragraph('Total Deductions', _H2))
    deduction_rows = [
        (section, _rupee(info['eligible']))
        for section, info in computed['deductions']['bySection'].items()
        if info['eligible'] > 0
    ] or [('No deductions claimed', '')]
    deduction_rows.append(('Total', _rupee(computed['totalDeductions'])))
    story.append(_money_table(deduction_rows))

    story.append(Paragraph('Tax Paid', _H2))
    paid = computed['taxesPaid']
    story.append(_money_table([
        ('TDS1 (salary)', _rupee(paid['tds1'])),
        ('TDS2 (other than salary)', _rupee(paid['tds2'])),
        ('TDS3', _rupee(paid['tds3'])),
        ('TCS', _rupee(paid['tcs'])),
        ('Advance tax', _rupee(paid['advanceTax'])),
        ('Self-assessment tax', _rupee(paid['selfAssessmentTax'])),
        ('Total', _rupee(paid['total'])),
    ]))

    story.append(Paragraph('Tax Liability', _H2))
    story.append(_money_table([
        ('Total Income', _rupee(computed['totalIncome'])),
        ('Total Tax, Fee and Interest', _rupee(computed['totalTaxFeeAndInterest'])),
    ]))

    story.append(Paragraph('Result', _H2))
    if computed['refundDue'] > 0:
        story.append(Paragraph(f"Refund due: {_rupee(computed['refundDue'])}", _GREEN))
    elif computed['balanceTaxPayable'] > 0:
        story.append(Paragraph(f"Tax payable: {_rupee(computed['balanceTaxPayable'])}", _AMBER))
    else:
        story.append(Paragraph('No tax payable and no refund due.', _BODY))

    doc.build(story)
    return buffer.getvalue()
