"""core/middleware.py — Custom Django middleware utilities."""

import time
import logging

logger = logging.getLogger(__name__)


class RequestTimingMiddleware:
    """Logs the wall-clock time of every request for performance monitoring."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > 500:
            logger.warning(
                'Slow request: %s %s took %.0f ms',
                request.method, request.path, elapsed_ms,
            )
        return response


class LastSeenMiddleware:
    """Update user.last_seen and gamification metrics on every authenticated request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from datetime import datetime, date, timedelta
            try:
                user = request.user
                today = date.today()
                changed = False

                if user.last_active_date != today:
                    # Award 10 XP for daily activity
                    user.xp = (user.xp or 0) + 10
                    
                    if user.last_active_date == today - timedelta(days=1):
                        user.current_streak = (user.current_streak or 0) + 1
                    else:
                        user.current_streak = 1
                        
                    if user.current_streak > (user.longest_streak or 0):
                        user.longest_streak = user.current_streak
                        
                    # Award 50 XP bonus every 7th consecutive active day
                    if user.current_streak % 7 == 0:
                        user.xp += 50
                        
                    user.last_active_date = today
                    changed = True

                user.last_seen = datetime.utcnow()
                
                if changed:
                    user.save(update_fields=['last_seen', 'last_active_date', 'current_streak', 'longest_streak', 'xp'])
                else:
                    user.save(update_fields=['last_seen'])
            except Exception:
                pass  # Non-fatal

        response = self.get_response(request)
        return response
