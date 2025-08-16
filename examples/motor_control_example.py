#!/usr/bin/env python3
"""Example motor control application using custom status payloads.

This example demonstrates how to use the MQTT application framework with
custom status payload configuration for motor control applications.

The status payload is defined in motor_config.yaml and updated in real-time
as the motor system state changes.
"""

import asyncio
import random
import time
from typing import Any

from mqtt_application import MqttApplication


class MotorControlApp:
    """Motor control application with Motor Control API compliance."""

    def __init__(self, config_file: str = "config.yaml"):
        # Motor state variables
        self.current_position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.current_speed = 100
        self.is_moving = False
        self.is_homed = False

        # System monitoring variables
        self.temperature = 25.0
        self.voltage = 12.0
        self.error_count = 0
        self.start_time = time.time()

        # Initialize MQTT application with motor control config
        self.app = MqttApplication(config_file)

        self._setup_commands()

    def _setup_commands(self):
        """Register motor control and camera commands."""
        # Motor Control API commands
        self.app.register_command("move", self._move_command)
        self.app.register_command("home", self._home_command)
        self.app.register_command("stop", self._stop_command)
        self.app.register_command("set_speed", self._set_speed_command)
        self.app.register_command("get_position", self._get_position_command)

    def _update_system_status(self):
        """Update the status payload with current system values.

        This method reads the current system state and updates the MQTT
        status payload in one operation. The fields match those defined
        in motor_config.yaml under status.payload.
        """
        # Simulate some sensor readings
        self.temperature += random.uniform(-0.5, 0.5)  # Temperature drift
        self.voltage = 12.0 + random.uniform(-0.2, 0.2)  # Voltage variation

        # Build the complete status update
        current_values = {
            # Motor position (required by Motor Control API)
            "current_position": self.current_position.copy(),
            "speed": self.current_speed,
            "moving": self.is_moving,
            "homed": self.is_homed,
            # System monitoring fields
            "temperature": round(self.temperature, 1),
            "voltage": round(self.voltage, 2),
            "error_count": self.error_count,
            "uptime_seconds": int(time.time() - self.start_time),
        }

        # Update the status payload in one go
        self.app.update_status(current_values)

        if self.app.logger:
            self.app.logger.info(
                f"Status updated: Position=({self.current_position['x']: .1f}, "
                f"{self.current_position['y']: .1f}, {self.current_position['z']: .1f}), "
                f"Moving={self.is_moving}, Temp={self.temperature: .1f}°C"
            )

    async def _move_command(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle move command according to Motor Control API.

        Payload is automatically validated against the schema defined in config.yaml.
        """
        try:
            # Data is already validated, so we can access fields safely
            target_position = data["target_position"]  # Guaranteed to exist with x, y, z
            speed = data.get("speed", self.current_speed)  # Default applied if not provided
            mode = data.get("mode", "absolute")  # Default applied if not provided

            if self.app.logger:
                self.app.logger.info(f"Moving to position: {target_position}, speed: {speed}, mode: {mode}")

            # Set moving state and update status
            self.is_moving = True
            self.current_speed = speed
            self._update_system_status()

            # Simulate movement time based on distance
            if mode == "absolute":
                distance = sum(abs(target_position[axis] - self.current_position[axis]) for axis in ["x", "y", "z"])
            else:
                distance = sum(abs(target_position.get(axis, 0)) for axis in ["x", "y", "z"])

            movement_time = max(0.1, distance / speed)  # Simple time calculation
            await asyncio.sleep(movement_time)

            # Update position based on mode
            if mode == "absolute":
                self.current_position = target_position.copy()
            elif mode == "relative":
                for axis in ["x", "y", "z"]:
                    self.current_position[axis] += target_position.get(axis, 0)

            # Movement complete
            self.is_moving = False
            self._update_system_status()

            return {
                "final_position": self.current_position.copy(),
                "speed": speed,
                "mode": mode,
                "movement_time": movement_time,
            }

        except Exception:
            self.is_moving = False
            self.error_count += 1
            self._update_system_status()
            raise

    async def _home_command(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle home command according to Motor Control API.

        Payload is automatically validated against the schema defined in config.yaml.
        """
        try:
            axis = data.get("axis", "all")  # Default applied by validation framework
            if self.app.logger:
                self.app.logger.info(f"Starting homing sequence for axis: {axis}")

            self.is_moving = True
            self.is_homed = False
            self._update_system_status()

            # Simulate homing sequence
            await asyncio.sleep(0.5)  # Homing takes time

            # Set home position (for this example, we home all axes)
            if axis == "all":
                self.current_position = {"x": 0.0, "y": 0.0, "z": 0.0}
            elif axis in ["x", "y", "z"]:
                self.current_position[axis] = 0.0

            self.is_homed = True
            self.is_moving = False
            self._update_system_status()

            if self.app.logger:
                self.app.logger.info("Homing sequence completed")

            return {
                "homed": True,
                "axis": axis,
                "home_position": self.current_position.copy(),
            }

        except Exception:
            self.is_moving = False
            self.error_count += 1
            self._update_system_status()
            raise

    async def _stop_command(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle stop command according to Motor Control API."""
        if self.app.logger:
            self.app.logger.warning("Emergency stop activated")

        self.is_moving = False
        self._update_system_status()

        return {"stopped": True, "final_position": self.current_position.copy()}

    async def _set_speed_command(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle set_speed command according to Motor Control API.

        Payload is automatically validated against the schema defined in config.yaml.
        """
        try:
            # Data is already validated, so speed is guaranteed to exist and be correct type
            speed = data["speed"]  # Guaranteed to exist
            units = data.get("units", "mm/s")  # Default applied if not provided

            if speed <= 0:
                self.error_count += 1
                self._update_system_status()
                raise ValueError("Speed must be positive")

            old_speed = self.current_speed
            self.current_speed = speed
            self._update_system_status()

            if self.app.logger:
                self.app.logger.info(f"Speed changed from {old_speed} to {speed} {units}")

            return {"old_speed": old_speed, "new_speed": speed, "units": units}

        except Exception:
            self.error_count += 1
            self._update_system_status()
            raise

    async def _get_position_command(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle get_position command - returns current motor state."""
        self._update_system_status()

        return {
            "current_position": self.current_position.copy(),
            "speed": self.current_speed,
            "moving": self.is_moving,
            "homed": self.is_homed,
            "temperature": self.temperature,
            "voltage": self.voltage,
            "uptime_seconds": int(time.time() - self.start_time),
        }

    async def _status_monitor_loop(self):
        """Background task to periodically update status."""
        while True:
            try:
                await asyncio.sleep(5.0)  # Update every 5 seconds
                self._update_system_status()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.app.logger:
                    self.app.logger.error(f"Error in status monitor: {e}")
                self.error_count += 1

    async def run(self):
        """Run the motor control application."""
        async with self.app as app:
            # Log startup information
            startup_info = {
                "device_id": app.app_config.get("device", {}).get("device_id", "motor_controller_01"),
                "mqtt_broker": app.app_config.get("mqtt", {}).get("broker", "test.mosquitto.org"),
                "status_topic": app.app_config.get("topics", {}).get("status", {}).get("current", "unknown"),
                "command_topic": app.app_config.get("topics", {}).get("command", "unknown"),
            }
            if app.logger:
                app.logger.info("Motor Control Application Started", startup_info)

            # Start background status monitoring
            status_task = asyncio.create_task(self._status_monitor_loop())

            # Initial status update
            self._update_system_status()

            try:
                namespace = app.app_config.get("namespace", "icsia")
                device_id = app.app_config.get("device", {}).get("device_id", "motor_controller_01")
                command_info = {
                    "move": f"{namespace}/{device_id}/cmd/move",
                    "home": f"{namespace}/{device_id}/cmd/home",
                    "stop": f"{namespace}/{device_id}/cmd/stop",
                    "set_speed": f"{namespace}/{device_id}/cmd/set_speed",
                }
                if app.logger:
                    app.logger.info(
                        "Motor control ready. Send MQTT commands to control the motor.",
                        {"available_commands": command_info},
                    )

                await app.run()

            finally:
                status_task.cancel()
                try:
                    await status_task
                except asyncio.CancelledError:
                    pass


async def main():
    """Main entry point."""
    try:
        motor_app = MotorControlApp("config.yaml")
        await motor_app.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")  # Keep this print for immediate user feedback
    except Exception as e:
        print(f"Application error: {e}")  # Keep this print for immediate error visibility
        raise


if __name__ == "__main__":
    asyncio.run(main())
