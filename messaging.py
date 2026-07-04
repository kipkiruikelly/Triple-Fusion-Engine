"""
messaging.py
Lightweight inter-service message queue abstraction.

Provides a uniform pub/sub interface that works with Redis in production
and falls back to an in-memory queue in development when Redis is
unavailable. Used by the microservice architecture for:

  - Prediction requests (web → predictor service)
  - Trading signals (predictor → trader service)
  - Data pipeline completion notifications
  - Model training job submissions

Usage:
    from messaging import get_queue
    q = get_queue()
    q.publish("predictions.requested", {"ticker": "AAPL"})

Author: BullLogic
"""

import json
import logging
import threading
from collections import deque
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# ── Abstract interface ──────────────────────────────────────────────────────────

class MessageQueue:
    """Abstract message queue with pub/sub semantics."""

    def publish(self, channel: str, message: dict) -> None:
        raise NotImplementedError

    def subscribe(self, channel: str, callback: Callable[[dict], None]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# ── In-Memory Queue (development / no Redis) ────────────────────────────────────

class InMemoryQueue(MessageQueue):
    """Thread-safe in-memory message queue for single-process development.

    Each channel holds up to 1000 messages; older messages are dropped.
    Supports multiple subscribers per channel with regex channel patterns.
    """

    def __init__(self, maxlen: int = 1000):
        self._channels: Dict[str, deque] = {}
        self._subscribers: Dict[str, list] = {}
        self._lock = threading.Lock()
        self._maxlen = maxlen

    def publish(self, channel: str, message: dict) -> None:
        with self._lock:
            if channel not in self._channels:
                self._channels[channel] = deque(maxlen=self._maxlen)
            self._channels[channel].append(message)

        # Notify subscribers
        subs = self._subscribers.get(channel, [])
        for cb in subs:
            try:
                cb(message)
            except Exception as e:
                logger.error("Subscriber callback error on channel '%s': %s", channel, e)

    def subscribe(self, channel: str, callback: Callable[[dict], None]) -> None:
        with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(callback)

        # Deliver any backlog
        backlog = self._channels.get(channel, deque())
        for msg in list(backlog):
            try:
                callback(msg)
            except Exception as e:
                logger.error("Backlog delivery error on channel '%s': %s", channel, e)

    def close(self) -> None:
        with self._lock:
            self._channels.clear()
            self._subscribers.clear()


# ── Redis Queue (production) ────────────────────────────────────────────────────

class RedisQueue(MessageQueue):
    """Redis-backed pub/sub queue for multi-process/multi-container setups.

    Requires a running Redis instance accessible at REDIS_URL.
    Falls back to InMemoryQueue if Redis is unavailable.
    """

    def __init__(self, redis_url: str = ""):
        self._redis = None
        self._pubsub = None
        self._listener_thread = None
        self._callbacks: Dict[str, list] = {}
        self._fallback = InMemoryQueue()

        if not redis_url:
            logger.info("No REDIS_URL configured; using in-memory queue")
            return

        try:
            import redis
            self._redis = redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
            self._pubsub = self._redis.pubsub()
            logger.info("Connected to Redis at %s", redis_url)
        except ImportError:
            logger.warning("redis-py not installed; using in-memory queue")
        except Exception as e:
            logger.warning("Redis connection failed (%s); using in-memory queue", e)
            self._redis = None

    def publish(self, channel: str, message: dict) -> None:
        if self._redis:
            try:
                self._redis.publish(channel, json.dumps(message))
            except Exception as e:
                logger.error("Redis publish failed: %s", e)

        # Always publish to fallback for local subscribers
        self._fallback.publish(channel, message)

    def subscribe(self, channel: str, callback: Callable[[dict], None]) -> None:
        self._fallback.subscribe(channel, callback)

        if self._redis and self._pubsub:
            try:
                self._pubsub.subscribe(**{channel: lambda msg: self._on_redis_message(msg, callback)})
                if not self._listener_thread or not self._listener_thread.is_alive():
                    self._listener_thread = threading.Thread(
                        target=self._pubsub.run_in_thread, daemon=True,
                        name="redis-listener",
                    )
                    self._listener_thread.start()
            except Exception as e:
                logger.error("Redis subscribe failed: %s", e)

    def _on_redis_message(self, msg: dict, callback: Callable[[dict], None]) -> None:
        """Handle incoming Redis pub/sub message."""
        if msg.get("type") != "message":
            return
        try:
            data = json.loads(msg["data"])
            callback(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Invalid Redis message: %s", e)

    def close(self) -> None:
        if self._pubsub:
            try:
                self._pubsub.close()
            except Exception:
                pass
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
        self._fallback.close()


# ── Singleton ───────────────────────────────────────────────────────────────────

_queue: Optional[MessageQueue] = None
_lock = threading.Lock()


def get_queue() -> MessageQueue:
    """Return the singleton message queue, creating it on first call."""
    global _queue
    if _queue is None:
        with _lock:
            if _queue is None:
                try:
                    from config import settings
                    if settings.USE_REDIS and settings.REDIS_URL:
                        _queue = RedisQueue(settings.REDIS_URL)
                    else:
                        _queue = InMemoryQueue()
                except ImportError:
                    _queue = InMemoryQueue()
    return _queue


def reset_queue() -> None:
    """Reset the queue singleton (used in tests)."""
    global _queue
    if _queue:
        _queue.close()
    _queue = None
