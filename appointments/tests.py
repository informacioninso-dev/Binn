from django.test import SimpleTestCase

from .forms import AppointmentForm


class AppointmentFormTests(SimpleTestCase):
    def test_datetime_local_input_format_is_configured(self):
        form = AppointmentForm()

        self.assertIn("%Y-%m-%dT%H:%M", form.fields["scheduled_at"].input_formats)
