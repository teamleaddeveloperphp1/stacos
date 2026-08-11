import re

from django.core.validators import RegexValidator
from django import forms

from apps.itr.models import TaxFiler

RETURN_FILE_SEC_CHOICES = [
    (11, '139(1) — on/before due date'),
    (12, '139(4) — belated'),
    (17, '139(5) — revised'),
    (20, '119(2)(b) — after condonation'),
    (18, '139(9) — filed in response to defective-return notice'),
    (13, '142(1) — filed in response to notice u/s 142(1)'),
    (14, '148 — filed in response to notice u/s 148'),
    (16, '153C — filed in response to notice u/s 153C'),
    # NB: the schema's ReturnFileSec enum (11/12/13/14/16/17/18/20) has no
    # code for 139(8A) "updated return" at all.
]

CAPACITY_CHOICES = [
    ('S', 'Self'),
    ('R', 'Representative'),
]

EMPLOYER_CATEGORY_CHOICES = [
    ('', '— Select —'),
    ('CGOV', 'Central Government'),
    ('SGOV', 'State Government'),
    ('PSU', 'Public Sector Undertaking'),
    ('PENSCGOV', 'Pensioners (CG)'),
    ('PENSSGOV', 'Pensioners (SG)'),
    ('PENSPSU', 'Pensioners (PSU)'),
    ('PENSOTH', 'Pensioners (Other)'),
    ('OTH', 'Others'),
    ('NA', 'Not Applicable'),
]

YES_NO_CHOICES = [('Y', 'Yes'), ('N', 'No')]

ACCOUNT_TYPE_CHOICES = [
    ('SB', 'Savings'),
    ('CA', 'Current'),
    ('CC', 'Cash Credit'),
    ('OD', 'Overdraft'),
    ('NRO', 'NRO'),
    ('Other', 'Other'),
]


class FilingSectionForm(forms.Form):
    """A standalone gate screen shown right after Continue/Start, before the
    Personal Information form: which u/s 139 filing section applies, and
    which tax regime -- these two decide which fields the rest of the return
    even shows (see the regime-hidden CSS toggling on Gross Total Income /
    Total Deductions), so they're answered first, on their own."""

    return_file_sec = forms.TypedChoiceField(
        label='Filing section', choices=RETURN_FILE_SEC_CHOICES, coerce=int,
    )
    opt_out_of_new_regime = forms.ChoiceField(
        label='Which tax regime do you want to file under?',
        choices=[('N', 'New Tax Regime (default u/s 115BAC)'), ('Y', 'Old Tax Regime')],
        initial='N',
        help_text=(
            'This choice decides which fields you see on the rest of this return -- Old Tax Regime unlocks '
            'Chapter VI-A deductions (80C, 80D, HRA, etc.), the New Tax Regime hides them. Old Tax Regime '
            'becomes unavailable when the filing section requires a belated/revised return (rule A-151).'
        ),
    )

    def clean(self):
        cleaned = super().clean()
        # A-151: old regime unavailable once filed belated u/s 139(4) (or later
        # sections that likewise foreclose it) — force the opt-out to "No".
        if cleaned.get('return_file_sec') in (12, 17, 18) and cleaned.get('opt_out_of_new_regime') == 'Y':
            self.add_error(
                'opt_out_of_new_regime',
                'Old regime unavailable: return is being filed after the due date (rule A-151).',
            )
        return cleaned


class PersonalInfoForm(forms.Form):
    first_name = forms.CharField(label='First name', max_length=60)
    middle_name = forms.CharField(label='Middle name', max_length=60, required=False)
    last_name = forms.CharField(label='Last / Surname', max_length=60)
    pan = forms.CharField(label='PAN', max_length=10)
    dob = forms.DateField(label='Date of birth', widget=forms.DateInput(attrs={'type': 'date'}))
    aadhaar = forms.CharField(label='Aadhaar number', max_length=12, required=False)
    employer_category = forms.ChoiceField(label='Nature of employment', choices=EMPLOYER_CATEGORY_CHOICES, required=False)

    primary_mobile = forms.CharField(label='Primary mobile', max_length=10)
    secondary_mobile = forms.CharField(label='Secondary mobile', max_length=10, required=False)
    primary_email = forms.EmailField(label='Primary email', max_length=125)
    secondary_email = forms.EmailField(label='Secondary email', max_length=125, required=False)

    flat_door_building = forms.CharField(label='Flat/Door/Building', max_length=120)
    premise_building_name = forms.CharField(label='Premise/Building name', max_length=120, required=False)
    road_street = forms.CharField(label='Road/Street', max_length=120, required=False)
    area_locality = forms.CharField(label='Area/Locality', max_length=120)
    town_city_district = forms.CharField(label='Town/City/District', max_length=120)
    state_code = forms.CharField(label='State code', max_length=2)
    pin_code = forms.CharField(label='PIN code', max_length=6)

    secondary_address_same_as_primary = forms.ChoiceField(
        label='Is the secondary address same as primary?', choices=YES_NO_CHOICES, initial='Y',
    )

    # --- Original return details (139(5) revised / 139(9) defective-response) ---
    orig_return_ack_no = forms.CharField(label='Original return acknowledgement no.', max_length=30, required=False)
    orig_return_filed_date = forms.DateField(label='Original return filed date', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    orig_return_file_sec = forms.TypedChoiceField(
        label='Original return filing section', choices=[('', '— Not applicable —')] + RETURN_FILE_SEC_CHOICES,
        required=False, coerce=lambda v: int(v) if v else None, empty_value=None,
    )
    a23_responses_original = forms.CharField(
        label='A23 responses in the original/defective ITR', widget=forms.Textarea(attrs={'rows': 2}), required=False,
    )
    a23_responses_current = forms.CharField(
        label='A23 responses in this return', widget=forms.Textarea(attrs={'rows': 2}), required=False,
        help_text='A-219: for a 139(9) defective-return response, these must match the original.',
    )

    # --- Seventh proviso to s.139(1) ---------------------------------------
    seventh_proviso_139 = forms.ChoiceField(
        label='Filing under the seventh proviso to s.139(1) though otherwise not required to file?',
        choices=YES_NO_CHOICES, initial='N',
    )
    travel_expense_above_2lakh = forms.ChoiceField(
        label='Incurred travel expense > ₹2 lakh for foreign travel?', choices=YES_NO_CHOICES, required=False, initial='N',
    )
    travel_expense_amount = forms.IntegerField(label='Travel expense amount', min_value=0, required=False)
    electricity_above_1lakh = forms.ChoiceField(
        label='Incurred electricity expense > ₹1 lakh?', choices=YES_NO_CHOICES, required=False, initial='N',
    )
    electricity_amount = forms.IntegerField(label='Electricity expense amount', min_value=0, required=False)
    clause_iv_applies = forms.ChoiceField(
        label='Any other condition under clause (iv) of the seventh proviso?', choices=YES_NO_CHOICES, required=False, initial='N',
    )

    # --- Representative assessee -------------------------------------------
    representative_assessee_flag = forms.ChoiceField(
        label='Is this return being filed by a representative assessee?', choices=YES_NO_CHOICES, initial='N',
    )
    representative_name = forms.CharField(label='Representative name', max_length=120, required=False)
    representative_email = forms.EmailField(label='Representative email', max_length=125, required=False)
    representative_mobile = forms.CharField(label='Representative mobile', max_length=10, required=False)
    representative_pan = forms.CharField(label='Representative PAN', max_length=10, required=False)
    representative_capacity_other = forms.CharField(label='Capacity (e.g. guardian, agent)', max_length=60, required=False)
    verification_capacity = forms.ChoiceField(label='Verification capacity', choices=CAPACITY_CHOICES, initial='S')

    def clean_pan(self):
        return self.cleaned_data['pan'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        # §4.5 / A-293: representative details mandatory once the flag is Yes.
        if cleaned.get('representative_assessee_flag') == 'Y':
            for field, label in (
                ('representative_name', 'Representative name'),
                ('representative_email', 'Representative email'),
                ('representative_mobile', 'Representative contact no.'),
                ('representative_pan', 'Representative PAN'),
            ):
                if not cleaned.get(field):
                    self.add_error(field, f'{label} is mandatory when filing by a representative assessee (A-293).')
            # A-331: representative email/mobile must differ from the taxpayer's own.
            own_emails = {cleaned.get('primary_email', '').lower(), cleaned.get('secondary_email', '').lower()}
            own_mobiles = {cleaned.get('primary_mobile', ''), cleaned.get('secondary_mobile', '')}
            if cleaned.get('representative_email', '').lower() in own_emails - {''}:
                self.add_error('representative_email', "Representative's email must differ from the taxpayer's (A-331).")
            if cleaned.get('representative_mobile', '') in own_mobiles - {''}:
                self.add_error('representative_mobile', "Representative's mobile must differ from the taxpayer's (A-331).")

        return cleaned


class TaxFilerForm(forms.Form):
    """Adds/edits a reusable TaxFiler (itr.models.TaxFiler) -- the identity
    a Continue click carries into that person's TaxReturn.data['personalInfo'],
    kept separate from PersonalInfoForm because a TaxFiler exists before any
    return does and is never filing-status/regime aware."""

    pan = forms.CharField(label='PAN', max_length=10)
    dob = forms.DateField(label='Date of birth', widget=forms.DateInput(attrs={'type': 'date'}))
    email = forms.EmailField(label='Email', max_length=125)
    first_name = forms.CharField(label='First Name', max_length=60)
    middle_name = forms.CharField(label='Middle Name', max_length=60, required=False)
    last_name = forms.CharField(label='Last Name', max_length=60)
    gender = forms.ChoiceField(label='Gender', choices=[('', '--Select--')] + TaxFiler.GENDER_CHOICES)
    father_name = forms.CharField(label='Father Name', max_length=120)
    mobile_number = forms.CharField(label='Mobile Number', max_length=10, validators=[RegexValidator(
        r'^[0-9]{10}$', 'Enter a valid 10-digit mobile number.')],
        help_text='WhatsApp number preferred - for updates to tax filing')

    def clean_pan(self):
        pan = self.cleaned_data['pan'].strip().upper()
        if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', pan):
            raise forms.ValidationError('Enter a valid PAN (e.g. ABCDE1234F).')
        return pan


class BankAccountForm(forms.Form):
    ifsc = forms.CharField(label='IFSC', max_length=11)
    bank_name = forms.CharField(label='Bank name', max_length=120, required=False)
    account_number = forms.CharField(label='Account number', max_length=20)
    account_type = forms.ChoiceField(label='Account type', choices=ACCOUNT_TYPE_CHOICES, initial='SB')
    nominate_for_refund = forms.BooleanField(label='Nominate for refund', required=False)


BankAccountFormSet = forms.formset_factory(BankAccountForm, extra=1, can_delete=True)


def bank_accounts_structural_errors(accounts):
    """§4.6: at least one bank account is mandatory, and exactly one must be
    nominated for refund. This is a screen-level (tier-2, Confirm-time)
    product constraint, not one of the numbered CBDT rules, so it is checked
    here rather than in the rule registry -- and only enforced on Confirm,
    not on every intermediate Save, since screens are save-anytime drafts."""
    errors = []
    if not accounts:
        errors.append('At least one bank account is mandatory.')
    nominated = sum(1 for b in accounts if b.get('nominateForRefund'))
    if accounts and nominated != 1:
        errors.append(f'Exactly one bank account must be nominated for refund ({nominated} currently nominated).')
    return errors


# ---------------------------------------------------------------------------
# Screen 2 — Gross Total Income
# ---------------------------------------------------------------------------

ALLOWANCE_NATURE_CHOICES = [
    ('', '— Select —'),
    ('10(5)', '10(5) — Leave Travel Concession/Assistance'),
    ('10(6)', '10(6) — Remuneration as official of embassy etc.'),
    ('10(7)', '10(7) — Allowances/perquisites paid outside India by Govt.'),
    ('10(10)', '10(10) — Death-cum-retirement gratuity'),
    ('10(10A)', '10(10A) — Commuted value of pension'),
    ('10(10AA)', '10(10AA) — Earned leave encashment on retirement'),
    ('10(10B)(i)', '10(10B)(i) — Retrenchment compensation (first proviso)'),
    ('10(10B)(ii)', '10(10B)(ii) — Retrenchment compensation (second proviso)'),
    ('10(10C)', '10(10C) — Voluntary retirement/termination'),
    ('10(10CC)', '10(10CC) — Tax paid by employer on non-monetary perquisite'),
    ('10(13A)', '10(13A) — House Rent Allowance'),
    ('10(14)(i)', '10(14)(i) — Prescribed allowances (actual expenditure)'),
    ('10(14)(ii)', '10(14)(ii) — Prescribed allowances (personal expenses)'),
    ('10(14)(i)(115BAC)', '10(14)(i)(115BAC) — Rule 2BB(1)(a)-(c) allowances'),
    ('10(14)(ii)(115BAC)', '10(14)(ii)(115BAC) — Transport allowance (handicapped)'),
    ('EIC', 'EIC — Exempt income of a Judge'),
    ('10(17)', '10(17) — Allowance to MP/MLA/MLC'),
]

PROPERTY_TYPE_CHOICES = [
    ('', '— Select —'),
    ('S', 'Self-Occupied'),
    ('L', 'Let Out'),
    ('D', 'Deemed Let Out'),
]

PROPERTY_OWNER_CHOICES = [
    ('', '— Select —'),
    ('SE', 'Self'),
    ('MI', 'Minor'),
    ('SP', 'Spouse'),
    ('OT', 'Others'),
]

OTHER_SOURCE_NATURE_CHOICES = [
    ('', '— Select —'),
    ('SAV', 'Interest from savings account'),
    ('IFD', 'Interest from deposits (bank/post office/co-op society)'),
    ('TAX', 'Interest on income tax refund'),
    ('FAP', 'Family pension'),
    ('DIV', 'Dividend'),
    ('10(11)(iP)', '10(11)(iP) — PF interest, first proviso'),
    ('10(11)(iiP)', '10(11)(iiP) — PF interest, second proviso'),
    ('10(12)(iP)', '10(12)(iP) — RPF interest, first proviso'),
    ('10(12)(iiP)', '10(12)(iiP) — RPF interest, second proviso'),
    ('OTH', 'Any other'),
]

EXEMPT_INCOME_CATEGORY_CHOICES = [
    ('', '— Select —'),
    ('AGRI', 'Agricultural & related incomes'),
    ('GOVC', 'Compensation/other sums from government or approved entities'),
    ('ISI', 'Income from specified investments'),
    ('SSRA', 'Specified sums received by armed forces personnel'),
    ('SRSC', 'Sums received by senior citizens/minors'),
    ('SRST', 'Sums received by specified category of taxpayers'),
    ('SRPC', 'Sums received from policies/contributions (LIC/NPS/PF/SSY)'),
    ('OTH', 'Other incomes'),
]

EXEMPT_INCOME_SUBCATEGORY_CHOICES = [
    ('', '— Select —'),
    ('10(1)', '10(1) — Agricultural income (≤ ₹5,000)'),
    ('10(30)', '10(30) — Subsidy from/through the Tea Board'),
    ('10(31)', '10(31) — Rubber/Coffee/Tea development accounts/funds'),
    ('10(10BB)', '10(10BB) — Bhopal Gas Leak Disaster payments'),
    ('10(10BC)', '10(10BC) — Disaster compensation from Govt./local authority'),
    ('10(17A)', '10(17A) — Award instituted by Government'),
    ('10(12AB)', '10(12AB) — Lump sum per notification FX-1/3/2024-PR'),
    ('10(15)', '10(15) — Interest on specified securities/investments'),
    ('10(23FBB)', '10(23FBB) — Investment fund income u/s 115UB'),
    ('10(23FD)', '10(23FD) — Unit holder income from Business Trust'),
    ('10(35)', '10(35) — Income from specified Mutual Funds'),
    ('10(35A)', '10(35A) — Distributed income from a securitisation trust'),
    ('10(12C)', '10(12C) — Agniveer Corpus Fund income'),
    ('10(18)', '10(18) — Pension of gallantry award winners'),
    ('10(19)', '10(19) — Armed Forces family pension (death on duty)'),
    ('10(23AA)', '10(23AA) — Sum received on behalf of armed forces fund'),
    ('DMD', 'Defense Medical Disability Pension'),
    ('10(32)', "10(32) — Minor child's income (small exemption)"),
    ('10(43)', '10(43) — Reverse mortgage payments to senior citizens'),
    ('10(19A)', '10(19A) — Annual value of one palace of an ex-ruler'),
    ('10(26)', '10(26) — Income u/s 10(26)'),
    ('10(26AAA)', '10(26AAA) — Income u/s 10(26AAA)'),
    ('10(10D)', '10(10D) — Sum received under a life insurance policy'),
    ('10(11)', '10(11) — Statutory Provident Fund received'),
    ('10(11A)', '10(11A) — Sukanya Samriddhi Yojana receipt'),
    ('10(12)', '10(12) — Recognized Provident Fund received'),
    ('10(12A)', '10(12A) — Payment from NPS Trust to an assessee'),
    ('10(12AA)', '10(12AA) — Payment from NPS Trust'),
    ('10(12B)', '10(12B) — Payment from NPS Trust to a CG employee'),
    ('10(12BA)', '10(12BA) — Partial withdrawal from NPS'),
    ('10(13)', '10(13) — Approved superannuation fund received'),
    ('10(25)', '10(25) — Sum received by trustees of approved funds'),
    ('10(44)', '10(44) — Income received by/on behalf of NPS Trust'),
    ('10(2)', "10(2) — Member's share from HUF"),
    ('10(16)', '10(16) — Scholarships for education'),
    ('Incmexmptcircular', 'Income exempt as per CBDT Circular'),
    ('Incmexmptnotification', 'Income exempt as per CBDT Notification'),
    ('Receiptnotincme', 'Receipts not in the nature of income'),
]


class SalaryForm(forms.Form):
    salary17_1 = forms.IntegerField(label='Salary as per section 17(1)', min_value=0, initial=0)
    perquisites17_2 = forms.IntegerField(label='Value of perquisites u/s 17(2)', min_value=0, initial=0)
    profits_in_lieu17_3 = forms.IntegerField(label='Profits in lieu of salary u/s 17(3)', min_value=0, initial=0)
    entertainment_allowance_16ii = forms.IntegerField(
        label='Entertainment allowance u/s 16(ii)', min_value=0, initial=0, required=False,
    )
    professional_tax_16iii = forms.IntegerField(
        label='Professional tax u/s 16(iii)', min_value=0, initial=0, required=False,
    )


HRA_PLACE_OF_WORK_CHOICES = [('', '— Select —'), ('1', 'Metro city'), ('2', 'Non-metro city')]


class HraForm(forms.Form):
    """Schedule 10(13A) — feeds itr.engine.compute.compute_hra, which
    already computes the least-of-three exemption and zeroes it under the
    new regime; this form just captures the four facts that computation
    needs (model_blank.blank_hra)."""

    place_of_work = forms.ChoiceField(label='Place of work', choices=HRA_PLACE_OF_WORK_CHOICES, required=False)
    actual_hra_received = forms.IntegerField(label='Actual HRA received', min_value=0, initial=0, required=False)
    actual_rent_paid = forms.IntegerField(label='Actual rent paid', min_value=0, initial=0, required=False)
    basic_salary = forms.IntegerField(label='Basic salary', min_value=0, initial=0, required=False)
    dearness_allowance = forms.IntegerField(label='Dearness allowance (forming part of retirement benefits)', min_value=0, initial=0, required=False)


class ExemptAllowanceForm(forms.Form):
    nature = forms.ChoiceField(label='Nature of allowance', choices=ALLOWANCE_NATURE_CHOICES, required=False)
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


ExemptAllowanceFormSet = forms.formset_factory(ExemptAllowanceForm, extra=1, can_delete=True)


class HousePropertyForm(forms.Form):
    property_type = forms.ChoiceField(label='Type of house property', choices=PROPERTY_TYPE_CHOICES, required=False)
    property_owner = forms.ChoiceField(label='Property owner', choices=PROPERTY_OWNER_CHOICES, required=False)
    flat_door_building = forms.CharField(label='Flat/Door/Building', max_length=120, required=False)
    area_locality = forms.CharField(label='Area/Locality', max_length=120, required=False)
    town_city_district = forms.CharField(label='Town/City/District', max_length=120, required=False)
    state_code = forms.CharField(label='State code', max_length=2, required=False)
    pin_code = forms.CharField(label='PIN code', max_length=6, required=False)
    co_owned = forms.ChoiceField(label='Is property co-owned?', choices=YES_NO_CHOICES, initial='N', required=False)
    assessee_share_percent = forms.IntegerField(
        label="Assessee's share %", min_value=0, max_value=100, required=False, initial=100,
    )
    gross_rent = forms.IntegerField(label='Gross rent received/receivable/lettable value', min_value=0, required=False, initial=0)
    local_taxes = forms.IntegerField(label='Tax paid to local authorities', min_value=0, required=False, initial=0)
    rent_not_realized = forms.IntegerField(label='Rent which cannot be realized', min_value=0, required=False, initial=0)
    interest_on_borrowed_capital = forms.IntegerField(
        label='Interest payable on borrowed capital', min_value=0, required=False, initial=0,
    )

    def clean(self):
        cleaned = super().clean()
        # A-336: unrealised rent cannot exceed gross rent.
        if (cleaned.get('rent_not_realized') or 0) > (cleaned.get('gross_rent') or 0):
            self.add_error('rent_not_realized', 'Cannot exceed gross rent (rule A-336).')
        return cleaned


HousePropertyFormSet = forms.formset_factory(HousePropertyForm, extra=1, can_delete=True)


class OtherSourceForm(forms.Form):
    nature = forms.ChoiceField(label='Nature of income', choices=OTHER_SOURCE_NATURE_CHOICES, required=False)
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


OtherSourceFormSet = forms.formset_factory(OtherSourceForm, extra=1, can_delete=True)


class ExemptIncomeForm(forms.Form):
    category = forms.ChoiceField(label='Category', choices=EXEMPT_INCOME_CATEGORY_CHOICES, required=False)
    sub_category = forms.ChoiceField(label='Sub-category', choices=EXEMPT_INCOME_SUBCATEGORY_CHOICES, required=False)
    description = forms.CharField(label='Description', max_length=125, required=False)
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


ExemptIncomeFormSet = forms.formset_factory(ExemptIncomeForm, extra=1, can_delete=True)


# ---------------------------------------------------------------------------
# Screen 3 — Total Deductions
# ---------------------------------------------------------------------------
#
# Row-shape note: the schedule row keys below were verified against
# itr/serialize/importer.py (the CBDT-schema reader, which is ground truth
# for the field names compute.py/facts.py expect) rather than guessed:
#   schedule80C row               -> {id, typeOfIdentifier, identificationNo, amount}
#   pensionContribution80CCC row  -> {id, typeOfIdentifier, nameOfIdentifier, amount}
#   schedule80E/80EE/80EEA/80EEB  -> {id, loanTakenFrom, lenderName, loanAccountNo,
#                                      dateOfLoan, totalLoanAmount, loanOutstandingAmount,
#                                      interest, vehicleRegNo} (all four share this shape)
#   schedule80D block             -> {healthInsurancePremium, insurers, preventiveHealthCheckup,
#                                      medicalExpenditure}
#   schedule80DD / schedule80U    -> {natureOfDisability, typeOfDisability, amount,
#                                      dependentType, dependentPan, dependentAadhaar,
#                                      form10IAFiled, form10IAAckNo, udidNo}
#   schedule80G donee row         -> {id, name, pan, arnNo, address, donationCash,
#                                      donationOtherMode, transactionRefNo, ifsc}
#   schedule80GGA row             -> {id, relevantClause, name, pan, address,
#                                      donationCash, donationOtherMode}
#   schedule80GGC row             -> {id, donationDate, politicalPartyName,
#                                      politicalPartyPan, donationCash, donationOtherMode,
#                                      transactionRefNo, ifsc}
#
# compute.py's tier-2 rules (A-241 to A-245, and the 80DD/80U equivalents)
# require the top-level aggregate (s80C, s80CCC, s80E, s80EE, s80EEA, s80EEB,
# s80DD, s80U) to *equal exactly* the corresponding schedule total. Rather than
# ask the user to re-enter that total by hand (and risk an inconsistent
# figure that tier-2 validation would then reject), the view derives those
# eight aggregates automatically from the schedule rows below and does not
# expose separate input fields for them. s80D, s80GGA and s80GGC only need to
# be <= their schedule's eligible amount (not an exact match), so those keep
# a genuine user-entered field on DeductionsForm.

DISABILITY_NATURE_CHOICES = [
    ('', '— Select —'),
    ('1', 'Disability (40% or more but less than 80%)'),
    ('2', 'Severe disability (80% or more)'),
]

DDB_USER_TYPE_CHOICES = [
    ('', '— Select —'),
    ('1', 'Self or dependent'),
    ('2', 'Other than self'),
]


class DeductionsForm(forms.Form):
    """Aggregate figures that are entered directly (not derived from a
    mandatory sub-schedule this screen builds)."""

    s80CCD1 = forms.IntegerField(
        label='80CCD(1) — Employee/self contribution to pension scheme', min_value=0, required=False, initial=0,
    )
    pran_numbers = forms.CharField(
        label='PRAN number(s) (comma-separated)', required=False,
        help_text='Simplification: one comma-separated text field instead of a repeating PRAN grid.',
    )
    s80CCD1B = forms.IntegerField(label='80CCD(1B) — Additional NPS contribution', min_value=0, required=False, initial=0)
    s80CCD2 = forms.IntegerField(label="80CCD(2) — Employer's contribution to pension scheme", min_value=0, required=False, initial=0)
    s80CCH = forms.IntegerField(label='80CCH — Agnipath Scheme contribution', min_value=0, required=False, initial=0)

    s80D = forms.IntegerField(label='80D — claimed amount', min_value=0, required=False, initial=0)
    s80G = forms.IntegerField(label='80G — Donations to certain funds/charitable institutions', min_value=0, required=False, initial=0)

    s80DDB = forms.IntegerField(label='80DDB — Medical treatment of specified disease', min_value=0, required=False, initial=0)
    s80DDBUsrType = forms.ChoiceField(label='80DDB claimant category', choices=DDB_USER_TYPE_CHOICES, required=False)
    s80DDBDisease = forms.CharField(label='Name of specified disease', max_length=125, required=False)

    stampDutyValue80EEA = forms.IntegerField(label='Stamp duty value of house property (80EEA)', min_value=0, required=False, initial=0)

    s80GG = forms.IntegerField(label='80GG — Rent paid (no HRA received)', min_value=0, required=False, initial=0)
    form10BAFiled = forms.BooleanField(label='Form 10BA filed?', required=False)
    form10BAAckNo = forms.CharField(label='Form 10BA acknowledgement number', max_length=20, required=False)

    s80GGA = forms.IntegerField(label='80GGA — claimed amount', min_value=0, required=False, initial=0)
    s80GGC = forms.IntegerField(label='80GGC — claimed amount', min_value=0, required=False, initial=0)

    s80TTA = forms.IntegerField(label='80TTA — Interest on savings account', min_value=0, required=False, initial=0)
    s80TTB = forms.IntegerField(label='80TTB — Interest income (senior citizens)', min_value=0, required=False, initial=0)


# --- 80C group (80C / 80CCC schedules; 80CCD1 is a plain field above, sharing
#     the same ₹1,50,000 aggregate cap) ----------------------------------------

class Schedule80CRowForm(forms.Form):
    identification_no = forms.CharField(label='Identification no. / policy no.', max_length=60, required=False)
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


Schedule80CFormSet = forms.formset_factory(Schedule80CRowForm, extra=1, can_delete=True)


class Schedule80CCCRowForm(forms.Form):
    name_of_identifier = forms.CharField(label='Name of pension fund/insurer', max_length=120, required=False)
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


Schedule80CCCFormSet = forms.formset_factory(Schedule80CCCRowForm, extra=1, can_delete=True)


# --- 80D — fixed 4-block structure (not a repeating formset) ----------------

class Schedule80DForm(forms.Form):
    """Simplification: the CBDT schema also carries an `insurers` sub-list
    (insurer name/policy number/amount) per block; this pass captures only
    the block-level totals compute.py actually reads
    (healthInsurancePremium/preventiveHealthCheckup/medicalExpenditure)."""

    self_family_senior_flag = forms.ChoiceField(
        label='Any member of self/family is a senior citizen?', choices=[('', '— Select —')] + YES_NO_CHOICES, required=False,
    )
    self_family_health_insurance_premium = forms.IntegerField(label='Self/Family — health insurance premium', min_value=0, required=False, initial=0)
    self_family_preventive_health_checkup = forms.IntegerField(label='Self/Family — preventive health check-up', min_value=0, required=False, initial=0)
    self_family_medical_expenditure = forms.IntegerField(label='Self/Family — medical expenditure', min_value=0, required=False, initial=0)

    self_family_senior_health_insurance_premium = forms.IntegerField(label='Self/Family (incl. senior citizen) — health insurance premium', min_value=0, required=False, initial=0)
    self_family_senior_preventive_health_checkup = forms.IntegerField(label='Self/Family (incl. senior citizen) — preventive health check-up', min_value=0, required=False, initial=0)
    self_family_senior_medical_expenditure = forms.IntegerField(label='Self/Family (incl. senior citizen) — medical expenditure', min_value=0, required=False, initial=0)

    parents_senior_flag = forms.ChoiceField(
        label='Are parents senior citizens?', choices=[('', '— Select —')] + YES_NO_CHOICES, required=False,
    )
    parents_health_insurance_premium = forms.IntegerField(label='Parents — health insurance premium', min_value=0, required=False, initial=0)
    parents_preventive_health_checkup = forms.IntegerField(label='Parents — preventive health check-up', min_value=0, required=False, initial=0)
    parents_medical_expenditure = forms.IntegerField(label='Parents — medical expenditure', min_value=0, required=False, initial=0)

    parents_senior_health_insurance_premium = forms.IntegerField(label='Parents (senior citizen) — health insurance premium', min_value=0, required=False, initial=0)
    parents_senior_preventive_health_checkup = forms.IntegerField(label='Parents (senior citizen) — preventive health check-up', min_value=0, required=False, initial=0)
    parents_senior_medical_expenditure = forms.IntegerField(label='Parents (senior citizen) — medical expenditure', min_value=0, required=False, initial=0)


# --- 80DD / 80U — identical shape, used for both sections -------------------

class Disability80DDUForm(forms.Form):
    nature_of_disability = forms.ChoiceField(label='Nature of disability', choices=DISABILITY_NATURE_CHOICES, required=False)
    type_of_disability = forms.CharField(label='Type of disability', max_length=60, required=False)
    amount = forms.IntegerField(label='Deduction amount claimed', min_value=0, required=False, initial=0)
    form10IAFiled = forms.BooleanField(label='Form 10-IA filed?', required=False)
    form10IAAckNo = forms.CharField(label='Form 10-IA acknowledgement number', max_length=20, required=False)


# --- Loan-interest schedules — 80E / 80EE / 80EEA / 80EEB share one row shape

class LoanInterestRowForm(forms.Form):
    lender_name = forms.CharField(label='Lender name', max_length=120, required=False)
    loan_account_no = forms.CharField(label='Loan account no.', max_length=20, required=False)
    date_of_loan = forms.DateField(label='Date of loan sanction', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    interest = forms.IntegerField(label='Interest paid this year', min_value=0, required=False, initial=0)


Schedule80EFormSet = forms.formset_factory(LoanInterestRowForm, extra=1, can_delete=True)
Schedule80EEFormSet = forms.formset_factory(LoanInterestRowForm, extra=1, can_delete=True)
Schedule80EEAFormSet = forms.formset_factory(LoanInterestRowForm, extra=1, can_delete=True)
Schedule80EEBFormSet = forms.formset_factory(LoanInterestRowForm, extra=1, can_delete=True)


# --- 80G — one combined formset with a block selector instead of 4 tables ---

SCHEDULE_80G_BLOCK_CHOICES = [
    ('A', 'A — 100% deduction, no qualifying limit'),
    ('B', 'B — 50% deduction, no qualifying limit'),
    ('C', 'C — 100% deduction, subject to qualifying limit'),
    ('D', 'D — 50% deduction, subject to qualifying limit'),
]

SCHEDULE_80G_BLOCK_MODEL_KEY = {
    'A': 'don100Percent',
    'B': 'don50PercentNoApprReqd',
    'C': 'don100PercentApprReqd',
    'D': 'don50PercentApprReqd',
}


class Schedule80GRowForm(forms.Form):
    block = forms.ChoiceField(label='Table', choices=SCHEDULE_80G_BLOCK_CHOICES, required=False)
    donee_name = forms.CharField(label='Donee name', max_length=120, required=False)
    pan = forms.CharField(label='Donee PAN', max_length=10, required=False)
    donation_cash = forms.IntegerField(label='Donation — cash', min_value=0, required=False, initial=0)
    donation_other_mode = forms.IntegerField(label='Donation — other mode', min_value=0, required=False, initial=0)
    ifsc = forms.CharField(label='IFSC (for non-cash donations)', max_length=11, required=False)
    transaction_ref_no = forms.CharField(label='Transaction reference no.', max_length=30, required=False)


Schedule80GFormSet = forms.formset_factory(Schedule80GRowForm, extra=1, can_delete=True)


class Schedule80GGARowForm(forms.Form):
    donee_name = forms.CharField(label='Donee name', max_length=120, required=False)
    pan = forms.CharField(label='Donee PAN', max_length=10, required=False)
    donation_cash = forms.IntegerField(label='Donation — cash', min_value=0, required=False, initial=0)
    donation_other_mode = forms.IntegerField(label='Donation — other mode', min_value=0, required=False, initial=0)


Schedule80GGAFormSet = forms.formset_factory(Schedule80GGARowForm, extra=1, can_delete=True)


class Schedule80GGCRowForm(forms.Form):
    donation_date = forms.DateField(label='Donation date', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    political_party_name = forms.CharField(label='Political party name', max_length=120, required=False)
    political_party_pan = forms.CharField(label='Political party PAN', max_length=10, required=False)
    donation_cash = forms.IntegerField(label='Donation — cash', min_value=0, required=False, initial=0)
    donation_other_mode = forms.IntegerField(label='Donation — other mode', min_value=0, required=False, initial=0)
    ifsc = forms.CharField(label='IFSC (for non-cash donations)', max_length=11, required=False)
    transaction_ref_no = forms.CharField(label='Transaction reference no.', max_length=30, required=False)


Schedule80GGCFormSet = forms.formset_factory(Schedule80GGCRowForm, extra=1, can_delete=True)


# ---------------------------------------------------------------------------
# Screen 4 — Tax Paid
# ---------------------------------------------------------------------------
#
# Row-shape note: verified against itr/serialize/importer.py, same as the
# Screen 3 note above:
#   taxPaid.tds1 row     -> {id, tan, deductorName, incomeChargeableSalary, totalTaxDeducted}
#   taxPaid.tds2 row     -> {id, tanOrPan, deductorName, grossReceipt, deductedYear,
#                             taxDeducted, tdsClaimedThisYear, tdsSection, headOfIncome}
#   taxPaid.tds3 row     -> {id, panOfTenant, aadhaarOfTenant, nameOfTenant, grossReceipt,
#                             deductedYear, taxDeducted, tdsClaimedThisYear, tdsSection,
#                             headOfIncome}  (TDS3 names its payer fields around "tenant"
#                             rather than "deductor" — different from TDS2 — per
#                             facts.py's `tds3HeadsWithoutIncome` reading `r['nameOfTenant']`)
#   taxPaid.tcs row      -> {id, tan, collectorName, taxCollected, collectedYear,
#                             totalTcs, tcsClaimedThisYear}
#   taxPaid.challans row -> {id, bsrCode, dateOfDeposit, challanSerialNo, amount}
#
# `headOfIncome` is a plain ChoiceField (not the Category-B advisory section
# list from the build prompt, which the already-ported rule engine enforces
# on its own) restricted to the literals facts.py's `_head_is_offered` switch
# actually understands: SALARY / HP / OS / EXEMPT.

TAN_VALIDATOR = RegexValidator(r'^[A-Z]{4}[0-9]{5}[A-Z]{1}$', 'Enter a valid TAN (e.g. MUMS27065D).')
BSR_CODE_VALIDATOR = RegexValidator(r'^[0-9]{7}$', 'BSR code must be 7 digits.')
CHALLAN_SERIAL_VALIDATOR = RegexValidator(r'^[0-9]{5}$', 'Challan serial number must be 5 digits.')

HEAD_OF_INCOME_CHOICES = [
    ('', '— Select —'),
    ('SALARY', 'Salary'),
    ('HP', 'House Property'),
    ('OS', 'Other Sources'),
    ('EXEMPT', 'Exempt'),
]


class Tds1RowForm(forms.Form):
    tan = forms.CharField(label='TAN of deductor', max_length=10, required=False, validators=[TAN_VALIDATOR])
    deductor_name = forms.CharField(label='Name of deductor', max_length=120, required=False)
    income_chargeable_salary = forms.IntegerField(label='Income chargeable under Salaries', min_value=0, required=False, initial=0)
    total_tax_deducted = forms.IntegerField(label='Total tax deducted', min_value=0, required=False, initial=0)

    def clean_tan(self):
        return self.cleaned_data['tan'].strip().upper()


Tds1FormSet = forms.formset_factory(Tds1RowForm, extra=1, can_delete=True)


class Tds2RowForm(forms.Form):
    tan_or_pan = forms.CharField(label='TAN/PAN of deductor', max_length=10, required=False)
    deductor_name = forms.CharField(label='Name of deductor', max_length=120, required=False)
    gross_receipt = forms.IntegerField(label='Gross receipt', min_value=0, required=False, initial=0)
    deducted_year = forms.CharField(label='Year of tax deduction', max_length=4, required=False)
    tax_deducted = forms.IntegerField(label='Tax deducted', min_value=0, required=False, initial=0)
    tds_claimed_this_year = forms.IntegerField(label='TDS credit claimed this year', min_value=0, required=False, initial=0)
    tds_section = forms.CharField(label='Section under which deducted', max_length=20, required=False)
    head_of_income = forms.ChoiceField(label='Head of income', choices=HEAD_OF_INCOME_CHOICES, required=False)

    def clean_tan_or_pan(self):
        return self.cleaned_data['tan_or_pan'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        # A-98
        if (cleaned.get('tds_claimed_this_year') or 0) > (cleaned.get('tax_deducted') or 0):
            self.add_error('tds_claimed_this_year', 'TDS claimed cannot exceed tax deducted (rule A-98).')
        # A-260
        if (cleaned.get('tds_section') or '').strip() == '192':
            self.add_error('tds_section', 'Section 192 is not selectable in Schedule TDS2 (rule A-260).')
        return cleaned


Tds2FormSet = forms.formset_factory(Tds2RowForm, extra=1, can_delete=True)


class Tds3RowForm(forms.Form):
    pan_of_tenant = forms.CharField(label='PAN of tenant', max_length=10, required=False)
    aadhaar_of_tenant = forms.CharField(label='Aadhaar of tenant', max_length=12, required=False)
    name_of_tenant = forms.CharField(label='Name of tenant', max_length=120, required=False)
    gross_receipt = forms.IntegerField(label='Gross receipt', min_value=0, required=False, initial=0)
    deducted_year = forms.CharField(label='Year of tax deduction', max_length=4, required=False)
    tax_deducted = forms.IntegerField(label='Tax deducted', min_value=0, required=False, initial=0)
    tds_claimed_this_year = forms.IntegerField(label='TDS credit claimed this year', min_value=0, required=False, initial=0)
    tds_section = forms.CharField(label='Section under which deducted', max_length=20, required=False)
    head_of_income = forms.ChoiceField(label='Head of income', choices=HEAD_OF_INCOME_CHOICES, required=False)

    def clean_pan_of_tenant(self):
        return self.cleaned_data['pan_of_tenant'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        # A-98 equivalent for TDS3
        if (cleaned.get('tds_claimed_this_year') or 0) > (cleaned.get('tax_deducted') or 0):
            self.add_error('tds_claimed_this_year', 'TDS claimed cannot exceed tax deducted.')
        # A-260
        if (cleaned.get('tds_section') or '').strip() == '192':
            self.add_error('tds_section', 'Section 192 is not selectable in Schedule TDS3 (rule A-260).')
        return cleaned


Tds3FormSet = forms.formset_factory(Tds3RowForm, extra=1, can_delete=True)


class TcsRowForm(forms.Form):
    tan = forms.CharField(label='TAN of collector', max_length=10, required=False, validators=[TAN_VALIDATOR])
    collector_name = forms.CharField(label='Name of collector', max_length=120, required=False)
    tax_collected = forms.IntegerField(label='Tax collected', min_value=0, required=False, initial=0)
    collected_year = forms.CharField(label='Year of tax collection', max_length=4, required=False)
    tcs_claimed_this_year = forms.IntegerField(label='TCS credit claimed this year', min_value=0, required=False, initial=0)

    def clean_tan(self):
        return self.cleaned_data['tan'].strip().upper()

    def clean(self):
        cleaned = super().clean()
        # A-96
        if (cleaned.get('tcs_claimed_this_year') or 0) > (cleaned.get('tax_collected') or 0):
            self.add_error('tcs_claimed_this_year', 'TCS claimed cannot exceed tax collected (rule A-96).')
        return cleaned


TcsFormSet = forms.formset_factory(TcsRowForm, extra=1, can_delete=True)


class ChallanRowForm(forms.Form):
    bsr_code = forms.CharField(label='BSR code', max_length=7, required=False, validators=[BSR_CODE_VALIDATOR])
    date_of_deposit = forms.DateField(label='Date of deposit', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    challan_serial_no = forms.CharField(label='Challan serial number', max_length=5, required=False, validators=[CHALLAN_SERIAL_VALIDATOR])
    amount = forms.IntegerField(label='Amount', min_value=0, required=False, initial=0)


ChallanFormSet = forms.formset_factory(ChallanRowForm, extra=1, can_delete=True)


# ---------------------------------------------------------------------------
# Screen 5 — Tax Liability
# ---------------------------------------------------------------------------
#
# Almost the entire screen is computed (D1-D5, D9, D10a); the only genuine
# user inputs are relief u/s 89 (D6, plus the Form 10E filing flag/ack no.)
# and the D7/D8/D10 overrides — each of which defaults to the engine's
# computed value when left blank. `required=False` on the override fields
# means an empty submission cleans to `None`, matching model_blank.py's
# `interest234AOverride`/`interest234BOverride`/`fee234FOverride` default of
# `None` (as opposed to 0, which would incorrectly pin the override to nil).

class TaxLiabilityForm(forms.Form):
    relief89 = forms.IntegerField(label='Relief u/s 89', min_value=0, required=False, initial=0)
    form10EFiled = forms.BooleanField(label='Form 10E filed', required=False)
    form10EAckNo = forms.CharField(label='Form 10E acknowledgement no.', max_length=30, required=False)
    interest234AOverride = forms.IntegerField(
        label='Interest u/s 234A override', min_value=0, required=False,
    )
    interest234BOverride = forms.IntegerField(
        label='Interest u/s 234B override', min_value=0, required=False,
    )
    fee234FOverride = forms.IntegerField(
        label='Fee u/s 234F override', min_value=0, required=False,
    )


class VerificationForm(forms.Form):
    """The e-filing portal's mandatory declaration -- schema `Verification.Declaration`
    (§11.2). Not a numbered screen in §3.1, but the JSON cannot be generated
    without it, so it lives on the Validation & JSON screen as the final step."""
    assessee_ver_name = forms.CharField(label='Name of person verifying', max_length=127)
    father_name = forms.CharField(label="Father's name", max_length=125)
    assessee_ver_pan = forms.CharField(label='PAN of person verifying', max_length=10)
    capacity = forms.ChoiceField(label='Capacity', choices=CAPACITY_CHOICES, initial='S')
    place = forms.CharField(label='Place', max_length=50)
