"""Comprehensive tests for status validation and message structure.

This module tests:
1. Command status message structure with error codes and messages
   - Phase 1: Acknowledgment (received/error) with error_code and error_msg
   - Phase 2: Completion (completed/error) with error_code and error_msg

2. Status payload validation and custom status functionality
   - Custom status payload updates
   - Type validation for status fields
   - Integration tests

The tests verify that error handling includes structured error codes and messages
for better debugging and monitoring.

Note: This file consolidates all status-related tests. The previous test_status_messages.py
has been merged into this file to eliminate duplication.
"""

import json
import pytest
from datetime import datetime

from mqtt_application.command_handler import AsyncCommandHandler
from mqtt_application.connection_manager import MqttConnectionManager
from mqtt_application.status_publisher import StatusValidationError
from mqtt_logger import MqttLogger


@pytest.fixture
def command_handler_with_config(mqtt_logger, trackable_connection_manager):
    """Create a command handler with test configuration for testing."""
    return AsyncCommandHandler(
        logger=mqtt_logger,
        connection_manager=trackable_connection_manager,
        command_config={
            "test_command": {
                "param": "default_value",
                "optional_param": {"default": "optional_default"},
            }
        },
    )


# ============================================================================
# COMMAND STATUS MESSAGE TESTS
# ============================================================================


class TestAcknowledgmentMessages:
    """Test acknowledgment message format and validation."""

    @pytest.mark.asyncio
    async def test_successful_acknowledgment(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test successful acknowledgment without errors."""
        await command_handler_with_config.send_acknowledgment(
            device_id="test_device",
            cmd_id="cmd_123",
            status="received",
            command_timestamp="2025-08-10T14:30:15.123Z",
        )

        # Verify the acknowledgment was sent
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        # Check topic
        assert call_args[0][0] == "icsia/test_device/status/ack"

        # Check payload structure
        payload = call_args[0][1]
        assert payload["cmd_id"] == "cmd_123"
        assert payload["status"] == "received"
        assert payload["command_timestamp"] == "2025-08-10T14:30:15.123Z"
        assert "timestamp" in payload

        # Should not have error fields for successful acknowledgment
        assert "error_code" not in payload
        assert "error_msg" not in payload

    @pytest.mark.asyncio
    async def test_error_acknowledgment_with_details(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error acknowledgment with error code and message."""
        await command_handler_with_config.send_acknowledgment(
            device_id="test_device",
            cmd_id="cmd_123",
            status="error",
            command_timestamp="2025-08-10T14:30:15.123Z",
            error_code="INVALID_PAYLOAD",
            error_msg="Missing required field 'action'",
        )

        # Verify the acknowledgment was sent
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        # Check payload structure
        payload = call_args[0][1]
        assert payload["cmd_id"] == "cmd_123"
        assert payload["status"] == "error"
        assert payload["command_timestamp"] == "2025-08-10T14:30:15.123Z"
        assert payload["error_code"] == "INVALID_PAYLOAD"
        assert payload["error_msg"] == "Missing required field 'action'"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_error_acknowledgment_without_error_details_raises_error(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error acknowledgment without error details raises ValueError (improved behavior)."""
        with pytest.raises(
            ValueError, match="Error status requires both error_code and error_msg"
        ):
            await command_handler_with_config.send_acknowledgment(
                device_id="test_device",
                cmd_id="cmd_123",
                status="error",
                command_timestamp="2025-08-10T14:30:15.123Z",
            )

        # No message should be sent when error occurs
        trackable_connection_manager.publish.assert_not_called()


class TestCompletionMessages:
    """Test completion message structure and error handling."""

    @pytest.mark.asyncio
    async def test_successful_completion(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test successful completion without errors."""
        await command_handler_with_config.send_completion_status(
            device_id="test_device",
            cmd_id="cmd_123",
            status="completed",
            command_timestamp="2025-08-10T14:30:15.123Z",
        )

        # Verify the completion was sent
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        # Check topic
        assert call_args[0][0] == "icsia/test_device/status/completion"

        # Check payload structure
        payload = call_args[0][1]
        assert payload["cmd_id"] == "cmd_123"
        assert payload["status"] == "completed"
        assert payload["command_timestamp"] == "2025-08-10T14:30:15.123Z"
        assert "timestamp" in payload

        # Should not have error fields for successful completion
        assert "error_code" not in payload
        assert "error_msg" not in payload

    @pytest.mark.asyncio
    async def test_error_completion_with_details(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error completion with error code and message."""
        await command_handler_with_config.send_completion_status(
            device_id="test_device",
            cmd_id="cmd_123",
            status="error",
            command_timestamp="2025-08-10T14:30:15.123Z",
            error_code="VALIDATION_ERROR",
            error_msg="Invalid parameter value",
        )

        # Verify the completion was sent
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        # Check payload structure
        payload = call_args[0][1]
        assert payload["cmd_id"] == "cmd_123"
        assert payload["status"] == "error"
        assert payload["command_timestamp"] == "2025-08-10T14:30:15.123Z"
        assert payload["error_code"] == "VALIDATION_ERROR"
        assert payload["error_msg"] == "Invalid parameter value"
        assert "timestamp" in payload


class TestCommandHandlerErrorScenarios:
    """Test error scenarios in command handling with new status structure."""

    @pytest.mark.asyncio
    async def test_missing_command_error(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error handling when command is missing."""
        payload = json.dumps(
            {
                "cmd_id": "test_123",
                # Missing 'command' field
                "data": {},
            }
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd", payload
        )

        # Should send error acknowledgment only (no completion since command determination failed)
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        payload_data = call_args[0][1]
        assert payload_data["status"] == "error"
        assert payload_data["error_code"] == "INVALID_PAYLOAD"
        assert (
            payload_data["error_msg"]
            == "Missing required field 'command'. Include command field in payload or specify command in topic."
        )

    @pytest.mark.asyncio
    async def test_missing_cmd_id_error(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error handling when cmd_id is missing."""
        payload = json.dumps(
            {
                "command": "test_command",
                # Missing 'cmd_id' field
                "data": {},
            }
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/test_command", payload
        )

        # Should send error acknowledgment
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        payload_data = call_args[0][1]
        assert payload_data["status"] == "error"
        assert payload_data["error_code"] == "INVALID_PAYLOAD"
        assert (
            payload_data["error_msg"]
            == "Missing required field 'cmd_id'. Include cmd_id field in command payload."
        )

    @pytest.mark.asyncio
    async def test_invalid_json_error(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test error handling for invalid JSON payload."""
        invalid_payload = "{ invalid json }"

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/test", invalid_payload
        )

        # Should send error acknowledgment
        trackable_connection_manager.publish.assert_called_once()
        call_args = trackable_connection_manager.publish.call_args

        payload_data = call_args[0][1]
        assert payload_data["status"] == "error"
        assert payload_data["error_code"] == "INVALID_JSON"
        assert "Invalid JSON payload:" in payload_data["error_msg"]
        assert "Please check JSON syntax and formatting." in payload_data["error_msg"]

    @pytest.mark.asyncio
    async def test_validation_error_completion(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test validation error sends proper completion message."""
        # Set up a command schema that requires a field
        command_handler_with_config.command_schemas["start_task"] = {
            "required_param": "test_value"
        }

        # Create a payload that will fail validation (missing required_param)
        payload = json.dumps(
            {"command": "start_task", "cmd_id": "test_123", "data": {}}
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/start_task", payload
        )

        # Should send acknowledgment first, then completion with error
        assert trackable_connection_manager.publish.call_count == 2

        # Check acknowledgment (first call)
        ack_call = trackable_connection_manager.publish.call_args_list[0]
        ack_payload = ack_call[0][1]
        assert ack_payload["status"] == "received"

        # Check completion (second call)
        completion_call = trackable_connection_manager.publish.call_args_list[1]
        completion_payload = completion_call[0][1]
        assert completion_payload["status"] == "error"
        assert completion_payload["error_code"] == "VALIDATION_ERROR"
        assert "missing required field" in completion_payload["error_msg"]

    @pytest.mark.asyncio
    async def test_unknown_command_error(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test unknown command sends proper completion error."""
        payload = json.dumps(
            {"command": "unknown_command", "cmd_id": "test_123", "data": {}}
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/unknown_command", payload
        )

        # Should send acknowledgment first, then completion with error
        assert trackable_connection_manager.publish.call_count == 2

        # Check completion (second call)
        completion_call = trackable_connection_manager.publish.call_args_list[1]
        completion_payload = completion_call[0][1]
        assert completion_payload["status"] == "error"
        assert completion_payload["error_code"] == "UNKNOWN_COMMAND"
        assert "Unknown command 'unknown_command'" in completion_payload["error_msg"]
        assert "Available commands:" in completion_payload["error_msg"]

    @pytest.mark.asyncio
    async def test_execution_error_completion(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test execution error sends proper completion message."""

        # Mock a command that raises an exception
        def failing_command(data):
            raise RuntimeError("Command execution failed")

        command_handler_with_config.commands["failing_command"] = failing_command

        payload = json.dumps(
            {"command": "failing_command", "cmd_id": "test_123", "data": {}}
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/failing_command", payload
        )

        # Should send acknowledgment first, then completion with error
        assert trackable_connection_manager.publish.call_count == 2

        # Check completion (second call)
        completion_call = trackable_connection_manager.publish.call_args_list[1]
        completion_payload = completion_call[0][1]
        assert completion_payload["status"] == "error"
        assert completion_payload["error_code"] == "EXECUTION_ERROR"
        assert "Command execution failed" in completion_payload["error_msg"]


class TestSuccessfulCommandFlow:
    """Test successful command execution flow."""

    @pytest.mark.asyncio
    async def test_successful_command_flow(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test complete successful command flow."""

        # Mock a successful command
        def successful_command(data):
            return {"result": "success"}

        command_handler_with_config.commands["successful_command"] = successful_command

        payload = json.dumps(
            {"command": "successful_command", "cmd_id": "test_123", "data": {}}
        )

        await command_handler_with_config.handle_command(
            "icsia/test_device/cmd/successful_command", payload
        )

        # Should send acknowledgment first, then completion
        assert trackable_connection_manager.publish.call_count == 2

        # Check acknowledgment (first call)
        ack_call = trackable_connection_manager.publish.call_args_list[0]
        ack_payload = ack_call[0][1]
        assert ack_payload["status"] == "received"
        assert "error_code" not in ack_payload
        assert "error_msg" not in ack_payload

        # Check completion (second call)
        completion_call = trackable_connection_manager.publish.call_args_list[1]
        completion_payload = completion_call[0][1]
        assert completion_payload["status"] == "completed"
        assert "error_code" not in completion_payload
        assert "error_msg" not in completion_payload


class TestErrorCodes:
    """Test specific error codes are used correctly."""

    @pytest.mark.asyncio
    async def test_all_error_codes_coverage(
        self, command_handler_with_config, trackable_connection_manager
    ):
        """Test that all defined error codes are used appropriately."""
        test_cases = [
            {
                "scenario": "missing_command",
                "payload": '{"cmd_id": "test"}',
                "expected_code": "INVALID_PAYLOAD",
                "phase": "acknowledgment",
            },
            {
                "scenario": "missing_cmd_id",
                "payload": '{"command": "test"}',
                "expected_code": "INVALID_PAYLOAD",
                "phase": "acknowledgment",
            },
            {
                "scenario": "invalid_json",
                "payload": "{ invalid json }",
                "expected_code": "INVALID_JSON",
                "phase": "acknowledgment",
            },
            {
                "scenario": "unknown_command",
                "payload": '{"command": "unknown", "cmd_id": "test"}',
                "expected_code": "UNKNOWN_COMMAND",
                "phase": "completion",
            },
        ]

        for test_case in test_cases:
            trackable_connection_manager.publish.reset_mock()

            # Use appropriate topic for the test scenario
            topic = "icsia/test_device/cmd"
            if test_case["scenario"] == "unknown_command":
                topic = "icsia/test_device/cmd/unknown"

            await command_handler_with_config.handle_command(
                topic, test_case["payload"]
            )

            # Find the call with the expected error code
            found_error = False
            for call in trackable_connection_manager.publish.call_args_list:
                payload = call[0][1]
                if payload.get("error_code") == test_case["expected_code"]:
                    found_error = True
                    break

            assert (
                found_error
            ), f"Error code {test_case['expected_code']} not found for {test_case['scenario']}"


# ============================================================================
# STATUS PAYLOAD VALIDATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_custom_status_payload_update(status_publisher):
    """Test updating status payload with custom values."""
    # Define test values
    test_values = {
        "temperature": 45.2,
        "position": {"x": 100.5, "y": 50.0, "z": -20.2},
        "error_count": 1,
        "custom_mode": "testing",
    }

    # Update status payload
    status_publisher.update_status_payload(test_values)

    # Build status payload
    status_payload = status_publisher._build_status_payload()

    # Verify custom fields are included
    assert status_payload["temperature"] == 45.2
    assert status_payload["position"]["x"] == 100.5
    assert status_payload["position"]["y"] == 50.0
    assert status_payload["position"]["z"] == -20.2
    assert status_payload["error_count"] == 1
    assert status_payload["custom_mode"] == "testing"

    # Verify standard fields are still present
    assert "operational_status" in status_payload
    assert "timestamp" in status_payload

    # Verify timestamp format
    timestamp = status_payload["timestamp"]
    assert timestamp.endswith("Z")
    # Should be valid ISO format
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_status_payload_with_config_defaults():
    """Test status payload uses defaults from config when values not provided."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    # Mock config with defaults
    config_payload = {
        "voltage": {"default": 12.0},
        "temperature": 25.0,
        "speed": 100,
        "system_mode": "idle",
    }

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=config_payload,
    )

    # Only update some values
    publisher.update_status_payload({"temperature": 30.0, "speed": 200})

    status_payload = publisher._build_status_payload()

    # Should use updated values
    assert status_payload["temperature"] == 30.0
    assert status_payload["speed"] == 200

    # Should use defaults for non-updated fields
    assert status_payload["voltage"] == 12.0  # From default
    assert status_payload["system_mode"] == "idle"  # Direct value


@pytest.mark.asyncio
async def test_status_payload_multiple_updates():
    """Test multiple status payload updates work correctly."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload={"counter": 0, "mode": "idle"},
    )

    # First update
    publisher.update_status_payload({"counter": 1, "mode": "active"})
    payload1 = publisher._build_status_payload()
    assert payload1["counter"] == 1
    assert payload1["mode"] == "active"

    # Second update - should merge with previous
    publisher.update_status_payload({"counter": 2})
    payload2 = publisher._build_status_payload()
    assert payload2["counter"] == 2
    assert payload2["mode"] == "active"  # Should retain previous value

    # Third update - new field
    publisher.update_status_payload({"new_field": "test"})
    payload3 = publisher._build_status_payload()
    assert payload3["counter"] == 2  # Should retain
    assert payload3["mode"] == "active"  # Should retain
    assert payload3["new_field"] == "test"  # New field


@pytest.mark.integration
@pytest.mark.asyncio
async def test_motor_control_status_payload_integration():
    """Integration test for motor control status payload."""
    from mqtt_application import MqttApplication

    # Motor control configuration
    config_override = {
        "device_id": "test_motor_01",
        "mqtt": {"broker": "test.mosquitto.org", "port": 1883},
        "status_payload": {
            "current_position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "speed": 100,
            "moving": False,
            "temperature": {"default": 25.0},
        },
    }

    async with MqttApplication(config_override=config_override) as app:
        # Update with motor status
        motor_status = {
            "current_position": {"x": 10.5, "y": 20.0, "z": -5.2},
            "speed": 150,
            "moving": True,
            "temperature": 45.3,
        }

        app.update_status(motor_status)

        # Verify status payload
        status_payload = app.status_publisher._build_status_payload()

        # Check Motor Control API compliance
        assert "current_position" in status_payload
        assert status_payload["current_position"]["x"] == 10.5
        assert status_payload["current_position"]["y"] == 20.0
        assert status_payload["current_position"]["z"] == -5.2
        assert status_payload["speed"] == 150
        assert status_payload["moving"] is True
        assert status_payload["temperature"] == 45.3

        # Check standard fields
        assert "operational_status" in status_payload
        assert "timestamp" in status_payload


@pytest.mark.asyncio
async def test_empty_config_payload_fallback():
    """Test that publisher works with empty config payload."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # No config payload provided
    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=None,
    )

    # Should still work with basic status
    status_payload = publisher._build_status_payload()

    # Should have standard fields
    assert "operational_status" in status_payload
    assert "timestamp" in status_payload
    assert status_payload["operational_status"] == "idle"

    # Update with custom values
    publisher.update_status_payload({"custom_field": "test_value"})
    updated_payload = publisher._build_status_payload()

    assert updated_payload["custom_field"] == "test_value"


# ============================================================================
# STATUS VALIDATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_status_payload_validation_type_mismatch():
    """Test that status update fails when data type doesn't match config."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # Config expects specific types
    config_payload = {
        "temperature": 25.0,  # float
        "speed": 100,  # int
        "moving": False,  # bool
        "system_mode": "idle",  # str
    }

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=config_payload,
    )

    # Test type mismatches
    with pytest.raises(
        StatusValidationError, match="Field 'temperature' expected float, got str"
    ):
        publisher.update_status_payload({"temperature": "hot"})

    with pytest.raises(
        StatusValidationError, match="Field 'speed' expected int, got float"
    ):
        publisher.update_status_payload({"speed": 100.5})

    with pytest.raises(
        StatusValidationError, match="Field 'moving' expected bool, got str"
    ):
        publisher.update_status_payload({"moving": "yes"})

    with pytest.raises(
        StatusValidationError, match="Field 'system_mode' expected str, got int"
    ):
        publisher.update_status_payload({"system_mode": 123})


@pytest.mark.asyncio
async def test_status_payload_validation_dict_structure():
    """Test validation of nested dictionary structures."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # Config with nested structure
    config_payload = {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "sensor_data": {"temperature": 25.0, "humidity": 50.0},
    }

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=config_payload,
    )

    # Valid nested structure should work
    valid_update = {
        "position": {"x": 10.5, "y": 20.0, "z": -5.2},
        "sensor_data": {"temperature": 28.5, "humidity": 45.0},
    }
    publisher.update_status_payload(valid_update)

    # Missing required keys should fail
    with pytest.raises(
        StatusValidationError, match="Field 'position' missing required key 'z'"
    ):
        publisher.update_status_payload({"position": {"x": 10.0, "y": 20.0}})

    # Wrong nested type should fail
    with pytest.raises(
        StatusValidationError, match="Field 'position.x' expected float, got str"
    ):
        publisher.update_status_payload(
            {"position": {"x": "invalid", "y": 20.0, "z": -5.2}}
        )


@pytest.mark.asyncio
async def test_status_payload_validation_with_defaults():
    """Test validation works correctly with default value configs."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # Config with default values
    config_payload = {
        "temperature": {"default": 25.0},
        "error_count": {"default": 0},
        "status_message": {"default": "ok"},
    }

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=config_payload,
    )

    # Valid types matching defaults should work
    publisher.update_status_payload(
        {"temperature": 30.5, "error_count": 2, "status_message": "warning"}
    )

    # Invalid types should fail even with default configs
    with pytest.raises(
        StatusValidationError, match="Field 'temperature' expected float, got int"
    ):
        publisher.update_status_payload({"temperature": 30})

    with pytest.raises(
        StatusValidationError, match="Field 'error_count' expected int, got str"
    ):
        publisher.update_status_payload({"error_count": "none"})


@pytest.mark.asyncio
async def test_status_payload_validation_allows_extra_fields():
    """Test that validation allows fields not defined in config."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # Limited config
    config_payload = {"temperature": 25.0}

    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=config_payload,
    )

    # Should allow extra fields not in config (for flexibility)
    publisher.update_status_payload(
        {
            "temperature": 30.0,  # Must match config type
            "new_field": "any_value",  # Not in config, should be allowed
            "custom_data": {
                "arbitrary": "structure"
            },  # Not in config, should be allowed
        }
    )

    payload = publisher._build_status_payload()
    assert payload["temperature"] == 30.0
    assert payload["new_field"] == "any_value"
    assert payload["custom_data"]["arbitrary"] == "structure"


@pytest.mark.asyncio
async def test_status_payload_validation_no_config():
    """Test that validation is skipped when no config is provided."""
    from mqtt_application.status_publisher import PeriodicStatusPublisher

    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,
        service_name="test_service",
    )
    connection_manager = MqttConnectionManager(
        broker="test.mosquitto.org", port=1883, logger=logger
    )

    # No config payload
    publisher = PeriodicStatusPublisher(
        device_id="test_device",
        logger=logger,
        connection_manager=connection_manager,
        config_status_payload=None,
    )

    # Should accept any values without validation
    publisher.update_status_payload(
        {
            "anything": "goes",
            "mixed_types": [1, "string", True],
            "nested": {"deep": {"structure": {"is": "ok"}}},
        }
    )

    payload = publisher._build_status_payload()
    assert payload["anything"] == "goes"
    assert payload["mixed_types"] == [1, "string", True]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_application_status_validation_integration():
    """Integration test for status validation through MqttApplication."""
    from mqtt_application import MqttApplication

    # Configuration with validation requirements
    config_override = {
        "device_id": "test_validation_device",
        "mqtt": {"broker": "test.mosquitto.org", "port": 1883},
        "status_payload": {
            "motor_position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "speed": 100,
            "operational": True,
        },
    }

    async with MqttApplication(config_override=config_override) as app:
        # Valid update should work
        valid_status = {
            "motor_position": {"x": 15.5, "y": 25.0, "z": -10.2},
            "speed": 200,
            "operational": False,
        }
        app.update_status(valid_status)

        # Invalid type should raise exception
        with pytest.raises(
            StatusValidationError, match="Field 'speed' expected int, got str"
        ):
            app.update_status({"speed": "fast"})

        # Missing required nested key should fail
        with pytest.raises(
            StatusValidationError,
            match="Field 'motor_position' missing required key 'y'",
        ):
            app.update_status({"motor_position": {"x": 10.0, "z": 5.0}})
