"""MQTT Application Library - A comprehensive async MQTT application framework.

This library provides a complete asynchronous MQTT application framework with:
- Async MQTT client with automatic reconnection
- Command handler for processing MQTT messages
- Periodic status publisher
- Worker system for concurrent message processing
- Configuration management with YAML support

Example:
    Basic usage:

    >>> from mqtt_application import AsyncMqttClient, AppConfig
    >>> from mqtt_logger import MqttLogger
    >>> import asyncio
    >>>
    >>> async def main():
    ...     async with MqttLogger(...) as logger:
    ...         client = AsyncMqttClient(
    ...             broker_address="localhost",
    ...             port=1883,
    ...             topics=["test/topic"],
    ...             message_queue=asyncio.Queue(),
    ...             logger=logger
    ...         )
    ...         await client.connect_and_subscribe()
"""

from .application import MqttApplication
from .command_handler import AsyncCommandHandler, MqttErrorCode
from .config import AppConfig, ConfigError, load_config
from .connection_manager import MqttConnectionManager
from .mqtt_client import AsyncMqttClient
from .status_publisher import PeriodicStatusPublisher, StatusValidationError
from .worker import async_worker, create_worker_pool

try:
    import importlib.metadata

    __version__ = importlib.metadata.version("muxu-io-mqtt-application")
except (importlib.metadata.PackageNotFoundError, ImportError):
    __version__ = "unknown"
__author__ = "Alex Gonzalez"
__email__ = "alex@muxu.io"
__description__ = "A comprehensive asynchronous MQTT application framework"
__license__ = "MIT"

__all__ = [
    # Core classes
    "AsyncMqttClient",
    "AsyncCommandHandler",
    "PeriodicStatusPublisher",
    "StatusValidationError",
    "MqttConnectionManager",
    "MqttApplication",
    # Configuration
    "ConfigError",
    "AppConfig",
    "load_config",
    # Error handling
    "MqttErrorCode",
    # Workers
    "async_worker",
    "create_worker_pool",
    # Metadata
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    "__license__",
]
