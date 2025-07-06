"""Webhook dispatcher with automatic failure handling."""

import hashlib
import hmac
import json
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import requests

from mlflow.entities.model_registry.webhook import Webhook
from mlflow.environment_variables import MLFLOW_WEBHOOKS_ALLOWED_SCHEMES
from mlflow.store.model_registry.abstract_store import AbstractStore
from mlflow.webhooks.webhook_cache import WebhookCache

_logger = logging.getLogger(__name__)


@dataclass
class WebhookDispatchTask:
    """Represents a webhook dispatch task in the queue."""

    webhook: Webhook
    event_type: str
    payload: dict[str, Any]
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    delivery_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class WebhookDispatchResult:
    """Result of webhook dispatch attempt."""

    webhook_id: str
    success: bool
    delivery_id: str
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    retry_count: int = 0


class WebhookStore(Protocol):
    """Protocol for webhook store operations."""

    def list_webhooks(self) -> list[Webhook]:
        """List all webhooks."""
        ...

    def update_webhook(self, webhook_id: str, **kwargs) -> Webhook:
        """Update webhook properties."""
        ...


class WebhookDispatcher:
    """
    Webhook dispatcher with automatic failure handling.

    Features:
    - Non-blocking webhook dispatch using thread pool
    - Automatic retry with exponential backoff
    - Auto-disable webhooks after consecutive failures (configurable)
    - Configurable dispatch queue and worker pool
    - Periodic webhook cache refresh for improved performance
    """

    DEFAULT_TIMEOUT_SECONDS = 10
    MAX_PAYLOAD_SIZE = 1024 * 1024  # 1MB
    MAX_RETRY_COUNT = 3
    MAX_CONSECUTIVE_FAILURES = 5
    RETRY_DELAYS = (1, 2, 4)  # Exponential backoff in seconds
    DEFAULT_CACHE_REFRESH_INTERVAL = 60  # Refresh webhook cache every 60 seconds

    def __init__(
        self,
        store: AbstractStore,
        max_workers: int = 5,
        queue_size: int = 1000,
        auto_disable_on_failure: bool = True,
        cache_refresh_interval: int = DEFAULT_CACHE_REFRESH_INTERVAL,
    ):
        """
        Initialize the webhook dispatcher.

        Args:
            store: The model registry store to fetch webhooks from
            max_workers: Maximum number of concurrent dispatch workers
            queue_size: Maximum size of the dispatch queue
            auto_disable_on_failure: Automatically disable webhooks after consecutive failures
            cache_refresh_interval: Interval in seconds for refreshing webhook cache
        """
        self.store = store
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.auto_disable_on_failure = auto_disable_on_failure

        # Dispatch queue and thread pool
        self._dispatch_queue: queue.Queue[Optional[WebhookDispatchTask]] = queue.Queue(
            maxsize=queue_size
        )
        self._executor: Optional[ThreadPoolExecutor] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

        # Webhook cache
        self._webhook_cache = WebhookCache(refresh_interval=cache_refresh_interval)
        self._webhook_cache.set_store(store)

        # Track webhook failures for auto-sync
        self._failure_counts: dict[str, int] = {}
        self._failure_lock = threading.Lock()

        # Start the service
        self.start()

    def start(self) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="MlflowWebhookExecutor"
            )
            self._worker_thread = threading.Thread(
                target=self._process_queue, daemon=True, name="MlflowWebhookDispatcherWorker"
            )
            self._worker_thread.start()
            self._webhook_cache.start()
            _logger.debug(f"Started webhook dispatcher with {self.max_workers} workers")

    def stop(self) -> None:
        if self._executor is not None:
            _logger.debug("Shutting down webhook dispatcher...")
            self._shutdown.set()

            # Signal worker thread to stop
            self._dispatch_queue.put(None)

            # Wait for worker thread to finish
            if self._worker_thread is not None:
                self._worker_thread.join(timeout=5)

            # Stop webhook cache
            self._webhook_cache.stop()

            # Shutdown executor
            self._executor.shutdown(wait=True)
            self._executor = None
            self._worker_thread = None
            self._shutdown.clear()
            _logger.debug("Webhook dispatcher stopped")

    def dispatch_webhook(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Dispatch webhooks for a specific event type asynchronously.

        Args:
            event_type: The type of event that occurred
            payload: The event data to send
        """
        try:
            # Get active webhooks for this event type
            active_webhooks = self._webhook_cache.get_active_webhooks_for_event(event_type)

            if not active_webhooks:
                _logger.debug(f"No active webhooks found for event type: {event_type}")
                return

            # Queue for asynchronous dispatch
            for webhook in active_webhooks:
                delivery_id = str(uuid.uuid4())
                webhook_payload = self._build_webhook_payload(event_type, payload, delivery_id)
                task = WebhookDispatchTask(
                    webhook=webhook,
                    event_type=event_type,
                    payload=webhook_payload,
                    delivery_id=delivery_id,
                )
                try:
                    self._dispatch_queue.put_nowait(task)
                    _logger.debug(
                        f"Queued webhook {webhook.id} (delivery {task.delivery_id}) "
                        f"for event {event_type}"
                    )
                except queue.Full:
                    _logger.warning(
                        f"Webhook dispatch queue is full, dropping webhook {webhook.id}"
                    )

        except Exception as e:
            _logger.error(f"Error in webhook dispatcher: {e!s}")

    def _process_queue(self) -> None:
        """Process webhook dispatch tasks from the queue."""
        while not self._shutdown.is_set():
            try:
                # Get task from queue with timeout
                task = self._dispatch_queue.get(timeout=1)

                if task is None:
                    # Shutdown signal
                    break

                # Submit task to executor
                if self._executor is not None:
                    self._executor.submit(self._process_dispatch_task, task)

            except queue.Empty:
                continue
            except Exception as e:
                _logger.error(f"Error processing dispatch queue: {e!s}")

    def _process_dispatch_task(self, task: WebhookDispatchTask) -> None:
        webhook = task.webhook

        # Attempt dispatch
        result = self._send_webhook_request(webhook, task.payload, task.delivery_id)

        if not result.success and task.retry_count < self.MAX_RETRY_COUNT:
            # Schedule retry with exponential backoff
            retry_delay = self.RETRY_DELAYS[task.retry_count]
            _logger.debug(
                f"Retrying webhook {webhook.id} (delivery {task.delivery_id}) after {retry_delay}s "
                f"(attempt {task.retry_count + 1}/{self.MAX_RETRY_COUNT})"
            )

            # Sleep before retry
            time.sleep(retry_delay)

            # Create retry task
            retry_task = WebhookDispatchTask(
                webhook=webhook,
                event_type=task.event_type,
                payload=task.payload,
                retry_count=task.retry_count + 1,
                created_at=task.created_at,
                delivery_id=task.delivery_id,
            )

            # Re-queue the task
            try:
                self._dispatch_queue.put_nowait(retry_task)
            except queue.Full:
                _logger.warning(
                    f"Cannot retry webhook {webhook.id} (delivery {task.delivery_id}), "
                    f"queue is full"
                )
                self._handle_dispatch_failure(webhook, result)

        elif not result.success:
            # Max retries exceeded
            _logger.error(
                f"Webhook {webhook.id} (delivery {task.delivery_id}) failed after "
                f"{task.retry_count} retries: {result.error_message}"
            )
            self._handle_dispatch_failure(webhook, result)

        else:
            # Success - reset failure count
            self._reset_failure_count(webhook.id)
            _logger.debug(
                f"Successfully dispatched webhook {webhook.id} (delivery {task.delivery_id}) "
                f"for event {task.event_type}"
            )

    def _handle_dispatch_failure(
        self,
        webhook: Webhook,
        result: WebhookDispatchResult,
    ) -> None:
        """Handle webhook delivery failure and potentially disable the webhook."""
        if not self.auto_disable_on_failure:
            return

        with self._failure_lock:
            # Increment failure count
            webhook_id = webhook.id
            self._failure_counts[webhook_id] = self._failure_counts.get(webhook_id, 0) + 1
            failure_count = self._failure_counts[webhook_id]

            _logger.warning(f"Webhook {webhook_id} has failed {failure_count} times consecutively")

            # Auto-disable webhook after too many failures
            if failure_count >= self.MAX_CONSECUTIVE_FAILURES:
                try:
                    from mlflow.entities.model_registry.webhook import WebhookStatus

                    self.store.update_webhook(
                        webhook_id=webhook_id,
                        status=WebhookStatus.DISABLED,
                    )
                    _logger.warning(
                        f"Auto-disabled webhook {webhook_id} after "
                        f"{self.MAX_CONSECUTIVE_FAILURES} consecutive failures"
                    )

                    # Reset failure count after disabling
                    self._failure_counts[webhook_id] = 0

                    # Force cache refresh to pick up the status change
                    self._webhook_cache.refresh()

                except Exception as e:
                    _logger.error(f"Failed to auto-disable webhook {webhook_id}: {e!s}")

    def _reset_failure_count(self, webhook_id: str) -> None:
        with self._failure_lock:
            if webhook_id in self._failure_counts:
                del self._failure_counts[webhook_id]

    def _send_webhook_request(
        self,
        webhook: Webhook,
        payload: dict[str, Any],
        delivery_id: str,
    ) -> WebhookDispatchResult:
        start_time = time.time()

        try:
            # Validate URL scheme
            allowed_schemes = MLFLOW_WEBHOOKS_ALLOWED_SCHEMES.get()
            url_scheme = webhook.url.split("://")[0].lower()
            if url_scheme not in allowed_schemes:
                return WebhookDispatchResult(
                    webhook_id=webhook.id,
                    success=False,
                    delivery_id=delivery_id,
                    error_message=f"URL scheme '{url_scheme}' not allowed. "
                    f"Allowed schemes: {', '.join(allowed_schemes)}",
                )

            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "MLflow-Webhook/1.0",
                "X-MLflow-Event": payload["event_type"],
                "X-MLflow-Delivery": delivery_id,
            }

            # Convert payload to JSON
            payload_json = json.dumps(payload)
            payload_bytes = payload_json.encode("utf-8")

            # Check payload size
            if len(payload_bytes) > self.MAX_PAYLOAD_SIZE:
                return WebhookDispatchResult(
                    webhook_id=webhook.id,
                    success=False,
                    delivery_id=delivery_id,
                    error_message=f"Payload size ({len(payload_bytes)} bytes) exceeds maximum "
                    f"allowed size ({self.MAX_PAYLOAD_SIZE} bytes)",
                )

            # Add HMAC signature support if webhook has a secret
            if webhook.secret:
                signature = self._sign_payload(payload_bytes, webhook.secret)
                headers["X-MLflow-Signature"] = f"sha256={signature}"

            # Send the request
            response = requests.post(
                webhook.url,
                data=payload_json,
                headers=headers,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )

            response_time_ms = int((time.time() - start_time) * 1000)

            # Check response status
            response.raise_for_status()

            return WebhookDispatchResult(
                webhook_id=webhook.id,
                success=True,
                delivery_id=delivery_id,
                response_status=response.status_code,
                response_body=response.text[:1000],  # Truncate large responses
                response_time_ms=response_time_ms,
            )

        except requests.exceptions.Timeout:
            return WebhookDispatchResult(
                webhook_id=webhook.id,
                success=False,
                delivery_id=delivery_id,
                error_message=f"Request timeout after {self.DEFAULT_TIMEOUT_SECONDS} seconds",
                response_time_ms=int((time.time() - start_time) * 1000),
            )
        except requests.exceptions.RequestException as e:
            return WebhookDispatchResult(
                webhook_id=webhook.id,
                success=False,
                delivery_id=delivery_id,
                error_message=f"Request failed: {e!s}",
                response_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return WebhookDispatchResult(
                webhook_id=webhook.id,
                success=False,
                delivery_id=delivery_id,
                error_message=f"Unexpected error: {e!s}",
                response_time_ms=int((time.time() - start_time) * 1000),
            )

    def _build_webhook_payload(
        self,
        event_type: str,
        data: dict[str, Any],
        delivery_id: str,
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "timestamp": int(time.time() * 1000),
            "delivery_id": delivery_id,
            "data": data,
        }

    def _sign_payload(self, payload: bytes, secret: str) -> str:
        """
        Generate HMAC-SHA256 signature for webhook payload.

        This creates a cryptographic signature that webhook receivers can use
        to verify the payload came from MLflow and hasn't been tampered with.

        Args:
            payload: The webhook payload as bytes
            secret: The webhook's secret key for signing

        Returns:
            Hex-encoded HMAC-SHA256 signature
        """
        return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def get_queue_size(self) -> int:
        return self._dispatch_queue.qsize()

    def get_failure_counts(self) -> dict[str, int]:
        with self._failure_lock:
            return self._failure_counts.copy()

    def get_cache_info(self) -> dict[str, Any]:
        return self._webhook_cache.get_info()

    def force_cache_refresh(self) -> None:
        self._webhook_cache.refresh()
        _logger.debug("Forced webhook cache refresh completed")


# Global instances for singleton pattern (one per store)
_webhook_dispatchers: dict[AbstractStore, WebhookDispatcher] = {}
_service_lock = threading.Lock()


def get_webhook_dispatcher(
    store: AbstractStore,
    max_workers: int = 5,
    queue_size: int = 1000,
    auto_disable_on_failure: bool = True,
    cache_refresh_interval: int = WebhookDispatcher.DEFAULT_CACHE_REFRESH_INTERVAL,
) -> WebhookDispatcher:
    """
    Get or create a webhook dispatcher instance for the given store.

    This ensures we have a single dispatcher instance per store.
    """
    global _webhook_dispatchers  # noqa: PLW0602

    with _service_lock:
        if store not in _webhook_dispatchers:
            _webhook_dispatchers[store] = WebhookDispatcher(
                store=store,
                max_workers=max_workers,
                queue_size=queue_size,
                auto_disable_on_failure=auto_disable_on_failure,
                cache_refresh_interval=cache_refresh_interval,
            )
        return _webhook_dispatchers[store]


def shutdown_webhook_dispatcher(store: Optional[AbstractStore] = None) -> None:
    """
    Shutdown webhook dispatcher(s).

    Args:
        store: If provided, shutdown only the dispatcher for this store.
               If None, shutdown all dispatchers.
    """
    global _webhook_dispatchers  # noqa: PLW0602

    with _service_lock:
        if store is not None:
            # Shutdown specific dispatcher
            if store in _webhook_dispatchers:
                _webhook_dispatchers[store].stop()
                del _webhook_dispatchers[store]
        else:
            # Shutdown all dispatchers
            for dispatcher in _webhook_dispatchers.values():
                dispatcher.stop()
            _webhook_dispatchers.clear()
