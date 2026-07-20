"""users/hashers.py — Werkzeug password hash compatibility.

Werkzeug (used by Flask) supports multiple hash formats:
  - scrypt:32768:8:1$...  (Werkzeug >= 2.0 default)
  - pbkdf2:sha256:...     (legacy Werkzeug)

This hasher lets Django verify any Werkzeug hash transparently.
On next successful login, Django re-hashes with its native PBKDF2 hasher.
"""

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class WerkzeugHasher(BasePasswordHasher):
    """Verifies any hash produced by werkzeug.security.generate_password_hash."""
    algorithm = 'werkzeug'

    def identify(self, encoded):
        """Return True for any Werkzeug hash format."""
        if not encoded:
            return False
        return (
            encoded.startswith('scrypt:') or
            encoded.startswith('pbkdf2:sha256:') or
            encoded.startswith('pbkdf2:sha1:')
        )

    def verify(self, password, encoded):
        try:
            from werkzeug.security import check_password_hash
            return check_password_hash(encoded, password)
        except Exception:
            return False

    def encode(self, password, salt):
        # This method is called to create NEW hashes - use Werkzeug so we
        # stay compatible. But Django will prefer its own PBKDF2 hasher for
        # new users (this hasher is listed second in PASSWORD_HASHERS).
        from werkzeug.security import generate_password_hash
        return generate_password_hash(password)

    def safe_summary(self, encoded):
        algo = 'scrypt' if encoded.startswith('scrypt:') else 'pbkdf2'
        return {'algorithm': f'werkzeug-{algo}', 'hash': mask_hash(encoded)}

    def must_update(self, encoded):
        # Force upgrade to Django's native hasher after successful verify
        return True
