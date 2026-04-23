import logging

from mlflow.gateway.config import EndpointConfig, _OpenAICompatibleConfig
from mlflow.gateway.providers.openai_compatible import OpenAICompatibleProvider

_logger = logging.getLogger(__name__)


class OllamaConfig(_OpenAICompatibleConfig):
    # Ollama runs locally and doesn't require an API key by default
    api_key: str = "ollama"


class OllamaProvider(OpenAICompatibleProvider):
    DISPLAY_NAME = "Ollama"
    CONFIG_TYPE = OllamaConfig
    DEFAULT_API_BASE = "http://localhost:11434/v1"

    def __init__(self, config: EndpointConfig, enable_tracing: bool = False) -> None:
        super().__init__(config, enable_tracing=enable_tracing)
        _logger.debug(
            "[gateway-debug] OllamaProvider initialized: api_base=%s, model=%s, "
            "api_key_is_default=%s, config_type=%s",
            self._api_base,
            config.model.name,
            self._provider_config.api_key == "ollama",
            type(self._provider_config).__name__,
        )

    @property
    def headers(self) -> dict[str, str]:
        # Ollama doesn't require auth — only send Authorization if a real key was set
        if self._provider_config.api_key and self._provider_config.api_key != "ollama":
            return {"Authorization": f"Bearer {self._provider_config.api_key}"}
        return {}
