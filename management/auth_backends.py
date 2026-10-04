from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate against settings.AUTH_USER_MODEL using either username or email.
    Matching is case-insensitive for both username and email.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        identifier = username or kwargs.get('email') or kwargs.get(UserModel.USERNAME_FIELD)
        if not identifier or not password:
            return None

        identifier = str(identifier).strip()
        if not identifier:
            return None

        # Exclude empty email strings so empty emails never match
        users = UserModel._default_manager.filter(
            Q(username__iexact=identifier) | (Q(email__iexact=identifier) & ~Q(email=''))
        ).order_by('id')

        matched_user = None
        for user in users:
            if user.check_password(password) and self.user_can_authenticate(user):
                matched_user = user
                break

        if matched_user is None:
            # Run the default password hasher once to reduce timing differences
            UserModel().set_password(password)
            return None

        return matched_user
