"""Periodic status publisher for MQTT device status messages."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from mqtt_logger import MqttLogger
from .connection_manager import MqttConnectionManager


class StatusValidationError(Exception):
    """Raised when status payload validation fails."""

    pass


class PeriodicStatusPublisher:
    """Publishes system status messages for device topics with intelligent change detection.

    Publishes to: {namespace}/<device_id>/status/current

    Features:
    - Change-only publishing: Only publishes when status actually changes (default: enabled)
    - Retained messages: Uses MQTT retain flag for on-demand status access (default: enabled)
    - Keep-alive publishing: Optional periodic publishing even without changes (configurable)
    - Uses QoS 0 (fire and forget for non-critical status updates)
    - Publishes operational status, last command time, and timestamp
    """

    def __init__(
        self,
        device_id: str,
        logger: MqttLogger,
        connection_manager: MqttConnectionManager,
        publish_interval: float = 30.0,
        enable_keepalive_publishing: bool = False,
        status_topic_pattern: str = "{namespace}/{device_id}/status/current",
        namespace: str = "icsia",
        config_status_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the PeriodicStatusPublisher.

        Args:
            device_id: The device identifier for this system instance
            logger: The logger instance to use for logging
            connection_manager: Shared connection manager
            publish_interval: Seconds between status publications (default: 30.0)
            enable_keepalive_publishing: Enable periodic keep-alive publishing even without changes (default: False)
            status_topic_pattern: Topic pattern for status messages
            namespace: The MQTT topic namespace/prefix
            config_status_payload: Status payload field definitions from config
        """
        self.device_id = device_id
        self.logger = logger
        self.publish_interval = publish_interval
        self.namespace = namespace
        self.status_topic = status_topic_pattern.format(
            namespace=namespace, device_id=device_id
        )

        # System state tracking
        self.operational_status = "idle"  # idle, busy, error
        self.last_command_time: Optional[datetime] = None
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

        # Custom status payload support
        self.config_status_payload = config_status_payload or {}
        self.custom_status_values: Dict[str, Any] = {}
        self.status_payload_fields = self.config_status_payload

        # Use the provided connection manager
        self.connection_manager = connection_manager
        self._owns_connection = False

        # Publishing behavior - optimized by default
        self.enable_change_only_publishing = True  # Always enabled for efficiency
        self.use_retained_messages = True  # Always enabled for on-demand access
        self.enable_keepalive_publishing = enable_keepalive_publishing  # Configurable
        self._last_published_status: Optional[Dict[str, Any]] = None
        self._pending_immediate_publish = False

    def update_status_payload(self, values: Dict[str, Any]) -> None:
        """Update the entire status payload with new values.

        Args:
            values: Dictionary containing field names and their current values
                   Keys should match the fields defined in config.yaml

        Raises:
            StatusValidationError: If the values don't match the config schema
        """
        self._validate_status_payload(values)
        old_values = self.custom_status_values.copy()
        self.custom_status_values.update(values)
        self.logger.debug(f"Status payload updated with: {values}")

        # Trigger immediate publish if values changed
        if old_values != self.custom_status_values:
            self._pending_immediate_publish = True
            self.logger.debug("Status change detected, immediate publish triggered")

    def _validate_status_payload(self, values: Dict[str, Any]) -> None:
        """Validate that status payload values match the config schema.

        Args:
            values: Dictionary containing field names and their current values

        Raises:
            StatusValidationError: If validation fails
        """
        if not self.status_payload_fields:
            # No config schema defined, accept any values
            return

        for field_name, field_value in values.items():
            if field_name in self.status_payload_fields:
                expected_config = self.status_payload_fields[field_name]
                try:
                    self._validate_field_type(field_name, field_value, expected_config)
                except StatusValidationError:
                    raise
            # Allow fields not in config for flexibility (as per current behavior)

    def _validate_field_type(
        self, field_name: str, field_value: Any, expected_config: Any
    ) -> None:
        """Validate that a field value matches the expected type from config.

        Args:
            field_name: Name of the field being validated
            field_value: The actual value to validate
            expected_config: The expected configuration (type or structure)

        Raises:
            StatusValidationError: If the field type doesn't match
        """
        # Handle default value configs - extract the default for type checking
        if isinstance(expected_config, dict) and "default" in expected_config:
            expected_value = expected_config["default"]
        else:
            expected_value = expected_config

        # Get the expected type from the config value
        expected_type = type(expected_value)

        # Validate basic type compatibility
        if not isinstance(field_value, expected_type):
            raise StatusValidationError(
                f"Field '{field_name}' expected {expected_type.__name__}, "
                f"got {type(field_value).__name__}"
            )

        # Additional validation for complex types
        if isinstance(expected_value, dict) and isinstance(field_value, dict):
            self._validate_dict_structure(field_name, field_value, expected_value)

    def _validate_dict_structure(
        self,
        field_name: str,
        field_value: Dict[str, Any],
        expected_structure: Dict[str, Any],
    ) -> None:
        """Validate that a dictionary field matches the expected structure.

        Args:
            field_name: Name of the field being validated
            field_value: The actual dictionary value
            expected_structure: The expected dictionary structure

        Raises:
            StatusValidationError: If the structure doesn't match
        """
        # Check for required keys based on config structure
        for key, expected_val in expected_structure.items():
            if key not in field_value:
                raise StatusValidationError(
                    f"Field '{field_name}' missing required key '{key}'"
                )

            # Recursively validate nested structures
            actual_val = field_value[key]
            expected_type = type(expected_val)

            if not isinstance(actual_val, expected_type):
                raise StatusValidationError(
                    f"Field '{field_name}.{key}' expected {expected_type.__name__}, "
                    f"got {type(actual_val).__name__}"
                )

    def _build_status_payload(self) -> Dict[str, Any]:
        """Build the complete status payload using config fields and current values."""
        # Start with default operational status
        status_data = {
            "operational_status": self.operational_status,
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }

        # Add last_command_time if available
        if self.last_command_time:
            status_data["last_command_time"] = self.last_command_time.isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")

        # Add custom fields from config
        for field_name, field_config in self.status_payload_fields.items():
            if field_name in self.custom_status_values:
                # Use current value
                status_data[field_name] = self.custom_status_values[field_name]
            elif isinstance(field_config, dict) and "default" in field_config:
                # Use default value from config
                status_data[field_name] = field_config["default"]
            else:
                # Use config value directly as default
                status_data[field_name] = field_config

        # Add any custom status values that aren't in config (for flexibility)
        for field_name, value in self.custom_status_values.items():
            if field_name not in status_data:
                status_data[field_name] = value

        return status_data

    def set_operational_status(self, status: str) -> None:
        """Update the operational status.

        Args:
            status: The new operational status ('idle', 'busy', 'error')
        """
        if status in ["idle", "busy", "error"]:
            old_status = self.operational_status
            self.operational_status = status
            self.logger.debug(f"Operational status updated to: {status}")

            # Trigger immediate publish for significant status changes
            if old_status != status:
                self._pending_immediate_publish = True
                self.logger.debug(
                    "Operational status change detected, immediate publish triggered"
                )
        else:
            self.logger.warning(f"Invalid operational status: {status}")

    def update_last_command_time(self) -> None:
        """Update the last command time to current UTC time."""
        self.last_command_time = datetime.now(timezone.utc)
        self.logger.debug("Last command time updated")

    def _status_changed(self, current_status: Dict[str, Any]) -> bool:
        """Check if the current status differs from the last published status.

        Args:
            current_status: The current status payload

        Returns:
            True if status has changed, False otherwise
        """
        if self._last_published_status is None:
            return True  # Always publish the first status

        # Compare status excluding timestamp (which always changes)
        current_without_timestamp = {
            k: v for k, v in current_status.items() if k != "timestamp"
        }
        last_without_timestamp = {
            k: v for k, v in self._last_published_status.items() if k != "timestamp"
        }

        return current_without_timestamp != last_without_timestamp

    async def publish_immediately(self) -> None:
        """Publish status immediately, bypassing change detection.

        Useful for forcing a status update on significant events.
        """
        await self._publish_status(force=True)

    async def _publish_status(self, force: bool = False) -> None:
        """Publish the current system status using custom payload.

        Args:
            force: Force publish even if status hasn't changed
        """
        try:
            # Build status payload with custom fields
            status_data = self._build_status_payload()

            # Check if we should publish based on change detection and settings
            status_changed = self._status_changed(status_data)
            has_pending_changes = self._pending_immediate_publish

            should_publish = (
                force  # Force publish (e.g., initial status)
                or not self.enable_change_only_publishing  # Change-only disabled, always publish
                or status_changed  # Status actually changed
                or has_pending_changes  # Immediate publish requested
            )

            # Log decision for debugging
            if not should_publish:
                self.logger.debug(
                    f"Status publish skipped: change_only={self.enable_change_only_publishing}, "
                    f"changed={status_changed}, pending={has_pending_changes}, force={force}"
                )

            if not should_publish:
                return

            # Connect if not already connected
            if not self.connection_manager.is_connected:
                await self.connection_manager.connect()

            # Publish with QoS 0 and optional retain flag
            await self.connection_manager.publish(
                self.status_topic, status_data, qos=0, retain=self.use_retained_messages
            )

            # Update tracking
            self._last_published_status = status_data.copy()
            self._pending_immediate_publish = False

            retention_info = " (retained)" if self.use_retained_messages else ""
            self.logger.debug(
                f"Status published to {self.status_topic}{retention_info}: {json.dumps(status_data)}"
            )

        except Exception as e:
            self.logger.error(f"Error publishing status: {str(e)}")
            # Set error status if not already set
            if self.operational_status != "error":
                self.operational_status = "error"

    async def _status_loop(self) -> None:
        """Main status publishing loop with change detection and optional keep-alive."""
        features = []
        if self.enable_change_only_publishing:
            features.append("change-only")
        if self.use_retained_messages:
            features.append("retained")
        if self.enable_keepalive_publishing:
            features.append(f"keep-alive:{self.publish_interval}s")
        else:
            features.append("no-keep-alive")

        feature_str = f" ({', '.join(features)})" if features else ""

        self.logger.info(
            f"Status publisher started for device {self.device_id}{feature_str}"
        )

        # Always publish initial status
        await self._publish_status(force=True)

        try:
            while self._is_running:
                # Handle immediate publishes or keep-alive publish
                if self.enable_keepalive_publishing:
                    # Regular keep-alive publishing (may still be skipped if no changes and change-only is enabled)
                    await self._publish_status()
                elif self._pending_immediate_publish:
                    # Only publish if there are pending changes
                    await self._publish_status()

                await asyncio.sleep(self.publish_interval)

        except asyncio.CancelledError:
            self.logger.info("Status publisher task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in status loop: {str(e)}")
            self.operational_status = "error"
        finally:
            self.logger.info("Status publisher loop ended")

    async def start(self) -> None:
        """Start the periodic status publisher."""
        if self._is_running:
            self.logger.warning("Status publisher is already running")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._status_loop())
        self.logger.info(f"Status publisher started for device: {self.device_id}")

    async def stop(self) -> None:
        """Stop the periodic status publisher."""
        if not self._is_running:
            self.logger.warning("Status publisher is not running")
            return

        self.logger.info("Stopping status publisher...")
        self._is_running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Disconnect from MQTT broker only if we own the connection
        if self._owns_connection:
            await self.connection_manager.disconnect()
        self.logger.info("Status publisher stopped")

    def is_running(self) -> bool:
        """Check if the status publisher is currently running.

        Returns:
            True if running, False otherwise
        """
        return self._is_running
