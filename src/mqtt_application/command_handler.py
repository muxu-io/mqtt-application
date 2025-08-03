"""Asynchronous command handler for processing MQTT messages."""

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from mqtt_logger import MqttLogger
from .connection_manager import MqttConnectionManager


class MqttErrorCode(Enum):
    """Standardized MQTT error codes for consistent error handling."""

    INVALID_JSON = "INVALID_JSON"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"


class CommandValidationError(Exception):
    """Raised when command payload validation fails."""

    pass


class AsyncCommandHandler:
    """Handles incoming commands asynchronously for device topics.

    Implements a two-phase response system:
    - Phase 1: Acknowledgment (received/error)
    - Phase 2: Completion status (completed/error)

    Both phases can include error_code and error_msg fields for detailed error reporting.

    Only processes topics following the pattern: icsia/<device_id>/cmd/*
    """

    def __init__(
        self,
        logger: MqttLogger,
        connection_manager: MqttConnectionManager,
        ack_topic_pattern: str = "{namespace}/{device_id}/status/ack",
        completion_topic_pattern: str = "{namespace}/{device_id}/status/completion",
        namespace: str = "icsia",
        command_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the AsyncCommandHandler with a dictionary of command mappings.

        Args:
            logger (MqttLogger): The logger instance to use for logging.
            connection_manager (MqttConnectionManager): Shared connection manager.
            ack_topic_pattern (str): Topic pattern for acknowledgment messages.
            completion_topic_pattern (str): Topic pattern for completion messages.
            namespace (str): The MQTT topic namespace/prefix.
            command_config (Dict[str, Any], optional): Command payload schemas from config.
        """
        self.logger = logger
        self.namespace = namespace
        self.ack_topic_pattern = ack_topic_pattern
        self.completion_topic_pattern = completion_topic_pattern
        self.commands = {
            "start_task": self.start_task,
            "stop_task": self.stop_task,
            "report_status": self.report_status,
            "async_operation": self.perform_async_operation,
        }

        # Command payload validation configuration
        self.command_schemas = command_config or {}

        # Reference to status publisher for updating system state
        self.status_publisher = None

        # Use the provided connection manager
        self.connection_manager = connection_manager
        self._owns_connection = False

        # Graceful shutdown support
        self._active_commands = set()
        self._shutdown_requested = False
        self._shutdown_event = asyncio.Event()
        self._connection_lock = asyncio.Lock()
        self._status_publisher_lock = asyncio.Lock()

    def set_status_publisher(self, status_publisher) -> None:
        """Set the status publisher reference for updating system state.

        Args:
            status_publisher: The PeriodicStatusPublisher instance
        """
        self.status_publisher = status_publisher

    async def _update_operational_status(self, status: str) -> None:
        """Update operational status with proper locking.

        Args:
            status: The operational status ('idle', 'busy', 'error')
        """
        if self.status_publisher:
            async with self._status_publisher_lock:
                self.status_publisher.set_operational_status(status)

    async def _validate_basic_command_structure(
        self, data: Dict[str, Any], topic: str, device_id: str, command_timestamp: str
    ) -> Optional[tuple[str, str]]:
        """Validate basic command structure and return cmd_id and command_name.

        Args:
            data: Parsed JSON data from command payload
            topic: MQTT topic
            device_id: Device ID extracted from topic
            command_timestamp: Generated timestamp for the command

        Returns:
            Tuple of (cmd_id, command_name) if valid, None if validation failed
        """
        cmd_id = data.get("cmd_id")

        # Validate required standard fields
        if not cmd_id:
            # Send error acknowledgment for missing cmd_id
            await self.send_acknowledgment(
                device_id,
                "unknown",
                "error",
                command_timestamp,
                error_code=MqttErrorCode.INVALID_PAYLOAD.value,
                error_msg="Missing required field 'cmd_id'. Include cmd_id field in command payload.",
            )
            self.logger.warning(
                f"[CommandHandler] Missing required field 'cmd_id' from topic '{topic}'"
            )
            await self._update_operational_status("error")
            return None

        # Extract command from topic first (for API specs like Camera Control)
        command_name = self.extract_command_from_topic(topic)

        # Fall back to payload-based command identification (for backward compatibility)
        if not command_name:
            command_name = data.get("command")

        if not command_name:
            # Send error acknowledgment for missing command name (we have cmd_id)
            await self.send_acknowledgment(
                device_id,
                cmd_id,
                "error",
                command_timestamp,
                error_code=MqttErrorCode.INVALID_PAYLOAD.value,
                error_msg="Missing required field 'command'. Include command field in payload or specify command in topic.",
            )
            self.logger.warning(
                f"[CommandHandler] Cannot determine command from topic '{topic}' or payload"
            )
            await self._update_operational_status("error")
            return None

        return cmd_id, command_name

    def _extract_command_info(
        self, topic: str, data: Dict[str, Any]
    ) -> tuple[str, str]:
        """Extract command information from topic and payload.

        Args:
            topic: MQTT topic
            data: Command payload data

        Returns:
            Tuple of (device_id, command_timestamp)
        """
        device_id = self.extract_device_id_from_topic(topic)

        # Generate timestamp when message is received and processed
        # This timestamp represents when the server received/processed the command
        # Note: Client-provided timestamps are ignored - server always generates its own
        command_timestamp = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        data["timestamp"] = command_timestamp
        self.logger.debug(
            f"Generated server timestamp for command: {command_timestamp}"
        )

        return device_id, command_timestamp

    async def _validate_command_payload_safe(
        self,
        command_name: str,
        data: Dict[str, Any],
        cmd_id: str,
        device_id: str,
        command_timestamp: str,
    ) -> Optional[Dict[str, Any]]:
        """Safely validate command payload and apply defaults.

        Args:
            command_name: Name of the command
            data: Command payload data
            cmd_id: Command ID
            device_id: Device ID
            command_timestamp: Command timestamp

        Returns:
            Validated data with defaults applied, or None if validation failed
        """
        try:
            # Validate command payload
            self.validate_command_payload(command_name, data)

            # Apply default values
            validated_data = self.apply_defaults(command_name, data)
            return validated_data

        except CommandValidationError as e:
            # Phase 2: Send completion with validation error
            await self.send_completion_status(
                device_id,
                cmd_id,
                "error",
                command_timestamp,
                error_code=MqttErrorCode.VALIDATION_ERROR.value,
                error_msg=f"Validation failed: {str(e)}. Please check command parameters.",
            )
            self.logger.error(f"Command validation failed for {command_name}: {e}")
            await self._update_operational_status("error")
            return None

    def validate_command_payload(
        self, command_name: str, payload: Dict[str, Any]
    ) -> None:
        """Validate command payload against its schema.

        If a field is defined in the schema, it's required (but defaults can be applied).
        If a field is not defined in the schema, it's accepted but not validated.

        Args:
            command_name: Name of the command to validate
            payload: The command payload to validate

        Raises:
            CommandValidationError: If validation fails
        """
        if command_name not in self.command_schemas:
            # No schema defined for this command - allow any payload
            return

        schema = self.command_schemas[command_name]

        # Apply defaults first, then validate
        enriched_payload = self.apply_defaults(command_name, payload)
        self._validate_payload_structure(command_name, enriched_payload, schema)

    def _validate_payload_structure(
        self, command_name: str, payload: Dict[str, Any], schema: Dict[str, Any]
    ) -> None:
        """Validate payload structure against schema.

        Args:
            command_name: Name of the command being validated
            payload: The payload to validate (should have defaults applied)
            schema: The expected schema

        Raises:
            CommandValidationError: If structure doesn't match
        """
        for field_name, expected_config in schema.items():
            # Skip standard command fields (including timestamp)
            if field_name in ["command", "cmd_id", "timestamp"]:
                continue

            # Check if field is present in payload
            if field_name not in payload:
                # Field is missing - check if it's explicitly optional
                if self._is_optional_field(expected_config):
                    continue  # Skip optional fields
                else:
                    # Get expected type/value for better error message
                    if (
                        isinstance(expected_config, dict)
                        and "default" in expected_config
                    ):
                        expected_hint = f"Expected type: {type(expected_config['default']).__name__}"
                    else:
                        expected_hint = (
                            f"Expected type: {type(expected_config).__name__}"
                        )

                    raise CommandValidationError(
                        f"Command '{command_name}' missing required field '{field_name}'. {expected_hint}"
                    )

            # Validate field type and structure
            self._validate_field_type(
                f"{command_name}.{field_name}", payload[field_name], expected_config
            )

    def _is_optional_field(self, expected_config: Any) -> bool:
        """Check if a field is explicitly marked as optional.

        Args:
            expected_config: The field configuration

        Returns:
            True if field is optional (has explicit default), False if required
        """
        # Only fields with explicit {"default": value} syntax are optional
        return isinstance(expected_config, dict) and "default" in expected_config

    def _validate_field_type(
        self, field_path: str, field_value: Any, expected_config: Any
    ) -> None:
        """Validate that a field value matches the expected type from config.

        Args:
            field_path: Path to the field (for error messages)
            field_value: The actual value
            expected_config: The expected configuration

        Raises:
            CommandValidationError: If type doesn't match
        """
        # Handle default value configs
        if isinstance(expected_config, dict) and "default" in expected_config:
            expected_value = expected_config["default"]
        else:
            expected_value = expected_config

        expected_type = type(expected_value)

        # Basic type validation with coercion for numeric types
        if not isinstance(field_value, expected_type):
            # Allow int/float coercion for numeric fields
            if (
                expected_type is int
                and isinstance(field_value, float)
                and field_value.is_integer()
            ):
                # Float that represents an integer (e.g., 100.0) - coerce to int
                return
            elif expected_type is float and isinstance(field_value, int):
                # Int can be used where float is expected
                return
            else:
                raise CommandValidationError(
                    f"Field '{field_path}' expected {expected_type.__name__}, "
                    f"got {type(field_value).__name__} ({field_value}). "
                    f"Please provide a value of type {expected_type.__name__}"
                )

        # Validate nested dictionary structures
        if isinstance(expected_value, dict) and isinstance(field_value, dict):
            self._validate_dict_structure(field_path, field_value, expected_value)

    def _validate_dict_structure(
        self,
        field_path: str,
        field_value: Dict[str, Any],
        expected_structure: Dict[str, Any],
    ) -> None:
        """Validate nested dictionary structure.

        Args:
            field_path: Path to the field
            field_value: The actual dictionary
            expected_structure: The expected structure

        Raises:
            CommandValidationError: If structure doesn't match
        """
        for key, expected_val in expected_structure.items():
            if key not in field_value:
                raise CommandValidationError(
                    f"Field '{field_path}' missing required key '{key}'. "
                    f"Expected nested structure with key '{key}'"
                )

            actual_val = field_value[key]
            expected_type = type(expected_val)

            if not isinstance(actual_val, expected_type):
                raise CommandValidationError(
                    f"Field '{field_path}.{key}' expected {expected_type.__name__}, "
                    f"got {type(actual_val).__name__}"
                )

    def apply_defaults(
        self, command_name: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply default values to command payload.

        Args:
            command_name: Name of the command
            payload: The original payload

        Returns:
            Payload with defaults applied
        """
        if command_name not in self.command_schemas:
            return payload

        result = payload.copy()
        schema = self.command_schemas[command_name]

        for field_name, expected_config in schema.items():
            if field_name not in result:
                # Only apply defaults for explicitly optional fields
                if self._is_optional_field(expected_config):
                    result[field_name] = expected_config["default"]
                # Required fields (simple values or nested) must be provided

        return result

    async def send_acknowledgment(
        self,
        device_id: str,
        cmd_id: str,
        status: str = "received",
        command_timestamp: Optional[str] = None,
        error_code: Optional[str] = None,
        error_msg: Optional[str] = None,
    ) -> None:
        """Send acknowledgment status for a command.

        Args:
            device_id: The device ID from the original topic
            cmd_id: The ID of the command being acknowledged (guaranteed to be non-None)
            status: The acknowledgment status ("received" or "error")
            command_timestamp: Original command timestamp for correlation
            error_code: Error code if status is "error" (required for error status)
            error_msg: Error message if status is "error" (required for error status)

        Raises:
            ValueError: If status is "error" but error_code or error_msg is missing
        """
        # Validate error status requirements
        if status == "error":
            if not error_code or not error_msg:
                raise ValueError(
                    "Error status requires both error_code and error_msg. "
                    f"Got error_code='{error_code}', error_msg='{error_msg}'"
                )

        if not self.connection_manager:
            self.logger.warning(
                "Cannot send acknowledgment: no MQTT connection manager configured"
            )
            return

        ack_topic = self.ack_topic_pattern.format(
            namespace=self.namespace, device_id=device_id
        )
        ack_data = {
            "cmd_id": cmd_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }

        # Include original command timestamp if provided
        if command_timestamp:
            ack_data["command_timestamp"] = command_timestamp

        # Include error details if status is "error" (now guaranteed to be present)
        if status == "error":
            assert error_code is not None and error_msg is not None  # Validated above
            ack_data["error_code"] = error_code
            ack_data["error_msg"] = error_msg

        # Use connection manager's publish_with_retry method
        if hasattr(self.connection_manager, "publish_with_retry"):
            await self.connection_manager.publish_with_retry(ack_topic, ack_data, qos=1)
        else:
            await self.connection_manager.publish(ack_topic, ack_data, qos=1)

    async def send_completion_status(
        self,
        device_id: str,
        cmd_id: str,
        status: str,
        command_timestamp: Optional[str] = None,
        error_code: Optional[str] = None,
        error_msg: Optional[str] = None,
    ) -> None:
        """Send completion status for a command.

        Args:
            device_id: The device ID from the original topic
            cmd_id: The ID of the command whose completion is being reported
            status: The completion status ("completed" or "error")
            command_timestamp: Original command timestamp for correlation
            error_code: Error code if status is "error" (required for error status)
            error_msg: Error message if status is "error" (required for error status)

        Raises:
            ValueError: If status is "error" but error_code or error_msg is missing
        """
        # Validate error status requirements
        if status == "error":
            if not error_code or not error_msg:
                raise ValueError(
                    "Error status requires both error_code and error_msg. "
                    f"Got error_code='{error_code}', error_msg='{error_msg}'"
                )

        if not self.connection_manager:
            self.logger.warning(
                "Cannot send completion status: no MQTT connection manager configured"
            )
            return

        completion_topic = self.completion_topic_pattern.format(
            namespace=self.namespace, device_id=device_id
        )
        completion_data = {
            "cmd_id": cmd_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }

        # Include original command timestamp if provided
        if command_timestamp:
            completion_data["command_timestamp"] = command_timestamp

        # Include error details if status is "error" (now guaranteed to be present)
        if status == "error":
            assert error_code is not None and error_msg is not None  # Validated above
            completion_data["error_code"] = error_code
            completion_data["error_msg"] = error_msg

        # Use connection manager's publish_with_retry method
        if hasattr(self.connection_manager, "publish_with_retry"):
            await self.connection_manager.publish_with_retry(
                completion_topic, completion_data, qos=1
            )
        else:
            await self.connection_manager.publish(
                completion_topic, completion_data, qos=1
            )

    def extract_device_id_from_topic(self, topic: str) -> Optional[str]:
        """Extract device ID from topic following {namespace}/<device_id>/cmd/* pattern.

        Args:
            topic: The MQTT topic to parse

        Returns:
            The device ID if topic matches pattern, None otherwise
        """
        parts = topic.split("/")
        if len(parts) >= 3 and parts[0] == self.namespace and parts[2] == "cmd":
            return parts[1]
        return None

    def extract_command_from_topic(self, topic: str) -> Optional[str]:
        """Extract command type from topic following {namespace}/<device_id>/cmd/<command> pattern.

        Args:
            topic: The MQTT topic to parse

        Returns:
            The command type if topic matches pattern, None otherwise
        """
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == self.namespace and parts[2] == "cmd":
            return parts[3]  # settings, enable, etc.
        return None

    async def handle_command(self, topic: str, payload: str) -> None:
        """Parse the payload, identify the command, and execute the corresponding handler.

        Args:
            topic (str): The MQTT topic the message was received on.
            payload (str): The message payload as a string.

        """
        if self._shutdown_requested:
            self.logger.warning(
                "Command handler is shutting down, ignoring new commands"
            )
            return

        device_id = self.extract_device_id_from_topic(topic)
        if not device_id:
            self.logger.warning(f"Cannot extract device_id from topic: {topic}")
            return

        try:
            data = json.loads(payload)

            # Extract command information and timestamps
            device_id, command_timestamp = self._extract_command_info(topic, data)

            # Validate basic command structure (cmd_id and command_name)
            validation_result = await self._validate_basic_command_structure(
                data, topic, device_id, command_timestamp
            )
            if validation_result is None:
                return  # Validation failed, error already handled

            cmd_id, command_name = validation_result

            # Ensure command name is available in payload for handlers
            if "command" not in data:
                data["command"] = command_name

            # Phase 1: Send immediate acknowledgment (include original timestamp)
            await self.send_acknowledgment(
                device_id, cmd_id, "received", command_timestamp
            )

            if command_name in self.commands:
                # Create a task for command execution tracking
                command_task = None
                try:
                    # Validate command payload and apply defaults
                    validated_data = await self._validate_command_payload_safe(
                        command_name, data, cmd_id, device_id, command_timestamp
                    )
                    if validated_data is None:
                        return  # Validation failed, error already handled

                    self.logger.info(
                        f"[CommandHandler] Executing command: {command_name} (ID: {cmd_id}) from topic '{topic}'"
                    )

                    # Update status publisher to busy state
                    await self._update_operational_status("busy")

                    # Execute the command with validated data and track it
                    if asyncio.iscoroutinefunction(self.commands[command_name]):
                        command_task = asyncio.create_task(
                            self.commands[command_name](validated_data)
                        )
                        self._active_commands.add(command_task)
                        try:
                            await command_task
                        finally:
                            self._active_commands.discard(command_task)
                    else:
                        # Run sync commands in thread pool to avoid blocking
                        loop = asyncio.get_event_loop()
                        command_future = loop.run_in_executor(
                            None, self.commands[command_name], validated_data
                        )
                        # Track the Future directly
                        self._active_commands.add(command_future)
                        try:
                            await command_future
                        finally:
                            self._active_commands.discard(command_future)

                    # Phase 2: Send completion status (include original timestamp)
                    await self.send_completion_status(
                        device_id, cmd_id, "completed", command_timestamp
                    )

                    # Update status publisher with success
                    if self.status_publisher:
                        async with self._status_publisher_lock:
                            self.status_publisher.update_last_command_time()
                    await self._update_operational_status("idle")

                except Exception as e:
                    # Phase 2: Send completion with execution error
                    await self.send_completion_status(
                        device_id,
                        cmd_id,
                        "error",
                        command_timestamp,
                        error_code=MqttErrorCode.EXECUTION_ERROR.value,
                        error_msg=f"Command execution failed: {str(e)}. Check command implementation and parameters.",
                    )

                    # Update status publisher with error
                    await self._update_operational_status("error")

                    self.logger.error(f"Error executing command {command_name}: {e}")
            else:
                self.logger.warning(
                    f"[CommandHandler] Unknown command: '{command_name}' on topic '{topic}'"
                )

                # Phase 2: Send completion with error for unknown command
                await self.send_completion_status(
                    device_id,
                    cmd_id,
                    "error",
                    command_timestamp,
                    error_code=MqttErrorCode.UNKNOWN_COMMAND.value,
                    error_msg=f"Unknown command '{command_name}'. Available commands: {', '.join(self.commands.keys())}",
                )

                # Update status publisher with error for unknown command
                await self._update_operational_status("error")

        except json.JSONDecodeError as e:
            self.logger.error(
                f"[CommandHandler] Invalid JSON payload on topic '{topic}': {payload}"
            )
            # Send acknowledgment with INVALID_JSON error code
            error_timestamp = (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            await self.send_acknowledgment(
                device_id,
                "unknown",
                "error",
                error_timestamp,
                error_code=MqttErrorCode.INVALID_JSON.value,
                error_msg=f"Invalid JSON payload: {str(e)}. Please check JSON syntax and formatting.",
            )

            # Update status publisher with error
            await self._update_operational_status("error")
            return

        except Exception as e:
            self.logger.error(f"[CommandHandler] Error handling command: {e}")
            # Send acknowledgment with error if possible (only if cmd_id is available)
            error_timestamp = (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            try:
                partial_data = json.loads(payload)
                cmd_id = partial_data.get("cmd_id")
                if cmd_id:
                    await self.send_acknowledgment(
                        device_id,
                        cmd_id,
                        "error",
                        error_timestamp,
                        error_code=MqttErrorCode.INTERNAL_ERROR.value,
                        error_msg=f"Internal server error: {str(e)}. Please contact support if this persists.",
                    )

                    # Update status publisher with error
                    await self._update_operational_status("error")
                    return
                else:
                    # No cmd_id available, send acknowledgment with fallback ID
                    await self.send_acknowledgment(
                        device_id,
                        "unknown",
                        "error",
                        error_timestamp,
                        error_code=MqttErrorCode.INVALID_PAYLOAD.value,
                        error_msg="Missing required field 'cmd_id'. Include cmd_id field in command payload.",
                    )

                    # Update status publisher with error
                    await self._update_operational_status("error")
                    return
            except json.JSONDecodeError as json_error:
                # JSON is invalid, send acknowledgment with fallback ID
                await self.send_acknowledgment(
                    device_id,
                    "unknown",
                    "error",
                    error_timestamp,
                    error_code=MqttErrorCode.INVALID_JSON.value,
                    error_msg=f"Invalid JSON payload: {str(json_error)}. Please check JSON syntax and formatting.",
                )

                # Update status publisher with error
                await self._update_operational_status("error")
                return
            except Exception:
                # Any other error, just log and update status
                self.logger.error(
                    "[CommandHandler] Failed to handle internal error properly"
                )
                await self._update_operational_status("error")

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Gracefully shutdown the command handler.

        Args:
            timeout: Maximum time to wait for pending commands to complete
        """
        self.logger.info("Shutting down command handler...")
        self._shutdown_requested = True

        # Cancel any pending command executions
        if self._active_commands:
            self.logger.info(
                f"Waiting for {len(self._active_commands)} active commands to complete..."
            )

            # Cancel all tasks/futures
            for command in list(self._active_commands):
                if hasattr(command, "cancel"):
                    command.cancel()

            # Wait for commands to complete or timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *list(self._active_commands), return_exceptions=True
                    ),
                    timeout=timeout,
                )
                self.logger.info("All commands completed during shutdown")
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Some commands did not complete within {timeout}s shutdown timeout"
                )
            finally:
                self._active_commands.clear()

        # Signal that shutdown is complete
        self._shutdown_event.set()
        self.logger.info("Command handler shutdown complete")

    async def wait_for_shutdown(self) -> None:
        """Wait for the shutdown process to complete."""
        await self._shutdown_event.wait()

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    def register_command(self, command_name: str, handler_func) -> None:
        """Register a command handler dynamically.

        Args:
            command_name: Name of the command
            handler_func: Function to handle the command (sync or async)
        """
        self.commands[command_name] = handler_func
        self.logger.info(f"Registered command handler: {command_name}")

    def unregister_command(self, command_name: str) -> None:
        """Unregister a command handler.

        Args:
            command_name: Name of the command to remove
        """
        if command_name in self.commands:
            del self.commands[command_name]
            if command_name in self.command_schemas:
                del self.command_schemas[command_name]
            self.logger.info(f"Unregistered command handler: {command_name}")

    # --- Example Command Functions (can be sync or async) ---

    def start_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Start a task.

        Args:
            data: Command data containing task information.

        Returns:
            Dict containing the task status.
        """
        task_id = data.get("task_id", "N/A")
        self.logger.info(f"[Command] Starting task with ID: {task_id}")

        # Return task status
        return {
            "task_id": task_id,
            "status": "started",
            "message": f"Task {task_id} started successfully",
            "timestamp": asyncio.get_event_loop().time(),
        }

    def stop_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Stop a task.

        Args:
            data: Command data containing task information.

        Returns:
            Dict containing the task status.
        """
        task_id = data.get("task_id", "N/A")
        self.logger.info(f"[Command] Stopping task with ID: {task_id}")

        # Return task status
        return {
            "task_id": task_id,
            "status": "stopped",
            "timestamp": asyncio.get_event_loop().time(),
        }

    def report_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Report status.

        Args:
            data: Command data containing status information.

        Returns:
            Dict containing the component status.
        """
        component = data.get("component", "N/A")
        status = data.get("status", "N/A")
        self.logger.info(
            f"[Command] Reporting status for component '{component}': {status}"
        )

        # Return system status
        return {
            "component": component,
            "status": status,
            "system_status": "healthy",
            "uptime": asyncio.get_event_loop().time(),
        }

    async def perform_async_operation(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate an async operation.

        Args:
            data: Command data containing operation parameters.

        Returns:
            Dict containing the operation result.
        """
        delay = data.get("delay", 1)
        self.logger.info(
            f"[Command] Starting async operation with delay of {delay} seconds..."
        )
        start_time = asyncio.get_event_loop().time()
        await asyncio.sleep(delay)  # Simulate an I/O bound operation
        end_time = asyncio.get_event_loop().time()
        self.logger.info(
            f"[Command] Async operation completed after {end_time - start_time: .2f} seconds."
        )

        # Return operation result
        return {
            "operation": "async_task",
            "status": "completed",
            "requested_delay": delay,
            "actual_duration": round(end_time - start_time, 2),
        }
