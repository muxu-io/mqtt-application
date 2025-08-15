"""Comprehensive tests for command payload validation framework.

This module provides complete test coverage for the MQTT application's command
validation framework. It tests all aspects of payload validation including:

- Basic type validation (string, int, float, bool)
- Nested structure validation
- Required vs optional field handling
- Default value application
- Error scenarios and edge cases
- Framework behavior with various configuration patterns
- Device-agnostic validation (motors, cameras, sensors, etc.)

The tests serve as both verification of functionality and documentation
of the framework's capabilities and expected behavior.

Key validation rules tested:
- ALL fields defined in config are REQUIRED unless explicitly optional
- Fields with {"default": value} syntax are OPTIONAL
- Fields not in config are IGNORED (no validation)
- Standard fields (command, cmd_id, timestamp) are always skipped
- Type validation matches configuration examples
"""

import pytest

from mqtt_application.command_handler import CommandValidationError


def test_command_validation_basic_types(trackable_command_handler):
    """Test validation of basic field types - all defined fields are required."""
    command_config = {
        "configure": {
            "threshold": 50.0,  # Float type - REQUIRED
            "count": 10,  # Integer type - REQUIRED
            "enabled": True,  # Boolean type - REQUIRED
            "name": "default",  # String type - REQUIRED
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Valid payload with all required fields should pass
    valid_payload = {
        "command": "configure",
        "cmd_id": "test_123",
        "threshold": 75.5,
        "count": 25,
        "enabled": False,
        "name": "custom",
    }
    handler.validate_command_payload("configure", valid_payload)

    # Missing required field should fail
    with pytest.raises(
        CommandValidationError,
        match="Command 'configure' missing required field 'count'",
    ):
        handler.validate_command_payload(
            "configure",
            {
                "command": "configure",
                "cmd_id": "test_123",
                "threshold": 75.5,
                # Missing required 'count' field
                "enabled": False,
                "name": "custom",
            },
        )

    # Invalid types should fail
    with pytest.raises(CommandValidationError, match="Field 'configure.count' expected int, got str"):
        handler.validate_command_payload(
            "configure",
            {
                "command": "configure",
                "cmd_id": "test_123",
                "threshold": 75.5,
                "count": "invalid",  # Should be int
                "enabled": False,
                "name": "custom",
            },
        )


def test_command_validation_nested_structure(trackable_command_handler):
    """Test validation of nested dictionary structures."""
    command_config = {
        "setup": {
            "coordinates": {"x": 0.0, "y": 0.0, "z": 0.0},
            "settings": {"mode": "auto", "priority": 1},
            "timeout": 30,
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Valid nested structure should pass
    valid_payload = {
        "command": "setup",
        "cmd_id": "test_123",
        "coordinates": {"x": 10.0, "y": 20.0, "z": 30.0},
        "settings": {"mode": "manual", "priority": 5},
        "timeout": 60,
    }
    handler.validate_command_payload("setup", valid_payload)

    # Missing required nested keys should fail
    with pytest.raises(
        CommandValidationError,
        match="Field 'setup.coordinates' missing required key 'z'",
    ):
        handler.validate_command_payload(
            "setup",
            {
                "command": "setup",
                "cmd_id": "test_123",
                "coordinates": {"x": 10.0, "y": 20.0},  # Missing z
                "settings": {"mode": "manual", "priority": 5},
                "timeout": 60,
            },
        )

    # Wrong nested type should fail
    with pytest.raises(
        CommandValidationError,
        match="Field 'setup.settings.priority' expected int, got str",
    ):
        handler.validate_command_payload(
            "setup",
            {
                "command": "setup",
                "cmd_id": "test_123",
                "coordinates": {"x": 10.0, "y": 20.0, "z": 30.0},
                "settings": {"mode": "manual", "priority": "high"},  # Should be int
                "timeout": 60,
            },
        )


def test_command_validation_missing_required_field(trackable_command_handler):
    """Test validation fails for missing required fields."""
    command_config = {
        "process": {
            "name": "default_process",  # Simple value = REQUIRED
            "parameters": {  # Nested structure = REQUIRED
                "input_file": "input.txt",
                "output_file": "output.txt",
            },
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Missing required simple field should fail
    with pytest.raises(CommandValidationError, match="Command 'process' missing required field 'name'"):
        handler.validate_command_payload(
            "process",
            {
                "command": "process",
                "cmd_id": "test_123",
                "parameters": {
                    "input_file": "custom_input.txt",
                    "output_file": "custom_output.txt",
                },
                # Missing required 'name' field
            },
        )

    # Missing required nested field should fail
    with pytest.raises(
        CommandValidationError,
        match="Command 'process' missing required field 'parameters'",
    ):
        handler.validate_command_payload(
            "process",
            {
                "command": "process",
                "cmd_id": "test_123",
                "name": "custom_process",
                # Missing required 'parameters' field
            },
        )


def test_command_validation_with_defaults(trackable_command_handler):
    """Test validation works correctly with explicit default value configs."""
    command_config = {
        "configure": {
            "setting_name": {"default": "default_setting"},  # OPTIONAL - explicit default
            "priority": {"default": 1},  # OPTIONAL - explicit default
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # All fields have explicit defaults, so minimal payload should work
    valid_payload = {"command": "configure", "cmd_id": "test_123"}
    handler.validate_command_payload("configure", valid_payload)

    # Apply defaults and verify they are set
    enriched = handler.apply_defaults("configure", valid_payload)
    assert enriched["setting_name"] == "default_setting"
    assert enriched["priority"] == 1


def test_command_validation_no_schema(trackable_command_handler):
    """Test that commands without schemas are allowed."""
    command_config = {}

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Any payload should be allowed for commands without schemas
    payload = {
        "command": "unknown_command",
        "cmd_id": "test_123",
        "arbitrary_field": "any_value",
        "nested": {"data": 123},
    }
    handler.validate_command_payload("unknown_command", payload)


def test_command_validation_all_defined_fields_required(trackable_command_handler):
    """Test that all fields defined in config are required unless explicitly optional."""
    command_config = {
        "device_settings": {
            "mode": "auto",  # Required (simple value in config)
            "speed": 100,  # Required (simple value in config)
            "threshold": 50.0,  # Required (simple value in config)
            "timeout": {"default": 30},  # Optional (explicit default)
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Missing required simple field should fail
    with pytest.raises(
        CommandValidationError,
        match="Command 'device_settings' missing required field 'mode'",
    ):
        handler.validate_command_payload(
            "device_settings",
            {
                "command": "device_settings",
                "cmd_id": "test_123",
                "speed": 100,
                "threshold": 50.0,
                # Missing required 'mode'
            },
        )

    # All required fields provided should pass
    valid_payload = {
        "command": "device_settings",
        "cmd_id": "test_123",
        "mode": "manual",
        "speed": 150,
        "threshold": 75.5,
        # timeout is optional, will get default
    }
    handler.validate_command_payload("device_settings", valid_payload)

    # Apply defaults and verify optional field gets default
    enriched = handler.apply_defaults("device_settings", valid_payload)
    assert enriched["timeout"] == 30  # Default applied
    assert enriched["mode"] == "manual"  # Provided value preserved


def test_command_validation_generic_device_api_example(trackable_command_handler):
    """Test validation with a realistic Device Control API example."""
    command_config = {
        "configure": {
            "mode": "auto",  # REQUIRED - Operation mode
            "speed": 100,  # REQUIRED - Speed setting
            "threshold": 50.0,  # REQUIRED - Threshold value
        },
        "enable": {"enabled": True},  # REQUIRED - Enable/disable flag
        "setup": {
            "setting_name": "default",  # REQUIRED - Setting name
            "timeout": {"default": 30},  # OPTIONAL - Request timeout
            "retries": {"default": 3},  # OPTIONAL - Retry count
        },
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Valid configure command
    configure_payload = {
        "command": "configure",
        "cmd_id": "device_001",
        "mode": "manual",
        "speed": 150,
        "threshold": 75.5,
    }
    handler.validate_command_payload("configure", configure_payload)

    # Valid enable command
    enable_payload = {"command": "enable", "cmd_id": "device_002", "enabled": False}
    handler.validate_command_payload("enable", enable_payload)

    # Setup command with mix of required/optional
    setup_payload = {
        "command": "setup",
        "cmd_id": "device_003",
        "setting_name": "custom_setting",
        # timeout and retries will get defaults
    }
    handler.validate_command_payload("setup", setup_payload)
    enriched = handler.apply_defaults("setup", setup_payload)
    assert enriched["timeout"] == 30
    assert enriched["retries"] == 3

    # Missing required field should fail
    with pytest.raises(
        CommandValidationError,
        match="Command 'configure' missing required field 'threshold'",
    ):
        handler.validate_command_payload(
            "configure",
            {
                "command": "configure",
                "cmd_id": "device_004",
                "mode": "auto",
                "speed": 100,
                # Missing required 'threshold'
            },
        )


def test_command_validation_skips_standard_fields(trackable_command_handler):
    """Test that standard command fields (command, cmd_id, timestamp) are skipped in validation."""
    command_config = {"test_command": {"custom_field": "required_value"}}

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Standard fields should not be validated even if they don't match schema
    valid_payload = {
        "command": "test_command",  # This is a string, not validated
        "cmd_id": "test_123",  # This is a string, not validated
        "timestamp": "2025-08-10T14:30:15.123Z",  # This is auto-generated by server, not validated
        "custom_field": "required_value",
    }
    handler.validate_command_payload("test_command", valid_payload)


def test_command_validation_apply_defaults(trackable_command_handler):
    """Test that default values are applied correctly."""
    command_config = {
        "initialize": {
            "timeout": {"default": 30},  # Optional with default
            "retries": {"default": 3},  # Optional with default
            "debug": {"default": False},  # Optional with default
            "message": {"default": "Starting"},  # Optional with default
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Minimal payload with some fields missing
    minimal_payload = {
        "command": "initialize",
        "cmd_id": "test_123",
        "timeout": 60,  # Override one default
        # Missing retries, debug, message - should get defaults
    }

    # Validation should pass
    handler.validate_command_payload("initialize", minimal_payload)

    # Apply defaults and verify
    enriched = handler.apply_defaults("initialize", minimal_payload)
    assert enriched["timeout"] == 60  # Provided value preserved
    assert enriched["retries"] == 3  # Default applied
    assert not enriched["debug"]  # Default applied
    assert enriched["message"] == "Starting"  # Default applied


def test_command_validation_complex_nested_defaults(trackable_command_handler):
    """Test validation with complex nested structures and defaults."""
    command_config = {
        "deploy": {
            "version": {"default": "1.0.0"},  # Optional with default
            "environment": {"default": "dev"},  # Optional with default
            "config": {  # Required nested structure
                "database_url": "localhost:5432",
                "cache_size": 100,
                "features": {"logging": True, "metrics": False},
            },
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Valid payload with nested structure
    valid_payload = {
        "command": "deploy",
        "cmd_id": "test_123",
        "config": {
            "database_url": "prod:5432",
            "cache_size": 500,
            "features": {"logging": True, "metrics": True},
        },
        # Missing version and environment - should get defaults
    }

    handler.validate_command_payload("deploy", valid_payload)
    enriched = handler.apply_defaults("deploy", valid_payload)

    assert enriched["version"] == "1.0.0"
    assert enriched["environment"] == "dev"
    assert enriched["config"]["database_url"] == "prod:5432"
    assert enriched["config"]["features"]["metrics"] is True


def test_command_validation_missing_nested_structure(trackable_command_handler):
    """Test validation fails when entire nested structure is missing."""
    command_config = {
        "backup": {
            "schedule": {"default": "daily"},  # Optional with default
            "settings": {  # Required nested structure
                "compression": True,
                "encryption": False,
                "retention_days": 30,
            },
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Missing entire nested structure should fail
    with pytest.raises(
        CommandValidationError,
        match="Command 'backup' missing required field 'settings'",
    ):
        handler.validate_command_payload(
            "backup",
            {
                "command": "backup",
                "cmd_id": "test_123",
                # Missing required 'settings' nested structure
            },
        )


def test_command_validation_empty_schema(trackable_command_handler):
    """Test validation with empty schema (no required fields)."""
    command_config = {"ping": {}}  # No required fields

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Minimal payload should work
    minimal_payload = {"command": "ping", "cmd_id": "test_123"}
    handler.validate_command_payload("ping", minimal_payload)

    # Additional fields should also be allowed
    extended_payload = {
        "command": "ping",
        "cmd_id": "test_123",
        "extra_field": "allowed",
    }
    handler.validate_command_payload("ping", extended_payload)


def test_command_validation_type_mismatch_scenarios(trackable_command_handler):
    """Test various type mismatch scenarios."""
    command_config = {
        "validate_types": {
            "string_field": "default",
            "int_field": 42,
            "float_field": 3.14,
            "bool_field": True,
            "list_field": [],  # Note: This would need special handling
            "nested": {"inner_string": "value", "inner_number": 123},
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Test string type mismatch
    with pytest.raises(
        CommandValidationError,
        match="Field 'validate_types.string_field' expected str, got int",
    ):
        handler.validate_command_payload(
            "validate_types",
            {
                "command": "validate_types",
                "cmd_id": "test_123",
                "string_field": 123,  # Should be string
                "int_field": 42,
                "float_field": 3.14,
                "bool_field": True,
                "nested": {"inner_string": "value", "inner_number": 123},
            },
        )

    # Test bool type mismatch
    with pytest.raises(
        CommandValidationError,
        match="Field 'validate_types.bool_field' expected bool, got str",
    ):
        handler.validate_command_payload(
            "validate_types",
            {
                "command": "validate_types",
                "cmd_id": "test_123",
                "string_field": "valid",
                "int_field": 42,
                "float_field": 3.14,
                "bool_field": "true",  # Should be boolean
                "nested": {"inner_string": "value", "inner_number": 123},
            },
        )


def test_command_validation_simple_fields_required_by_default(
    trackable_command_handler,
):
    """Test that simple fields defined in config are required by default (new behavior)."""
    command_config = {
        "device_settings": {
            "mode": "auto",  # Required (simple value in config)
            "speed": 100,  # Required (simple value in config)
            "threshold": 50.0,  # Required (simple value in config)
            "timeout": {"default": 30},  # Optional (explicit default)
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Missing required simple field should fail
    with pytest.raises(CommandValidationError, match="missing required field 'mode'"):
        handler.validate_command_payload(
            "device_settings",
            {
                "command": "device_settings",
                "cmd_id": "test_123",
                "speed": 100,
                "threshold": 50.0,
                # Missing required 'mode'
            },
        )

    # All required fields provided should pass
    valid_payload = {
        "command": "device_settings",
        "cmd_id": "test_123",
        "mode": "manual",
        "speed": 150,
        "threshold": 75.5,
        # timeout is optional, will get default
    }
    handler.validate_command_payload("device_settings", valid_payload)

    enriched = handler.apply_defaults("device_settings", valid_payload)
    assert enriched["timeout"] == 30  # Default applied


def test_command_validation_generic_device_comprehensive(trackable_command_handler):
    """Test comprehensive Device Control API validation with new behavior."""
    command_config = {
        "configure": {
            "mode": "auto",  # Required - must be provided
            "speed": 100,  # Required - must be provided
            "threshold": 50.0,  # Required - must be provided
        },
        "enable": {"enabled": True},  # Required - must be provided
        "setup": {
            "setting_name": "default",  # Required - must be provided
            "timeout": {"default": 30},  # Optional - has default
            "retries": {"default": 3},  # Optional - has default
        },
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Valid configure command - all required fields provided
    configure_payload = {
        "command": "configure",
        "cmd_id": "device_001",
        "mode": "manual",
        "speed": 150,
        "threshold": 75.5,
    }
    handler.validate_command_payload("configure", configure_payload)

    # Invalid configure command - missing required field
    with pytest.raises(CommandValidationError, match="missing required field 'threshold'"):
        handler.validate_command_payload(
            "configure",
            {
                "command": "configure",
                "cmd_id": "device_002",
                "mode": "auto",
                "speed": 100,
                # Missing required 'threshold'
            },
        )

    # Valid enable command
    enable_payload = {"command": "enable", "cmd_id": "device_003", "enabled": False}
    handler.validate_command_payload("enable", enable_payload)

    # Valid setup command with optional fields getting defaults
    setup_payload = {
        "command": "setup",
        "cmd_id": "device_004",
        "setting_name": "custom",
        # timeout and retries will get defaults
    }
    handler.validate_command_payload("setup", setup_payload)

    enriched = handler.apply_defaults("setup", setup_payload)
    assert enriched["setting_name"] == "custom"  # Provided value preserved
    assert enriched["timeout"] == 30  # Default applied
    assert enriched["retries"] == 3  # Default applied


def test_command_validation_edge_cases_and_boundaries(trackable_command_handler):
    """Test edge cases and boundary conditions for the validation framework."""
    command_config = {
        "edge_test": {
            # Test various data types and edge values
            "zero_value": 0,
            "negative_value": -1,
            "float_zero": 0.0,
            "empty_string": "",
            "boolean_false": False,
            "optional_none": {"default": None},
            "optional_empty_list": {"default": []},
            "optional_empty_dict": {"default": {}},
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Test all edge values are properly handled
    edge_payload = {
        "command": "edge_test",
        "cmd_id": "edge_001",
        "zero_value": 0,
        "negative_value": -10,
        "float_zero": 0.0,
        "empty_string": "",
        "boolean_false": False,
        # Optional fields will get defaults
    }

    handler.validate_command_payload("edge_test", edge_payload)
    enriched = handler.apply_defaults("edge_test", edge_payload)

    # Verify edge values are preserved
    assert enriched["zero_value"] == 0
    assert enriched["negative_value"] == -10
    assert enriched["float_zero"] == 0.0
    assert enriched["empty_string"] == ""
    assert enriched["boolean_false"] is False

    # Verify defaults are applied
    assert enriched["optional_none"] is None
    assert enriched["optional_empty_list"] == []
    assert enriched["optional_empty_dict"] == {}

    # Test that None values in required fields fail validation
    with pytest.raises(
        CommandValidationError,
        match="Field 'edge_test.zero_value' expected int, got NoneType",
    ):
        handler.validate_command_payload(
            "edge_test",
            {
                "command": "edge_test",
                "cmd_id": "edge_002",
                "zero_value": None,  # None not allowed for required fields
                "negative_value": -1,
                "float_zero": 0.0,
                "empty_string": "",
                "boolean_false": False,
            },
        )


def test_standard_fields_validation_in_handle_command(trackable_command_handler, trackable_connection_manager):
    """Test that handle_command validates standard fields (command, cmd_id) presence."""
    import asyncio
    import json

    command_config = {"test_cmd": {"value": 42}}  # Simple required field

    # Use trackable fixtures
    handler = trackable_command_handler
    handler.command_schemas = command_config
    connection_manager = trackable_connection_manager

    # Test missing 'command' field (use a topic without command extraction)
    async def test_missing_command():
        payload_missing_command = json.dumps(
            {
                "cmd_id": "test_001",
                "value": 42,
                # Missing 'command' field, and topic doesn't contain command name
            }
        )

        # Use a topic that doesn't follow the standard pattern to force payload-based command lookup
        await handler.handle_command("icsia/device_01/cmd", payload_missing_command)

        # Should send error acknowledgment via publish call
        assert connection_manager.publish.called
        call_args = connection_manager.publish.call_args
        payload = call_args[0][1]
        assert payload["error_code"] == "INVALID_PAYLOAD"
        assert (
            payload["error_msg"]
            == "Missing required field 'command'. Include command field in payload or specify command in topic."
        )

    # Test missing 'cmd_id' field
    async def test_missing_cmd_id():
        connection_manager.publish.reset_mock()

        payload_missing_cmd_id = json.dumps(
            {
                "command": "test_cmd",
                "value": 42,
                # Missing 'cmd_id' field
            }
        )

        await handler.handle_command("icsia/device_01/cmd/test_cmd", payload_missing_cmd_id)

        # Should send error acknowledgment via publish call
        assert connection_manager.publish.called
        call_args = connection_manager.publish.call_args
        payload = call_args[0][1]
        assert payload["error_code"] == "INVALID_PAYLOAD"
        assert payload["error_msg"] == "Missing required field 'cmd_id'. Include cmd_id field in command payload."

    # Test empty string values
    async def test_empty_string_values():
        connection_manager.publish.reset_mock()

        # Empty command - use topic pattern that doesn't extract command
        payload_empty_command = json.dumps({"command": "", "cmd_id": "test_001", "value": 42})  # Empty string

        await handler.handle_command("icsia/device_01/cmd", payload_empty_command)
        # Should send error acknowledgment
        assert connection_manager.publish.called
        call_args = connection_manager.publish.call_args
        payload = call_args[0][1]
        assert payload["error_code"] == "INVALID_PAYLOAD"

        connection_manager.publish.reset_mock()

        # Empty cmd_id
        payload_empty_cmd_id = json.dumps({"command": "test_cmd", "cmd_id": "", "value": 42})  # Empty string

        await handler.handle_command("icsia/device_01/cmd/test_cmd", payload_empty_cmd_id)
        # Should send error acknowledgment
        assert connection_manager.publish.called
        call_args = connection_manager.publish.call_args
        payload = call_args[0][1]
        assert payload["error_code"] == "INVALID_PAYLOAD"

    # Run the async tests using asyncio.run for each
    asyncio.run(test_missing_command())
    asyncio.run(test_missing_cmd_id())
    asyncio.run(test_empty_string_values())


def test_timestamp_field_validation_behavior(trackable_command_handler):
    """Test that timestamp field is properly handled as a standard field."""
    command_config = {
        "test_timestamp": {
            "action": "start",  # Required field
            # NOTE: timestamp is NOT defined here but should be skipped in validation
        }
    }

    handler = trackable_command_handler
    handler.command_schemas = command_config

    # Test 1: Payload with timestamp field should validate successfully
    # (timestamp should be skipped during validation)
    payload_with_timestamp = {
        "command": "test_timestamp",
        "cmd_id": "test_001",
        "timestamp": "2025-08-10T14:30:15.123Z",  # Should be ignored during validation
        "action": "start",  # Required field
    }

    # Should not raise any validation errors
    handler.validate_command_payload("test_timestamp", payload_with_timestamp)

    # Test 2: Payload without timestamp should also validate successfully
    # (timestamp is auto-generated by server)
    payload_without_timestamp = {
        "command": "test_timestamp",
        "cmd_id": "test_002",
        "action": "start",  # Required field
    }

    # Should not raise any validation errors
    handler.validate_command_payload("test_timestamp", payload_without_timestamp)

    # Test 3: Missing required field should still fail validation
    # (even with timestamp present)
    payload_missing_required = {
        "command": "test_timestamp",
        "cmd_id": "test_003",
        "timestamp": "2025-08-10T14:30:15.123Z",
        # Missing "action" field
    }

    # Should raise validation error for missing required field
    with pytest.raises(CommandValidationError, match="missing required field 'action'"):
        handler.validate_command_payload("test_timestamp", payload_missing_required)


# ============================================================================
# Command Handler Fixes Tests (Error Handling, Thread Safety, Graceful Shutdown)
# ============================================================================


@pytest.mark.asyncio
async def test_error_code_consistency(trackable_command_handler, trackable_connection_manager):
    """Test that error codes are consistent across all error scenarios."""
    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    connection_manager = trackable_connection_manager

    # Test 1: Invalid JSON should use INVALID_JSON error code
    await handler.handle_command("icsia/test_device/cmd/test", "{ invalid json }")

    # Check that publish was called with INVALID_JSON error code
    assert connection_manager.publish.called
    call_args = connection_manager.publish.call_args
    payload = call_args[0][1]
    assert payload["error_code"] == "INVALID_JSON"
    assert (
        "Invalid JSON payload:" in payload["error_msg"]
        and "Please check JSON syntax and formatting." in payload["error_msg"]
    )

    # Reset mock
    connection_manager.publish.reset_mock()

    # Test 2: Missing cmd_id should send INVALID_PAYLOAD error acknowledgment
    await handler.handle_command("icsia/test_device/cmd/test", '{"command": "test"}')

    # Check that publish was called with INVALID_PAYLOAD error code
    assert connection_manager.publish.called
    call_args = connection_manager.publish.call_args
    payload = call_args[0][1]
    assert payload["error_code"] == "INVALID_PAYLOAD"
    assert payload["error_msg"] == "Missing required field 'cmd_id'. Include cmd_id field in command payload."

    # Reset mock
    connection_manager.publish.reset_mock()

    # Test 3: Missing command name should use INVALID_PAYLOAD error code
    await handler.handle_command("icsia/test_device/cmd", '{"cmd_id": "test123"}')

    # Check error code
    assert connection_manager.publish.called
    call_args = connection_manager.publish.call_args
    payload = call_args[0][1]
    assert payload["error_code"] == "INVALID_PAYLOAD"
    assert (
        payload["error_msg"]
        == "Missing required field 'command'. Include command field in payload or specify command in topic."
    )

    # Reset mock
    connection_manager.publish.reset_mock()

    # Test 4: Unknown command should use UNKNOWN_COMMAND error code
    await handler.handle_command("icsia/test_device/cmd/unknown", '{"cmd_id": "test123", "command": "unknown"}')

    # Should send acknowledgment first, then completion with error
    assert connection_manager.publish.call_count == 2

    # Check completion (second call)
    completion_call = connection_manager.publish.call_args_list[1]
    completion_payload = completion_call[0][1]
    assert completion_payload["error_code"] == "UNKNOWN_COMMAND"
    assert (
        "Unknown command 'unknown'." in completion_payload["error_msg"]
        and "Available commands:" in completion_payload["error_msg"]
    )


@pytest.mark.asyncio
async def test_status_publisher_thread_safety(
    trackable_command_handler, trackable_status_publisher, trackable_connection_manager
):
    """Test that status publisher updates are thread-safe."""
    import asyncio

    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    status_publisher = trackable_status_publisher

    # Set status publisher on handler
    handler.set_status_publisher(status_publisher)

    # Test that status publisher lock exists
    assert hasattr(handler, "_status_publisher_lock")
    assert isinstance(handler._status_publisher_lock, asyncio.Lock)

    # Test concurrent status updates don't conflict
    async def test_concurrent_commands():
        # These should all use the status publisher lock
        tasks = []
        for i in range(5):
            task = asyncio.create_task(
                handler.handle_command(
                    f"icsia/test_device_{i}/cmd/start_task",
                    f'{{"cmd_id": "test{i}", "command": "start_task"}}',
                )
            )
            tasks.append(task)

        # Wait for all to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    await test_concurrent_commands()

    # Verify status publisher was called (should be thread-safe)
    assert status_publisher.set_operational_status.called


@pytest.mark.asyncio
async def test_connection_manager_thread_safety(trackable_command_handler, trackable_connection_manager):
    """Test that connection manager operations are thread-safe."""
    import asyncio

    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    connection_manager = trackable_connection_manager

    # Test that connection lock exists
    assert hasattr(handler, "_connection_lock")
    assert isinstance(handler._connection_lock, asyncio.Lock)

    # Test concurrent connection operations
    async def test_concurrent_publishes():
        tasks = []
        for i in range(3):
            task = asyncio.create_task(
                handler.handle_command(
                    f"icsia/test_device_{i}/cmd/test",
                    f'{{"cmd_id": "test{i}", "command": "test"}}',
                )
            )
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    await test_concurrent_publishes()

    # Verify connection manager publish was called
    assert connection_manager.publish.called


@pytest.mark.asyncio
async def test_graceful_shutdown_mechanism(trackable_command_handler, trackable_connection_manager):
    """Test graceful shutdown functionality."""
    # Use trackable fixtures that properly manage the logger
    handler = trackable_command_handler
    connection_manager = trackable_connection_manager

    # Test shutdown mechanism exists
    assert hasattr(handler, "_shutdown_requested")
    assert hasattr(handler, "_shutdown_event")
    assert hasattr(handler, "_active_commands")

    # Test that shutdown flag prevents new commands
    handler._shutdown_requested = True
    await handler.handle_command("icsia/test_device/cmd/test", '{"cmd_id": "test", "command": "test"}')

    # Should not process the command
    assert not connection_manager.publish.called

    # Test shutdown method with cleanup
    handler._shutdown_requested = False
    try:
        await handler.shutdown(timeout=1.0)

        assert handler._shutdown_requested is True
        assert handler._shutdown_event.is_set()
    finally:
        # Reset the handler to clean state to prevent issues in other tests
        handler._shutdown_requested = False
        handler._shutdown_event.clear()
        handler._active_commands.clear()


@pytest.mark.asyncio
async def test_command_execution_error_handling(trackable_command_handler, trackable_connection_manager):
    """Test error handling during command execution."""
    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    connection_manager = trackable_connection_manager

    # Register a command that raises an exception
    async def failing_command(data):
        raise RuntimeError("Simulated command failure")

    handler.register_command("fail_test", failing_command)

    # Execute the failing command
    await handler.handle_command(
        "icsia/test_device/cmd/fail_test",
        '{"cmd_id": "test123", "command": "fail_test"}',
    )

    # Should send acknowledgment first, then completion with execution error
    assert connection_manager.publish.call_count == 2

    # Check completion (second call) has EXECUTION_ERROR
    completion_call = connection_manager.publish.call_args_list[1]
    completion_payload = completion_call[0][1]
    assert completion_payload["error_code"] == "EXECUTION_ERROR"
    assert (
        "Command execution failed:" in completion_payload["error_msg"]
        and "Check command implementation and parameters." in completion_payload["error_msg"]
    )


@pytest.mark.asyncio
async def test_command_validation_error_handling(trackable_command_handler, trackable_connection_manager):
    """Test error handling for command validation failures."""
    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    connection_manager = trackable_connection_manager

    # Create command config for validation testing
    command_config = {"validate_test": {"required_field": "value", "required_number": 42}}

    # Update handler's config (correct property name)
    handler.command_schemas = command_config

    # Register a simple command
    async def test_command(data):
        return {"status": "success"}

    handler.register_command("validate_test", test_command)

    # Execute command with validation error (missing required field)
    await handler.handle_command(
        "icsia/test_device/cmd/validate_test",
        '{"cmd_id": "test123", "command": "validate_test", "required_field": "value"}',
    )

    # Should send acknowledgment first, then completion with validation error
    assert connection_manager.publish.call_count == 2

    # Check completion (second call) has VALIDATION_ERROR
    completion_call = connection_manager.publish.call_args_list[1]
    completion_payload = completion_call[0][1]
    assert completion_payload["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_status_publisher_error_path_updates(
    trackable_command_handler, trackable_status_publisher, trackable_connection_manager
):
    """Test that status publisher is updated correctly in error paths."""
    # Use trackable fixtures that have mocking built-in
    handler = trackable_command_handler
    status_publisher = trackable_status_publisher

    # Set status publisher on handler
    handler.set_status_publisher(status_publisher)

    # Test 1: Invalid JSON should update status publisher with error
    await handler.handle_command("icsia/test_device/cmd/test", "{ invalid json }")
    status_publisher.set_operational_status.assert_called_with("error")

    # Reset mock
    status_publisher.reset_mock()

    # Test 2: Missing cmd_id should update status publisher with error
    await handler.handle_command("icsia/test_device/cmd/test", '{"command": "test"}')
    status_publisher.set_operational_status.assert_called_with("error")

    # Reset mock
    status_publisher.reset_mock()

    # Test 3: Unknown command should update status publisher with error
    await handler.handle_command("icsia/test_device/cmd/unknown", '{"cmd_id": "test123", "command": "unknown"}')
    status_publisher.set_operational_status.assert_called_with("error")
