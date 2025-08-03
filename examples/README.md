# MQTT Application Examples

This directory contains example applications demonstrating how to use the MQTT application framework with custom payload validation for different device types.

## Motor Control Example

The `motor_control_example.py` demonstrates how to implement a motor control application that uses custom status and command payload validation.

### Key Features

- **Custom Status Payload**: Status fields defined in `config.yaml`
- **Command Payload Validation**: Automatic validation of incoming command payloads
- **Real-time Updates**: Status payload updated automatically as system state changes
- **Device-Specific Commands**: Implements move, home, stop, and set_speed commands for motor control
- **System Monitoring**: Includes temperature, voltage, and error tracking
- **Background Status Updates**: Periodic status broadcasting

### Configuration Examples

The framework uses topic-based command identification where:
- Command type is extracted from the topic path: `icsia/<device_id>/cmd/<command_name>`
- Payload contains only `cmd_id` and command-specific data (no `command` field)

#### Motor Control Configuration
```yaml
# Status payload for motor control devices
status:
  payload:
    current_position:
      x: 0.0
      y: 0.0
      z: 0.0
    speed: 100
    moving: false
    homed: false
    temperature:
      default: 25.0
    voltage:
      default: 12.0

# Command validation for motor control
commands:
  move:
    target_position:        # Required nested object
      x: 0.0               # Required coordinate
      y: 0.0               # Required coordinate
      z: 0.0               # Required coordinate
    speed:                 # Optional with default
      default: 100
    mode: "absolute"       # Required mode setting

  home:
    axis:                  # Optional with default
      default: "all"

  set_speed:
    speed: 100             # Required speed value
    units:                 # Optional with default
      default: "mm/s"

  get_position: {}         # No additional fields required
```

### Running the Example

1. Make sure you have a local MQTT broker running (or update the broker in config):
   ```bash
   # Using mosquitto
   mosquitto -v
   ```

2. Run the motor control application:
   ```bash
   python examples/motor_control_example.py
   ```

3. Send commands via MQTT using topic-based command identification:

   #### Motor Control Commands (New Syntax)
   ```bash
   # Move command - command type in topic path, no "command" field in payload
   mosquitto_pub -t "icsia/motor_controller_01/cmd/move" -m '{
     "cmd_id": "move_001",
     "target_position": {"x": 10.5, "y": 20.0, "z": -5.2},
     "mode": "absolute"
   }'

   # Home command - only cmd_id required, axis has default
   mosquitto_pub -t "icsia/motor_controller_01/cmd/home" -m '{
     "cmd_id": "home_001"
   }'

   # Set speed command
   mosquitto_pub -t "icsia/motor_controller_01/cmd/set_speed" -m '{
     "cmd_id": "speed_001",
     "speed": 200
   }'

   # Get position command
   mosquitto_pub -t "icsia/motor_controller_01/cmd/get_position" -m '{
     "cmd_id": "pos_001"
   }'

   # Enable/disable command
   mosquitto_pub -t "icsia/motor_controller_01/cmd/enable" -m '{
     "cmd_id": "enable_001",
     "enabled": true
   }'
   ```
   ```

4. Monitor status updates:
   ```bash
   mosquitto_sub -t "icsia/motor_controller_01/status/current"
   ```

### Expected Status Output

The application will publish status messages like:

```json
{
  "operational_status": "idle",
  "timestamp": "2025-08-09T14:30:15.123Z",
  "current_position": {
    "x": 10.5,
    "y": 20.0,
    "z": -5.2
  },
  "speed": 150,
  "moving": false,
  "homed": true,
  "temperature": 25.3,
  "voltage": 12.15,
  "error_count": 0,
  "uptime_seconds": 1205
}
```

## Custom Status Payload Usage

### 1. Define Status Fields in Configuration

Add a `status.payload` section to your `config.yaml`:

```yaml
status:
  payload:
    # Your custom fields here
    sensor_value: 0.0
    system_mode: "idle"
    custom_data:
      field1: "value1"
      field2: 42
    error_count:
      default: 0  # Use 'default' for optional fields
```

### 2. Update Status in Your Application

```python
from src.mqtt_application import MqttApplication

class MyApp:
    def __init__(self):
        self.app = MqttApplication(config_file="my_config.yaml")

    def update_system_status(self):
        # Read current sensor values, system state, etc.
        current_values = {
            "sensor_value": self.read_sensor(),
            "system_mode": self.get_mode(),
            "custom_data": {
                "field1": "updated_value",
                "field2": self.calculate_value()
            },
            "error_count": self.error_counter
        }

        # Update status payload in one operation
        self.app.update_status(current_values)
```

### 3. Status Field Types

- **Simple values**: Numbers, strings, booleans
- **Objects**: Nested dictionaries for complex data
- **Default values**: Use `{"default": value}` for optional fields
- **Reserved fields**: `operational_status`, `timestamp`, `last_command_time` are automatically managed

### 4. Best Practices

1. **Update frequency**: Call `update_status()` when system state changes
2. **Field consistency**: Keep field names consistent with your API specification
3. **Error handling**: Update error counters when exceptions occur
4. **Performance**: Batch multiple field updates into a single `update_status()` call
5. **Configuration**: Define sensible defaults in config for all fields

## Command Payload Validation

### 1. Define Command Schemas in Configuration

Add a `commands.payload` section to your `config.yaml`:

```yaml
commands:
  payload:
    # All defined fields are REQUIRED unless explicitly marked as optional
    my_command:
      required_field: "default_value"    # REQUIRED - must be provided
      numeric_field: 42                  # REQUIRED - must be provided
      optional_field:                    # OPTIONAL - has explicit default
        default: "optional_default"
      nested_data:                       # REQUIRED - entire nested object
        x: 0.0                          # REQUIRED - must be in nested_data
        y: 0.0                          # REQUIRED - must be in nested_data
        z: 0.0                          # REQUIRED - must be in nested_data
```

**Key Validation Rules:**
- **Simple values** (`"string"`, `42`, `true`) = **REQUIRED** fields
- **Nested objects** (`{x: 0.0, y: 0.0}`) = **REQUIRED** entire structure
- **Explicit defaults** (`{default: "value"}`) = **OPTIONAL** fields
- **Fields not defined** = **IGNORED** (no validation)

### 2. Automatic Validation in Command Handlers

Command handlers receive validated payloads with defaults applied:

```python
async def my_command_handler(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle command with automatic payload validation.

    The data parameter is guaranteed to:
    - Have all required fields present
    - Have correct data types
    - Include default values for optional fields
    """
    # Access required fields safely - validation already done
    required_value = data["required_field"]  # Guaranteed to exist and be string
    numeric_value = data["numeric_field"]    # Guaranteed to exist and be int

    # Access optional fields (defaults applied if not provided)
    optional_value = data["optional_field"]  # Has default if not provided

    # Access nested structures safely
    position = data["nested_data"]  # Guaranteed to have x, y, z fields
    x = position["x"]  # Guaranteed to be float

    # Your business logic here
    return {"status": "completed"}
```

### 3. Validation Features

- **Type checking**: Validates field types match configuration
- **Required fields**: Ensures all defined fields are present (unless explicitly optional)
- **Default values**: Automatically applies defaults for optional fields only
- **Nested validation**: Supports complex nested dictionary structures
- **Error messages**: Provides clear error messages for validation failures

### 4. Configuration Examples

#### Device Control API
```yaml
commands:
  payload:
    configure:
      mode: "auto"         # REQUIRED - must be provided
      speed: 100           # REQUIRED - must be provided
      threshold: 50.0      # REQUIRED - must be provided

    enable:
      enabled: true        # REQUIRED - must be provided
```

#### Mixed Required/Optional Fields
```yaml
commands:
  payload:
    setup:
      setting_name: "default"  # REQUIRED - must be provided
      timeout:             # OPTIONAL - has explicit default
        default: 30
      retries:             # OPTIONAL - has explicit default
        default: 3
      debug: false         # REQUIRED - must be provided
```

#### Status Payload Configuration
```yaml
status:
  payload:
    # Simple defaults (always included in status)
    temperature: 25.0
    connection_status: "connected"

    # Explicit defaults (included only if not set elsewhere)
    error_count:
      default: 0
    uptime_seconds:
      default: 0
```

### 6. Command Validation Benefits

1. **Safety**: Commands receive clean, validated data
2. **Consistency**: Enforces API compliance through configuration
3. **Error handling**: Automatic validation error responses
4. **Documentation**: Configuration serves as API documentation
5. **Maintenance**: Centralized validation rules in configuration

## Testing

The examples follow the integration-first testing strategy. To test:

1. Start a local MQTT broker
2. Run the example application
3. Use MQTT client tools to send commands and monitor status
4. Verify the status payload matches your configuration structure

This approach tests real MQTT communication without mocking, providing confidence that the application works correctly with actual MQTT brokers.
