"""End-to-end web write-path coverage for the Phase 3 service-layer
extraction. tests/test_access_control.py is GET-only, and the golden tests
bypass itr/views.py entirely (they call compute()/validate() directly on a
hand-built model) -- neither exercises a single POST through the forms ->
service -> render path this refactor rewrote. This file is that coverage:
create -> filing_section -> personal_info -> gross_total_income ->
total_deductions -> tax_paid -> tax_liability -> tax_summary -> validation,
using django.test.Client (the real HTTP path), plus every non-happy-path
this rewrite specifically had to get right: a stale-version conflict, a
confirm that fails validation and must re-render fresh (not stale) data
without a second explicit re-fetch, the AJAX autosave response shape, and
every PDF/JSON export action now routed through the service layer.
"""

import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from itr.models import AuditLogEntry, TaxReturn
from tests.itr.test_golden import golden_model

User = get_user_model()


def _version(html):
    return re.search(r'name="_version" value="(\d+)"', html).group(1)


class FullReturnLifecycleTests(TestCase):
    """One return, walked start to finish through the real HTTP forms."""

    def setUp(self):
        self.user = User.objects.create_user(username='lifecycle1', email='lifecycle1@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_create_through_filing_section_and_personal_info(self):
        r = self.client.post('/returns/new/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/filing-section/', r['Location'])
        return_id = r['Location'].split('/')[2]
        tr = TaxReturn.objects.get(pk=return_id)

        r = self.client.post(f'/returns/{return_id}/filing-section/', {
            'return_file_sec': '11', 'opt_out_of_new_regime': 'Y',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/personal-info/'))
        tr.refresh_from_db()
        self.assertEqual(tr.data['filingStatus']['optOutOfNewRegime'], 'Y')
        self.assertEqual(tr.version, 2)

        r = self.client.get(f'/returns/{return_id}/personal-info/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('regime comparison', body)
        version = _version(body)
        self.assertEqual(version, '2')

        data = self._personal_info_post_data(version, action='save')
        r = self.client.post(f'/returns/{return_id}/personal-info/', data)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/personal-info/'))
        tr.refresh_from_db()
        self.assertEqual(tr.data['bankAccounts'], [{
            'id': 'bank-1', 'ifsc': 'HDFC0000123', 'bankName': 'HDFC BANK',
            'accountNumber': '123456', 'accountType': 'SB', 'nominateForRefund': True,
        }])
        self.assertEqual(tr.data['personalInfo']['firstName'], 'Test')
        self.assertEqual(tr.version, 3)
        self.assertEqual(tr.data['screenStatus']['PERSONAL_INFO'], 'IN_PROGRESS')

        data = self._personal_info_post_data('3', action='confirm')
        r = self.client.post(f'/returns/{return_id}/personal-info/', data)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/gross-total-income/'))
        tr.refresh_from_db()
        self.assertEqual(tr.data['screenStatus']['PERSONAL_INFO'], 'CONFIRMED')
        self.assertEqual(tr.version, 4)

    def test_stale_version_reports_conflict_without_saving(self):
        return_id = self._new_return()
        r = self.client.get(f'/returns/{return_id}/personal-info/')
        version = _version(r.content.decode())

        data = self._personal_info_post_data(version, action='save')
        self.client.post(f'/returns/{return_id}/personal-info/', data)  # bumps version once

        stale_data = self._personal_info_post_data(version, action='save', first_name='ShouldNotSave')
        r = self.client.post(f'/returns/{return_id}/personal-info/', stale_data)
        self.assertEqual(r.status_code, 200)  # re-render, not a redirect
        self.assertIn('edited by', r.content.decode())

        tr = TaxReturn.objects.get(pk=return_id)
        self.assertNotEqual(tr.data['personalInfo']['firstName'], 'ShouldNotSave')

    def test_confirm_with_validation_errors_rerenders_fresh_data_without_refetch(self):
        # No bank account -> the §4.6 structural check fails, confirm_screen
        # returns confirmed=False, and the view must render the JUST-SAVED
        # personal info (not stale/blank) using only what the service
        # returned -- this is the exact case _sync_tax_return replaces
        # refresh_from_db() for.
        return_id = self._new_return()
        r = self.client.get(f'/returns/{return_id}/personal-info/')
        version = _version(r.content.decode())
        data = self._personal_info_post_data(version, action='confirm')
        data['bank-TOTAL_FORMS'] = '0'

        r = self.client.post(f'/returns/{return_id}/personal-info/', data)
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('At least one bank account is mandatory', body)
        self.assertIn('Test', body)  # the just-submitted name, not "Unnamed taxpayer"

        tr = TaxReturn.objects.get(pk=return_id)
        self.assertEqual(tr.data['screenStatus']['PERSONAL_INFO'], 'HAS_ERRORS')
        self.assertEqual(tr.data['personalInfo']['firstName'], 'Test')  # was still saved

    def test_gross_total_income_confirm_advances_to_total_deductions(self):
        return_id = self._confirmed_personal_info_return()
        r = self.client.get(f'/returns/{return_id}/gross-total-income/')
        version = _version(r.content.decode())
        gti_data = {
            '_version': version, 'action': 'confirm',
            'salary17_1': '900000', 'perquisites17_2': '0', 'profits_in_lieu17_3': '0',
            'entertainment_allowance_16ii': '0', 'professional_tax_16iii': '0',
            'place_of_work': '1', 'actual_hra_received': '180000', 'actual_rent_paid': '200000',
            'basic_salary': '400000', 'dearness_allowance': '0',
            'allow-TOTAL_FORMS': '0', 'allow-INITIAL_FORMS': '0', 'allow-MIN_NUM_FORMS': '0', 'allow-MAX_NUM_FORMS': '1000',
            'hp-TOTAL_FORMS': '0', 'hp-INITIAL_FORMS': '0', 'hp-MIN_NUM_FORMS': '0', 'hp-MAX_NUM_FORMS': '1000',
            'os-TOTAL_FORMS': '1', 'os-INITIAL_FORMS': '0', 'os-MIN_NUM_FORMS': '0', 'os-MAX_NUM_FORMS': '1000',
            'os-0-nature': 'SAV', 'os-0-amount': '12000',
            'ei-TOTAL_FORMS': '0', 'ei-INITIAL_FORMS': '0', 'ei-MIN_NUM_FORMS': '0', 'ei-MAX_NUM_FORMS': '1000',
        }
        r = self.client.post(f'/returns/{return_id}/gross-total-income/', gti_data)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/total-deductions/'))

        tr = TaxReturn.objects.get(pk=return_id)
        self.assertEqual(tr.data['income']['salary17_1'], 900000)
        self.assertEqual(tr.data['income']['hra10_13A']['actualHraReceived'], 180000)
        self.assertEqual(len(tr.data['income']['otherSources']), 1)

    def test_total_deductions_save_derives_schedule_totals_through_full_stack(self):
        return_id = self._confirmed_personal_info_return()
        r = self.client.get(f'/returns/{return_id}/total-deductions/')
        version = _version(r.content.decode())
        dd_data = self._blank_deductions_post_data(version, action='save')
        dd_data.update({
            's80c-TOTAL_FORMS': '2', 's80c-INITIAL_FORMS': '0',
            's80c-0-identification_no': 'PPF123', 's80c-0-amount': '50000',
            's80c-1-identification_no': 'LIC456', 's80c-1-amount': '30000',
        })
        r = self.client.post(f'/returns/{return_id}/total-deductions/', dd_data)
        self.assertEqual(r.status_code, 302)

        tr = TaxReturn.objects.get(pk=return_id)
        self.assertEqual(tr.data['deductions']['s80C'], 80000)

    def test_ajax_autosave_returns_json_not_redirect(self):
        return_id = self._confirmed_personal_info_return()
        r = self.client.get(f'/returns/{return_id}/total-deductions/')
        version = _version(r.content.decode())
        dd_data = self._blank_deductions_post_data(version, action='save')
        r = self.client.post(
            f'/returns/{return_id}/total-deductions/', dd_data, HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        payload = json.loads(r.content)
        self.assertTrue(payload['saved'])
        self.assertIn('version', payload)
        self.assertIn('savedAt', payload)

    def test_tax_paid_and_tax_liability_save(self):
        return_id = self._confirmed_personal_info_return()

        r = self.client.get(f'/returns/{return_id}/tax-paid/')
        version = _version(r.content.decode())
        tp_data = {'_version': version, 'action': 'save'}
        for prefix in ('tds1', 'tds2', 'tds3', 'tcs', 'challan'):
            tp_data[f'{prefix}-TOTAL_FORMS'] = '0'
            tp_data[f'{prefix}-INITIAL_FORMS'] = '0'
            tp_data[f'{prefix}-MIN_NUM_FORMS'] = '0'
            tp_data[f'{prefix}-MAX_NUM_FORMS'] = '1000'
        r = self.client.post(f'/returns/{return_id}/tax-paid/', tp_data)
        self.assertEqual(r.status_code, 302)

        r = self.client.get(f'/returns/{return_id}/tax-liability/')
        version = _version(r.content.decode())
        r = self.client.post(f'/returns/{return_id}/tax-liability/', {
            '_version': version, 'action': 'save', 'relief89': '0', 'form10EAckNo': '',
        })
        self.assertEqual(r.status_code, 302)

    # -- helpers ------------------------------------------------------------

    def _new_return(self):
        r = self.client.post('/returns/new/')
        return_id = r['Location'].split('/')[2]
        self.client.post(f'/returns/{return_id}/filing-section/', {
            'return_file_sec': '11', 'opt_out_of_new_regime': 'Y',
        })
        return return_id

    def _confirmed_personal_info_return(self):
        return_id = self._new_return()
        r = self.client.get(f'/returns/{return_id}/personal-info/')
        version = _version(r.content.decode())
        self.client.post(
            f'/returns/{return_id}/personal-info/', self._personal_info_post_data(version, action='confirm'),
        )
        return return_id

    def _personal_info_post_data(self, version, action, first_name='Test'):
        return {
            '_version': version, 'action': action,
            'first_name': first_name, 'last_name': 'User', 'pan': 'ABCDE1234F', 'dob': '1990-01-01',
            'aadhaar': '', 'employer_category': 'OTH',
            'primary_mobile': '9999999999', 'secondary_mobile': '', 'primary_email': 'test@example.com', 'secondary_email': '',
            'flat_door_building': 'X', 'premise_building_name': '', 'road_street': '', 'area_locality': 'Y',
            'town_city_district': 'Z', 'state_code': '05', 'pin_code': '800001',
            'secondary_address_same_as_primary': 'Y',
            'orig_return_ack_no': '', 'orig_return_filed_date': '', 'orig_return_file_sec': '',
            'a23_responses_original': '', 'a23_responses_current': '',
            'seventh_proviso_139': 'N', 'travel_expense_above_2lakh': 'N', 'travel_expense_amount': '',
            'electricity_above_1lakh': 'N', 'electricity_amount': '', 'clause_iv_applies': 'N',
            'representative_assessee_flag': 'N', 'verification_capacity': 'S',
            'bank-TOTAL_FORMS': '1', 'bank-INITIAL_FORMS': '0', 'bank-MIN_NUM_FORMS': '0', 'bank-MAX_NUM_FORMS': '1000',
            'bank-0-ifsc': 'HDFC0000123', 'bank-0-bank_name': 'HDFC BANK', 'bank-0-account_number': '123456',
            'bank-0-account_type': 'SB', 'bank-0-nominate_for_refund': 'on',
        }

    def _blank_deductions_post_data(self, version, action):
        data = {
            '_version': version, 'action': action,
            's80CCD1': '0', 'pran_numbers': '', 's80CCD1B': '0', 's80CCD2': '0', 's80CCH': '0',
            's80D': '0', 's80DDB': '0', 's80DDBUsrType': '', 's80DDBDisease': '',
            'stampDutyValue80EEA': '0', 's80G': '0', 's80GG': '0', 'form10BAAckNo': '', 's80GGA': '0', 's80GGC': '0',
            's80TTA': '0', 's80TTB': '0',
            'self_family_senior_flag': 'N', 'parents_senior_flag': 'N',
            'self_family_health_insurance_premium': '0', 'self_family_preventive_health_checkup': '0', 'self_family_medical_expenditure': '0',
            'self_family_senior_health_insurance_premium': '0', 'self_family_senior_preventive_health_checkup': '0', 'self_family_senior_medical_expenditure': '0',
            'parents_health_insurance_premium': '0', 'parents_preventive_health_checkup': '0', 'parents_medical_expenditure': '0',
            'parents_senior_health_insurance_premium': '0', 'parents_senior_preventive_health_checkup': '0', 'parents_senior_medical_expenditure': '0',
            'dd-nature_of_disability': '', 'dd-type_of_disability': '', 'dd-amount': '0',
            'u-nature_of_disability': '', 'u-type_of_disability': '', 'u-amount': '0',
        }
        for prefix in ('s80c', 's80ccc', 's80e', 's80ee', 's80eea', 's80eeb', 's80g', 's80gga', 's80ggc'):
            data[f'{prefix}-TOTAL_FORMS'] = '0'
            data[f'{prefix}-INITIAL_FORMS'] = '0'
            data[f'{prefix}-MIN_NUM_FORMS'] = '0'
            data[f'{prefix}-MAX_NUM_FORMS'] = '1000'
        return data


class ValidationScreenActionsTests(TestCase):
    """The golden model, walked through every Validation-screen action."""

    def setUp(self):
        self.user = User.objects.create_user(username='lifecycle2', email='lifecycle2@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')
        self.tr = TaxReturn.objects.create(owner=self.user)
        self.tr.data = golden_model()
        self.tr.data['tenantId'] = str(self.user.pk)
        self.tr.data['returnId'] = str(self.tr.pk)
        self.tr.save()

    def test_validation_get_renders_successful_report(self):
        r = self.client.get(f'/returns/{self.tr.pk}/validation/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Validation successful', r.content.decode())

    def test_save_verification_persists_and_uppercases_pan(self):
        r = self.client.post(f'/returns/{self.tr.pk}/validation/', {
            'action': 'save_verification',
            'assessee_ver_name': 'NEW NAME', 'father_name': 'NEW FATHER',
            'assessee_ver_pan': 'aaapz1234c', 'capacity': 'S', 'place': 'MUMBAI',
        })
        self.assertEqual(r.status_code, 302)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['verification']['assesseeVerName'], 'NEW NAME')
        self.assertEqual(self.tr.data['verification']['assesseeVerPan'], 'AAAPZ1234C')
        self.assertTrue(AuditLogEntry.objects.filter(tax_return=self.tr, kind=AuditLogEntry.KIND_FIELD_CHANGE).exists())

    def test_download_returns_json_attachment_and_logs_audit(self):
        r = self.client.post(f'/returns/{self.tr.pk}/validation/', {'action': 'download'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertTrue(AuditLogEntry.objects.filter(tax_return=self.tr, kind=AuditLogEntry.KIND_JSON_GENERATION).exists())

    def test_preview_returns_pdf_via_service(self):
        r = self.client.post(f'/returns/{self.tr.pk}/validation/', {'action': 'preview'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_export_report_returns_pdf_via_service(self):
        r = self.client.post(f'/returns/{self.tr.pk}/validation/', {'action': 'export_report'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_acknowledge_action_redirects(self):
        r = self.client.post(f'/returns/{self.tr.pk}/validation/', {'action': 'acknowledge'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/validation/'))

    def test_tax_summary_export_pdf_via_service(self):
        r = self.client.post(f'/returns/{self.tr.pk}/tax-summary/', {'action': 'export_pdf'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_tax_summary_proceed_confirms_and_redirects(self):
        r = self.client.post(f'/returns/{self.tr.pk}/tax-summary/', {'action': 'proceed'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].endswith('/validation/'))
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['TAX_SUMMARY'], 'CONFIRMED')


class CrossOwnerAccessTests(TestCase):
    """The 404 gate that has to run before any service call -- a service
    function raising TaxReturn.DoesNotExist is NOT auto-converted to a 404
    response the way get_object_or_404 is, so every view's early ownership
    check earns its own test."""

    def setUp(self):
        self.owner = User.objects.create_user(username='owner1', email='owner1@example.com', password='x')
        self.other = User.objects.create_user(username='other1', email='other1@example.com', password='x')
        self.tr = TaxReturn.objects.create(owner=self.owner)
        self.client.force_login(self.other, backend='accounts.backends.EmailBackend')

    def test_every_screen_404s_for_non_owner(self):
        for path in (
            'personal-info', 'gross-total-income', 'total-deductions',
            'tax-paid', 'tax-liability', 'tax-summary', 'validation', 'filing-section',
        ):
            r = self.client.get(f'/returns/{self.tr.pk}/{path}/')
            self.assertEqual(r.status_code, 404, path)

    def test_tax_summary_proceed_404s_for_non_owner(self):
        r = self.client.post(f'/returns/{self.tr.pk}/tax-summary/', {'action': 'proceed'})
        self.assertEqual(r.status_code, 404)
