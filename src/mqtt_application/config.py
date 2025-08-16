"""Configuration module using dataclasses and environment variables."""

import inspect
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml


class ConfigError(Exception):
    """Base configuration error."""

    pass


@dataclass
class MqttConfig:
    """MQTT broker configuration."""

    broker: str = "localhost"
    port: int = 1883
    reconnect_interval: int = 5
    max_reconnect_attempts: int = -1
    throttle_interval: float = 0.1


@dataclass
class DeviceConfig:
    """Device configuration."""

    device_id: str = "default_device"
    status_publish_interval: float = 30.0


@dataclass
class TopicsConfig:
    """Topics configuration."""

    command: str = "{namespace}/+/cmd/#"
    status_ack: str = "{namespace}/{device_id}/status/ack"
    status_completion: str = "{namespace}/{device_id}/status/completion"
    status_current: str = "{namespace}/{device_id}/status/current"
    log: str = "{namespace}/{device_id}/logs"

    def format_topics(self, namespace: str, device_id: str) -> "TopicsConfig":
        """Format topic patterns with namespace and device_id."""
        return TopicsConfig(
            command=self.command.format(namespace=namespace),
            status_ack=self.status_ack.format(namespace=namespace, device_id=device_id),
            status_completion=self.status_completion.format(namespace=namespace, device_id=device_id),
            status_current=self.status_current.format(namespace=namespace, device_id=device_id),
            log=self.log.format(namespace=namespace, device_id=device_id),
        )


@dataclass
class LoggerConfig:
    """Logger configuration."""

    log_file: str = "mqtt_app.log"
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class WorkersConfig:
    """Workers configuration."""

    count: int = 3


@dataclass
class SubscriptionConfig:
    """MQTT subscription configuration."""

    topic_pattern: str
    callback_method: str


@dataclass
class AppConfig:
    """Complete application configuration."""

    mqtt: MqttConfig = field(default_factory=MqttConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    namespace: str = "icsia"
    topics: TopicsConfig = field(default_factory=TopicsConfig)
    logger: LoggerConfig = field(default_factory=LoggerConfig)
    workers: WorkersConfig = field(default_factory=WorkersConfig)
    subscriptions: dict[str, SubscriptionConfig] = field(default_factory=dict)

    @classmethod
    def _find_main_script(cls) -> Optional[str]:
        """Find the main script file using frame inspection."""
        frame = inspect.currentframe()
        try:
            # Go through the entire call stack to find the main module
            while frame:
                frame = frame.f_back
                if frame:
                    # Look for the main script - it will have __name__ == '__main__'
                    frame_globals = frame.f_globals
                    if frame_globals.get("__name__") == "__main__":
                        return frame.f_code.co_filename
            return None
        finally:
            del frame

    @classmethod
    def _resolve_config_path(cls, config_file: str, base_dir: Optional[str]) -> str:
        """Resolve config file path based on various scenarios."""
        if base_dir is not None:
            # Explicit base_dir provided - use it
            if not os.path.isabs(config_file):
                return os.path.join(base_dir, config_file)
            return config_file

        if config_file == "config.yaml":
            # Default config.yaml - look in main script's directory
            main_file = cls._find_main_script()
            if main_file:
                script_dir = os.path.dirname(os.path.abspath(main_file))
                return os.path.join(script_dir, config_file)

        # For any other specified path, ensure it's resolved relative to CWD if not absolute
        if not os.path.isabs(config_file):
            return os.path.abspath(config_file)

        return config_file

    @classmethod
    def _load_yaml_config(cls, config_file: str, base_dir: Optional[str] = None) -> tuple[dict[str, Any], str]:
        """Load YAML config file and return data with original filename."""
        original_config_file = config_file
        resolved_config_file = cls._resolve_config_path(config_file, base_dir)

        if os.path.exists(resolved_config_file):
            with open(resolved_config_file) as f:
                config_data = yaml.safe_load(f) or {}
            return config_data, original_config_file
        else:
            # Warn that no config file was found and defaults will be used
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Configuration file '{original_config_file}' not found (looked in: {resolved_config_file}). "
                f"Using default configuration values."
            )
            return {}, original_config_file

    def _apply_simple_section(self, target_obj: Any, section_data: dict[str, Any]) -> None:
        """Apply a simple key-value section to a target object."""
        for key, value in section_data.items():
            if hasattr(target_obj, key):
                setattr(target_obj, key, value)

    def _apply_topics_section(self, section_data: dict[str, Any]) -> None:
        """Apply the topics section with special handling for nested status topics."""
        for key, value in section_data.items():
            if key == "status" and isinstance(value, dict):
                # Handle nested status topics
                for status_key, status_value in value.items():
                    topic_key = f"status_{status_key}"
                    if hasattr(self.topics, topic_key):
                        setattr(self.topics, topic_key, status_value)
            elif hasattr(self.topics, key):
                setattr(self.topics, key, value)

    def _apply_subscriptions_section(self, section_data: dict[str, Any]) -> None:
        """Apply the subscriptions section to create SubscriptionConfig objects."""
        for subscription_name, subscription_data in section_data.items():
            if isinstance(subscription_data, dict):
                topic_pattern = subscription_data.get("topic_pattern", "")
                callback_method = subscription_data.get("callback_method", "")
                if topic_pattern and callback_method:
                    self.subscriptions[subscription_name] = SubscriptionConfig(
                        topic_pattern=topic_pattern, callback_method=callback_method
                    )

    def _apply_config_section(self, section_name: str, section_data: Any) -> None:
        """Apply a configuration section to the app config."""
        if section_name == "namespace":
            self.namespace = section_data
        elif section_name == "topics" and isinstance(section_data, dict):
            self._apply_topics_section(section_data)
        elif section_name == "subscriptions" and isinstance(section_data, dict):
            self._apply_subscriptions_section(section_data)
        elif isinstance(section_data, dict):
            # Handle simple key-value sections
            target_map = {
                "mqtt": self.mqtt,
                "device": self.device,
                "logger": self.logger,
                "workers": self.workers,
            }
            if section_name in target_map:
                self._apply_simple_section(target_map[section_name], section_data)

    def _merge_config_sections(self, config_data: dict[str, Any]) -> None:
        """Apply all configuration sections to the app config."""
        for section_name, section_data in config_data.items():
            self._apply_config_section(section_name, section_data)

    @classmethod
    def from_file(cls, config_file: str = "config.yaml", base_dir: Optional[str] = None) -> "AppConfig":
        """Load configuration from YAML file with environment variable override.

        Args:
            config_file: Path to config file. If relative and base_dir is None,
                        looks relative to the main script's directory.
            base_dir: Base directory for relative paths. If None, uses the main script's directory.
        """
        # Create config with defaults
        app_config = cls()

        # Load config data from file
        config_data, _ = cls._load_yaml_config(config_file, base_dir)

        # Apply configuration sections
        app_config._merge_config_sections(config_data)

        # Override with environment variables
        app_config._apply_env_overrides()

        return app_config

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        # MQTT overrides
        if broker := os.getenv("MQTT_BROKER"):
            self.mqtt.broker = broker
        if port := os.getenv("MQTT_PORT"):
            self.mqtt.port = int(port)

        # Device overrides
        if device_id := os.getenv("DEVICE_ID"):
            self.device.device_id = device_id
        if interval := os.getenv("STATUS_PUBLISH_INTERVAL"):
            self.device.status_publish_interval = float(interval)

        # Logger overrides
        if log_level := os.getenv("LOG_LEVEL"):
            self.logger.log_level = log_level
        if log_file := os.getenv("LOG_FILE"):
            self.logger.log_file = log_file

        # Workers override
        if worker_count := os.getenv("WORKER_COUNT"):
            self.workers.count = int(worker_count)

    def get_formatted_topics(self) -> TopicsConfig:
        """Get topics with device_id formatting applied."""
        return self.topics.format_topics(self.namespace, self.device.device_id)

    def get_log_level_int(self) -> int:
        """Convert log level string to integer."""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return level_map.get(self.logger.log_level.upper(), logging.INFO)

    def get_mqtt_config(self) -> dict[str, Any]:
        """Get MQTT configuration in the format expected by the application."""
        return {
            "mqtt_broker": self.mqtt.broker,
            "mqtt_port": self.mqtt.port,
            "reconnect_interval": self.mqtt.reconnect_interval,
            "max_reconnect_attempts": self.mqtt.max_reconnect_attempts,
            "throttle_interval": self.mqtt.throttle_interval,
        }

    def get(self, key: str, default=None):
        """Get configuration value using dot notation for backward compatibility."""
        try:
            keys = key.split(".")
            value = self
            for k in keys:
                if hasattr(value, k):
                    value = getattr(value, k)
                else:
                    return default
            return value
        except (AttributeError, KeyError):
            return default

    def get_log_level(self) -> int:
        """Get log level as integer for backward compatibility."""
        return self.get_log_level_int()


# Convenience function for quick setup
def load_config(config_file: str = "config.yaml") -> AppConfig:
    """Load application configuration from file."""
    return AppConfig.from_file(config_file)
