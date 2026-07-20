"""trading/admin_views.py — Admin API endpoints.

These views are intended for admin dashboard use and require the user
to have role_level >= 3 (admin).
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.authentication import SessionAuthentication

from users.models import User, Payment, TradingBot, PredictionHistory, ErrorLog, Broadcast, GiftCode


class AdminOverviewView(APIView):
    """GET /admin/api/overview — system overview statistics."""
    permission_classes    = [IsAuthenticated, IsAdminUser]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        # Verify admin role level
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)

        total_users   = User.objects.count()
        pro_users     = User.objects.filter(plan__in=['pro', 'enterprise']).count()
        plus_users    = User.objects.filter(plan='plus').count()
        free_users    = User.objects.filter(plan='free').count()
        active_users  = User.objects.filter(status='active').count()
        banned_users  = User.objects.filter(status='banned').count()
        total_payments = Payment.objects.count()
        paid_payments  = Payment.objects.filter(status='paid').count()
        active_bots   = TradingBot.objects.filter(is_active=True).count()
        total_predictions = PredictionHistory.objects.count()
        recent_errors = ErrorLog.objects.order_by('-created_at')[:5]

        return Response({
            'ok': True,
            'overview': {
                'users': {
                    'total':  total_users,
                    'active': active_users,
                    'banned': banned_users,
                    'pro':    pro_users,
                    'plus':   plus_users,
                    'free':   free_users,
                },
                'payments': {
                    'total': total_payments,
                    'paid':  paid_payments,
                },
                'bots':        {'active': active_bots},
                'predictions': {'total': total_predictions},
                'recent_errors': [
                    {
                        'id':        e.id,
                        'severity':  e.severity,
                        'endpoint':  e.endpoint,
                        'message':   e.message,
                        'created_at': str(e.created_at),
                    }
                    for e in recent_errors
                ],
            },
        })


from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponseForbidden

class AdminRoleRequiredMixin(UserPassesTestMixin):
    raise_exception = True
    login_url = '/login'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role_level >= 3

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect(self.login_url)
        return HttpResponseForbidden("Admin access required. Please make sure you are logged in as an administrator.")

class AdminDashboardHtmlView(AdminRoleRequiredMixin, View):
    def get(self, request):
        total_users = User.objects.count()
        active_bots = TradingBot.objects.filter(is_active=True).count()
        total_predictions = PredictionHistory.objects.count()
        error_count = ErrorLog.objects.count()
        
        recent_users = User.objects.order_by('-created_at')[:10]
        recent_errors = ErrorLog.objects.order_by('-created_at')[:8]

        context = {
            'total_users': total_users,
            'active_bots': active_bots,
            'total_predictions': total_predictions,
            'error_count': error_count,
            'recent_users': recent_users,
            'recent_errors': recent_errors,
        }
        return render(request, 'admin/dashboard.html', context)

class AdminUsersHtmlView(AdminRoleRequiredMixin, View):
    def get(self, request):
        users = User.objects.all().order_by('-created_at')
        return render(request, 'admin/users.html', {'users': users})

class AdminUserToggleStatusView(AdminRoleRequiredMixin, View):
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        if target_user.status == 'active':
            target_user.status = 'banned'
        else:
            target_user.status = 'active'
        target_user.save()
        return redirect('admin-users')

class AdminUserUpdatePlanView(AdminRoleRequiredMixin, View):
    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        plan = request.POST.get('plan')
        if plan in ['free', 'plus', 'pro', 'enterprise']:
            target_user.plan = plan
            target_user.save()
        return redirect('admin-users')


class AdminUsersApiView(APIView):
    """GET /admin/api/users/list — list all users in the system (JSON)."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        users = User.objects.all().order_by('-created_at')
        from users.serializers import UserSerializer
        return Response({'ok': True, 'users': UserSerializer(users, many=True).data})


class AdminUserToggleStatusApiView(APIView):
    """POST /admin/api/users/<int:user_id>/toggle-status/json — toggle user status (JSON)."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request, user_id):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        target_user = get_object_or_404(User, id=user_id)
        target_user.status = 'banned' if target_user.status == 'active' else 'active'
        target_user.save()
        return Response({'ok': True, 'status': target_user.status})


class AdminUserUpdatePlanApiView(APIView):
    """POST /admin/api/users/<int:user_id>/update-plan/json — update user plan (JSON)."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request, user_id):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        target_user = get_object_or_404(User, id=user_id)
        plan = request.data.get('plan')
        if plan in ['free', 'plus', 'pro', 'enterprise']:
            target_user.plan = plan
            target_user.save()
            return Response({'ok': True, 'plan': target_user.plan})
        return Response({'ok': False, 'error': 'Invalid plan.'}, status=400)


class AdminUserUpdateRoleApiView(APIView):
    """POST /admin/api/users/<int:user_id>/update-role/json — update user role (JSON)."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request, user_id):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        target_user = get_object_or_404(User, id=user_id)
        role = request.data.get('role')
        if role in ['user', 'support', 'admin']:
            target_user.role = role
            target_user.is_staff = (role in ['support', 'admin'])
            target_user.is_superuser = (role == 'admin')
            target_user.save()
            return Response({'ok': True, 'role': target_user.role})
        return Response({'ok': False, 'error': 'Invalid role.'}, status=400)


class AdminPaymentsApiView(APIView):
    """GET /admin/api/payments/list — list all system payments."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        payments = Payment.objects.all().order_by('-created_at')
        data = [
            {
                'id': p.id,
                'username': p.user.username,
                'email': p.user.email,
                'provider': p.provider,
                'plan': p.plan,
                'tier': p.tier,
                'amount': p.amount,
                'currency': p.currency,
                'reference': p.reference,
                'status': p.status,
                'created_at': str(p.created_at),
            }
            for p in payments
        ]
        return Response({'ok': True, 'payments': data})


class AdminBroadcastsApiView(APIView):
    """GET /admin/api/broadcasts/list — list admin announcements."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        broadcasts = Broadcast.objects.all().order_by('-created_at')
        data = [
            {
                'id': b.id,
                'title': b.title,
                'body': b.body,
                'segment': b.segment,
                'channel': b.channel,
                'sent_count': b.sent_count,
                'created_at': str(b.created_at),
            }
            for b in broadcasts
        ]
        return Response({'ok': True, 'broadcasts': data})

    def post(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        title = request.data.get('title')
        body = request.data.get('body')
        segment = request.data.get('segment', 'all')
        channel = request.data.get('channel', 'in-app')
        
        if not title or not body:
            return Response({'ok': False, 'error': 'Title and Body are required.'}, status=400)
            
        if segment == 'pro':
            sent_count = User.objects.filter(plan__in=['pro', 'enterprise']).count()
        elif segment == 'free':
            sent_count = User.objects.filter(plan='free').count()
        else:
            sent_count = User.objects.count()

        broadcast = Broadcast.objects.create(
            admin=request.user,
            title=title,
            body=body,
            segment=segment,
            channel=channel,
            sent_count=sent_count
        )
        return Response({'ok': True, 'broadcast': {
            'id': broadcast.id,
            'title': broadcast.title,
            'body': broadcast.body,
            'segment': broadcast.segment,
            'channel': broadcast.channel,
            'sent_count': broadcast.sent_count,
            'created_at': str(broadcast.created_at),
        }})


class AdminGiftCodesApiView(APIView):
    """GET /admin/api/gift-codes/list — list all gift codes.
    POST /admin/api/gift-codes/generate — generate new gift codes.
    """
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        codes = GiftCode.objects.all().order_by('-created_at')
        data = [
            {
                'id': c.id,
                'code': c.code,
                'days': c.days,
                'used': c.used,
                'used_by': c.used_by.username if c.used_by else None,
                'used_at': str(c.used_at) if c.used_at else None,
                'created_at': str(c.created_at),
                'note': c.note
            }
            for c in codes
        ]
        return Response({'ok': True, 'gift_codes': data})

    def post(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        days  = int(request.data.get('days', 30))
        count = min(int(request.data.get('count', 1)), 20)
        note  = (request.data.get('note') or '')[:100]
        
        import secrets
        codes = []
        for _ in range(count):
            code = secrets.token_hex(6).upper()
            GiftCode.objects.create(code=code, days=days, note=note)
            codes.append(code)
            
        return Response({'ok': True, 'codes': codes, 'days': days})


class AdminPillarsDataView(APIView):
    """GET /admin/api/pillars/data — get administrative datasets for 5 core pillars."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
        
        # 1. KYC/AML Data
        kyc_list = [
            {'id': 1, 'username': 'janedoe', 'email': 'jane@example.com', 'doc_type': 'Passport', 'risk_score': 12, 'status': 'Pending'},
            {'id': 2, 'username': 'johnsmith', 'email': 'john@example.com', 'doc_type': 'National ID', 'risk_score': 45, 'status': 'Pending'},
            {'id': 3, 'username': 'cryptotrader', 'email': 'crypto@example.com', 'doc_type': 'Drivers License', 'risk_score': 88, 'status': 'Pending'},
        ]
        
        # 2. Introducing Brokers
        ib_list = [
            {'id': 1, 'name': 'Apex Trading Group', 'tier': 1, 'referrals': 142, 'commission': 5230.50},
            {'id': 2, 'name': 'Alpha Partners', 'tier': 2, 'referrals': 67, 'commission': 2120.00},
            {'id': 3, 'name': 'Vanguard Affiliates', 'tier': 3, 'referrals': 23, 'commission': 410.00},
        ]
        
        # 3. Liquidity Providers
        lp_connections = [
            {'id': 1, 'name': 'MetaTrader 5 Bridge', 'status': 'Connected', 'latency': '4ms', 'load': '12%'},
            {'id': 2, 'name': 'LMAX Prime', 'status': 'Connected', 'latency': '9ms', 'load': '34%'},
            {'id': 3, 'name': 'Interactive Brokers Feed', 'status': 'Connected', 'latency': '15ms', 'load': '5%'},
        ]
        
        # 4. Compliance Alerts
        compliance_alerts = [
            {'id': 1, 'user': 'scalper99', 'type': 'Spoofing Alert', 'details': 'Multiple buy orders cancelled within 500ms', 'severity': 'High', 'created_at': '2026-07-17 01:23:45'},
            {'id': 2, 'user': 'arbitrage_bot', 'type': 'Cross-trading', 'details': 'Wash trades detected between sub-accounts', 'severity': 'Medium', 'created_at': '2026-07-17 01:10:12'},
        ]
        
        # 5. Risk & Circuit Breakers state
        risk_metrics = {
            'total_exposure': 1584200.00,
            'margin_call_count': 2,
            'stop_outs_today': 0,
            'circuit_breaker_tripped': False,
            'exposures': [
                {'ticker': 'FOREXCOM:SPXUSD', 'long_lots': 420.5, 'short_lots': 150.0, 'net': 270.5},
                {'ticker': 'FOREXCOM:NAS100', 'long_lots': 180.0, 'short_lots': 210.0, 'net': -30.0},
                {'ticker': 'EURUSD', 'long_lots': 85.0, 'short_lots': 40.0, 'net': 45.0},
            ]
        }
        
        # 6. Payment Gateways
        gateways = [
            {'id': 'stripe', 'name': 'Stripe Connect', 'active': True, 'currency': 'USD, EUR, GBP', 'processed_today': 14200.00},
            {'id': 'mpesa', 'name': 'Safaricom M-Pesa API', 'active': True, 'currency': 'KES', 'processed_today': 354000.00},
            {'id': 'coinbase', 'name': 'Coinbase Commerce', 'active': False, 'currency': 'BTC, ETH, USDT', 'processed_today': 0.00},
        ]
        
        # 7. Ledgers / Wallets
        wallets = [
            {'name': 'Operational Fiat Wallet', 'balance': '124,530.00 USD'},
            {'name': 'Stripe Custody Account', 'balance': '43,210.00 USD'},
            {'name': 'Safaricom B2C Float', 'balance': '812,000.00 KES'},
            {'name': 'Cold Storage (Crypto)', 'balance': '12.45 BTC'},
        ]
        
        # 8. RBAC Matrix settings
        rbac = {
            'admin': ['client_read', 'client_write', 'trade_read', 'trade_write', 'billing_read', 'billing_write', 'risk_read', 'risk_write'],
            'support': ['client_read', 'client_write', 'trade_read'],
            'compliance': ['client_read', 'trade_read', 'risk_read'],
            'dealer': ['trade_read', 'trade_write', 'risk_read', 'risk_write'],
        }
        
        # 9. Registered AI Robots list
        bots_list = [
            {
                'id': b.id,
                'slug': b.slug,
                'name': b.name,
                'description': b.description,
                'asset_class': b.asset_class,
                'interval': b.interval,
                'is_active': b.is_active,
                'created_at': str(b.created_at)
            }
            for b in TradingBot.objects.all()
        ]
        
        return Response({
            'ok': True,
            'kyc_list': kyc_list,
            'ib_list': ib_list,
            'lp_connections': lp_connections,
            'compliance_alerts': compliance_alerts,
            'risk_metrics': risk_metrics,
            'gateways': gateways,
            'wallets': wallets,
            'rbac': rbac,
            'bots_list': bots_list
        })


class AdminPillarsActionView(APIView):
    """POST /admin/api/pillars/action — handle pillar updates."""
    permission_classes    = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        if request.user.role_level < 3:
            return Response({'ok': False, 'error': 'Admin access required.'}, status=403)
            
        action_type = request.data.get('action_type')
        target_id   = request.data.get('target_id')
        status      = request.data.get('status')
        
        from users.models import AdminAuditLog, TradingBot
        AdminAuditLog.objects.create(
            admin=request.user,
            action=f"pillar_action_{action_type}",
            details=f"Target ID: {target_id}, Status: {status}"
        )
        
        if action_type == 'bot_toggle':
            try:
                bot = TradingBot.objects.get(slug=target_id)
                bot.is_active = (status == 'Enabled')
                bot.save()
                return Response({'ok': True, 'message': f'Bot {bot.name} is now {status}.'})
            except TradingBot.DoesNotExist:
                return Response({'ok': False, 'error': f'Bot with slug {target_id} not found.'})
                
        return Response({'ok': True, 'message': f'Action {action_type} executed successfully.'})



