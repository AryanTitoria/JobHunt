from html.parser import HTMLParser
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from careers.models import Preferences


class AccountParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.profile_href = None
        self.profile_form = None
        self.form_action = None
        self.signout_form = None
        self.in_signout = False
        self.signout_text = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.form_action = attrs.get('action')
        if tag == 'a' and 'account-profile' in attrs.get('class', '').split():
            self.profile_href = attrs.get('href')
            self.profile_form = self.form_action
        if tag == 'button' and 'account-signout-button' in attrs.get('class', '').split():
            self.signout_form = self.form_action
            self.in_signout = True

    def handle_data(self, text):
        if self.in_signout:
            self.signout_text += text

    def handle_endtag(self, tag):
        if tag == 'button':
            self.in_signout = False
        if tag == 'form':
            self.form_action = None


@override_settings(ALLOWED_HOSTS=['testserver'])
class AccountNavigationTests(TestCase):
    def test_bottom_profile_opens_preferences_without_logging_out(self):
        user = get_user_model().objects.create_user('profile-navigation')
        Preferences.objects.create(user=user)
        self.client.force_login(user)
        parser = AccountParser()
        parser.feed(self.client.get('/jobs/').content.decode())
        self.assertEqual(parser.profile_href, '/profile/')
        self.assertIsNone(parser.profile_form)
        self.assertEqual(parser.signout_form, '/logout/')
        self.assertEqual(parser.signout_text.strip(), 'Sign out')
        self.assertEqual(self.client.get(parser.profile_href).status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.client.post(parser.signout_form)
        self.assertNotIn('_auth_user_id', self.client.session)
