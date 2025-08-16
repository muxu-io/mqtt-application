"""Simplified MQTT Application class for easy initialization and management."""

import asyncio
import os
import signal
import sys
from typing import Any, Callable, Optional

from mqtt_logger import MqttLogger

from .command_handler import AsyncCommandHandler
from .config import AppConfig
from .connection_manager import MqttConnectionManager
from .mqtt_client import AsyncMqttClient
from .status_publisher import PeriodicStatusPublisher
from .worker import create_worker_pool


class MqttApplication:
    """Simplified MQTT application that handles all component initialization and lifecycle.

    This class provides a simple interface for creating MQTT applications by reading
    configuration from config.yaml and automatically setting up all components.

    Example:
        Basic usage:

        >>> async def main():
        ...     async with MqttApplication() as app:
        ...         await app.run()

        With custom commands:

        >>> async def main():
        ...     async with MqttApplication() as app:
        ...         app.register_command("my_command", my_handler)
        ...         await app.run()

        Standalone usage:

        >>> if __name__ == "__main__":
        ...     MqttApplication.run_from_config()
    """

    def __init__(
        self,
        config_file: Optional[str] = None,
        config_override: Optional[dict[str, Any]] = None,
        callback_context: Optional[Any] = None,
    ):
        """Initialize the MQTT application.

        Args:
            config_file: Path to config file (defaults to config.yaml)
            config_override: Override configuration values
            callback_context: Object that contains callback methods referenced in config
                              (defaults to self)
        """
        self.config_file = config_file
        self.config_override = config_override or {}
        self._callback_context = callback_context if callback_context is not None else self

        # Components (initialized in __aenter__)
        self.app_config: dict[str, Any] = {}
        self.logger: Optional[MqttLogger] = None
        self.connection_manager: Optional[MqttConnectionManager] = None
        self.command_handler: Optional[AsyncCommandHandler] = None
        self.status_publisher: Optional[PeriodicStatusPublisher] = None
        self.mqtt_client: Optional[AsyncMqttClient] = None
        self.message_queue: Optional[asyncio.Queue] = None
        self.worker_tasks: list[asyncio.Task] = []
        self.mqtt_task: Optional[asyncio.Task] = None

        # Custom command handlers
        self._custom_commands: dict[str, Callable] = {}

        # Custom callback handlers for subscriptions
        self._callback_handlers: dict[str, Callable] = {}

        # Running state
        self._running = False

    async def __aenter__(self):
        """Async context manager entry - initialize all components."""
        await self._initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup all components."""
        await self._cleanup()

    def register_command(self, command_name: str, handler: Callable):
        """Register a custom command handler.

        Args:
            command_name: Name of the command to handle
            handler: Async or sync function to handle the command
        """
        self._custom_commands[command_name] = handler

    def register_callback_handler(self, method_name: str, handler: Callable):
        """Register a custom callback handler for subscriptions.

        Args:
            method_name: Name of the callback method referenced in config
            handler: Async or sync function to handle the callback
        """
        self._callback_handlers[method_name] = handler

    def update_status(self, values: dict[str, Any]) -> None:
        """Update the status payload with current system values.

        Args:
            values: Dictionary of field names and their current values
                   Fields should match those defined in config.yaml status.payload

        Raises:
            StatusValidationError: If the values don't match the config schema
        """
        if self.status_publisher:
            self.status_publisher.update_status_payload(values)
        else:
            if self.logger:
                self.logger.warning("Cannot update status: status publisher not initialized")

    async def run(self):
        """Run the application until interrupted."""
        if not self.logger:
            raise RuntimeError("Application not initialized. Use 'async with MqttApplication():'")

        self._running = True
        self.logger.info("Starting MQTT application...")

        try:
            # Start all services
            await self._start_services()

            # Run until interrupted
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            self.logger.info("Application received cancellation signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in application: {e}")
            raise
        finally:
            await self._stop_services()

    def stop(self):
        """Stop the application gracefully."""
        self._running = False

    async def _initialize(self):
        """Initialize all components from configuration."""
        # Load configuration
        self.app_config = self._create_app_config()

        # Create logger
        self.logger = self._create_logger()
        if self.logger:
            await self.logger.__aenter__()

        # Create components
        await self._create_components()

        # Register custom commands
        if self.command_handler:
            for cmd_name, handler in self._custom_commands.items():
                self.command_handler.commands[cmd_name] = handler

        # Register config-based subscriptions
        await self._register_config_subscriptions()

    async def _register_config_subscriptions(self):
        """Register callbacks for subscriptions defined in config.yaml."""
        if not self.connection_manager:
            return

        # Load the raw config to get subscriptions
        from .config import AppConfig

        app_config_instance = AppConfig.from_file(self.config_file or "config.yaml")

        for (
            subscription_name,
            subscription,
        ) in app_config_instance.subscriptions.items():
            callback_method_name = subscription.callback_method
            topic_pattern = subscription.topic_pattern

            # Resolve the callback function
            callback_func = self._resolve_callback_method(callback_method_name)

            if callback_func:
                self.connection_manager.register_callback(topic_pattern, callback_func)
                if self.logger:
                    self.logger.info(
                        f"Registered callback '{callback_method_name}' "
                        f"for topic pattern '{topic_pattern}' (subscription: {subscription_name})"
                    )
            else:
                if self.logger:
                    self.logger.warning(
                        f"Could not resolve callback method '{callback_method_name}' "
                        f"for subscription '{subscription_name}'"
                    )

    def _resolve_callback_method(self, method_name: str) -> Optional[Callable]:
        """Resolve a callback method by name.

        Args:
            method_name: Name of the method to resolve

        Returns:
            The callback function if found, None otherwise
        """
        # First check custom registered handlers
        if method_name in self._callback_handlers:
            return self._callback_handlers[method_name]

        # Then check callback context (defaults to self)
        if self._callback_context and hasattr(self._callback_context, method_name):
            attr = getattr(self._callback_context, method_name)
            if callable(attr):
                return attr

        return None

    async def _cleanup(self):
        """Cleanup all components."""
        if self.logger:
            await self.logger.__aexit__(None, None, None)

    def _create_app_config(self) -> dict[str, Any]:
        """Create application configuration with defaults and overrides."""
        # Create config instance with custom file if specified
        app_config_instance = AppConfig.from_file(self.config_file or "config.yaml")

        # Extract values from the new config structure
        device_id = app_config_instance.device.device_id
        namespace = app_config_instance.namespace

        app_config = {
            "device_id": device_id,
            "namespace": namespace,
            "status_interval": app_config_instance.device.status_publish_interval,
            "worker_count": app_config_instance.workers.count,
            "log_file": app_config_instance.logger.log_file,
            "log_level": app_config_instance.get_log_level_int(),
            "mqtt": app_config_instance.get_mqtt_config(),
            # Status payload configuration - get from YAML file directly
            "status_payload": {},  # This would need to be handled separately if needed
        }

        # Apply overrides
        app_config = self._merge_config(app_config, self.config_override)

        # Build topics and log file with final device_id and namespace values
        final_device_id = app_config["device_id"]
        final_namespace = app_config["namespace"]

        app_config["topics"] = {
            "command": f"{final_namespace}/{final_device_id}/cmd/#",
            "log": f"{final_namespace}/{final_device_id}/logs",
            "status_ack": f"{final_namespace}/{final_device_id}/status/ack",
            "status_completion": (f"{final_namespace}/{final_device_id}/status/completion"),
            "status_current": f"{final_namespace}/{final_device_id}/status/current",
        }

        # Format log file with final values
        app_config["log_file"] = app_config_instance.logger.log_file.format(
            namespace=final_namespace, device_id=final_device_id
        )

        return app_config

    def _create_logger(self) -> MqttLogger:
        """Create configured MQTT logger."""
        return MqttLogger(
            log_file=self.app_config["log_file"],
            mqtt_broker=self.app_config["mqtt"]["mqtt_broker"],
            mqtt_port=self.app_config["mqtt"]["mqtt_port"],
            mqtt_topic=self.app_config["topics"]["log"],
            log_level=self.app_config["log_level"],
            reconnect_interval=self.app_config["mqtt"]["reconnect_interval"],
            max_reconnect_attempts=self.app_config["mqtt"]["max_reconnect_attempts"],
            throttle_interval=self.app_config["mqtt"]["throttle_interval"],
            enable_stdout=os.environ.get("MQTT_LOGGER_ENABLE_STDOUT", "false").lower() in ("true", "1", "yes", "on"),
        )

    async def _create_components(self):
        """Create and configure all application components."""
        if not self.logger:
            raise RuntimeError("Logger not initialized")

        # Create message queue
        self.message_queue = asyncio.Queue()

        # Create shared connection manager
        self.connection_manager = MqttConnectionManager(
            broker=self.app_config["mqtt"]["mqtt_broker"],
            port=self.app_config["mqtt"]["mqtt_port"],
            logger=self.logger,
            reconnect_interval=self.app_config["mqtt"]["reconnect_interval"],
            max_reconnect_attempts=self.app_config["mqtt"]["max_reconnect_attempts"],
        )

        # Create command handler
        command_config = self.app_config.get("commands", {}).get("payload", {})
        self.command_handler = AsyncCommandHandler(
            logger=self.logger,
            ack_topic_pattern=self.app_config["topics"]["status_ack"],
            completion_topic_pattern=self.app_config["topics"]["status_completion"],
            connection_manager=self.connection_manager,
            command_config=command_config,
        )

        # Create status publisher with optimization features
        self.status_publisher = PeriodicStatusPublisher(
            device_id=self.app_config["device_id"],
            logger=self.logger,
            publish_interval=self.app_config["status_interval"],
            status_topic_pattern=self.app_config["topics"]["status_current"],
            connection_manager=self.connection_manager,
            config_status_payload=self.app_config["status_payload"],
            enable_keepalive_publishing=self.app_config.get("enable_keepalive_publishing", False),
        )

        # Link command handler with status publisher
        self.command_handler.set_status_publisher(self.status_publisher)

        # Create MQTT client
        self.mqtt_client = AsyncMqttClient(
            topics=[self.app_config["topics"]["command"]],
            message_queue=self.message_queue,
            logger=self.logger,
            connection_manager=self.connection_manager,
        )

    async def _start_services(self):
        """Start all application services."""
        if not self.logger:
            raise RuntimeError("Components not initialized")

        self.logger.info("Starting application services...")

        # Start status publisher
        if self.status_publisher:
            await self.status_publisher.start()

        # Start MQTT client
        if self.mqtt_client:
            self.mqtt_task = asyncio.create_task(self.mqtt_client.connect_and_subscribe(), name="mqtt-application")

        # Start worker pool
        if self.message_queue and self.command_handler:
            self.worker_tasks = await create_worker_pool(
                self.app_config["worker_count"],
                self.message_queue,
                self.command_handler,
                self.logger,
            )

        self.logger.info(f"Application started with {len(self.worker_tasks)} workers")

    async def _stop_services(self):
        """Stop all application services."""
        if not self.logger:
            return

        self.logger.info("Stopping application services...")

        # Stop status publisher
        if self.status_publisher:
            await self.status_publisher.stop()

        # Cancel all tasks
        if self.mqtt_task:
            self.mqtt_task.cancel()

        for task in self.worker_tasks:
            task.cancel()

        # Wait for tasks to complete
        all_tasks = [self.mqtt_task] + self.worker_tasks if self.mqtt_task else self.worker_tasks
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)

        self.logger.info("Application stopped")

    @staticmethod
    def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge configuration dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = MqttApplication._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def run_from_config(
        cls,
        config_file: Optional[str] = None,
        config_override: Optional[dict[str, Any]] = None,
    ):
        """Run the application directly from configuration (convenience method).

        Args:
            config_file: Path to config file (defaults to config.yaml)
            config_override: Override configuration values
        """

        async def main():
            async with cls(config_file, config_override) as app:
                await app.run()

        # Set up signal handler for graceful shutdown
        def handle_sigint(signum, frame):
            sys.stderr.write("SIGINT received, scheduling shutdown...\n")
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass

        signal.signal(signal.SIGINT, handle_sigint)

        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            sys.stderr.write("KeyboardInterrupt caught, exiting.\n")
        except Exception as e:
            sys.stderr.write(f"Application error: {e}\n")
            sys.exit(1)
