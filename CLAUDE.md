# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

ICSIA is a collection of three Python packages for building MQTT-based IoT applications:

- **mqtt-application/**: Core application framework with async MQTT client, command handling, and status publishing
- **mqtt-connector/**: Low-level MQTT connection management with reconnection handling
- **mqtt-logger/**: MQTT-enabled logging with systemd journal integration
- **api-specs/**: MQTT API specifications for various IoT systems (camera, motor, LED control)
- **dummy-icsia/**: Demo applications (camera-control, computer-vision, motion-control, orchestrator, log-printer)

## Development Commands

### Environment Setup
```bash
# For mqtt-application (main package)
cd mqtt-application
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows
pip install -e ".[dev]"

# Full project setup (install all packages in correct order)
cd /path/to/icsia
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./mqtt-connector
pip install -e ./mqtt-logger  
pip install -e ./mqtt-application
```

### Testing
The project uses integration-first testing with real MQTT brokers:

```bash
# Run all tests (from mqtt-application directory)
cd mqtt-application
python -m pytest

# Run only integration tests
python -m pytest -m integration

# Run without slow network tests
python -m pytest -m "integration and not slow"

# Run specific test patterns
python -m pytest -k "mqtt_logger"

# Run specific test files
python -m pytest tests/test_main.py -v
python -m pytest tests/test_command_handler.py -v

# With coverage
python -m pytest --cov=src/mqtt_application --cov-report=html

# Quick development testing (skip integration)
python -m pytest -m "not integration" -x
```

**Note**: Tests require internet access to `test.mosquitto.org` for real MQTT broker integration.

### Code Quality
```bash
# Format code (from mqtt-application directory)
cd mqtt-application
black .

# Lint code
ruff check .

# Type checking
mypy src/
```

### Build and Install
```bash
# Install in development mode (from mqtt-application directory)
cd mqtt-application
pip install -e .

# Build package
python -m build
```

### Docker Development
```bash
# Run full system with MQTT broker and all services
docker-compose up

# Run specific services
docker-compose up broker camera-control

# Build and restart services
docker-compose up --build

# View logs
docker-compose logs -f camera-control
```

## Architecture

### Core Components
- **MqttApplication**: Main application class handling lifecycle and component orchestration
- **AsyncMqttClient**: Handles MQTT connections, subscriptions, and message routing
- **AsyncCommandHandler**: Processes commands with two-phase acknowledgment/completion system
- **PeriodicStatusPublisher**: Publishes device status at regular intervals
- **MqttConnectionManager**: Manages connections with automatic reconnection
- **Worker Pool**: Concurrent message processing system

### Protocol Structure
- **Command Topics**: `{namespace}/{device_id}/cmd/{command_name}`
- **Status Topics**: `{namespace}/{device_id}/status/{ack|completion|current}`
- **Log Topics**: `{namespace}/{device_id}/logs`

### Configuration
All components are configured via `config.yaml` with YAML-based payload validation for commands and status messages. The framework automatically handles topic subscription (`{namespace}/+/cmd/#`), device ID extraction, and response routing.

### Dependencies
- mqtt-logger and mqtt-connector are local file dependencies installed from relative paths
- External dependencies: paho-mqtt, asyncio-mqtt, pyyaml, systemd-python

## Common Tasks

### Running Examples
```bash
# Run mqtt-application examples
cd mqtt-application/examples
python motor_control_example.py

# Run demo applications
cd dummy-icsia/camera-control
python camera-control.py

# Run with debug logging
MQTT_LOGGER_ENABLE_STDOUT=true python camera-control.py

# Run with timeout (useful for testing)
MQTT_LOGGER_ENABLE_STDOUT=true timeout 5s python camera-control.py
```

### Running Application
```bash
# Simple run (uses config.yaml in current directory)
python -c "from mqtt_application import MqttApplication; MqttApplication.run_from_config()"

# Or with custom config
python -c "from mqtt_application import MqttApplication; import asyncio; asyncio.run(MqttApplication('custom.yaml').run())"
```

### Working with Individual Packages
Each package (mqtt-application, mqtt-connector, mqtt-logger) is independent:
- mqtt-logger: Poetry-based (`pyproject.toml` with poetry backend)
- mqtt-connector: setuptools-based 
- mqtt-application: setuptools-based with extensive dev dependencies

### Demo Applications Architecture
The `dummy-icsia/` directory contains a complete IoT system demonstration:
- **Services**: camera-control, computer-vision, motion-control, orchestrator, log-printer
- **Communication**: All services communicate via MQTT using the ICSIA protocol
- **Orchestration**: orchestrator.py coordinates operations across all services
- **Logging**: Centralized logging system collects logs from all services
- **Configuration**: Each service has its own `config.yaml` with device-specific settings

## Testing Strategy

This project uses **integration-first testing** with real MQTT brokers rather than mocks. Tests validate actual network behavior and MQTT protocol compliance. This requires network access but provides higher confidence in production behavior.