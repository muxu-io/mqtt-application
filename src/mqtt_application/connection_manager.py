import asyncio
import os
import sys
from typing import Any, Callable, Dict, Optional

from mqtt_connector import MqttConnector
from mqtt_logger import MqttLogger


class MqttConnectionManager:
    """Manages a single MQTT connection shared across components."""

    def __init__(
        self,
        broker: str,
        port: int,
        logger: MqttLogger,
        client_id: Optional[str] = None,
        reconnect_interval: int = 5,
        max_reconnect_attempts: int = -1,
    ):
        """Initialize the connection manager.

        Args:
            broker: MQTT broker address
            port: MQTT broker port
            logger: Logger instance
            client_id: Optional client ID (auto-generated if None)
            reconnect_interval: Seconds between reconnection attempts
            max_reconnect_attempts: Maximum reconnection attempts (-1 for infinite)
        """
        self.logger = logger

        # Store reference to event loop for async callback scheduling
        try:
            import asyncio

            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        self._connector = MqttConnector(
            mqtt_broker=broker,
            mqtt_port=port,
            client_id=client_id or f"mqtt_manager_{id(self)}",
            reconnect_interval=reconnect_interval,
            max_reconnect_attempts=max_reconnect_attempts,
        )

        # Set up logging callback
        self._connector.set_log_callback(self._handle_connector_log)

        # Track message callbacks for different topics
        self._message_callbacks: Dict[str, Callable] = {}
        self._subscribed_topics = set()

    @property
    def is_connected(self) -> bool:
        """Check if the MQTT connection is active."""
        return hasattr(self._connector, "connected") and self._connector.connected

    def _handle_connector_log(self, level: str, message: str) -> None:
        """Handle log messages from the MQTT connector.

        This can be called from background threads, so we need to handle
        the case where there's no running event loop.
        """
        log_message = f"MqttConnectionManager: {message}"

        # Check if stdout logging is enabled (same mechanism as MqttLogger)
        enable_stdout = os.environ.get("MQTT_LOGGER_ENABLE_STDOUT", "false").lower() in ("true", "1", "yes", "on")

        try:
            # Check if we're in an async context first
            import asyncio

            asyncio.get_running_loop()

            # We have a running loop, try to use the logger
            if level == "DEBUG":
                self.logger.debug(log_message)
            elif level == "INFO":
                self.logger.info(log_message)
            elif level == "WARNING":
                self.logger.warning(log_message)
            elif level == "ERROR":
                self.logger.error(log_message)
            elif level == "CRITICAL":
                self.logger.critical(log_message)

        except RuntimeError:
            # No running event loop - only print if stdout is explicitly enabled
            # This avoids trying to call async methods from sync contexts
            if enable_stdout:
                import sys

                print(f"[{level}] {log_message}", file=sys.stderr)
        except Exception as e:
            # Any other error with the logger - only print if stdout is explicitly enabled
            if enable_stdout:
                import sys

                print(f"[{level}] {log_message} (logger error: {e})", file=sys.stderr)

    def _simple_message_callback(self, topic: str, payload: str) -> None:
        """Simple callback that converts to the more detailed format."""
        # Find matching callback(s) for this topic
        for topic_pattern, callback in self._message_callbacks.items():
            if self._topic_matches(topic, topic_pattern):
                try:
                    callback(topic, payload, None)
                except Exception as e:
                    self.logger.error(f"Error in message callback for topic {topic}: {e}")

    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """Check if a topic matches a pattern with MQTT wildcards.

        MQTT wildcards:
        - '+' matches a single level
        - '#' matches multiple levels (must be at the end)
        """
        # Split both topic and pattern into parts
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        # Handle the multi-level wildcard '#'
        if pattern_parts and pattern_parts[-1] == "#":
            pattern_prefix = pattern_parts[:-1]
            if len(topic_parts) >= len(pattern_prefix):
                for _i, (t_part, p_part) in enumerate(zip(topic_parts[: len(pattern_prefix)], pattern_prefix)):
                    if p_part != "+" and p_part != t_part:
                        return False
                return True
            return False

        # No multi-level wildcard, must match exactly (considering single-level wildcards)
        if len(topic_parts) != len(pattern_parts):
            return False

        for i, (t_part, p_part) in enumerate(zip(topic_parts, pattern_parts)):
            self.logger.debug(f"Comparing topic part '{t_part}' with pattern part '{p_part}' at position {i}")
            if p_part != "+" and p_part != t_part:
                return False

        return True

    async def connect(self) -> bool:
        """Connect to the MQTT broker."""
        # Check if stdout logging is enabled (same mechanism as MqttLogger)
        enable_stdout = os.environ.get("MQTT_LOGGER_ENABLE_STDOUT", "false").lower() in ("true", "1", "yes", "on")

        # Log connection attempt if stdout is enabled - this prints immediately before any network operations
        if enable_stdout:
            print(
                f"[INFO] MqttConnectionManager: Attempting to connect to "
                f"{self._connector.mqtt_broker}: {self._connector.mqtt_port}",
                file=sys.stderr,
            )
            sys.stderr.flush()  # Ensure immediate output

        connected = await self._connector.connect()
        if connected:
            # Set the global message callback
            self._connector.set_message_callback(self._global_message_callback)
            # Log successful connection using the MQTT logger (which respects enable_stdout)
            try:
                self.logger.info(
                    f"Successfully connected to MQTT broker {self._connector.mqtt_broker}: {self._connector.mqtt_port}"
                )
            except Exception:
                # Fallback if logger isn't available
                if enable_stdout:
                    print(
                        f"[INFO] MqttConnectionManager: Successfully connected to "
                        f"{self._connector.mqtt_broker}: {self._connector.mqtt_port}",
                        file=sys.stderr,
                    )
        return connected

    def _global_message_callback(self, topic: str, payload: str) -> None:
        """Global message callback that dispatches to registered topic callbacks.

        Args:
            topic: The MQTT topic the message was received on
            payload: The message payload as a string
        """
        # Find matching callback(s) for this topic
        for topic_pattern, callback in self._message_callbacks.items():
            match_result = self._topic_matches(topic, topic_pattern)
            if match_result:
                try:
                    # Check if callback is async and handle appropriately
                    import inspect

                    if inspect.iscoroutinefunction(callback):
                        # Schedule async callback to run in the event loop
                        import asyncio

                        if self._event_loop and self._event_loop.is_running():
                            asyncio.run_coroutine_threadsafe(callback(topic, payload, None), self._event_loop)
                        else:
                            # Try to find a running event loop
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(callback(topic, payload, None))
                            except RuntimeError:
                                self.logger.error(
                                    f"Cannot run async callback {callback.__name__} - no event loop available"
                                )
                    else:
                        callback(topic, payload, None)
                except Exception as e:
                    self.logger.error(f"Error in message callback for topic {topic}: {e}")

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        await self._connector.disconnect()
        self._subscribed_topics.clear()
        self._message_callbacks.clear()

    async def subscribe(self, topic: str, callback: Callable[[str, str, Optional[Dict[str, Any]]], None]) -> bool:
        """Subscribe to a topic with a callback.

        Args:
            topic: Topic pattern to subscribe to
            callback: Function to call when messages arrive (topic, payload_str, properties)

        Returns:
            True if subscription successful, False otherwise
        """
        # Store the callback for this topic
        self._message_callbacks[topic] = callback

        # Always ensure the connector's message callback is set to the global dispatcher
        self._connector.set_message_callback(self._global_message_callback)

        # Only subscribe if we haven't already
        if topic not in self._subscribed_topics:
            success = await self._connector.subscribe(topic)
            if success:
                self._subscribed_topics.add(topic)
                self.logger.info(f"Subscribed to topic: {topic}")
                return True
            else:
                self.logger.warning(f"Failed to subscribe to topic: {topic}")
                # Remove the callback since subscription failed
                del self._message_callbacks[topic]
                return False
        else:
            self.logger.info(f"Already subscribed to topic: {topic}")
            return True

    def get_registered_callbacks(self) -> Dict[str, Callable]:
        """Return a copy of the registered topic callbacks."""
        return dict(self._message_callbacks)

    async def unsubscribe(self, topic: str) -> bool:
        """Unsubscribe from a topic and remove its callback.

        Note: The underlying MqttConnector may not support unsubscription,
        so we just remove the callback and tracking.
        """
        if topic in self._message_callbacks:
            del self._message_callbacks[topic]

        if topic in self._subscribed_topics:
            # Try to unsubscribe if the method exists
            if hasattr(self._connector, "unsubscribe"):
                try:
                    success = await self._connector.unsubscribe(topic)
                    if success:
                        self._subscribed_topics.remove(topic)
                        self.logger.info(f"Unsubscribed from topic: {topic}")
                    return success
                except Exception as e:
                    self.logger.warning(f"Failed to unsubscribe from {topic}: {e}")
            else:
                # Just remove from tracking if unsubscribe not supported
                self._subscribed_topics.remove(topic)
                self.logger.info(f"Removed topic from tracking: {topic}")
                return True
        return True

    async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        """Publish a message to a topic.

        Args:
            topic: Topic to publish to
            payload: Message payload (will be JSON-encoded if not a string)
            qos: Quality of Service level
            retain: Whether to retain the message

        Returns:
            True if publish successful, False otherwise
        """
        return await self._connector.publish(topic, payload, qos, retain)

    async def publish_with_retry(
        self,
        topic: str,
        payload: Any,
        qos: int = 1,
        retain: bool = False,
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> bool:
        """Publish a message with connection check and retry logic.

        Args:
            topic: Topic to publish to
            payload: Message payload
            qos: Quality of Service level
            retain: Whether to retain the message
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff

        Returns:
            True if publish successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                # Ensure connection is established
                if not self.is_connected:
                    connected = await self.connect()
                    if not connected:
                        self.logger.warning(f"MQTT not connected (attempt {attempt + 1}/{max_retries})")
                        raise RuntimeError("MQTT not connected")

                # Try to publish
                result = await self.publish(topic, payload, qos, retain)
                if result:
                    # Log command publishing more prominently
                    if "/cmd/" in topic:
                        self.logger.info(f"📤 Command published to {topic}")
                        self.logger.debug(f"Command payload: {payload}")
                    else:
                        self.logger.debug(f"Published to {topic} (attempt {attempt + 1})")
                    return True
                else:
                    self.logger.warning(f"Publish failed for {topic} (attempt {attempt + 1})")
            except Exception as e:
                self.logger.warning(f"Publish error for {topic} (attempt {attempt + 1}): {e}")

            # Exponential backoff (except on final attempt)
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                self.logger.debug(f"Retrying in {delay: .1f} seconds...")
                await asyncio.sleep(delay)

        self.logger.error(f"Failed to publish to {topic} after {max_retries} attempts")
        return False

    def register_callback(
        self,
        topic_pattern: str,
        callback: Callable[[str, str, Optional[Dict[str, Any]]], None],
    ) -> None:
        """
        Register a callback for a topic pattern and automatically subscribe to the topic if not already subscribed.

        Args:
            topic_pattern: MQTT topic pattern (wildcards supported)
            callback: Function to call when messages arrive (topic, payload_str, properties)
        """
        self._message_callbacks[topic_pattern] = callback
        self._connector.set_message_callback(self._global_message_callback)

        # Subscribe if not already subscribed - use simpler approach
        if topic_pattern not in self._subscribed_topics:
            # Schedule the subscription for the next event loop iteration
            # This avoids blocking the current call and prevents deadlocks
            try:
                loop = asyncio.get_running_loop()
                # Use call_soon to schedule the subscription without blocking
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self._auto_subscribe_safe(topic_pattern)))
            except RuntimeError:
                # No event loop running - subscription will need to happen manually
                self.logger.warning(
                    f"No running event loop to auto-subscribe to topic: {topic_pattern}. "
                    f"Use subscribe() method manually."
                )

            self._subscribed_topics.add(topic_pattern)
            self.logger.info(f"Scheduled auto-subscription to topic: {topic_pattern} when registering callback.")

    async def _auto_subscribe_safe(self, topic_pattern: str) -> None:
        """Safely handle auto-subscription in async context."""
        try:
            if hasattr(self._connector, "subscribe"):
                success = await self._connector.subscribe(topic_pattern)
                if success:
                    self.logger.debug(f"Auto-subscription successful for topic: {topic_pattern}")
                else:
                    self.logger.warning(f"Auto-subscription failed for topic: {topic_pattern}")
            else:
                self.logger.warning(f"Connector does not support subscription for topic: {topic_pattern}")
        except Exception as e:
            self.logger.error(f"Error during auto-subscription to {topic_pattern}: {e}")
