"""Asynchronous MQTT client for message handling."""

from __future__ import annotations

import asyncio
from typing import Any

from mqtt_logger import MqttLogger

from .connection_manager import MqttConnectionManager


class AsyncMqttClient:
    """Asynchronous MQTT client to connect, subscribe, and put messages into a queue."""

    def __init__(
        self,
        topics: list[str],
        message_queue: asyncio.Queue,  # type: ignore[type-arg]
        logger: MqttLogger,
        connection_manager: MqttConnectionManager,
    ) -> None:
        """Initialize the AsyncMqttClient.

        Args:
            topics (list[str]): A list of topics to subscribe to.
            message_queue (asyncio.Queue): The queue to put received messages into.
            logger (MqttLogger): The logger instance to use for logging.
            connection_manager (MqttConnectionManager): Shared connection manager.

        """
        self.topics = topics
        self.message_queue = message_queue
        self.logger = logger
        self.connection_manager = connection_manager
        self._owns_connection = False

    def _message_callback(self, topic: str, payload: str, properties: dict[str, Any] | None) -> None:
        """Handle incoming MQTT messages.

        Args:
            topic: The MQTT topic the message was received on
            payload: The message payload as a string
            properties: Message properties (unused in this implementation)
        """
        try:
            self.logger.info(f"Received message on topic '{topic}': {payload}")
            # Use thread-safe method to put message in queue
            # This callback might be called from a different thread than the event loop
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self.message_queue.put((topic, payload))))
            except RuntimeError:
                # No event loop running, use sync put_nowait
                try:
                    self.message_queue.put_nowait((topic, payload))
                except asyncio.QueueFull:
                    self.logger.warning(f"Message queue full, dropping message from topic '{topic}'")
        except Exception as e:
            self.logger.error(f"Error processing message from topic '{topic}': {str(e)}")

    async def connect_and_subscribe(self) -> None:
        """Connect to the MQTT broker and subscribe to the specified topics.

        It then continuously listens for messages and puts them into the queue.
        """
        self.logger.info("Starting MQTT client and connecting to broker...")
        try:
            # Connect to the MQTT broker
            connected = await self.connection_manager.connect()
            if not connected:
                self.logger.error("Failed to connect to MQTT broker")
                return

            # Subscribe to all specified topics with our message callback
            for topic in self.topics:
                success = await self.connection_manager.subscribe(topic, self._message_callback)
                if success:
                    self.logger.info(f"Subscribed to topic: {topic}")
                else:
                    self.logger.warning(f"Failed to subscribe to topic: {topic}")

            # Keep the client running indefinitely
            while True:
                await asyncio.sleep(1)  # Sleep to prevent busy waiting

        except asyncio.CancelledError:
            self.logger.info("MQTT client task cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"An unexpected error occurred in MQTT client: {str(e)}")
        finally:
            # Only disconnect if we own the connection
            if self._owns_connection:
                await self.connection_manager.disconnect()

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._owns_connection:
            await self.connection_manager.disconnect()
