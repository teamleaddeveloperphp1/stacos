"""ITR REST API (Phase 4) -- /api/v1/itr/. Per endpoint: success, an
unauthenticated request, and a cross-owner request against DEBUG=False so
a TaxReturn.DoesNotExist-turned-500 (the exact gap the exception handler
was added to close) can't quietly come back."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from itr.models import AuditLogEntry, TaxReturn
from tests.itr.test_golden import golden_model

User = get_user_model()


def _golden_return(owner):
    tr = TaxReturn.objects.create(owner=owner)
    tr.data = golden_model()
    tr.data['tenantId'] = str(owner.pk)
    tr.data['returnId'] = str(tr.pk)
    tr.save()
    return tr


def _personal_info_body(version=None, **overrides):
    body = {
        'personal_info': {
            'first_name': 'API', 'middle_name': '', 'last_name': 'Test', 'pan': 'ABCDE1234F',
            'dob': '1990-06-15', 'aadhaar': '', 'employer_category': 'OTH',
            'primary_mobile': '9999999999', 'secondary_mobile': '', 'primary_email': 'a@example.com', 'secondary_email': '',
            'flat_door_building': 'X', 'premise_building_name': '', 'road_street': '', 'area_locality': 'Y',
            'town_city_district': 'Z', 'state_code': '05', 'pin_code': '800001',
            'secondary_address_same_as_primary': 'Y',
            'orig_return_ack_no': '', 'orig_return_filed_date': None, 'orig_return_file_sec': None,
            'a23_responses_original': '', 'a23_responses_current': '',
            'seventh_proviso_139': 'N', 'travel_expense_above_2lakh': 'N', 'travel_expense_amount': None,
            'electricity_above_1lakh': 'N', 'electricity_amount': None, 'clause_iv_applies': 'N',
            'representative_assessee_flag': 'N', 'verification_capacity': 'S',
        },
        'bank_accounts': [{
            'ifsc': 'HDFC0000123', 'bank_name': 'HDFC BANK', 'account_number': '123456',
            'account_type': 'SB', 'nominate_for_refund': True,
        }],
    }
    body['personal_info'].update(overrides)
    if version is not None:
        body['version'] = version
    return body


def _blank_deductions_body(version=None):
    body = {
        'deductions': {
            's80CCD1': 0, 'pran_numbers': '', 's80CCD1B': 0, 's80CCD2': 0, 's80CCH': 0,
            's80D': 0, 's80DDB': 0, 's80DDBUsrType': '', 's80DDBDisease': '',
            'stampDutyValue80EEA': 0, 's80G': 0, 's80GG': 0, 'form10BAFiled': False, 'form10BAAckNo': '',
            's80GGA': 0, 's80GGC': 0, 's80TTA': 0, 's80TTB': 0,
        },
        'schedule_80c': [
            {'identification_no': 'PPF1', 'amount': 50000},
            {'identification_no': 'LIC1', 'amount': 30000},
        ],
        'schedule_80ccc': [],
        'schedule_80d': {
            'self_family_senior_flag': 'N', 'parents_senior_flag': 'N',
            'self_family_health_insurance_premium': 0, 'self_family_preventive_health_checkup': 0, 'self_family_medical_expenditure': 0,
            'self_family_senior_health_insurance_premium': 0, 'self_family_senior_preventive_health_checkup': 0, 'self_family_senior_medical_expenditure': 0,
            'parents_health_insurance_premium': 0, 'parents_preventive_health_checkup': 0, 'parents_medical_expenditure': 0,
            'parents_senior_health_insurance_premium': 0, 'parents_senior_preventive_health_checkup': 0, 'parents_senior_medical_expenditure': 0,
        },
        'disability_80dd': {'nature_of_disability': '', 'type_of_disability': '', 'amount': 0},
        'disability_80u': {'nature_of_disability': '', 'type_of_disability': '', 'amount': 0},
        'schedule_80e': [], 'schedule_80ee': [], 'schedule_80eea': [], 'schedule_80eeb': [],
        'schedule_80g': [], 'schedule_80gga': [], 'schedule_80ggc': [],
    }
    if version is not None:
        body['version'] = version
    return body


_NARRATIVE_TEXT_KEYS = {'reason', 'capreason'}


def _leaf_number_leaks(obj, path=''):
    """Every string leaf containing a ₹ sign or a comma-grouped numeral,
    EXCLUDING any path under a `trace`/`Trace` key or a narrative-text key
    (`reason`/`capReason`). Both exclusions are stated, scoped exceptions
    (see itr/api/v1/serializers.py's docstring): itr/engine/compute.py's
    TraceBuilder bakes formatted currency into human-readable narration
    ("₹400,000 to ₹800,000 @ 5%"), and every Chapter VI-A section's `put()`
    helper (compute.py:563) does the same into `bySection.<code>.capReason`
    ("14% of salary u/s 17(1) (A-216) = ₹46200"). Rewriting either is
    off-limits this phase (ground rule 2). Every actual amount FIELD --
    including each trace line's own `amount` key -- is still asserted a
    plain int elsewhere in this file; this walk only excludes the prose."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if 'trace' in str(k).lower() or str(k).lower() in _NARRATIVE_TEXT_KEYS:
                continue
            bad.extend(_leaf_number_leaks(v, f'{path}.{k}'))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_leaf_number_leaks(v, f'{path}[{i}]'))
    elif isinstance(obj, str):
        if '₹' in obj or (',' in obj and obj.replace(',', '').replace('.', '').replace('-', '').isdigit()):
            bad.append((path, obj))
    return bad


@override_settings(DEBUG=False)
class ReturnsListAndDetailTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api1', email='api1@example.com', password='x')
        self.other = User.objects.create_user(username='api2', email='api2@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')

    def test_list_is_owner_scoped(self):
        mine = TaxReturn.objects.create(owner=self.owner)
        TaxReturn.objects.create(owner=self.other)
        r = self.client.get('/api/v1/itr/returns/')
        self.assertEqual(r.status_code, 200)
        ids = [row['id'] for row in r.json()['results']]
        self.assertEqual(ids, [str(mine.pk)])

    def test_create_returns_201(self):
        r = self.client.post('/api/v1/itr/returns/')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(TaxReturn.objects.filter(pk=r.json()['id'], owner=self.owner).exists())

    def test_detail_matches_get_return_service(self):
        tr = _golden_return(self.owner)
        r = self.client.get(f'/api/v1/itr/returns/{tr.pk}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['model']['personalInfo']['pan'], 'AHKPT5171E')
        self.assertIn('computed', body)

    def test_detail_404s_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.get(f'/api/v1/itr/returns/{tr.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_list_401_or_403_when_unauthenticated(self):
        self.client.logout()
        r = self.client.get('/api/v1/itr/returns/')
        self.assertIn(r.status_code, (401, 403))


@override_settings(DEBUG=False)
class FilingSectionApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api3', email='api3@example.com', password='x')
        self.other = User.objects.create_user(username='api4', email='api4@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')

    def test_put_sets_filing_section_and_regime(self):
        tr = TaxReturn.objects.create(owner=self.owner)
        r = self.client.put(
            f'/api/v1/itr/returns/{tr.pk}/filing-section/',
            data=json.dumps({'return_file_sec': 11, 'opt_out_of_new_regime': 'Y'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        tr.refresh_from_db()
        self.assertEqual(tr.data['filingStatus']['optOutOfNewRegime'], 'Y')
        self.assertEqual(tr.version, 2)

    def test_404_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.put(
            f'/api/v1/itr/returns/{tr.pk}/filing-section/',
            data=json.dumps({'return_file_sec': 11, 'opt_out_of_new_regime': 'N'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 404)

    def test_401_or_403_unauthenticated(self):
        tr = TaxReturn.objects.create(owner=self.owner)
        self.client.logout()
        r = self.client.put(f'/api/v1/itr/returns/{tr.pk}/filing-section/', data=json.dumps({}), content_type='application/json')
        self.assertIn(r.status_code, (401, 403))


@override_settings(DEBUG=False)
class ScreenApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api5', email='api5@example.com', password='x')
        self.other = User.objects.create_user(username='api6', email='api6@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        self.tr = TaxReturn.objects.create(owner=self.owner)

    def _put(self, screen, body):
        return self.client.put(
            f'/api/v1/itr/returns/{self.tr.pk}/screens/{screen}/', data=json.dumps(body), content_type='application/json',
        )

    def test_get_screen_returns_get_return_shape(self):
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/screens/personal-info/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('model', r.json())

    def test_unknown_screen_404s(self):
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/screens/not-a-screen/')
        self.assertEqual(r.status_code, 404)

    def test_put_personal_info_with_date_as_json_string_is_coerced_and_saved(self):
        # The exact case the plan called out: a JSON client sends dates as
        # strings, not python date objects -- this must not 500.
        r = self._put('personal-info', _personal_info_body(version=1))
        self.assertEqual(r.status_code, 200, r.content)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['personalInfo']['dob'], '1990-06-15')
        self.assertEqual(self.tr.data['personalInfo']['firstName'], 'API')
        self.assertNotIn('ifscVerified', self.tr.data['bankAccounts'][0])

    def test_put_with_invalid_row_returns_400_with_field_errors(self):
        body = _personal_info_body(version=1)
        body['personal_info']['pan'] = ''  # required field left blank
        r = self._put('personal-info', body)
        self.assertEqual(r.status_code, 400)
        self.assertIn('pan', r.json()['errors']['personal_info'])

    def test_stale_version_returns_409_with_message_and_current_version(self):
        self._put('personal-info', _personal_info_body(version=1))  # bumps to version 2
        r = self._put('personal-info', _personal_info_body(version=1, first_name='ShouldNotLand'))
        self.assertEqual(r.status_code, 409)
        body = r.json()
        self.assertIn('edited by', body['detail'])
        self.assertEqual(body['version'], 2)
        self.tr.refresh_from_db()
        self.assertNotEqual(self.tr.data['personalInfo']['firstName'], 'ShouldNotLand')

    def test_confirm_personal_info_without_bank_account_reports_not_confirmed(self):
        body = _personal_info_body(version=1)
        body['bank_accounts'] = []
        r = self.client.post(
            f'/api/v1/itr/returns/{self.tr.pk}/screens/personal-info/confirm/',
            data=json.dumps(body), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertFalse(result['confirmed'])
        self.assertTrue(result['bank_errors'])

    def test_confirm_personal_info_success(self):
        r = self.client.post(
            f'/api/v1/itr/returns/{self.tr.pk}/screens/personal-info/confirm/',
            data=json.dumps(_personal_info_body(version=1)), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['confirmed'])
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['PERSONAL_INFO'], 'CONFIRMED')

    def test_total_deductions_derives_schedule_totals_through_api(self):
        r = self._put('total-deductions', _blank_deductions_body(version=1))
        self.assertEqual(r.status_code, 200, r.content)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['deductions']['s80C'], 80000)

    def test_404_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.get(f'/api/v1/itr/returns/{tr.pk}/screens/personal-info/')
        self.assertEqual(r.status_code, 404)

    def test_401_or_403_unauthenticated(self):
        self.client.logout()
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/screens/personal-info/')
        self.assertIn(r.status_code, (401, 403))


@override_settings(DEBUG=False)
class VerificationAndTaxSummaryApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api7', email='api7@example.com', password='x')
        self.other = User.objects.create_user(username='api8', email='api8@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        self.tr = _golden_return(self.owner)

    def test_save_verification_uppercases_pan_and_logs_audit(self):
        r = self.client.post(
            f'/api/v1/itr/returns/{self.tr.pk}/verification/',
            data=json.dumps({
                'assessee_ver_name': 'NEW NAME', 'father_name': 'FATHER',
                'assessee_ver_pan': 'aaapz1234c', 'capacity': 'S', 'place': 'DELHI',
            }),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['verification']['assesseeVerPan'], 'AAAPZ1234C')
        self.assertTrue(AuditLogEntry.objects.filter(tax_return=self.tr, kind=AuditLogEntry.KIND_FIELD_CHANGE).exists())

    def test_confirm_tax_summary(self):
        r = self.client.post(f'/api/v1/itr/returns/{self.tr.pk}/tax-summary/confirm/')
        self.assertEqual(r.status_code, 200)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['TAX_SUMMARY'], 'CONFIRMED')

    def test_verification_404_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.post(f'/api/v1/itr/returns/{tr.pk}/verification/', data=json.dumps({}), content_type='application/json')
        self.assertEqual(r.status_code, 404)


@override_settings(DEBUG=False)
class ComputationValidateGenerateImportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api9', email='api9@example.com', password='x')
        self.other = User.objects.create_user(username='api10', email='api10@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        self.tr = _golden_return(self.owner)

    def test_computation_matches_web_template_view(self):
        # The parity test: the API and the template view must be reading
        # the same figures, because both call compute() through the same
        # itr.services.return_service.get_computation -- there is only one
        # compute() call site left anywhere (see itr/views.py).
        api_computed = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/computation/').json()

        from itr.services import return_service
        service_computed = return_service.get_computation(self.tr.pk, self.owner)
        self.assertEqual(api_computed, service_computed)

        web_response = self.client.get(f'/returns/{self.tr.pk}/tax-liability/')
        self.assertEqual(web_response.status_code, 200)
        self.assertEqual(web_response.context['computed']['grossTotalIncome'], api_computed['grossTotalIncome'])
        self.assertEqual(web_response.context['computed']['totalTaxFeeAndInterest'], api_computed['totalTaxFeeAndInterest'])

    def test_computation_money_shape_every_field_is_a_plain_number(self):
        body = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/computation/').json()
        leaks = _leaf_number_leaks(body)
        self.assertEqual(leaks, [])

    def test_computation_404_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.get(f'/api/v1/itr/returns/{tr.pk}/computation/')
        self.assertEqual(r.status_code, 404)

    def test_computation_401_or_403_unauthenticated(self):
        self.client.logout()
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/computation/')
        self.assertIn(r.status_code, (401, 403))

    def test_validate_ok_for_golden_return(self):
        r = self.client.post(f'/api/v1/itr/returns/{self.tr.pk}/validate/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertTrue(r.json()['downloadable'])

    def test_validate_on_blank_return_has_errors_with_both_deeplink_and_goto_url(self):
        blank = TaxReturn.objects.create(owner=self.owner)
        r = self.client.post(f'/api/v1/itr/returns/{blank.pk}/validate/')
        self.assertEqual(r.status_code, 200)
        errors = r.json()['errors']
        self.assertTrue(errors)
        with_links = [e for e in errors if e['deepLink']]
        self.assertTrue(with_links)
        for e in with_links:
            self.assertTrue(e['goto_url'])
            self.assertIn(str(blank.pk), e['goto_url'])
            self.assertIn('#', e['deepLink'])
            self.assertNotIn('/returns/', e['deepLink'])  # bare token, not a path

    def test_generate_json_returns_payload_in_body_not_a_download(self):
        r = self.client.post(f'/api/v1/itr/returns/{self.tr.pk}/generate-json/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('Content-Disposition', r)
        body = r.json()
        self.assertIn('payload', body)
        self.assertEqual(body['payload']['ITR']['ITR1']['PersonalInfo']['AssesseeName']['SurNameOrOrgName'], 'THAKUR')

    def test_generate_json_download_variant_sets_content_disposition(self):
        r = self.client.post(f'/api/v1/itr/returns/{self.tr.pk}/generate-json/?download=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])

    def test_generate_json_422_when_blocked(self):
        blank = TaxReturn.objects.create(owner=self.owner)
        r = self.client.post(f'/api/v1/itr/returns/{blank.pk}/generate-json/')
        self.assertEqual(r.status_code, 422)
        self.assertIn('errors', r.json())

    def test_import_json_round_trips_and_derives_totals(self):
        generated = self.client.post(f'/api/v1/itr/returns/{self.tr.pk}/generate-json/').json()['payload']
        target = TaxReturn.objects.create(owner=self.owner)
        r = self.client.post(
            f'/api/v1/itr/returns/{target.pk}/import-json/', data=json.dumps(generated), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.data['personalInfo']['pan'], 'AHKPT5171E')

    def test_acknowledge_advisories_persists(self):
        r = self.client.post(
            f'/api/v1/itr/returns/{self.tr.pk}/advisories/acknowledge/',
            data=json.dumps({'rule_ids': ['B-1']}), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.tr.refresh_from_db()
        self.assertIn('B-1', self.tr.data['advisoryAcknowledgements'])

    def test_regime_comparison_returns_raw_integers(self):
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/regime-comparison/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body['NEW'], int)
        self.assertIsInstance(body['OLD'], int)


@override_settings(DEBUG=False)
class DocumentApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='api11', email='api11@example.com', password='x')
        self.other = User.objects.create_user(username='api12', email='api12@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        self.tr = _golden_return(self.owner)

    def test_each_document_kind_returns_pdf(self):
        for kind in ('validation-report', 'computation-sheet', 'preview'):
            r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/documents/{kind}/')
            self.assertEqual(r.status_code, 200, kind)
            self.assertEqual(r['Content-Type'], 'application/pdf', kind)

    def test_unknown_kind_404s(self):
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/documents/not-a-kind/')
        self.assertEqual(r.status_code, 404)

    def test_404_for_non_owner(self):
        tr = TaxReturn.objects.create(owner=self.other)
        r = self.client.get(f'/api/v1/itr/returns/{tr.pk}/documents/preview/')
        self.assertEqual(r.status_code, 404)

    def test_401_or_403_unauthenticated(self):
        self.client.logout()
        r = self.client.get(f'/api/v1/itr/returns/{self.tr.pk}/documents/preview/')
        self.assertIn(r.status_code, (401, 403))
