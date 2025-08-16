# MQTT Application

A comprehensive asynchronous MQTT client library for Python, designed for building robust IoT applications and message processing systems.

## Features

- **Asynchronous Architecture**: Built with `asyncio` for high-performance concurrent operations
- **Automatic Reconnection**: Robust connection handling with configurable retry logic
- **Message Processing**: Worker-based system for concurrent message handling
- **Status Publishing**: Periodic device status reporting
- **Command Handling**: Built-in command processing with acknowledgment system
- **Configuration Management**: YAML-based configuration with environment variable support
- **Logging Integration**: Seamless integration with mqtt-logger for distributed logging

## Installation

```bash
pip install muxu-io-mqtt-application
```

## Installation from Source

If you're working with the source code from this repository, you'll need to install the dependencies in the correct order:

```bash
cd ~/projects/icsia/dummy-icsia

# Create and activate virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # On Linux/macOS
# or
.venv\Scripts\activate     # On Windows

# Install the mqtt-logger package
pushd ../mqtt-logger && pip install -e "." && popd

# Install the mqtt-application package with dev dependencies
pushd ../mqtt-application && pip install -e "." && popd
```

## Dependencies

This package requires the following external modules:
- `mqtt-logger`: For MQTT-enabled logging capabilities
- `muxu-io-mqtt-connector`: For low-level MQTT connection management (PyPI package)

## Quick Start

### Simplified Usage (Recommended)

The easiest way to use the library is with the `MqttApplication` class that handles everything automatically:

```python
import asyncio
from mqtt_application import MqttApplication

async def main():
    # Everything configured from config.yaml
    async with MqttApplication() as app:
        await app.run()

if __name__ == "__main__":
    asyncio.run(main())
```

Or even simpler for standalone usage:

```python
from mqtt_application import MqttApplication

# One-liner to run the application
if __name__ == "__main__":
    MqttApplication.run_from_config()
```

### Custom Command Handlers

To add custom business logic, register command handlers:

```python
import asyncio
from mqtt_application import MqttApplication

async def my_custom_command(data):
    """Handle custom command."""
    # Your business logic here
    print(f"Processing custom command: {data}")
    return {"status": "completed", "result": "success"}

async def main():
    async with MqttApplication() as app:
        # Register custom commands
        app.register_command("my_command", my_custom_command)
        await app.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### Message Subscriptions

Subscribe to MQTT messages using config-based subscriptions or programmatic registration:

#### Config-Based Subscriptions (Recommended)

```yaml
# config.yaml
subscriptions:
  status_messages:
    topic_pattern: "icsia/+/status/current"
    callback_method: "_on_status_message"
  ack_messages:
    topic_pattern: "icsia/+/status/ack"
    callback_method: "_on_ack_message"
```

```python
class MyApplication:
    def __init__(self):
        # Pass self as callback_context so config can find your methods
        self.app = MqttApplication(callback_context=self)

    async def _on_status_message(self, topic: str, payload: str, properties):
        """Handle status messages from any device."""
        print(f"Status from {topic}: {payload}")

    async def _on_ack_message(self, topic: str, payload: str, properties):
        """Handle acknowledgment messages."""
        print(f"ACK from {topic}: {payload}")

    async def run(self):
        async with self.app:
            await self.app.run()
```

#### Programmatic Registration

```python
async def my_handler(topic: str, payload: str, properties):
    print(f"Message on {topic}: {payload}")

async def main():
    async with MqttApplication() as app:
        # Register handler for config-based subscriptions
        app.register_callback_handler("my_handler", my_handler)
        await app.run()
```

## Configuration

Create a `config.yaml` file in your project root:

```yaml
---
# MQTT Broker settings
mqtt:
  broker: "localhost"
  port: 1883
  reconnect_interval: 5
  max_reconnect_attempts: -1  # -1 means infinite attempts
  throttle_interval: 0.1

# Device configuration
device:
  device_id: "my_device_01"
  namespace: "icsia"  # Configurable namespace for topic patterns
  status_publish_interval: 30.0

# Auto-generated topic patterns from namespace + device_id:
# {namespace}/+/cmd/#
# {namespace}/{device_id}/logs
# {namespace}/{device_id}/status/ack
# {namespace}/{device_id}/status/completion
# {namespace}/{device_id}/status/current

# Logger settings
logger:
  log_file: "{device_id}.log"
  log_level: "INFO"

# Worker configuration
workers:
  count: 3
```

## API Reference

### AsyncMqttClient

The main MQTT client class for connecting to brokers and handling messages.

```python
AsyncMqttClient(
    broker_address: str,
    port: int,
    topics: list[str],
    message_queue: asyncio.Queue,
    logger: MqttLogger,
    reconnect_interval: int = 5,
    max_reconnect_attempts: int = -1
)
```

### AsyncCommandHandler

Handles command processing and acknowledgments.

```python
AsyncCommandHandler(
    logger: MqttLogger,
    mqtt_broker: Optional[str] = None,
    mqtt_port: Optional[int] = None,
    ack_topic_pattern: str = "devices/{device_id}/status/ack",
    completion_topic_pattern: str = "devices/{device_id}/status/completion"
)
```

### PeriodicStatusPublisher

Publishes device status at regular intervals.

```python
PeriodicStatusPublisher(
    device_id: str,
    logger: MqttLogger,
    mqtt_broker: str,
    mqtt_port: int,
    publish_interval: float = 30.0,
    status_topic_pattern: str = "devices/{device_id}/status/current"
)
```

### Config

Configuration management with YAML support.

```python
from mqtt_application import config

# Get configuration values
mqtt_config = config.get_mqtt_config()
device_id = config.get("device.device_id", "default")
log_level = config.get_log_level()
```

## Command Line Usage

You can also run the library as a standalone application:

```bash
mqtt-application  # Uses config.yaml in current directory
```

## Development Setup

### Virtual Environment Setup

It's recommended to use a virtual environment for development:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # On Linux/macOS
# or
.venv\Scripts\activate     # On Windows

# Install development dependencies
pip install -e ".[dev]"
```

### Running Integration Tests

This project uses comprehensive integration tests that validate real-world functionality with actual MQTT brokers and network connections.

**Prerequisites**: Ensure your virtual environment is activated and development dependencies are installed:

```bash
# Activate virtual environment
source .venv/bin/activate  # On Linux/macOS
.venv\Scripts\activate     # On Windows

# Install development dependencies
pip install -e ".[dev]"
```

**Note**: If you encounter issues with `python` command not finding pytest, use the virtual environment directly:
```bash
# Direct virtual environment usage (Linux/macOS)
.venv/bin/python -m pytest

# Direct virtual environment usage (Windows)
.venv\Scripts\python -m pytest
```

### Running Tests

This project uses comprehensive integration tests that validate real-world functionality with actual MQTT brokers and network connections.

#### Prerequisites

Make sure your virtual environment is activated and development dependencies are installed:

```bash
# Activate virtual environment
source .venv/bin/activate  # On Linux/macOS
.venv\Scripts\activate     # On Windows

# Install development dependencies
pip install -e ".[dev]"
```

**Note**: If you encounter `No module named pytest` errors, make sure your virtual environment is activated:

```bash
# Activate virtual environment
source .venv/bin/activate  # On Linux/macOS
.venv\Scripts\activate     # On Windows

# Install development dependencies
pip install -e ".[dev]"
```

**Alternative**: Use the virtual environment directly without activation:
```bash
# Direct virtual environment usage (Linux/macOS)
.venv/bin/python -m pytest

# Direct virtual environment usage (Windows)
.venv\Scripts\python -m pytest
```

#### Basic Test Commands

```bash
# Run all tests (integration and unit tests)
python -m pytest

# Run only integration tests
python -m pytest -m integration

# Run only unit tests (non-integration)
python -m pytest -m "not integration"

# Run with verbose output
python -m pytest -v

# Run specific test file
python -m pytest tests/test_integration.py

# Run specific test class
python -m pytest tests/test_integration.py::TestMqttIntegration

# Run specific test method
python -m pytest tests/test_integration.py::TestMqttIntegration::test_mqtt_logger_connection

# Run tests matching a pattern
python -m pytest -k "mqtt_logger"
```

#### Advanced Testing Options

```bash
# Skip slow tests during development
python -m pytest -m "integration and not slow"

# Run tests with coverage reporting (requires pytest-cov)
python -m pytest --cov=src/mqtt_application --cov-report=html --cov-report=term

# Generate XML coverage report for CI/CD
python -m pytest --cov=src/mqtt_application --cov-report=xml

# Run tests in parallel (requires pytest-xdist)
python -m pytest -n auto

# Stop on first failure (useful during development)
python -m pytest -x

# Run last failed tests only
python -m pytest --lf

# Show local variables in tracebacks for debugging
python -m pytest -l

# Run in quiet mode (less verbose output)
python -m pytest -q

# Show test durations (identify slow tests)
python -m pytest --durations=10
```

#### Common Development Workflows

```bash
# Quick feedback during development (unit tests only)
python -m pytest -m "not integration" -x

# Fast integration tests only (skip slow network tests)
python -m pytest -m "integration and not slow"

# Full test suite before committing
python -m pytest -v

# Debug a specific failing test with maximum verbosity
python -m pytest tests/test_integration.py::TestMqttIntegration::test_mqtt_logger_connection -vvv -s

# Test specific functionality you're working on
python -m pytest -k "command_handler" -v

# Continuous testing during development (requires pytest-watch)
ptw -- -m "not integration"
```

#### Test Organization

This project uses pytest markers to categorize tests:

- `@pytest.mark.integration`: Tests requiring network access and real MQTT connections
- `@pytest.mark.slow`: Tests that take longer to run (network resilience, retry mechanisms)

View all available markers:
```bash
python -m pytest --markers
```

#### CI/CD Integration

```bash
# Full test suite with coverage for CI
python -m pytest -v --cov=src/mqtt_application --cov-report=xml --cov-report=term

# Integration tests only for production validation
python -m pytest -v -m integration

# Quick validation (unit tests + fast integration tests)
python -m pytest -m "not slow" -v
```

**Note**: Integration tests use real MQTT connections to `test.mosquitto.org` and test actual component interactions. This provides more reliable validation than mock-based unit tests, but requires network access.

#### Troubleshooting

**Virtual Environment Issues:**
```bash
# If 'python' command doesn't work, use the virtual environment directly
.venv/bin/python -m pytest        # Linux/macOS
.venv\Scripts\python -m pytest    # Windows

# Check you're using the right Python version (3.8+)
python --version
which python  # Should point to .venv/bin/python (Linux/macOS)
```

**Common Issues and Solutions:**

1. **SyntaxError with pytest**: Ensure you're using Python 3.8+ from your virtual environment, not system Python 2.7
2. **ModuleNotFoundError**: Install development dependencies with `pip install -e ".[dev]"`
3. **Network timeouts**: Integration tests require internet access to `test.mosquitto.org`. Use `-m "not integration"` to skip them
4. **Permission denied**: Use the full path to the virtual environment's Python executable
5. **Tests hang**: Some integration tests make real network connections. Use `Ctrl+C` to interrupt and check your network connection

**Getting Help:**
```bash
# Show pytest help
python -m pytest --help

# Show available fixtures
python -m pytest --fixtures

# Show available markers
python -m pytest --markers

# Collect tests without running them
python -m pytest --collect-only
```
```bash
python -m pytest --markers | grep @pytest.mark
```

The integration test suite covers:
- Real MQTT broker connections and message publishing/subscribing
- End-to-end command processing workflows
- Status publishing and periodic operations
- Network resilience and error handling
- Malformed message handling
- Connection retry mechanisms

### Code Formatting

```bash
black .
ruff check .
```

## Architecture

The library is designed with a modular architecture:

- **AsyncMqttClient**: Core MQTT connectivity and message routing
- **AsyncCommandHandler**: Command processing with built-in acknowledgment system
- **PeriodicStatusPublisher**: Regular status reporting functionality
- **Workers**: Concurrent message processing system
- **Config**: Centralized configuration management

## Dependencies

- **External modules** (must be installed separately):
  - `mqtt-logger`: MQTT-enabled logging
  - `muxu-io-mqtt-connector`: Low-level MQTT operations
- **Standard dependencies**:
  - `aiomqtt`: Async MQTT client
  - `pyyaml`: YAML configuration parsing

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Set up development environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Linux/macOS
   pip install -e ".[dev]"
   ```
4. Make your changes
5. Add tests for new functionality
6. Run the test suite:
   ```bash
   # Run all tests
   python -m pytest

   # Or run quick tests during development
   python -m pytest -m "not integration" -x
   ```
7. Submit a pull request

## Support

For issues and questions:
- GitHub Issues: [Project Issues](https://github.com/muxu-io/mqtt-application/issues)
- Email: alex@muxu.io
