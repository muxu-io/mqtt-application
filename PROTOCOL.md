# MQTT Application Protocol Specification

This document describes the MQTT communication protocol used by the MQTT Application framework, including topic structure, message formats, and configuration patterns.

## Overview

The MQTT Application implements a structured protocol for device communication using a two-phase command-response system with configurable payload validation. The protocol supports:

- **Command processing** with acknowledgment and completion phases
- **Periodic status publishing** with customizable payload structures
- **Automatic payload validation** based on YAML configuration
- **Error handling** with structured error codes and messages
- **Flexible topic patterns** supporting multiple device instances

## Topic Structure

### Namespace Pattern

All topics follow a consistent namespace pattern:
```
{namespace}/{device_id}/{message_type}/{sub_type}
```

**Components:**
- `namespace`: Global namespace (default: "icsia")
- `device_id`: Unique device identifier
- `message_type`: Type of message (cmd, status, logs)
- `sub_type`: Message subtype (varies by message_type)

### Topic Categories

#### 1. Command Topics
**Pattern:** `{namespace}/{device_id}/cmd/{command_name}`

Commands are sent TO devices using topic-based command identification:
```
icsia/motor_controller_01/cmd/move
icsia/camera_01/cmd/capture
icsia/sensor_01/cmd/calibrate
```

#### 2. Status Topics
**Acknowledgment:** `{namespace}/{device_id}/status/ack`
**Completion:** `{namespace}/{device_id}/status/completion`
**Current Status:** `{namespace}/{device_id}/status/current`

Status messages are sent FROM devices:
```
icsia/motor_controller_01/status/ack
icsia/motor_controller_01/status/completion
icsia/motor_controller_01/status/current
```

#### 3. Log Topics
**Pattern:** `{namespace}/{device_id}/logs`

Application logs can be published to MQTT:
```
icsia/motor_controller_01/logs
```

## Message Types

### 1. Command Messages

Commands are sent to devices and follow a two-phase response system.

#### Command Request
**Topic:** `{namespace}/{device_id}/cmd/{command_name}`
**QoS:** 1 (at least once delivery)

**Payload Structure:**
```json
{
  "cmd_id": "unique_command_id",
  "timestamp": "2025-08-10T14:30:15.123Z",
  // Command-specific fields based on configuration
}
```

**Example - Motor Move Command:**
```json
{
  "cmd_id": "move_001",
  "target_position": {
    "x": 10.5,
    "y": 20.0,
    "z": -5.2
  },
  "speed": 150,
  "mode": "absolute"
}
```

#### Phase 1: Acknowledgment Response
**Topic:** `{namespace}/{device_id}/status/ack`
**QoS:** 1

**Success Payload:**
```json
{
  "cmd_id": "move_001",
  "status": "received",
  "timestamp": "2025-08-10T14:30:16.123Z",
  "command_timestamp": "2025-08-10T14:30:15.123Z"
}
```

**Error Payload:**
```json
{
  "cmd_id": "move_001",
  "status": "error",
  "timestamp": "2025-08-10T14:30:16.123Z",
  "command_timestamp": "2025-08-10T14:30:15.123Z",
  "error_code": "INVALID_PAYLOAD",
  "error_msg": "Missing required field 'target_position'"
}
```

#### Phase 2: Completion Response
**Topic:** `{namespace}/{device_id}/status/completion`
**QoS:** 1

**Success Payload:**
```json
{
  "cmd_id": "move_001",
  "status": "completed",
  "timestamp": "2025-08-10T14:30:25.123Z",
  "command_timestamp": "2025-08-10T14:30:15.123Z"
}
```

**Error Payload:**
```json
{
  "cmd_id": "move_001",
  "status": "error",
  "timestamp": "2025-08-10T14:30:18.123Z",
  "command_timestamp": "2025-08-10T14:30:15.123Z",
  "error_code": "EXECUTION_ERROR",
  "error_msg": "Motor position out of bounds"
}
```

### 2. Status Messages

#### Periodic Status Publishing
**Topic:** `{namespace}/{device_id}/status/current`
**QoS:** 0 (fire and forget)
**Frequency:** Configurable (default: 30 seconds)

**Payload Structure:**
```json
{
  "operational_status": "idle|busy|error",
  "timestamp": "2025-08-10T14:30:15.123Z",
  "last_command_time": "2025-08-10T14:25:30.123Z",
  // Custom fields defined in configuration
}
```

**Example - Motor Controller Status:**
```json
{
  "operational_status": "idle",
  "timestamp": "2025-08-10T14:30:15.123Z",
  "last_command_time": "2025-08-10T14:25:30.123Z",
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

## Configuration

### Basic Configuration Structure

```yaml
# Device and namespace configuration
device:
  device_id: "motor_controller_01"
  status_publish_interval: 30.0

namespace: "icsia"

# MQTT broker settings
mqtt:
  broker: "test.mosquitto.org"
  port: 1883
  reconnect_interval: 5
  max_reconnect_attempts: -1
  throttle_interval: 0.1

# Topic patterns (auto-generated from namespace and device_id)
topics:
  command: "{namespace}/+/cmd/#"
  status:
    ack: "{namespace}/{device_id}/status/ack"
    completion: "{namespace}/{device_id}/status/completion"
    current: "{namespace}/{device_id}/status/current"
  log: "{namespace}/{device_id}/logs"
```

### Command Payload Validation

Define validation schemas for command payloads to ensure data integrity and API compliance.

#### Validation Rules

- **Required Fields:** Simple values (string, number, boolean) or nested objects
- **Optional Fields:** Use `{"default": value}` syntax
- **Standard Fields:** 
  - `cmd_id`: REQUIRED (must be provided by client)
  - `timestamp`: AUTOMATIC (generated by framework)
  - `command`: OPTIONAL (extracted from topic or payload)

#### Configuration Examples

```yaml
commands:
  payload:
    # Move command - all fields required except those with defaults
    move:
      target_position:    # REQUIRED nested structure
        x: 0.0
        y: 0.0
        z: 0.0
      speed: 100          # REQUIRED with default value
      mode: "absolute"    # REQUIRED with default value

    # Home command - optional field with explicit default
    home:
      axis: "all"         # REQUIRED with default value

    # Get position - no additional validation
    get_position: {}

    # Enable command - simple required field
    enable:
      enabled: true       # REQUIRED boolean field

    # Complex mixed validation
    process:
      input_file: "input.txt"    # REQUIRED
      parameters:                # REQUIRED nested object
        mode: "auto"             # REQUIRED within parameters
        priority: 1              # REQUIRED within parameters
      timeout:                   # OPTIONAL with default
        default: 30
      debug_mode:                # OPTIONAL with default
        default: false
```

### Status Payload Configuration

Define the structure of status messages published by devices.

#### Validation Rules

- **Simple defaults:** Always included in status messages
- **Explicit defaults:** Use `{"default": value}` for optional fields
- **System fields:** `operational_status`, `timestamp`, `last_command_time` are automatically managed
- **Custom fields:** Domain-specific data (sensors, motors, etc.)

#### Configuration Examples

```yaml
status:
  payload:
    # Motor control fields
    current_position:
      x: 0.0
      y: 0.0
      z: 0.0
    speed: 100
    moving: false
    homed: false

    # System monitoring with explicit defaults
    temperature:
      default: 25.0
    voltage:
      default: 12.0
    error_count:
      default: 0
    uptime_seconds:
      default: 0

    # Connection status
    connection_quality: "good"
```

## Error Codes

### Standard Error Codes

| Code | Description | Phase | Usage |
|------|-------------|-------|-------|
| `INVALID_JSON` | Malformed JSON payload | Acknowledgment | JSON parsing failed |
| `INVALID_PAYLOAD` | Missing required fields | Acknowledgment | cmd_id or command missing |
| `UNKNOWN_COMMAND` | Command not recognized | Completion | Command not in handler registry |
| `VALIDATION_ERROR` | Payload validation failed | Completion | Schema validation failed |
| `EXECUTION_ERROR` | Command execution failed | Completion | Runtime error during execution |
| `INTERNAL_ERROR` | Unexpected system error | Both | System-level errors |

### Custom Error Codes

Applications can define domain-specific error codes:

```python
# In command handlers
if motor_position_invalid:
    raise CommandValidationError("POSITION_OUT_OF_BOUNDS: Target position exceeds limits")

if sensor_not_ready:
    raise Exception("SENSOR_ERROR: Temperature sensor not responding")
```

## Protocol Flow Examples

### Successful Command Flow

```
1. Client to Device:  icsia/motor_01/cmd/move
   {"cmd_id": "move_001", "target_position": {"x": 10, "y": 5, "z": 0}}

2. Device to Client:  icsia/motor_01/status/ack
   {"cmd_id": "move_001", "status": "received", "timestamp": "..."}

3. [Device executes command]

4. Device to Client:  icsia/motor_01/status/completion
   {"cmd_id": "move_001", "status": "completed", "timestamp": "..."}

5. Device to All:     icsia/motor_01/status/current
   {"operational_status": "idle", "current_position": {"x": 10, "y": 5, "z": 0}, ...}
```

### Error Command Flow

```
1. Client to Device:  icsia/motor_01/cmd/move
   {"cmd_id": "move_002", "invalid_field": "bad_data"}

2. Device to Client:  icsia/motor_01/status/ack
   {"cmd_id": "move_002", "status": "received", "timestamp": "..."}

3. [Device validates payload and fails]

4. Device to Client:  icsia/motor_01/status/completion
   {
     "cmd_id": "move_002", 
     "status": "error", 
     "error_code": "VALIDATION_ERROR",
     "error_msg": "Missing required field 'target_position'",
     "timestamp": "..."
   }

5. Device to All:     icsia/motor_01/status/current
   {"operational_status": "error", ...}
```

## Quality of Service (QoS)

### QoS Levels by Message Type

| Message Type | QoS | Reason |
|--------------|-----|--------|
| Commands | 1 | Ensure delivery of critical commands |
| Acknowledgments | 1 | Guarantee receipt confirmation |
| Completion Status | 1 | Ensure result delivery |
| Periodic Status | 0 | Allow message loss for performance |
| Logs | 0 | Non-critical, allow loss |

## Implementation Guidelines

### For Device Developers

When using the MQTT Application framework, the following are **automatically handled by the framework**:

1. **Topic Subscription:** Automatically subscribes to `{namespace}/+/cmd/#` (using `+` wildcard to receive commands for any device_id)
2. **Device ID Extraction:** Automatically parsed from incoming command topics
3. **Payload Validation:** Automatic validation based on `config.yaml` command schemas
4. **Response Timing:** Automatic acknowledgment and completion message sending
5. **Status Updates:** Automatic operational_status management and periodic publishing
6. **Error Handling:** Automatic structured error codes and descriptive messages

**Your responsibilities as a device developer:**
- Define command handlers as simple functions
- Update status payload with `app.update_status(values)`
- Configure validation schemas in `config.yaml`
- Implement your business logic in command functions

**Note:** The framework subscribes to `{namespace}/+/cmd/#` (where `+` is a wildcard for any device_id) and automatically extracts the target device_id from incoming command topics. This allows one application instance to handle commands for multiple logical devices if needed.

**Example:**
```python
from mqtt_application import MqttApplication

def move_motor(data):
    # Your motor control logic here
    target = data["target_position"]
    # ... move motor to target ...
    return {"result": "Motor moved successfully"}

async def main():
    async with MqttApplication() as app:
        app.register_command("move", move_motor)
        
        # Update status as system state changes
        app.update_status({
            "current_position": {"x": 10.5, "y": 20.0, "z": -5.2},
            "moving": False
        })
        
        await app.run()
```


## Examples

See the `examples/` directory for complete implementation examples:

- **Motor Control:** Motor control system with position tracking
- **Camera Control:** Camera control with settings management
- **Custom Status:** Custom status payload examples

## Security Considerations

- **Authentication:** Use MQTT broker authentication
- **Authorization:** Implement topic-level access controls
- **Encryption:** Use TLS for sensitive deployments
- **Validation:** Always validate incoming payloads
- **Rate Limiting:** Implement command rate limiting if needed


## Callback Subscription and Message Dispatch

The MQTT Application framework provides a flexible callback subscription mechanism for handling incoming messages on specific topics. This allows you to register Python functions that will be invoked automatically when messages matching certain topic patterns are received.


### How Callback Subscription Works

- **Registering a Callback:** Use `app.register_callback(topic_pattern, callback_fn)` to associate a function with a topic or topic pattern. Wildcards (`+`, `#`) are supported for flexible matching. Registering a callback automatically subscribes to the topic if not already subscribed.
- **Message Dispatch:** When a message arrives on a subscribed topic, the framework matches the topic against registered patterns and invokes the corresponding callback(s) with the message payload and metadata.

### Example: Registering and Subscribing to Status Topics

```python
def ack_callback(payload, topic):
    print(f"ACK received on {topic}: {payload}")

def completion_callback(payload, topic):
    print(f"Completion received on {topic}: {payload}")

async with MqttApplication() as app:
    # Register callbacks for status topics (auto-subscribes)
    app.register_callback("icsia/motor_controller_01/status/ack", ack_callback)
    app.register_callback("icsia/motor_controller_01/status/completion", completion_callback)

    await app.run()
```

### Notes

* **Wildcard Patterns:** You can use MQTT wildcards (`+`, `#`) in callback registration for broad topic matching.
* **Multiple Callbacks:** Multiple callbacks can be registered for overlapping topic patterns; all matching callbacks will be invoked.
* **Best Practice:** Just use `register_callback`—it will subscribe for you.

### Troubleshooting

- If your callback is not being invoked, verify that you registered the callback for the correct topic pattern.
- Use debug logging to trace message receipt and callback invocation.

---

## Monitoring and Debugging

**Status Messages:** Monitor operational_status for system health
**Error Codes:** Use structured error codes for troubleshooting
**Logs:** MQTT logging is enabled by default to `{namespace}/{device_id}/logs`
**Command Correlation:** Use cmd_id and timestamps for tracing
**Periodic Status:** Monitor last_command_time for activity
