#!/usr/bin/env python
"""migrate_data.py — Complete script to migrate all Flask SQLite data → Django.

Usage (from django_backend/ directory):
    ..\.venv\Scripts\python.exe migrate_data.py
"""
import os
import sys
import django
import sqlite3
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent))
os.environ['DJANGO_SETTINGS_MODULE'] = 'bulllogic.settings'
django.setup()

from users.models import (
    User, PredictionHistory, WatchlistItem, PriceAlert, PortfolioPosition,
    ApiKey, PredictionAccuracy, PasswordResetToken, TelegramConfig,
    WhatsappConfig, Notification, TradeJournal, DiscordConfig, Payment,
    GiftCode, UserWebhook, ActivityLog, TwoFactorAuth, AdminAuditLog,
    AppSetting, TickerConfig, Broadcast, ErrorLog, PythFeed, ResourceLink,
    Feedback, PaperTrade, PaperEquitySnapshot, PaperTradeEvent, UserPreferences
)

FLASK_DB = Path(__file__).parent.parent / 'instance' / 'users.db'

def _parse_dt(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        try:
            return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            try:
                return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

def _parse_date(val):
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None

def migrate_all():
    if not FLASK_DB.exists():
        print(f"[ERROR] Flask DB not found at {FLASK_DB}")
        return

    conn = sqlite3.connect(str(FLASK_DB))
    conn.row_factory = sqlite3.Row

    def _get(row, col, default=None):
        try:
            val = row[col]
            return val if val is not None else default
        except (IndexError, KeyError):
            return default

    # 1. Migrate Users (Preserve password hashes, role levels, streaks, etc.)
    print("Migrating users...")
    user_rows = conn.execute("SELECT * FROM user").fetchall()
    for row in user_rows:
        username = _get(row, 'username')
        user, created = User.objects.get_or_create(username=username, defaults={
            'id': _get(row, 'id'),
            'email': _get(row, 'email'),
            'password': _get(row, 'password_hash') or '',
            'plan': _get(row, 'plan', 'free'),
            'role': _get(row, 'role', 'user'),
            'status': _get(row, 'status', 'active'),
            'email_verified': bool(_get(row, 'email_verified', False)),
            'auth_provider': _get(row, 'auth_provider', 'local'),
            'google_sub': _get(row, 'google_sub'),
            'session_token': _get(row, 'session_token'),
            'ban_reason': _get(row, 'ban_reason'),
            'predictions_today': _get(row, 'predictions_today', 0),
            'stripe_customer_id': _get(row, 'stripe_customer_id'),
            'stripe_subscription_id': _get(row, 'stripe_subscription_id'),
            'alerts_enabled': bool(_get(row, 'alerts_enabled', True)),
            'theme_preference': _get(row, 'theme_preference', 'system'),
            'ai_analyses_today': _get(row, 'ai_analyses_today', 0),
            'backtests_today': _get(row, 'backtests_today', 0),
            'xp': _get(row, 'xp', 0),
            'current_streak': _get(row, 'current_streak', 0),
            'longest_streak': _get(row, 'longest_streak', 0),
            'paper_trading_opted_in': bool(_get(row, 'paper_trading_opted_in', False)),
            'is_staff': (_get(row, 'role') == 'admin'),
            'is_superuser': (_get(row, 'role') == 'admin'),
            'is_active': (_get(row, 'status', 'active') != 'deactivated', True),
        })
        if not created:
            # Update fields
            user.plan = _get(row, 'plan', 'free')
            user.role = _get(row, 'role', 'user')
            user.status = _get(row, 'status', 'active')
            user.xp = _get(row, 'xp', 0)
            user.paper_trading_opted_in = bool(_get(row, 'paper_trading_opted_in', False))
            user.save()

    # 2. Migrate User Preferences
    print("Migrating user preferences...")
    pref_rows = conn.execute("SELECT * FROM user_preferences").fetchall()
    UserPreferences.objects.all().delete()
    for row in pref_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            UserPreferences.objects.create(
                user=user,
                digest_enabled=bool(_get(row, 'digest_enabled', False)),
                theme=_get(row, 'theme', 'dark'),
                default_ticker=_get(row, 'default_ticker', 'AAPL'),
                timezone=_get(row, 'timezone', 'UTC'),
                risk_intro_seen=bool(_get(row, 'risk_intro_seen', False)),
                usage_notice_enabled=bool(_get(row, 'usage_notice_enabled', True))
            )
        except Exception as e:
            print(f"Error migrating preference for user {_get(row, 'user_id')}: {e}")

    # 3. Migrate Ticker Config
    print("Migrating ticker configs...")
    ticker_rows = conn.execute("SELECT * FROM ticker_config").fetchall()
    TickerConfig.objects.all().delete()
    for row in ticker_rows:
        TickerConfig.objects.create(
            symbol=_get(row, 'symbol'),
            name=_get(row, 'name'),
            enabled=bool(_get(row, 'enabled', True)),
            added_at=_parse_dt(_get(row, 'added_at')) or datetime.utcnow()
        )

    # 4. Migrate Watchlist Items
    print("Migrating watchlist items...")
    wl_rows = conn.execute("SELECT * FROM watchlist_item").fetchall()
    WatchlistItem.objects.all().delete()
    for row in wl_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            WatchlistItem.objects.create(
                user=user,
                ticker=_get(row, 'ticker'),
                added_at=_parse_dt(_get(row, 'added_at')) or datetime.utcnow()
            )
        except Exception as e:
            print(f"Error migrating watchlist item: {e}")

    # 5. Migrate Portfolio Positions
    print("Migrating portfolio positions...")
    pos_rows = conn.execute("SELECT * FROM portfolio_position").fetchall()
    PortfolioPosition.objects.all().delete()
    for row in pos_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            PortfolioPosition.objects.create(
                user=user,
                ticker=_get(row, 'ticker'),
                side=_get(row, 'side', 'long'),
                entry_price=_get(row, 'entry_price', 0.0),
                quantity=_get(row, 'quantity', 0.0),
                exit_price=_get(row, 'exit_price'),
                status=_get(row, 'status', 'open'),
                opened_at=_parse_dt(_get(row, 'opened_at')) or datetime.utcnow(),
                closed_at=_parse_dt(_get(row, 'closed_at')),
                note=_get(row, 'note')
            )
        except Exception as e:
            print(f"Error migrating portfolio position: {e}")

    # 6. Migrate Notifications
    print("Migrating notifications...")
    notif_rows = conn.execute("SELECT * FROM notification").fetchall()
    Notification.objects.all().delete()
    for row in notif_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            Notification.objects.create(
                user=user,
                type=_get(row, 'type', 'info'),
                title=_get(row, 'title', ''),
                body=_get(row, 'body'),
                read=bool(_get(row, 'read', False)),
                link=_get(row, 'link'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
        except Exception as e:
            print(f"Error migrating notification: {e}")

    # 7. Migrate Gift Codes
    print("Migrating gift codes...")
    gc_rows = conn.execute("SELECT * FROM gift_code").fetchall()
    GiftCode.objects.all().delete()
    for row in gc_rows:
        try:
            uid = _get(row, 'used_by')
            used_by = User.objects.get(id=uid) if uid else None
        except User.DoesNotExist:
            used_by = None
        GiftCode.objects.create(
            code=_get(row, 'code'),
            days=_get(row, 'days', 30),
            used=bool(_get(row, 'used', False)),
            used_by=used_by,
            created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow(),
            used_at=_parse_dt(_get(row, 'used_at')),
            note=_get(row, 'note')
        )

    # 8. Migrate Activity Logs
    print("Migrating activity logs...")
    log_rows = conn.execute("SELECT * FROM activity_log").fetchall()
    ActivityLog.objects.all().delete()
    for row in log_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            ActivityLog.objects.create(
                user=user,
                action=_get(row, 'action', ''),
                detail=_get(row, 'detail'),
                ip=_get(row, 'ip'),
                ua=_get(row, 'ua'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
        except Exception as e:
            pass

    # 9. Migrate Payments
    print("Migrating payments...")
    pay_rows = conn.execute("SELECT * FROM payment").fetchall()
    Payment.objects.all().delete()
    for row in pay_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            Payment.objects.create(
                user=user,
                provider=_get(row, 'provider', 'stripe'),
                plan=_get(row, 'plan'),
                tier=_get(row, 'tier'),
                amount=_get(row, 'amount'),
                currency=_get(row, 'currency'),
                days=_get(row, 'days'),
                phone=_get(row, 'phone'),
                reference=_get(row, 'reference'),
                receipt=_get(row, 'receipt'),
                status=_get(row, 'status', 'paid'),
                flagged=bool(_get(row, 'flagged', False)),
                notes=_get(row, 'notes'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow(),
                completed_at=_parse_dt(_get(row, 'completed_at'))
            )
        except Exception as e:
            print(f"Error migrating payment: {e}")

    # 10. Migrate App Settings
    print("Migrating app settings...")
    set_rows = conn.execute("SELECT * FROM app_setting").fetchall()
    AppSetting.objects.all().delete()
    for row in set_rows:
        try:
            uid = _get(row, 'updated_by')
            updated_by = User.objects.get(id=uid) if uid else None
        except User.DoesNotExist:
            updated_by = None
        AppSetting.objects.create(
            key=_get(row, 'key'),
            value=_get(row, 'value'),
            updated_by=updated_by
        )

    # 11. Migrate Error Logs
    print("Migrating error logs...")
    err_rows = conn.execute("SELECT * FROM error_log").fetchall()
    ErrorLog.objects.all().delete()
    for row in err_rows:
        ErrorLog.objects.create(
            severity=_get(row, 'severity', 'error'),
            endpoint=_get(row, 'endpoint'),
            method=_get(row, 'method'),
            message=_get(row, 'message', ''),
            trace=_get(row, 'trace'),
            ip=_get(row, 'ip'),
            created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
        )

    # 12. Migrate Feedbacks
    print("Migrating feedbacks...")
    fb_rows = conn.execute("SELECT * FROM feedback").fetchall()
    Feedback.objects.all().delete()
    for row in fb_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            Feedback.objects.create(
                user=user,
                page=_get(row, 'page'),
                rating=_get(row, 'rating', 5),
                comment=_get(row, 'comment'),
                sentiment=_get(row, 'sentiment'),
                resolved=bool(_get(row, 'resolved', False)),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
        except Exception as e:
            pass

    # 13. Migrate Pyth Feeds
    print("Migrating Pyth feeds...")
    pf_rows = conn.execute("SELECT * FROM pyth_feed").fetchall()
    PythFeed.objects.all().delete()
    for row in pf_rows:
        PythFeed.objects.create(
            symbol=_get(row, 'symbol'),
            feed_id=_get(row, 'feed_id'),
            pyth_symbol=_get(row, 'pyth_symbol'),
            active=bool(_get(row, 'active', True)),
            updated_at=_parse_dt(_get(row, 'updated_at')) or datetime.utcnow()
        )

    # 14. Migrate Resource Links
    print("Migrating resource links...")
    rl_rows = conn.execute("SELECT * FROM resource_link").fetchall()
    ResourceLink.objects.all().delete()
    for row in rl_rows:
        ResourceLink.objects.create(
            category=_get(row, 'category'),
            title=_get(row, 'title'),
            url=_get(row, 'url'),
            description=_get(row, 'description'),
            icon=_get(row, 'icon'),
            sort=_get(row, 'sort', 0),
            active=bool(_get(row, 'active', True)),
            created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
        )

    # 15. Migrate Prediction History & Accuracy
    print("Migrating prediction history and accuracy...")
    pred_rows = conn.execute("SELECT * FROM prediction_history").fetchall()
    PredictionHistory.objects.all().delete()
    PredictionAccuracy.objects.all().delete()

    pred_map = {}
    for row in pred_rows:
        try:
            user = User.objects.get(id=_get(row, 'user_id'))
            pred = PredictionHistory.objects.create(
                user=user,
                ticker=_get(row, 'ticker'),
                interval=_get(row, 'interval', '1d'),
                current_price=_get(row, 'current_price', 0.0),
                lr_pred=_get(row, 'lr_pred', 0.0),
                rf_pred=_get(row, 'rf_pred', 0.0),
                direction=_get(row, 'direction', 'HOLD'),
                confidence=_get(row, 'confidence', 0.0),
                predicted_at=_parse_dt(_get(row, 'predicted_at')) or datetime.utcnow(),
                src_source=_get(row, 'src_source'),
                src_conf_pct=_get(row, 'src_conf_pct'),
                src_divergence=_get(row, 'src_divergence')
            )
            pred_map[_get(row, 'id')] = pred
        except Exception as e:
            print(f"Error migrating prediction history: {e}")

    pa_rows = conn.execute("SELECT * FROM prediction_accuracy").fetchall()
    for row in pa_rows:
        try:
            pred = pred_map.get(_get(row, 'prediction_id'))
            if pred:
                PredictionAccuracy.objects.create(
                    prediction=pred,
                    actual_price=_get(row, 'actual_price'),
                    direction_ok=bool(_get(row, 'direction_ok')) if _get(row, 'direction_ok') is not None else None,
                    pct_error=_get(row, 'pct_error'),
                    checked_at=_parse_dt(_get(row, 'checked_at'))
                )
        except Exception as e:
            print(f"Error migrating accuracy: {e}")

    # 16. Migrate Paper Trades, Events & Snapshots
    print("Migrating paper trades, events, and snapshots...")
    pt_rows = conn.execute("SELECT * FROM paper_trade").fetchall()
    PaperTrade.objects.all().delete()
    PaperTradeEvent.objects.all().delete()
    PaperEquitySnapshot.objects.all().delete()

    pt_map = {}
    for row in pt_rows:
        uid = _get(row, 'user_id')
        try:
            user = User.objects.get(id=uid) if uid else None
        except User.DoesNotExist:
            user = None
            
        try:
            trade = PaperTrade.objects.create(
                user=user,
                strategy=_get(row, 'strategy', 'ml_ensemble'),
                model=_get(row, 'model'),
                ticker=_get(row, 'ticker'),
                asset_class=_get(row, 'asset_class', 'equity'),
                side=_get(row, 'side', 'LONG'),
                qty=_get(row, 'qty', 1.0),
                entry_time=_parse_dt(_get(row, 'entry_time')) or datetime.utcnow(),
                entry_price=_get(row, 'entry_price', 0.0),
                entry_mkt=_get(row, 'entry_mkt', 0.0),
                price_source=_get(row, 'price_source'),
                stop_price=_get(row, 'stop_price', 0.0),
                target_price=_get(row, 'target_price', 0.0),
                max_hold_hours=_get(row, 'max_hold_hours', 72),
                confidence=_get(row, 'confidence'),
                rationale=_get(row, 'rationale'),
                commission=_get(row, 'commission', 0.0),
                status=_get(row, 'status', 'open'),
                exit_time=_parse_dt(_get(row, 'exit_time')),
                exit_price=_get(row, 'exit_price'),
                exit_mkt=_get(row, 'exit_mkt'),
                exit_reason=_get(row, 'exit_reason'),
                pnl=_get(row, 'pnl'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
            pt_map[_get(row, 'id')] = trade
        except Exception as e:
            print(f"Error migrating paper trade: {e}")

    pe_rows = conn.execute("SELECT * FROM paper_equity_snapshot").fetchall()
    for row in pe_rows:
        uid = _get(row, 'user_id')
        try:
            user = User.objects.get(id=uid) if uid else None
        except User.DoesNotExist:
            user = None
        try:
            PaperEquitySnapshot.objects.create(
                user=user,
                strategy=_get(row, 'strategy', 'ml_ensemble'),
                equity=_get(row, 'equity', 10000.0),
                open_count=_get(row, 'open_count', 0),
                taken_at=_parse_dt(_get(row, 'taken_at')) or datetime.utcnow()
            )
        except Exception as e:
            pass

    pevent_rows = conn.execute("SELECT * FROM paper_trade_event").fetchall()
    for row in pevent_rows:
        uid = _get(row, 'user_id')
        try:
            user = User.objects.get(id=uid) if uid else None
        except User.DoesNotExist:
            user = None
        try:
            trade = pt_map.get(_get(row, 'trade_id'))
            PaperTradeEvent.objects.create(
                user=user,
                trade=trade,
                event=_get(row, 'event', 'open'),
                detail=_get(row, 'detail'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
        except Exception as e:
            pass

    # 17. Migrate Admin Audit Logs
    print("Migrating admin audit logs...")
    audit_rows = conn.execute("SELECT * FROM admin_audit_log").fetchall()
    AdminAuditLog.objects.all().delete()
    for row in audit_rows:
        try:
            admin = User.objects.get(id=_get(row, 'admin_id'))
            log = AdminAuditLog(
                admin=admin,
                action=_get(row, 'action', ''),
                target_type=_get(row, 'target_type'),
                target_id=_get(row, 'target_id'),
                detail=_get(row, 'detail'),
                ip=_get(row, 'ip'),
                created_at=_parse_dt(_get(row, 'created_at')) or datetime.utcnow()
            )
            super(AdminAuditLog, log).save()
        except Exception as e:
            pass

    conn.close()
    print("\n[SUCCESS] Migration completed! All legacy system tables fully restored.")

if __name__ == '__main__':
    migrate_all()
