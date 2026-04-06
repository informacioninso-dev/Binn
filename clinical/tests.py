from django.test import SimpleTestCase

from .forms import ClinicalEncounterForm, ClinicalOrderForm


class ClinicalEncounterFormTests(SimpleTestCase):
    def test_datetime_local_input_format_is_configured(self):
        form = ClinicalEncounterForm()

        self.assertIn("%Y-%m-%dT%H:%M", form.fields["encounter_date"].input_formats)


class ClinicalOrderFormTests(SimpleTestCase):
    def test_datetime_local_input_format_is_configured(self):
        form = ClinicalOrderForm()

        self.assertIn("%Y-%m-%dT%H:%M", form.fields["scheduled_for"].input_formats)
