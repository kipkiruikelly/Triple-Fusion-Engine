import os
import sys
import json
import secrets
import pyotp
from datetime import datetime, date, timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponse

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import SessionAuthentication

from .models import (
    User, UserPreferences, TwoFactorAuth, ApiKey, UserWebhook, GiftCode, ActivityLog,
    Payment, Notification
)
from .serializers import UserSerializer


def _user_response(request, user):
    """Build the standard user response payload."""
    return {
        'ok': True,
        'user': UserSerializer(user).data,
        'csrf_token': get_token(request),
    }


def _log_activity(user, action, details=None):
    try:
        ActivityLog.objects.create(
            user=user,
            action=action,
            details=details or "",
            ip_address="127.0.0.1"
        )
    except Exception:
        pass


# ── CSRF token endpoint (called by React on app load) ─────────────────────────

class CsrfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({'ok': True, 'csrf_token': get_token(request)})


# ── Login ─────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        identifier = (
            request.data.get('identifier') or
            request.data.get('username') or
            ''
        ).strip()
        password = request.data.get('password', '')

        if not identifier or not password:
            return Response({'ok': False, 'error': 'Username/email and password are required.'}, status=400)

        # Support login by email
        if '@' in identifier:
            try:
                user_obj = User.objects.get(email__iexact=identifier)
                identifier = user_obj.username
            except User.DoesNotExist:
                return Response({'ok': False, 'error': 'Invalid credentials.'}, status=401)

        user = authenticate(request, username=identifier, password=password)
        if user is None:
            return Response({'ok': False, 'error': 'Invalid credentials.'}, status=401)

        if user.status == 'banned':
            return Response({'ok': False, 'error': f'Account banned: {user.ban_reason or "contact support"}.'}, status=403)

        if user.status == 'deactivated':
            return Response({'ok': False, 'error': 'Account deactivated. Contact support.'}, status=403)

        login(request, user)
        _log_activity(user, "login_success")
        return Response(_user_response(request, user))


# ── Register ──────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        username = request.data.get('username', '').strip()
        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not username or not email or not password:
            return Response({'ok': False, 'error': 'username, email, and password are required.'}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({'ok': False, 'error': 'Username already taken.'}, status=409)

        if User.objects.filter(email=email).exists():
            return Response({'ok': False, 'error': 'Email already registered.'}, status=409)

        # Validate password strength
        try:
            validate_password(password)
        except ValidationError as e:
            return Response({'ok': False, 'error': ' '.join(e.messages)}, status=400)

        user = User.objects.create_user(username=username, email=email, password=password)
        login(request, user)
        _log_activity(user, "register_success")
        return Response(_user_response(request, user), status=201)


# ── Logout ────────────────────────────────────────────────────────────────────

class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({'ok': True})


# ── Me (current user) ─────────────────────────────────────────────────────────

class MeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({'ok': False, 'error': 'Not authenticated.'}, status=401)
        return Response(_user_response(request, request.user))


# ── Settings (theme, preferences, etc.) ──────────────────────────────────────

class SettingsView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        user = request.user
        allowed_fields = ['theme_preference', 'alerts_enabled', 'paper_trading_opted_in']
        updated = []

        for field in allowed_fields:
            if field in request.data:
                setattr(user, field, request.data[field])
                updated.append(field)

        if updated:
            user.save(update_fields=updated)

        return Response(_user_response(request, user))


# ── Profile ───────────────────────────────────────────────────────────────────

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        return Response(_user_response(request, request.user))

    def post(self, request):
        """Update display-name-safe profile fields."""
        user = request.user
        allowed = ['email']
        updated = []

        for field in allowed:
            if field in request.data:
                new_val = request.data[field].strip().lower()
                if field == 'email' and User.objects.filter(email=new_val).exclude(pk=user.pk).exists():
                    return Response({'ok': False, 'error': 'Email already in use.'}, status=409)
                setattr(user, field, new_val)
                updated.append(field)

        if updated:
            user.save(update_fields=updated)

        return Response(_user_response(request, user))


# ── Change Password ───────────────────────────────────────────────────────────

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        user         = request.user
        current      = request.data.get('current_password', '')
        new_password = request.data.get('new_password', '')

        if not current or not new_password:
            return Response({'ok': False, 'error': 'current_password and new_password are required.'}, status=400)

        if not user.check_password(current):
            return Response({'ok': False, 'error': 'Current password is incorrect.'}, status=403)

        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            return Response({'ok': False, 'error': ' '.join(e.messages)}, status=400)

        user.set_password(new_password)
        user.save()
        login(request, user)
        return Response({'ok': True, 'message': 'Password updated successfully.'})


# ── Preferences ────────────────────────────────────────────────────────────────

class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
        return Response({
            "ok": True,
            "digest_enabled": bool(prefs.digest_enabled),
            "theme": request.user.theme_preference or "system",
            "default_ticker": prefs.default_ticker,
            "timezone": prefs.timezone,
            "usage_notice_enabled": bool(prefs.usage_notice_enabled),
            "risk_intro_seen": bool(prefs.risk_intro_seen),
        })

    def post(self, request):
        prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
        data = request.data

        if "digest_enabled" in data:
            prefs.digest_enabled = bool(data["digest_enabled"])
        if "theme" in data and data["theme"] in ("dark", "light", "system"):
            request.user.theme_preference = data["theme"]
            request.user.save(update_fields=["theme_preference"])
        if "default_ticker" in data:
            prefs.default_ticker = (data["default_ticker"] or "AAPL").upper()[:12]
        if "timezone" in data:
            prefs.timezone = (data["timezone"] or "UTC")[:50]
        if "usage_notice_enabled" in data:
            prefs.usage_notice_enabled = bool(data["usage_notice_enabled"])
        if "risk_intro_seen" in data:
            prefs.risk_intro_seen = bool(data["risk_intro_seen"])

        prefs.save()
        return Response({"ok": True})


# ── Two-Factor Authentication (2FA) ───────────────────────────────────────────

class TwoFactorSetupView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        rec, created = TwoFactorAuth.objects.get_or_create(user=request.user)
        if rec.enabled:
            return Response({"ok": False, "error": "2FA already enabled"}, status=400)
            
        secret = pyotp.random_base32()
        rec.secret = secret
        rec.save()

        uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=request.user.email, issuer_name="BullLogic"
        )
        return Response({"ok": True, "secret": secret, "uri": uri})


class TwoFactorEnableView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        code = request.data.get("code", "")
        rec = TwoFactorAuth.objects.filter(user=request.user).first()
        if not rec or not rec.secret:
            return Response({"ok": False, "error": "Run setup first"}, status=400)
            
        totp = pyotp.TOTP(rec.secret)
        if not totp.verify(code, valid_window=1):
            return Response({"ok": False, "error": "Invalid code"}, status=400)
            
        backup = [secrets.token_hex(4).upper() for _ in range(8)]
        rec.enabled = True
        rec.backup_codes = json.dumps(backup)
        rec.save()

        # Add notification best-effort
        try:
            from trading.tools_views import _add_notification
            _add_notification(request.user.id, "system", "2FA Enabled", "Two-factor authentication is now active on your account.")
        except Exception:
            pass

        _log_activity(request.user, "2fa_enable")
        return Response({"ok": True, "backup_codes": backup})


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        password = request.data.get("password", "")
        code = request.data.get("code", "")
        
        if not request.user.check_password(password):
            return Response({"ok": False, "error": "Incorrect password"}, status=400)
            
        rec = TwoFactorAuth.objects.filter(user=request.user, enabled=True).first()
        if not rec:
            return Response({"ok": False, "error": "2FA is not enabled"}, status=400)
            
        totp = pyotp.TOTP(rec.secret)
        if not totp.verify(code, valid_window=1):
            return Response({"ok": False, "error": "Invalid 2FA code"}, status=400)
            
        rec.enabled = False
        rec.save()
        _log_activity(request.user, "2fa_disable")
        return Response({"ok": True})


class TwoFactorStatusView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        rec = TwoFactorAuth.objects.filter(user=request.user).first()
        return Response({
            "ok": True,
            "enabled": rec.enabled if rec else False,
            "available": True
        })


# ── Developer API Keys ─────────────────────────────────────────────────────────

class ApiKeysListView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        keys = ApiKey.objects.filter(user=request.user).order_by("-created_at")
        return Response([
            {
                "id": k.id,
                "name": k.name,
                "key_preview": k.key[:8] + "..." + k.key[-4:],
                "created_at": k.created_at.strftime("%Y-%m-%d") if k.created_at else "",
                "last_used": k.last_used.strftime("%Y-%m-%d %H:%M") if k.last_used else None,
                "calls_today": k.calls_today,
            }
            for k in keys
        ])


class ApiKeysCreateView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        if not request.user.is_pro:
            return Response({
                "ok": False, "error": "upgrade_required", "feature": "api_access",
                "message": "REST API access is a Pro feature.", "cta": "/pricing",
            }, status=403)
            
        if ApiKey.objects.filter(user=request.user).count() >= 5:
            return Response({"ok": False, "error": "Maximum 5 API keys per account"}, status=400)
            
        name = request.data.get("name", "Default")[:50]
        key = secrets.token_hex(32)
        ak = ApiKey.objects.create(user=request.user, key=key, name=name)
        return Response({"ok": True, "key": key, "id": ak.id, "name": name})


class ApiKeysDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        key_id = request.data.get("key_id")
        try:
            ak = ApiKey.objects.get(id=key_id, user=request.user)
            ak.delete()
            return Response({"ok": True})
        except ApiKey.DoesNotExist:
            return Response({"ok": False, "error": "Key not found"}, status=404)


# ── User Custom Webhooks ───────────────────────────────────────────────────────

class WebhooksListView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        hooks = UserWebhook.objects.filter(user=request.user)
        return Response({
            "ok": True,
            "webhooks": [
                {
                    "id": h.id, "name": h.name, "url": h.url[:60] + "...",
                    "events": h.events, "active": h.active, "fire_count": h.fire_count,
                    "last_fired": h.last_fired.strftime("%Y-%m-%d %H:%M") if h.last_fired else None,
                }
                for h in hooks
            ]
        })


class WebhooksAddView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        url = (request.data.get("url") or "").strip()
        if not url.startswith("http"):
            return Response({"ok": False, "error": "URL must start with http"}, status=400)
            
        if UserWebhook.objects.filter(user=request.user).count() >= 5:
            return Response({"ok": False, "error": "Max 5 webhooks per account"}, status=400)
            
        hook = UserWebhook.objects.create(
            user=request.user,
            url=url[:500],
            name=(request.data.get("name") or "My Webhook")[:50],
            events=(request.data.get("events") or "alert,signal")[:100],
            secret=secrets.token_hex(16)
        )
        return Response({"ok": True, "id": hook.id, "secret": hook.secret})


class WebhooksDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        hook_id = request.data.get("webhook_id")
        try:
            hook = UserWebhook.objects.get(id=hook_id, user=request.user)
            hook.delete()
            return Response({"ok": True})
        except UserWebhook.DoesNotExist:
            return Response({"ok": False, "error": "Not found"}, status=404)


class WebhooksTestView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        hook_id = request.data.get("webhook_id")
        try:
            hook = UserWebhook.objects.get(id=hook_id, user=request.user)
            # Mock firing webhook
            print(f"[Mock Webhook] Fired {hook.url} with events: {hook.events}")
            hook.fire_count += 1
            hook.last_fired = datetime.utcnow()
            hook.save(update_fields=["fire_count", "last_fired"])
            return Response({"ok": True})
        except UserWebhook.DoesNotExist:
            return Response({"ok": False, "error": "Not found"}, status=404)


# ── Gift Code Redemption ─────────────────────────────────────────────────────

class GiftRedeemView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        code_str = request.data.get("code", "").strip().upper()
        if not code_str:
            return Response({"ok": False, "error": "Code required"}, status=400)
            
        try:
            gift = GiftCode.objects.get(code=code_str, used=False)
        except GiftCode.DoesNotExist:
            return Response({"ok": False, "error": "Invalid or already redeemed code"}, status=400)
            
        gift.used = True
        gift.used_by = request.user
        gift.used_at = datetime.utcnow()
        gift.save()
        
        user = request.user
        days = gift.days or 30
        
        # Extend or grant Pro access
        if user.plan == 'pro' and user.pro_expires_at and user.pro_expires_at >= date.today():
            user.pro_expires_at = user.pro_expires_at + timedelta(days=days)
        else:
            user.pro_expires_at = date.today() + timedelta(days=days)
        user.plan = 'pro'
        user.role = 'pro'
        user.save()
        
        # Create payment audit log
        Payment.objects.create(
            user=user,
            provider='gift',
            plan='pro',
            tier='pro',
            amount=0.0,
            currency='USD',
            days=days,
            reference=f"gift:{gift.code}",
            status='paid',
            completed_at=datetime.utcnow()
        )
        
        # Create in-app notification
        Notification.objects.create(
            user=user,
            type='gift',
            title="Pro activated!",
            body=f"Your gift code added {days} days of Pro access.",
            link="/profile"
        )
        
        _log_activity(user, "redeem_gift", f"code: {code_str}, days: {days}")
        return Response({"ok": True, "plan": "pro", "days_added": days, "pro_until": str(user.pro_expires_at)})


# ── Account Export & Deletion ────────────────────────────────────────────────

class AccountExportView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        data = {
            "username": request.user.username,
            "email": request.user.email,
            "plan": request.user.plan,
            "created_at": request.user.created_at.isoformat() if request.user.created_at else None,
            "preferences": {
                "theme": request.user.theme_preference,
                "alerts_enabled": bool(request.user.alerts_enabled)
            }
        }
        response = HttpResponse(json.dumps(data, indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="bulllogic_data.json"'
        return response


class AccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        user = request.user
        logout(request)
        user.delete()
        return Response({"ok": True})


# ── Google OAuth 2.0 ──────────────────────────────────────────────────────────

class GoogleLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        if not client_id:
            from django.shortcuts import redirect
            return redirect('/login?error=Google auth client ID not configured.')
        
        state = secrets.token_hex(16)
        request.session['google_oauth_state'] = state
        
        referer = request.META.get('HTTP_REFERER', '')
        if 'localhost:8002' in referer:
            redirect_uri = "http://localhost:8002/auth/google/callback"
        elif 'localhost:5001' in referer:
            redirect_uri = "http://localhost:5001/auth/google/callback"
        elif 'localhost:5000' in referer:
            redirect_uri = "http://localhost:5000/auth/google/callback"
        else:
            host = request.get_host()
            if '8001' in host:
                redirect_uri = "http://localhost:8002/auth/google/callback"
            else:
                redirect_uri = f"http://{host}/auth/google/callback"
                
        request.session['google_oauth_redirect_uri'] = redirect_uri
        
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            "response_type=code&"
            "scope=openid%20email%20profile&"
            f"state={state}&"
            "prompt=select_account"
        )
        from django.shortcuts import redirect
        return redirect(auth_url)


class GoogleCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        import requests
        from django.shortcuts import redirect
        from django.contrib.auth.models import update_last_login
        
        code = request.GET.get('code')
        state = request.GET.get('state')
        saved_state = request.session.pop('google_oauth_state', None)
        
        if saved_state and state != saved_state:
            return redirect('/login?error=OAuth state verification failed.')
            
        if not code:
            return redirect('/login?error=Google authentication failed.')

        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        redirect_uri = request.session.pop('google_oauth_redirect_uri', 'http://localhost:5001/auth/google/callback')
        
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        try:
            r = requests.post(token_url, data=data)
            r.raise_for_status()
            tokens = r.json()
            access_token = tokens.get('access_token')
            
            if not access_token:
                return redirect('/login?error=Could not retrieve access token.')
                
            # Get user info from Google
            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            headers = {'Authorization': f'Bearer {access_token}'}
            info_res = requests.get(userinfo_url, headers=headers)
            info_res.raise_for_status()
            info = info_res.json()
            
            sub = str(info.get('sub') or '')
            email = (info.get('email') or '').strip().lower()
            
            if not sub or not email:
                return redirect('/login?error=Google did not return sub/email.')
                
            # Authenticate or Register user
            user = User.objects.filter(google_sub=sub).first()
            if not user:
                # Link existing email if same registered
                user = User.objects.filter(email=email).first()
                if user:
                    user.google_sub = sub
                    user.email_verified = True
                    user.save()
                else:
                    # Generate a unique username
                    base_username = (info.get('name') or email.split('@')[0]).replace(" ", "").lower()
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}{counter}"
                        counter += 1
                        
                    user = User(
                        username=username,
                        email=email,
                        auth_provider='google',
                        google_sub=sub,
                        email_verified=True,
                        plan='free',
                        role='user',
                        status='active'
                    )
                    user.set_password(secrets.token_urlsafe(24))
                    user.save()
                    
            if user.status != 'active':
                return redirect('/login?error=This account has been suspended.')
                
            # Login user session
            login(request, user)
            update_last_login(None, user)
            _log_activity(user, "login.google")
            
            # Redirect to portfolio dashboard (logged in successfully!)
            return redirect('/portfolio')
            
        except Exception as e:
            print("Google OAuth error:", e)
            return redirect('/login?error=Google sign-in failed.')


class ClaimXpView(APIView):
    """POST /api/gamification/claim-xp — claim XP points for onboarding task."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        amount = int(request.data.get("amount", 25))
        user = request.user
        old_level = user.level
        user.xp = (user.xp or 0) + amount
        user.save()

        level_up = user.level > old_level
        if level_up:
            try:
                from trading.tools_views import _add_notification
                _add_notification(
                    user.id,
                    "system",
                    "Level Up!",
                    f"Congratulations! You reached Level {user.level}."
                )
            except Exception:
                pass

        return Response({
            "ok": True,
            "xp_added": amount,
            "current_xp": user.xp,
            "level": user.level,
            "level_up": level_up
        })


class StreakBoostView(APIView):
    """POST /api/gamification/streak-boost — increment user active streak."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        from datetime import date, timedelta
        user = request.user
        today = date.today()
        
        last_active = user.last_active_date
        
        if last_active is None:
            user.current_streak = 1
        elif last_active == today:
            pass
        elif last_active == today - timedelta(days=1):
            user.current_streak = (user.current_streak or 0) + 1
        else:
            user.current_streak = 1

        if (user.current_streak or 1) > (user.longest_streak or 0):
            user.longest_streak = user.current_streak

        user.last_active_date = today
        user.xp = (user.xp or 0) + 10
        user.save()

        return Response({
            "ok": True,
            "current_streak": user.current_streak,
            "longest_streak": user.longest_streak,
            "xp": user.xp,
            "level": user.level
        })
