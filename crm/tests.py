from django.test import SimpleTestCase

from .forms import LeadForm


class LeadFormTests(SimpleTestCase):
    def test_datetime_local_input_format_is_configured(self):
        form = LeadForm()

        self.assertIn("%Y-%m-%dT%H:%M", form.fields["next_contact_at"].input_formats)
