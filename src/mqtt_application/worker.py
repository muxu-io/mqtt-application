"""Asynchronous worker module for processing MQTT messages."""

import asyncio

from .command_handler import AsyncCommandHandler
from mqtt_logger import MqttLogger


async def async_worker(
    worker_id: int,
    message_queue: asyncio.Queue,  # type: ignore[type-arg]
    command_handler: AsyncCommandHandler,
    logger: MqttLogger,
) -> None:
    """Fetch messages from the queue and processes them.

    Args:
        worker_id (int): Identifier for the worker.
        message_queue (asyncio.Queue): The queue to fetch messages from.
        command_handler (AsyncCommandHandler): The handler to process commands.
        logger (MqttLogger): The logger instance to use for logging.
    """
    logger.info(f"Worker {worker_id} started.")

    try:
        while True:
            # Get a message from the queue
            topic, payload = await message_queue.get()
            logger.info(
                f"[Worker {worker_id}] Processing message from topic '{topic}'..."
            )

            try:
                await command_handler.handle_command(topic, payload)
                logger.info(f"[Worker {worker_id}] Finished processing message.")
            except Exception as e:
                logger.error(f"[Worker {worker_id}] Error processing message: {e}")
            finally:
                message_queue.task_done()

    except asyncio.CancelledError:
        logger.info(f"Worker {worker_id} task cancelled.")
        raise  # Re-raise to properly handle cancellation
    except Exception as e:
        logger.error(f"[Worker {worker_id}] Unexpected error: {e}")
        raise


async def create_worker_pool(
    worker_count: int,
    message_queue: asyncio.Queue,  # type: ignore[type-arg]
    command_handler: AsyncCommandHandler,
    logger: MqttLogger,
) -> list[asyncio.Task]:
    """Create a pool of worker tasks.

    Args:
        worker_count: Number of workers to create
        message_queue: Queue for messages
        command_handler: Handler for processing commands
        logger: Logger instance

    Returns:
        List of worker tasks
    """
    tasks = []
    for i in range(worker_count):
        task = asyncio.create_task(
            async_worker(i + 1, message_queue, command_handler, logger),
            name=f"worker-{i + 1}",
        )
        tasks.append(task)
    return tasks
