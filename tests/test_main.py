"""Integration tests demonstrating how external applications would use the mqtt_application module."""

import asyncio
import pytest
import tempfile
import os
import yaml

from mqtt_application import (
    MqttApplication,
    AppConfig,
    AsyncMqttClient,
    AsyncCommandHandler,
    MqttConnectionManager,
    PeriodicStatusPublisher,
)


class TestMqttApplicationModule:
    """Tests for how external applications would use the mqtt_application module."""

    def test_module_imports(self):
        """Test that all main components can be imported from the module."""
        # Test that all main classes are available
        from mqtt_application import (
            MqttApplication,
            AsyncMqttClient,
            MqttConnectionManager,
            AppConfig,
            async_worker,
            create_worker_pool,
        )

        # Verify they are classes/functions
        assert callable(MqttApplication)
        assert callable(AsyncMqttClient)
        assert callable(AsyncCommandHandler)
        assert callable(MqttConnectionManager)
        assert callable(PeriodicStatusPublisher)
        assert callable(AppConfig)
        assert callable(async_worker)
        assert callable(create_worker_pool)

    def test_mqtt_application_simple_usage(self):
        """Test the simplest way an external app would use MqttApplication."""
        # This is how an external application would typically use the module
        app = MqttApplication()

        # Verify initial state
        assert app.app_config == {}
        assert app.logger is None
        assert app.connection_manager is None
        assert app.command_handler is None
        assert app.status_publisher is None
        assert app.mqtt_client is None
        assert app.message_queue is None
        assert app.worker_tasks == []
        assert app.mqtt_task is None
        assert app._custom_commands == {}
        assert app._running is False

    def test_mqtt_application_with_config_override(self):
        """Test MqttApplication with configuration override (typical external usage)."""
        # External app providing custom configuration
        config_override = {
            "device_id": "external_app_device",
            "namespace": "my_company",
            "worker_count": 2,
            "status_interval": 45.0,
        }

        app = MqttApplication(config_override=config_override)
        config = app._create_app_config()

        # Verify overrides are applied
        assert config["device_id"] == "external_app_device"
        assert config["namespace"] == "my_company"
        assert config["worker_count"] == 2
        assert config["status_interval"] == 45.0

    def test_mqtt_application_with_custom_config_file(self):
        """Test MqttApplication with custom config file (external app pattern)."""
        # Create a temporary config file like an external app would
        config_data = {
            "mqtt": {"broker": "custom.broker.com", "port": 8883},
            "device": {"device_id": "external_custom_device"},
            "namespace": "external_namespace",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name

        try:
            app = MqttApplication(config_file=temp_config_path)
            config = app._create_app_config()

            # Verify custom config is loaded
            assert config["mqtt"]["mqtt_broker"] == "custom.broker.com"
            assert config["mqtt"]["mqtt_port"] == 8883
            assert config["device_id"] == "external_custom_device"
            assert config["namespace"] == "external_namespace"
        finally:
            os.unlink(temp_config_path)

    def test_command_registration_pattern(self):
        """Test how external apps would register custom commands."""
        app = MqttApplication()

        # External app defining motion control business logic
        def move_axis(data):
            """Move axis to specified position."""
            axis = data.get("axis", "x")
            position = data.get("position", 0)
            return {"status": "moving", "axis": axis, "target_position": position}

        async def home_all_axes(data):
            """Home all axes asynchronously."""
            await asyncio.sleep(0.01)  # Simulate async homing operation
            axes = data.get("axes", ["x", "y", "z"])
            return {"status": "homed", "axes": axes, "positions": [0, 0, 0]}

        # Register commands like a motion control app would
        app.register_command("move", move_axis)
        app.register_command("home", home_all_axes)

        # Verify registration
        assert "move" in app._custom_commands
        assert "home" in app._custom_commands
        assert app._custom_commands["move"] == move_axis
        assert app._custom_commands["home"] == home_all_axes

    @pytest.mark.asyncio
    async def test_mqtt_application_context_manager_usage(self):
        """Test the typical async context manager pattern external apps would use."""
        # This simulates how an external application would use the module
        config_override = {
            "mqtt": {
                "mqtt_broker": "test.mosquitto.org",
                "mqtt_port": 1883,
                "reconnect_interval": 1,
                "max_reconnect_attempts": 2,
            },
            "device_id": "external_test_app",
            "worker_count": 1,
            "status_interval": 120.0,  # Long interval to avoid frequent operations
        }

        # External app custom command
        async def handle_motion_command(data):
            """Handle motion control commands."""
            command_type = data.get("type", "unknown")
            if command_type == "move":
                return {
                    "status": "moving",
                    "axis": data.get("axis"),
                    "position": data.get("position"),
                }
            elif command_type == "stop":
                return {"status": "stopped", "emergency": data.get("emergency", False)}
            else:
                return {"status": "unknown_command", "type": command_type}

        async with MqttApplication(config_override=config_override) as app:
            # Register custom business logic
            app.register_command("motion_command", handle_motion_command)

            # Verify the app is properly initialized
            assert app.logger is not None
            assert app.connection_manager is not None
            assert app.command_handler is not None
            assert app.status_publisher is not None
            assert app.mqtt_client is not None
            assert app.message_queue is not None

            # Verify custom command is registered
            assert "motion_command" in app._custom_commands

            # Verify component types (what external apps would expect)
            from mqtt_application import (
                AsyncCommandHandler,
                AsyncMqttClient,
                MqttConnectionManager,
                PeriodicStatusPublisher,
            )
            from mqtt_logger import MqttLogger

            assert isinstance(app.logger, MqttLogger)
            assert isinstance(app.connection_manager, MqttConnectionManager)
            assert isinstance(app.command_handler, AsyncCommandHandler)
            assert isinstance(app.status_publisher, PeriodicStatusPublisher)
            assert isinstance(app.mqtt_client, AsyncMqttClient)
            assert isinstance(app.message_queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_external_app_run_pattern(self):
        """Test how an external app would run the MQTT application."""
        config_override = {
            "mqtt": {
                "mqtt_broker": "test.mosquitto.org",
                "mqtt_port": 1883,
                "reconnect_interval": 1,
                "max_reconnect_attempts": 1,
            },
            "device_id": "external_run_test",
            "worker_count": 1,
            "status_interval": 300.0,  # Very long interval
        }

        async def execute_motion_sequence(data):
            """Simulate motion control sequence execution."""
            sequence = data.get("sequence", [])
            return {
                "executed": True,
                "sequence": sequence,
                "duration": len(sequence) * 0.1,
            }

        async with MqttApplication(config_override=config_override) as app:
            # Register motion control business logic
            app.register_command("execute_sequence", execute_motion_sequence)

            # Start the application briefly (like an external app would)
            run_task = asyncio.create_task(app.run())

            # Let it run briefly
            await asyncio.sleep(0.3)

            # Stop the application (graceful shutdown)
            app.stop()

            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(run_task, timeout=2.0)
            except asyncio.TimeoutError:
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass

    def test_standalone_usage_pattern(self):
        """Test the standalone usage pattern for external apps."""
        # Test the run_from_config method that external apps would use
        # for simple standalone execution

        config_override = {"device_id": "standalone_test", "worker_count": 1}

        # Verify the method exists and is callable
        assert hasattr(MqttApplication, "run_from_config")
        assert callable(MqttApplication.run_from_config)

        # Note: We don't actually call it here since it would run indefinitely
        # External apps would use: MqttApplication.run_from_config(config_override=config_override)

    @pytest.mark.asyncio
    async def test_manual_component_usage_pattern(self):
        """Test how external apps might use individual components manually."""
        # Some external apps might want to use components individually
        from mqtt_logger import MqttLogger

        # Get configuration (external app pattern)
        app_config = AppConfig.from_file()
        mqtt_config = app_config.get_mqtt_config()
        device_id = app_config.device.device_id

        # External app creates logger
        logger_config = {
            "log_file": f"{device_id}.log",
            "mqtt_broker": mqtt_config["mqtt_broker"],
            "mqtt_port": mqtt_config["mqtt_port"],
            "mqtt_topic": f"external_app/{device_id}/logs",
            "log_level": app_config.get_log_level_int(),
        }

        async with MqttLogger(**logger_config) as logger:
            # External app creates individual components
            message_queue = asyncio.Queue()

            connection_manager = MqttConnectionManager(
                broker=mqtt_config["mqtt_broker"],
                port=mqtt_config["mqtt_port"],
                logger=logger,
            )

            mqtt_client = AsyncMqttClient(
                topics=["external_app/+/cmd/#"],
                message_queue=message_queue,
                logger=logger,
                connection_manager=connection_manager,
            )

            # Verify components are created correctly
            assert connection_manager is not None
            assert mqtt_client is not None
            assert message_queue is not None

            # External apps would continue with their custom logic here

    def test_error_handling_patterns(self):
        """Test error handling patterns external apps should be aware of."""
        app = MqttApplication()

        # Test that run() requires initialization
        async def test_uninitialized_run():
            with pytest.raises(RuntimeError, match="Application not initialized"):
                await app.run()

        # Run the test
        asyncio.run(test_uninitialized_run())

        # Test stop method behavior
        assert app._running is False
        app.stop()
        assert app._running is False


class TestMqttApplicationIntegration:
    """Integration tests with MQTT connections (for external app validation)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_external_app_integration(self):
        """Test a realistic external application integration scenario."""
        # Simulate a real external application configuration
        config_override = {
            "mqtt": {
                "mqtt_broker": "test.mosquitto.org",
                "mqtt_port": 1883,
                "reconnect_interval": 1,
                "max_reconnect_attempts": 3,
            },
            "device_id": "integration_external_app",
            "namespace": "test_company",
            "worker_count": 2,
            "status_interval": 60.0,
        }

        # External app business logic
        async def process_motion_command(data):
            """Simulate processing a motion control command."""
            axis = data.get("axis", "x")
            command = data.get("command", "move")
            position = data.get("position", 0)
            return {
                "status": "executed",
                "axis": axis,
                "command": command,
                "position": position,
                "timestamp": "2025-01-01T00:00:00.000Z",
            }

        async def calibrate_axis(data):
            """Simulate axis calibration."""
            await asyncio.sleep(0.1)  # Simulate async calibration
            axis = data.get("axis", "x")
            return {"calibrated": True, "axis": axis, "reference_position": 0}

        async with MqttApplication(config_override=config_override) as app:
            # Register external app's motion control logic
            app.register_command("process_motion_command", process_motion_command)
            app.register_command("calibrate_axis", calibrate_axis)

            # Start the application
            run_task = asyncio.create_task(app.run())

            # Let it run and establish connections
            await asyncio.sleep(1.0)

            # In a real external app, this would run indefinitely
            # Here we stop it for testing
            app.stop()

            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(run_task, timeout=3.0)
            except asyncio.TimeoutError:
                run_task.cancel()
                await run_task

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_external_app_with_custom_config_file_integration(self):
        """Test external app using custom config file with MQTT."""
        # Create custom config like an external app would
        config_data = {
            "mqtt": {
                "broker": "test.mosquitto.org",
                "port": 1883,
                "reconnect_interval": 1,
                "max_reconnect_attempts": 2,
            },
            "device": {
                "device_id": "external_config_test",
                "status_publish_interval": 90.0,
            },
            "namespace": "external_integration",
            "workers": {"count": 1},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name

        try:

            async def motion_control_logic(data):
                """Motion control business logic for external app."""
                return {"motion_processing": "completed", "data": data}

            async with MqttApplication(config_file=temp_config_path) as app:
                app.register_command("motion_control", motion_control_logic)

                # Brief run to test integration
                run_task = asyncio.create_task(app.run())
                await asyncio.sleep(0.8)
                app.stop()

                try:
                    await asyncio.wait_for(run_task, timeout=2.0)
                except asyncio.TimeoutError:
                    run_task.cancel()
                    await run_task
        finally:
            os.unlink(temp_config_path)
