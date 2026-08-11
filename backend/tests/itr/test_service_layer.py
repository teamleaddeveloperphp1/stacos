"""Phase 3: every itr.services.return_service function, called from plain
Python -- no django.test.Client, no RequestFactory, no HttpRequest anywhere
in this file. If a service function needs the framework to work, that's a
bug in the extraction, not a missing test fixture.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from itr.engine.compute import compute
from itr.models import AuditLogEntry, TaxReturn
from itr.serialize.generate import GenerationBlockedError
from itr.services import return_service
from itr.services.return_service import VersionConflictError
from tests.itr.test_golden import golden_model
from tests.itr.test_golden_old_regime import old_regime_golden_model

User = get_user_model()


def _make_return(owner, model=None):
    tr = TaxReturn.objects.create(owner=owner)
    if model is not None:
        tr.data = model
        tr.data['tenantId'] = str(owner.pk)
        tr.data['returnId'] = str(tr.pk)
        tr.save()
    return tr


class GetReturnTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc1', email='svc1@example.com', password='x')
        self.other = User.objects.create_user(username='svc2', email='svc2@example.com', password='x')
        self.tr = _make_return(self.owner, golden_model())

    def test_returns_model_computed_and_screen_status(self):
        result = return_service.get_return(self.tr.pk, self.owner)
        self.assertEqual(result['id'], str(self.tr.pk))
        self.assertEqual(result['version'], self.tr.version)
        self.assertEqual(result['model']['personalInfo']['pan'], 'AHKPT5171E')
        self.assertEqual(result['computed']['grossTotalIncome'], compute(self.tr.data)['grossTotalIncome'])
        self.assertIn('screenStatus', {'screenStatus': result['screen_status']})

    def test_not_owner_raises_does_not_exist(self):
        with self.assertRaises(TaxReturn.DoesNotExist):
            return_service.get_return(self.tr.pk, self.other)


class SaveScreenTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc3', email='svc3@example.com', password='x')
        self.tr = TaxReturn.objects.create(owner=self.owner)

    def _personal_info_payload(self, **overrides):
        payload = {
            'personal_info': {
                'first_name': 'A', 'middle_name': '', 'last_name': 'B', 'pan': 'ABCDE1234F',
                'dob': None, 'aadhaar': '', 'employer_category': 'OTH',
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
        payload['personal_info'].update(overrides)
        return payload

    def test_save_screen_applies_payload_and_bumps_version(self):
        result = return_service.save_screen(
            self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), expected_version=1,
        )
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['personalInfo']['firstName'], 'A')
        self.assertEqual(self.tr.data['bankAccounts'][0]['ifsc'], 'HDFC0000123')
        self.assertNotIn('ifscVerified', self.tr.data['bankAccounts'][0])
        self.assertEqual(self.tr.version, 2)
        self.assertEqual(result['version'], 2)
        self.assertEqual(self.tr.data['screenStatus']['PERSONAL_INFO'], 'IN_PROGRESS')

    def test_save_screen_logs_field_changes_with_correct_path_and_values(self):
        # architecture mandate 6: audit entries must carry the real
        # field_path/old_value/new_value, not just "something" logged.
        return_service.save_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), 1)

        name_entry = AuditLogEntry.objects.get(
            tax_return=self.tr, kind=AuditLogEntry.KIND_FIELD_CHANGE, field_path='personalInfo.firstName',
        )
        self.assertEqual(name_entry.old_value, '')  # blank_return_model default
        self.assertEqual(name_entry.new_value, 'A')

        pan_entry = AuditLogEntry.objects.get(
            tax_return=self.tr, kind=AuditLogEntry.KIND_FIELD_CHANGE, field_path='personalInfo.pan',
        )
        self.assertEqual(pan_entry.old_value, '')
        self.assertEqual(pan_entry.new_value, 'ABCDE1234F')

    def test_second_edit_old_value_is_prior_saved_value_not_blank_default(self):
        return_service.save_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), 1)
        return_service.save_screen(
            self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(first_name='Changed'), 2,
        )
        entry = AuditLogEntry.objects.get(
            tax_return=self.tr, kind=AuditLogEntry.KIND_FIELD_CHANGE,
            field_path='personalInfo.firstName', new_value='Changed',
        )
        self.assertEqual(entry.old_value, 'A')

    def test_stale_expected_version_raises_conflict(self):
        return_service.save_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), 1)
        with self.assertRaises(VersionConflictError):
            return_service.save_screen(
                self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(first_name='C'), expected_version=1,
            )

    def test_none_expected_version_never_conflicts(self):
        return_service.save_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), 1)
        # Should not raise even though the real version has moved on.
        return_service.save_screen(
            self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(first_name='D'), expected_version=None,
        )
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['personalInfo']['firstName'], 'D')

    def test_confirm_screen_with_no_bank_account_reports_structural_error_and_does_not_confirm(self):
        payload = self._personal_info_payload()
        payload['bank_accounts'] = []
        result = return_service.confirm_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', payload, 1)
        self.assertFalse(result['confirmed'])
        self.assertTrue(result['bank_errors'])
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['PERSONAL_INFO'], 'HAS_ERRORS')

    def test_confirm_screen_success_sets_confirmed_status(self):
        result = return_service.confirm_screen(self.tr.pk, self.owner, 'PERSONAL_INFO', self._personal_info_payload(), 1)
        self.assertTrue(result['confirmed'])
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['PERSONAL_INFO'], 'CONFIRMED')

    def test_deductions_screen_derives_schedule_totals_through_service(self):
        payload = {
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
        return_service.save_screen(self.tr.pk, self.owner, 'TOTAL_DEDUCTIONS', payload, 1)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['deductions']['s80C'], 80000)


class ComputationAndValidationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc4', email='svc4@example.com', password='x')
        self.tr = _make_return(self.owner, golden_model())

    def test_get_computation_matches_compute_directly(self):
        service_result = return_service.get_computation(self.tr.pk, self.owner)
        direct_result = compute(self.tr.data)
        self.assertEqual(service_result, direct_result)

    def test_run_validation_reports_ok_for_golden_model(self):
        result = return_service.run_validation(self.tr.pk, self.owner)
        self.assertTrue(result['report']['ok'])
        self.assertEqual(result['report']['errors'], [])
        self.assertTrue(result['downloadable'])

    def test_generate_return_json_succeeds_and_logs_audit(self):
        result = return_service.generate_return_json(self.tr.pk, self.owner)
        self.assertIn('filename', result)
        self.assertIn('sha256', result)
        self.assertIn('json', result)
        self.assertTrue(
            AuditLogEntry.objects.filter(tax_return=self.tr, kind=AuditLogEntry.KIND_JSON_GENERATION).exists()
        )

    def test_generate_return_json_raises_when_blocked(self):
        blocked = TaxReturn.objects.create(owner=self.owner)  # blank return, will have errors
        with self.assertRaises(GenerationBlockedError):
            return_service.generate_return_json(blocked.pk, self.owner)

    def test_run_validation_sets_a_real_resolvable_goto_url_on_findings(self):
        # A blank return has real tier-3 errors with deepLinks; goto_url must
        # actually resolve (not just be present) to /returns/<id>/<screen>/#<anchor>.
        blank = TaxReturn.objects.create(owner=self.owner)
        result = return_service.run_validation(blank.pk, self.owner)
        errors_with_links = [e for e in result['report']['errors'] if e.get('deepLink')]
        self.assertTrue(errors_with_links)
        for finding in errors_with_links:
            self.assertIsNotNone(finding.get('goto_url'))
            self.assertIn(str(blank.pk), finding['goto_url'])
            self.assertIn('#', finding['goto_url'])


class AcknowledgeAdvisoriesTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc5', email='svc5@example.com', password='x')
        self.tr = _make_return(self.owner, golden_model())

    def test_acknowledge_persists_and_logs(self):
        result = return_service.acknowledge_advisories(self.tr.pk, self.owner, ['B-1', 'B-2'])
        self.assertEqual(sorted(result['acknowledged']), ['B-1', 'B-2'])
        self.tr.refresh_from_db()
        acks = self.tr.data['advisoryAcknowledgements']
        self.assertIn('B-1', acks)
        self.assertIn('B-2', acks)
        self.assertTrue(
            AuditLogEntry.objects.filter(tax_return=self.tr, kind=AuditLogEntry.KIND_ADVISORY_ACK).exists()
        )


class RegimeComparisonTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc6', email='svc6@example.com', password='x')

    def test_returns_raw_integers_for_both_regimes(self):
        tr = _make_return(self.owner, old_regime_golden_model())
        result = return_service.regime_comparison(tr.pk, self.owner)
        self.assertIn('NEW', result)
        self.assertIn('OLD', result)
        self.assertIsInstance(result['NEW'], int)
        self.assertIsInstance(result['OLD'], int)
        # OLD is the model's actual current regime -- its figure must match
        # what compute() reports directly for this same (unmodified) model.
        self.assertEqual(result['OLD'], compute(tr.data)['totalTaxFeeAndInterest'])


class VerificationAndTaxSummaryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc7', email='svc7@example.com', password='x')
        self.tr = _make_return(self.owner, golden_model())

    def test_save_verification_updates_and_uppercases_pan(self):
        return_service.save_verification(self.tr.pk, self.owner, {
            'assessee_ver_name': 'NEW NAME', 'father_name': 'FATHER',
            'assessee_ver_pan': 'aaapz1234c', 'capacity': 'S', 'place': 'DELHI',
        })
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['verification']['assesseeVerName'], 'NEW NAME')
        self.assertEqual(self.tr.data['verification']['assesseeVerPan'], 'AAAPZ1234C')

    def test_confirm_tax_summary_sets_confirmed_status(self):
        return_service.confirm_tax_summary(self.tr.pk, self.owner)
        self.tr.refresh_from_db()
        self.assertEqual(self.tr.data['screenStatus']['TAX_SUMMARY'], 'CONFIRMED')


class ImportReturnJsonTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='svc8', email='svc8@example.com', password='x')

    def test_import_derives_schedule_totals_instead_of_trusting_document(self):
        from itr.serialize.generate import generate_json

        source_tr = _make_return(self.owner, golden_model())
        computed = compute(source_tr.data)
        document = generate_json(source_tr.data, {'computed': computed}).payload

        target_tr = TaxReturn.objects.create(owner=self.owner)
        result = return_service.import_return_json(target_tr.pk, self.owner, document)
        target_tr.refresh_from_db()

        self.assertEqual(target_tr.data['personalInfo']['pan'], 'AHKPT5171E')
        self.assertEqual(result['version'], target_tr.version)
        self.assertEqual(target_tr.data['deductions']['s80C'], sum(r['amount'] for r in target_tr.data['deductions']['schedule80C']))
