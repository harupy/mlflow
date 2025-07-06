"""Thread-safe webhook cache with automatic refresh."""

import logging
import threading
import time
from typing import Any, Optional, Protocol

from mlflow.entities.model_registry.webhook import Webhook

_logger = logging.getLogger(__name__)


class WebhookStore(Protocol):
    """Protocol for webhook store operations."""

    def list_webhooks(
        self, max_results: Optional[int] = None, page_token: Optional[str] = None
    ) -> tuple[list[Webhook], Optional[str]]:
        """List all webhooks."""
        ...


class WebhookCache:
    """
    Thread-safe cache for webhook configurations.

    Features:
    - Automatic periodic refresh of webhook configurations
    - Thread-safe access to cached webhooks
    - Filtering by event type
    - Cache statistics and monitoring
    """

    DEFAULT_REFRESH_INTERVAL = 60  # seconds

    def __init__(self, refresh_interval: int = DEFAULT_REFRESH_INTERVAL):
        self.refresh_interval = refresh_interval

        # Cache storage
        self._webhooks: list[Webhook] = []
        self._lock = threading.RLock()
        self._store: Optional[WebhookStore] = None
        self._last_refresh = 0.0

        # Background refresh thread
        self._refresh_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._shutdown.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_loop, daemon=True, name="WebhookCacheRefresh"
            )
            self._refresh_thread.start()
            self._started = True
            _logger.debug(f"Started webhook cache with {self.refresh_interval}s refresh interval")

    def stop(self) -> None:
        if self._started:
            _logger.debug("Stopping webhook cache...")
            self._shutdown.set()

            if self._refresh_thread is not None:
                self._refresh_thread.join(timeout=5)
                self._refresh_thread = None

            self._started = False
            _logger.debug("Webhook cache stopped")

    def set_store(self, store: WebhookStore) -> None:
        with self._lock:
            if self._store != store:
                self._store = store
                self._refresh_cache()
                _logger.debug("Webhook store updated and cache refreshed")

    def get_webhooks(self) -> list[Webhook]:
        with self._lock:
            return self._webhooks.copy()

    def get_active_webhooks_for_event(self, event_type: str) -> list[Webhook]:
        with self._lock:
            return [
                webhook
                for webhook in self._webhooks
                if webhook.should_trigger_for_event(event_type)
            ]

    def refresh(self) -> None:
        with self._lock:
            if self._store is not None:
                self._refresh_cache()
                _logger.debug("Manual webhook cache refresh completed")

    def get_info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "webhook_count": len(self._webhooks),
                "last_refresh": self._last_refresh,
                "cache_age_seconds": (
                    time.time() - self._last_refresh if self._last_refresh > 0 else None
                ),
                "refresh_interval": self.refresh_interval,
                "is_running": self._started,
                "has_store": self._store is not None,
            }

    def _refresh_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                # Wait for refresh interval or shutdown signal
                if self._shutdown.wait(timeout=self.refresh_interval):
                    break  # Shutdown signal received

                # Refresh cache if we have a store
                with self._lock:
                    if self._store is not None:
                        self._refresh_cache()

            except Exception as e:
                _logger.error(f"Error in webhook cache refresh loop: {e!s}")

    def _refresh_cache(self) -> None:
        if self._store is None:
            return

        try:
            # Fetch fresh webhooks from store
            webhooks_list, _ = self._store.list_webhooks()
            self._webhooks = webhooks_list
            self._last_refresh = time.time()

            _logger.debug(f"Refreshed webhook cache with {len(self._webhooks)} webhooks")

        except Exception as e:
            _logger.error(f"Failed to refresh webhook cache: {e!s}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
