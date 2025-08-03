"""Pytest configuration and fixtures for MQTT client tests."""

import asyncio
import tempfile
import os
import pytest
import pytest_asyncio
import yaml

from mqtt_application import (
    AppConfig,
    AsyncCommandHandler,
    AsyncMqttClient,
    PeriodicStatusPublisher,
    MqttConnectionManager,
)
from mqtt_logger import MqttLogger
from mqtt_connector import MqttConnector


# Add pytest markers for integration tests
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "integration: mark test as an integration test")


@pytest_asyncio.fixture
async def mqtt_logger():
    """Create a real MqttLogger instance for testing."""
    logger = MqttLogger(
        mqtt_broker="test.mosquitto.org",
        mqtt_port=1883,
        mqtt_topic="test/logs",
        log_file="test.log",
        log_level=20,  # INFO level
        service_name="test_service",
    )

    # Start the logger
    await logger.__aenter__()

    yield logger

    # Enhanced cleanup to prevent warnings
    try:
        await logger.__aexit__(None, None, None)
        # Wait for any pending async operations
        await asyncio.sleep(0.1)
        # Ensure all tasks are properly cleaned up
        import gc

        gc.collect()
    except Exception:
        # Silence cleanup errors that might occur during test teardown
        pass


@pytest_asyncio.fixture
async def mqtt_connector():
    """Create a real MqttConnector instance for testing."""
    connector = MqttConnector(
        mqtt_broker="test.mosquitto.org", mqtt_port=1883, client_id="test_client"
    )
    yield connector
    # Cleanup
    if connector.connected:
        await connector.disconnect()


@pytest.fixture
def sample_config_data():
    """Sample configuration data for testing."""
    return {
        "mqtt": {
            "broker": "test.mosquitto.org",
            "port": 1883,
            "reconnect_interval": 5,
            "max_reconnect_attempts": -1,
            "throttle_interval": 0.1,
        },
        "device": {"device_id": "test_device_01", "status_publish_interval": 30.0},
        "topics": {
            "command": "icsia/+/cmd/#",
            "status": {
                "ack": "icsia/{device_id}/status/ack",
                "completion": "icsia/{device_id}/status/completion",
                "current": "icsia/{device_id}/status/current",
            },
            "log": "icsia/{device_id}/logs",
        },
        "logger": {"log_file": "icsia_{device_id}.log", "log_level": "INFO"},
        "workers": {"count": 3},
    }


@pytest.fixture
def temp_config_file(sample_config_data):
    """Create a temporary configuration file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_config_data, f)
        temp_file = f.name

    yield temp_file

    # Cleanup
    os.unlink(temp_file)


@pytest.fixture
def config_instance(temp_config_file):
    """Create an AppConfig instance with temporary configuration file."""
    return AppConfig.from_file(temp_config_file)


@pytest.fixture
def message_queue():
    """Create an asyncio queue for testing."""
    return asyncio.Queue()


@pytest.fixture
def sample_mqtt_message():
    """Sample MQTT message data for testing."""
    return {
        "topic": "icsia/test_device_01/cmd/start_task",
        "payload": '{"command": "start_task", "cmd_id": "cmd_123", "data": {"task_name": "test_task"}}',
    }


@pytest_asyncio.fixture
async def connection_manager(mqtt_logger):
    """Create a shared MqttConnectionManager instance for testing."""
    manager = MqttConnectionManager(
        broker="test.mosquitto.org",
        port=1883,
        logger=mqtt_logger,
        client_id="test_connection_manager",
        reconnect_interval=1,  # Short interval for tests
        max_reconnect_attempts=2,  # Limit attempts for tests
    )
    yield manager
    # Cleanup
    try:
        if manager.is_connected:
            await manager.disconnect()
    except Exception:
        # Handle cleanup gracefully
        pass


@pytest_asyncio.fixture
async def command_handler(mqtt_logger, connection_manager):
    """Create an AsyncCommandHandler instance for testing."""
    handler = AsyncCommandHandler(
        logger=mqtt_logger, connection_manager=connection_manager
    )
    yield handler

    # Cleanup is handled by the connection_manager fixture


@pytest_asyncio.fixture
async def status_publisher(mqtt_logger, connection_manager, config_instance):
    """Create a PeriodicStatusPublisher instance for testing."""
    # Get status payload from config (this would typically be in the YAML)
    status_payload = {}

    publisher = PeriodicStatusPublisher(
        device_id="test_device_01",
        logger=mqtt_logger,
        connection_manager=connection_manager,
        publish_interval=1.0,  # Short interval for testing
        config_status_payload=status_payload,
    )
    yield publisher
    # Cleanup is handled by the connection_manager fixture


@pytest_asyncio.fixture
async def mqtt_client(mqtt_logger, message_queue, connection_manager):
    """Create an AsyncMqttClient instance for testing."""
    client = AsyncMqttClient(
        topics=["icsia/+/cmd/#"],
        message_queue=message_queue,
        logger=mqtt_logger,
        connection_manager=connection_manager,
    )
    yield client

    # Cleanup is handled by the connection_manager fixture


# ============================================================================
# Trackable Fixtures for Testing (Hybrid Real + Mock)
# ============================================================================


@pytest_asyncio.fixture
async def trackable_connection_manager(connection_manager):
    """Connection manager that allows method tracking for tests."""
    from unittest.mock import AsyncMock

    # Use real fixture but override publish for tracking
    connection_manager.publish = AsyncMock()
    # Mock the underlying connector's connected property for connection state
    connection_manager._connector.connected = True
    return connection_manager


@pytest_asyncio.fixture
async def trackable_command_handler(mqtt_logger, trackable_connection_manager):
    """Command handler that allows method tracking."""
    handler = AsyncCommandHandler(
        logger=mqtt_logger, connection_manager=trackable_connection_manager
    )
    # Don't override send_acknowledgment - let it call the mocked publish method
    return handler


@pytest_asyncio.fixture
async def trackable_status_publisher(status_publisher):
    """Status publisher that allows method tracking for tests."""
    from unittest.mock import MagicMock

    # Use real fixture but override methods for tracking
    status_publisher.set_operational_status = MagicMock()

    # Add a reset_mock method to match mock behavior
    def reset_mock():
        status_publisher.set_operational_status.reset_mock()

    status_publisher.reset_mock = reset_mock
    return status_publisher
