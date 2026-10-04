"""Tests for username or email authentication, form, web login view, and API."""
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from .forms import EmailOrUsernameAuthenticationForm


class UsernameOrEmailAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.User = get_user_model()
        self.password = 'SecurePass123!'
        self.user = self.User.objects.create_user(
            username='johndoe',
            email='john.doe@example.com',
            password=self.password,
        )
        self.user_no_email = self.User.objects.create_user(
            username='noemailuser',
            email='',
            password=self.password,
        )
        self.inactive_user = self.User.objects.create_user(
            username='inactiveguy',
            email='inactive@example.com',
            password=self.password,
            is_active=False,
        )

    def tearDown(self):
        cache.clear()

    # -------------------------------------------------------------
    # 1. EmailOrUsernameModelBackend direct authenticate tests
    # -------------------------------------------------------------
    def test_authenticate_with_exact_username(self):
        user = authenticate(username='johndoe', password=self.password)
        self.assertEqual(user, self.user)

    def test_authenticate_with_case_insensitive_username(self):
        user = authenticate(username='JohnDoe', password=self.password)
        self.assertEqual(user, self.user)

    def test_authenticate_with_exact_email(self):
        user = authenticate(username='john.doe@example.com', password=self.password)
        self.assertEqual(user, self.user)

    def test_authenticate_with_case_insensitive_email(self):
        user = authenticate(username='JOHN.DOE@EXAMPLE.COM', password=self.password)
        self.assertEqual(user, self.user)

    def test_authenticate_with_email_in_kwargs(self):
        user = authenticate(email='john.doe@example.com', password=self.password)
        self.assertEqual(user, self.user)

    def test_authenticate_with_wrong_password(self):
        user = authenticate(username='johndoe', password='WrongPassword!')
        self.assertIsNone(user)

    def test_authenticate_with_email_wrong_password(self):
        user = authenticate(username='john.doe@example.com', password='WrongPassword!')
        self.assertIsNone(user)

    def test_authenticate_with_nonexistent_user(self):
        user = authenticate(username='ghost@example.com', password=self.password)
        self.assertIsNone(user)

    def test_authenticate_inactive_user_fails(self):
        user = authenticate(username='inactive@example.com', password=self.password)
        self.assertIsNone(user)

    def test_empty_email_never_matches_blank_identifier(self):
        user = authenticate(username='   ', password=self.password)
        self.assertIsNone(user)

    # -------------------------------------------------------------
    # 2. EmailOrUsernameAuthenticationForm tests
    # -------------------------------------------------------------
    def test_form_valid_with_username(self):
        form = EmailOrUsernameAuthenticationForm(
            data={'username': 'johndoe', 'password': self.password}
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_user(), self.user)

    def test_form_valid_with_email(self):
        form = EmailOrUsernameAuthenticationForm(
            data={'username': 'john.doe@example.com', 'password': self.password}
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_user(), self.user)

    def test_form_invalid_with_bad_password(self):
        form = EmailOrUsernameAuthenticationForm(
            data={'username': 'john.doe@example.com', 'password': 'bad'}
        )
        self.assertFalse(form.is_valid())

    def test_form_username_max_length_supports_long_emails(self):
        form = EmailOrUsernameAuthenticationForm()
        self.assertEqual(form.fields['username'].max_length, 254)

    # -------------------------------------------------------------
    # 3. Session Login View (/login/) tests
    # -------------------------------------------------------------
    def test_login_page_renders_username_or_email_label_and_placeholder(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Username or Email', content)
        self.assertIn('Enter your username or email', content)

    def test_web_login_with_username_success(self):
        client = Client()
        response = client.post(
            reverse('login'),
            {'username': 'johndoe', 'password': self.password},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_web_login_with_email_success(self):
        client = Client()
        response = client.post(
            reverse('login'),
            {'username': 'john.doe@example.com', 'password': self.password},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_web_login_with_case_insensitive_email_success(self):
        client = Client()
        response = client.post(
            reverse('login'),
            {'username': 'JOHN.DOE@EXAMPLE.COM', 'password': self.password},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_web_login_failed_shows_error(self):
        client = Client()
        response = client.post(
            reverse('login'),
            {'username': 'john.doe@example.com', 'password': 'WrongPassword!'},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Invalid username, email, or password. Please try again.', content)

    # -------------------------------------------------------------
    # 4. Mobile API Login View (/api/auth/login/) tests
    # -------------------------------------------------------------
    def test_api_login_with_username(self):
        response = self.client.post(
            reverse('api_login'),
            {'username': 'johndoe', 'password': self.password},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['user']['username'], 'johndoe')

    def test_api_login_with_email_in_username_field(self):
        response = self.client.post(
            reverse('api_login'),
            {'username': 'john.doe@example.com', 'password': self.password},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['user']['username'], 'johndoe')

    def test_api_login_with_email_field(self):
        response = self.client.post(
            reverse('api_login'),
            {'email': 'john.doe@example.com', 'password': self.password},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['user']['username'], 'johndoe')
