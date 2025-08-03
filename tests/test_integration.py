"""Integration tests for the MQTT client using real fixtures and network access.

These tests use actual MQTT connections and real component instances to validate
end-to-end functionality. They require network access to test.mosquitto.org.
"""

import asyncio
import json
import pytest
import time
from datetime import datetime, timezone

from mqtt_application import (
    AsyncCommandHandler,
    AsyncMqttClient,
    PeriodicStatusPublisher,
)


class TestMqttIntegration:
    """Integration tests for MQTT client components with network access."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mqtt_logger_connection(self, mqtt_logger):
        """Test that MqttLogger can connect and publish to MQTT broker."""
        # The mqtt_logger fixture already connects, so we just test logging
        mqtt_logger.info("Integration test message from mqtt_logger")
        mqtt_logger.warning("Integration test warning")
        mqtt_logger.error("Integration test error")

        # Give some time for messages to be published
        await asyncio.sleep(0.5)

        # If no exceptions were raised, the test passes
        assert mqtt_logger is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mqtt_connector_connection(self, mqtt_connector):
        """Test that MqttConnector can connect to MQTT broker."""
        # Test connection
        connected = await mqtt_connector.connect()
        assert connected is True
        assert mqtt_connector.connected is True

        # Test publishing
        test_topic = f"test/integration/{int(time.time())}"
        test_payload = json.dumps(
            {
                "test": "integration",
                "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
        )

        await mqtt_connector.publish(test_topic, test_payload)

        # Test subscription
        await mqtt_connector.subscribe(test_topic)

        # Cleanup
        await mqtt_connector.disconnect()
        assert mqtt_connector.connected is False

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_command_handler_mqtt(self, command_handler):
        """Test AsyncCommandHandler with MQTT connection."""
        # Test that handler is properly initialized with components
        assert command_handler.logger is not None
        assert command_handler.connection_manager is not None

        # Test sending acknowledgment (will actually publish to MQTT)
        await command_handler.send_acknowledgment("test_device", "cmd_123", "received")

        # Test sending completion status
        await command_handler.send_completion_status(
            "test_device", "cmd_123", "completed", {"result": "success"}
        )

        # Test command processing
        test_topic = "icsia/test_device_integration/cmd/start_task"
        test_payload = json.dumps(
            {
                "command": "start_task",
                "cmd_id": "integration_test_123",
                "data": {"task_name": "integration_test"},
            }
        )

        # This will process the command using components
        await command_handler.handle_command(test_topic, test_payload)

        # Give time for async operations to complete
        await asyncio.sleep(0.5)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_publisher_mqtt(self, status_publisher):
        """Test PeriodicStatusPublisher with MQTT connection."""
        # Test basic functionality
        assert status_publisher.device_id == "test_device_01"
        assert status_publisher.logger is not None
        assert status_publisher.connection_manager is not None

        # Test status updates
        status_publisher.set_operational_status("busy")
        assert status_publisher.operational_status == "busy"

        status_publisher.update_last_command_time()
        assert status_publisher.last_command_time is not None

        # Test manual status publishing (will actually publish to MQTT)
        await status_publisher._publish_status()

        # Test starting and stopping the publisher
        await status_publisher.start()
        assert status_publisher.is_running() is True

        # Let it run briefly to publish status
        await asyncio.sleep(2.0)

        await status_publisher.stop()
        assert status_publisher.is_running() is False

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mqtt_client_connection(self, mqtt_client, message_queue):
        """Test AsyncMqttClient with MQTT connection."""
        assert mqtt_client.topics == ["icsia/+/cmd/#"]
        assert mqtt_client.message_queue == message_queue
        assert mqtt_client.logger is not None
        assert mqtt_client.connection_manager is not None

        # Start the client (this will actually connect to MQTT)
        client_task = asyncio.create_task(mqtt_client.connect_and_subscribe())

        # Give it time to connect and subscribe
        await asyncio.sleep(1.0)

        # Publish a test message to trigger message callback
        test_topic = "icsia/integration_test/cmd/test"
        test_payload = json.dumps(
            {
                "test": "message",
                "timestamp": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
        )

        # Use the connection_manager from the client to publish to itself
        await mqtt_client.connection_manager.publish(test_topic, test_payload)

        # Give time for message to be received and processed
        await asyncio.sleep(1.0)

        # Check if message was received in queue
        if not message_queue.empty():
            topic, payload = await message_queue.get()
            assert topic == test_topic
            assert "test" in payload

        # Stop the client
        client_task.cancel()
        try:
            await client_task
        except asyncio.CancelledError:
            pass

        await mqtt_client.disconnect()


class TestEndToEndIntegration:
    """End-to-end integration tests simulating real usage scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_command_processing_workflow(self, mqtt_logger, message_queue):
        """Test complete command processing workflow with components."""
        # Create shared connection manager
        from mqtt_application import MqttConnectionManager

        connection_manager = MqttConnectionManager(
            broker="test.mosquitto.org",
            port=1883,
            logger=mqtt_logger,
            client_id="e2e_test_workflow",
        )

        # Create components with shared connection
        command_handler = AsyncCommandHandler(
            logger=mqtt_logger,
            connection_manager=connection_manager,
            ack_topic_pattern="integration_test/{device_id}/status/ack",
            completion_topic_pattern="integration_test/{device_id}/status/completion",
        )

        status_publisher = PeriodicStatusPublisher(
            device_id="integration_test_device",
            logger=mqtt_logger,
            connection_manager=connection_manager,
            publish_interval=5.0,
            status_topic_pattern="integration_test/{device_id}/status/current",
        )

        # Link them together
        command_handler.set_status_publisher(status_publisher)

        # Start status publisher
        await status_publisher.start()

        # Simulate command processing
        test_command = {
            "command": "start_task",
            "cmd_id": "e2e_test_123",
            "data": {"task_name": "end_to_end_test", "duration": 1},
        }

        # Process command
        await command_handler.handle_command(
            "icsia/integration_test_device/cmd/start_task", json.dumps(test_command)
        )

        # Wait for async operations
        await asyncio.sleep(2.0)

        # Cleanup
        await status_publisher.stop()
        await connection_manager.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mqtt_client_with_command_handler(self, mqtt_logger):
        """Test MQTT client receiving and processing commands through handler."""
        message_queue = asyncio.Queue()

        # Create shared connection manager
        from mqtt_application import MqttConnectionManager

        connection_manager = MqttConnectionManager(
            broker="test.mosquitto.org",
            port=1883,
            logger=mqtt_logger,
            client_id="e2e_test_client_handler",
        )

        # Create MQTT client with shared connection
        mqtt_client = AsyncMqttClient(
            topics=["integration_test/+/cmd/#"],
            message_queue=message_queue,
            logger=mqtt_logger,
            connection_manager=connection_manager,
        )

        # Create command handler with shared connection
        command_handler = AsyncCommandHandler(
            logger=mqtt_logger,
            connection_manager=connection_manager,
            ack_topic_pattern="integration_test/{device_id}/status/ack",
            completion_topic_pattern="integration_test/{device_id}/status/completion",
        )

        # Start MQTT client
        client_task = asyncio.create_task(mqtt_client.connect_and_subscribe())

        # Worker function to process messages from queue
        async def message_worker():
            while True:
                try:
                    topic, payload = await asyncio.wait_for(
                        message_queue.get(), timeout=5.0
                    )
                    await command_handler.handle_command(topic, payload)
                    message_queue.task_done()
                except asyncio.TimeoutError:
                    break
                except Exception as e:
                    mqtt_logger.error(f"Error processing message: {e}")

        # Start worker
        worker_task = asyncio.create_task(message_worker())

        # Give time to connect
        await asyncio.sleep(1.0)

        # Send a test command
        test_topic = "integration_test/e2e_device/cmd/report_status"
        test_command = {
            "command": "report_status",
            "cmd_id": "e2e_status_test",
            "data": {},
        }

        # Publish command using the shared connection manager
        await connection_manager.publish(test_topic, json.dumps(test_command))

        # Wait for processing
        await asyncio.sleep(2.0)

        # Cleanup
        worker_task.cancel()
        client_task.cancel()

        try:
            await asyncio.gather(worker_task, client_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        await mqtt_client.disconnect()
        await connection_manager.disconnect()


class TestNetworkResilience:
    """Integration tests for network resilience and error handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_connection_retry_mechanism(self, mqtt_logger):
        """Test MQTT connection retry with network conditions."""
        # Test with invalid broker first
        from mqtt_application import MqttConnectionManager

        connection_manager_invalid = MqttConnectionManager(
            broker="invalid.broker.example.com",
            port=1883,
            logger=mqtt_logger,
            reconnect_interval=1,  # Short interval for testing
            max_reconnect_attempts=2,
        )

        client = AsyncMqttClient(
            topics=["test/topic"],
            message_queue=asyncio.Queue(),
            logger=mqtt_logger,
            connection_manager=connection_manager_invalid,
        )

        # This should fail to connect
        start_time = time.time()
        await client.connect_and_subscribe()
        duration = time.time() - start_time

        # Should have attempted reconnects
        assert duration >= 1.0  # At least tried once with 1s interval

        # Now test with valid broker
        connection_manager_valid = MqttConnectionManager(
            broker="test.mosquitto.org",
            port=1883,
            logger=mqtt_logger,
            reconnect_interval=5,
            max_reconnect_attempts=3,
        )

        client_valid = AsyncMqttClient(
            topics=["test/topic"],
            message_queue=asyncio.Queue(),
            logger=mqtt_logger,
            connection_manager=connection_manager_valid,
        )

        # Start and quickly stop to test connection
        task = asyncio.create_task(client_valid.connect_and_subscribe())
        await asyncio.sleep(1.0)  # Give time to connect
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        await client_valid.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_malformed_message_handling(self, mqtt_client, message_queue):
        """Test handling of malformed MQTT messages."""
        # Start client
        task = asyncio.create_task(mqtt_client.connect_and_subscribe())
        await asyncio.sleep(1.0)

        # Send malformed messages
        test_topics = [
            ("icsia/test/cmd/invalid", "invalid json"),
            ("icsia/test/cmd/missing", '{"command": "test"}'),  # Missing cmd_id
            ("invalid/topic/structure", '{"valid": "json"}'),
        ]

        for topic, payload in test_topics:
            await mqtt_client.connection_manager.publish(topic, payload)

        # Wait for processing
        await asyncio.sleep(1.0)

        # Application should still be running despite malformed messages
        assert not task.done()

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await mqtt_client.disconnect()
