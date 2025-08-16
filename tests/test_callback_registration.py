"""Tests for the callback registration feature in MqttConnectionManager."""

import asyncio
from typing import Any, Optional

import pytest


class TestCallbackRegistration:
    """Test callback registration functionality."""

    @pytest.mark.asyncio
    async def test_register_callback_basic(self, connection_manager):
        """Test basic callback registration."""
        manager = connection_manager
        callback_calls = []

        def test_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            callback_calls.append((topic, payload))

        # Register callback
        manager.register_callback("test/topic", test_callback)

        # Verify callback is registered
        callbacks = manager.get_registered_callbacks()
        assert "test/topic" in callbacks
        assert callbacks["test/topic"] == test_callback

        # Simulate message arrival using the global callback
        await manager._global_message_callback("test/topic", "test message")

        # Verify callback was called
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("test/topic", "test message")

    @pytest.mark.asyncio
    async def test_register_callback_with_wildcards(self, connection_manager):
        """Test callback registration with MQTT wildcards."""
        manager = connection_manager
        single_level_calls = []
        multi_level_calls = []

        def single_level_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            single_level_calls.append((topic, payload))

        def multi_level_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            multi_level_calls.append((topic, payload))

        # Register callbacks with wildcards
        manager.register_callback("icsia/+/cmd/move", single_level_callback)
        manager.register_callback("icsia/device1/status/#", multi_level_callback)

        # Test single-level wildcard
        await manager._global_message_callback("icsia/device1/cmd/move", "move command")
        await manager._global_message_callback("icsia/device2/cmd/move", "another move")
        await manager._global_message_callback("icsia/device1/cmd/stop", "stop command")  # Should not match

        # Test multi-level wildcard
        await manager._global_message_callback("icsia/device1/status/current", "status")
        await manager._global_message_callback("icsia/device1/status/ack", "ack")
        await manager._global_message_callback("icsia/device1/status/completion/result", "completion")
        await manager._global_message_callback("icsia/device2/status/current", "other status")  # Should not match

        # Verify single-level wildcard matches
        assert len(single_level_calls) == 2
        assert ("icsia/device1/cmd/move", "move command") in single_level_calls
        assert ("icsia/device2/cmd/move", "another move") in single_level_calls

        # Verify multi-level wildcard matches
        assert len(multi_level_calls) == 3
        assert ("icsia/device1/status/current", "status") in multi_level_calls
        assert ("icsia/device1/status/ack", "ack") in multi_level_calls
        assert (
            "icsia/device1/status/completion/result",
            "completion",
        ) in multi_level_calls

    @pytest.mark.asyncio
    async def test_register_multiple_callbacks_same_topic(self, connection_manager):
        """Test multiple callbacks for the same topic pattern."""
        manager = connection_manager
        calls1 = []
        calls2 = []

        def callback1(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            calls1.append((topic, payload))

        def callback2(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            calls2.append((topic, payload))

        # Register first callback
        manager.register_callback("test/topic", callback1)

        # Register second callback for same topic (should replace first)
        manager.register_callback("test/topic", callback2)

        # Simulate message arrival
        await manager._global_message_callback("test/topic", "test message")

        # Only the second callback should be called
        assert len(calls1) == 0
        assert len(calls2) == 1
        assert calls2[0] == ("test/topic", "test message")

    @pytest.mark.asyncio
    async def test_register_async_callback(self, connection_manager):
        """Test registration and execution of async callbacks."""
        manager = connection_manager
        callback_calls = []

        async def async_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            # Simulate async work
            await asyncio.sleep(0.01)
            callback_calls.append((topic, payload))

        # Register async callback
        manager.register_callback("async/topic", async_callback)

        # Simulate message arrival - this should now directly await the async callback
        await manager._global_message_callback("async/topic", "async message")

        # No need for complex task gathering - the callback was awaited directly
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("async/topic", "async message")

    @pytest.mark.asyncio
    async def test_callback_error_handling(self, connection_manager):
        """Test error handling in callbacks."""
        manager = connection_manager

        def failing_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            raise ValueError("Callback error")

        # Register failing callback
        manager.register_callback("error/topic", failing_callback)

        # Simulate message arrival - should not raise exception
        try:
            await manager._global_message_callback("error/topic", "test message")
            # Test passes if no exception is raised
        except Exception:
            pytest.fail("Callback error should be handled gracefully")

    def test_get_registered_callbacks(self, connection_manager):
        """Test getting registered callbacks."""
        manager = connection_manager

        def callback1(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            pass

        def callback2(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            pass

        # Initially no callbacks
        callbacks = manager.get_registered_callbacks()
        assert len(callbacks) == 0

        # Register callbacks
        manager.register_callback("topic1", callback1)
        manager.register_callback("topic2", callback2)

        # Get callbacks
        callbacks = manager.get_registered_callbacks()
        assert len(callbacks) == 2
        assert "topic1" in callbacks
        assert "topic2" in callbacks
        assert callbacks["topic1"] == callback1
        assert callbacks["topic2"] == callback2

        # Verify it returns a copy (modifications don't affect original)
        callbacks["topic3"] = lambda t, p, pr: None
        original_callbacks = manager.get_registered_callbacks()
        assert "topic3" not in original_callbacks

    def test_topic_matching_logic(self, connection_manager):
        """Test the topic matching logic with various patterns."""
        manager = connection_manager

        # Test cases: (topic, pattern, should_match)
        test_cases = [
            ("icsia/device1/cmd/move", "icsia/device1/cmd/move", True),  # Exact match
            ("icsia/device1/cmd/move", "icsia/+/cmd/move", True),  # Single wildcard
            (
                "icsia/device1/cmd/move",
                "icsia/device1/cmd/+",
                True,
            ),  # Single wildcard at end
            (
                "icsia/device1/cmd/move",
                "icsia/+/+/+",
                True,
            ),  # Multiple single wildcards
            (
                "icsia/device1/cmd/move",
                "icsia/device1/cmd/#",
                True,
            ),  # Multi-level wildcard
            ("icsia/device1/cmd/move", "icsia/#", True),  # Multi-level from root
            (
                "icsia/device1/cmd/move/param",
                "icsia/device1/cmd/#",
                True,
            ),  # Multi-level with extra levels
            (
                "icsia/device1/cmd/move",
                "icsia/device2/cmd/move",
                False,
            ),  # Different device
            (
                "icsia/device1/status/ack",
                "icsia/+/cmd/+",
                False,
            ),  # Different message type
            ("icsia/device1/cmd", "icsia/+/cmd/+", False),  # Too few levels
            (
                "icsia/device1/cmd/move/extra",
                "icsia/+/cmd/move",
                False,
            ),  # Too many levels (no # wildcard)
        ]

        for topic, pattern, expected in test_cases:
            result = manager._topic_matches(topic, pattern)
            assert (
                result == expected
            ), f"Topic '{topic}' with pattern '{pattern}' should {'match' if expected else 'not match'}"

    @pytest.mark.asyncio
    async def test_disconnect_clears_callbacks(self, connection_manager):
        """Test that disconnect clears registered callbacks."""
        manager = connection_manager

        def test_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            pass

        # Register callback
        manager.register_callback("test/topic", test_callback)

        # Verify callback is registered
        callbacks = manager.get_registered_callbacks()
        assert len(callbacks) == 1
        assert "test/topic" in manager._subscribed_topics

        # Disconnect
        await manager.disconnect()

        # Verify callbacks and subscriptions are cleared
        callbacks = manager.get_registered_callbacks()
        assert len(callbacks) == 0
        assert len(manager._subscribed_topics) == 0

    @pytest.mark.asyncio
    async def test_callback_integration_with_subscribe(self, connection_manager):
        """Test callback registration works with explicit subscribe calls."""
        manager = connection_manager
        callback_calls = []

        def test_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            callback_calls.append((topic, payload))

        # Register callback (with auto-subscribe)
        manager.register_callback("test/integration", test_callback)

        # Give a moment for auto-subscription to complete
        await asyncio.sleep(0.1)

        # Verify the topic is tracked as subscribed
        assert "test/integration" in manager._subscribed_topics

        # Simulate message arrival
        await manager._global_message_callback("test/integration", "integration test")

        # Callback should be called
        assert len(callback_calls) == 1
        assert callback_calls[0] == ("test/integration", "integration test")

    @pytest.mark.asyncio
    async def test_callback_with_unsubscribe(self, connection_manager):
        """Test callback behavior with unsubscribe."""
        manager = connection_manager
        callback_calls = []

        def test_callback(topic: str, payload: str, properties: Optional[dict[str, Any]]):
            callback_calls.append((topic, payload))

        # Register callback (with auto-subscribe)
        manager.register_callback("test/unsub", test_callback)

        # Give a moment for auto-subscription to complete
        await asyncio.sleep(0.1)

        # Simulate message (should work)
        await manager._global_message_callback("test/unsub", "before unsub")
        assert len(callback_calls) == 1

        # Unsubscribe
        await manager.unsubscribe("test/unsub")

        # Simulate message (should not trigger callback since callback was removed)
        await manager._global_message_callback("test/unsub", "after unsub")
        assert len(callback_calls) == 1  # Still only 1 call
