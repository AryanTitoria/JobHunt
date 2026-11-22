from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError
from django.test import TestCase, override_settings
from careers.forms import RegisterForm
from careers.models import Preferences


@override_settings(ALLOWED_HOSTS=['testserver'])
class RegistrationTests(TestCase):
    def data(self, **overrides):
        values = {'username': 'new.person+demo@example.org', 'email': '',
                  'password1': 'A-clear-start-84729!', 'password2': 'A-clear-start-84729!'}
        values.update(overrides)
        return values

    def test_email_style_username_can_register_and_sign_in(self):
        response = self.client.post('/signup/', self.data())
        self.assertRedirects(response, '/profile/')
        user = get_user_model().objects.get(username='new.person+demo@example.org')
        self.assertTrue(Preferences.objects.filter(user=user).exists())
        self.client.post('/logout/')
        self.assertTrue(self.client.login(username=user.username, password=self.data()['password1']))

    def test_normal_username_can_register(self):
        self.assertRedirects(self.client.post('/signup/', self.data(username='new_user')), '/profile/')

    def test_username_is_normalized_and_duplicate_is_visible(self):
        get_user_model().objects.create_user('existing.user')
        response = self.client.post('/signup/', self.data(username='EXISTING.USER'))
        self.assertContains(response, 'Your account has not been created yet')
        self.assertContains(response, 'This username is already taken')
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_common_numeric_password_is_not_accepted(self):
        response = self.client.post('/signup/', self.data(password1='12345678', password2='12345678'))
        self.assertContains(response, 'Your account has not been created yet')
        self.assertFalse(get_user_model().objects.exists())
        self.assertContains(response, 'too common')

    def test_mismatching_passwords_show_summary(self):
        response = self.client.post('/signup/', self.data(password2='Different-84729!'))
        self.assertContains(response, 'signup-errors')
        self.assertFalse(get_user_model().objects.exists())

    def test_spaces_are_rejected_with_standard_rules(self):
        form = RegisterForm(data=self.data(username='a new user'))
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_database_busy_returns_visible_error_without_partial_account(self):
        with patch('careers.models.Preferences.objects.create', side_effect=OperationalError('database is locked')):
            response = self.client.post('/signup/', self.data())
        self.assertContains(response, 'database is busy')
        self.assertFalse(get_user_model().objects.exists())

    def test_concurrent_duplicate_is_a_validation_error_not_500(self):
        with patch('careers.models.Preferences.objects.create', side_effect=IntegrityError('unique constraint')):
            response = self.client.post('/signup/', self.data())
        self.assertContains(response, 'This username was just taken')
        self.assertFalse(get_user_model().objects.exists())
