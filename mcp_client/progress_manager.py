"""Progress queue management for long-running MCP operations."""

import asyncio
import time
import logging
from collections import deque
from typing import Callable, Optional, Dict, Set, List
from .announcements import generate_progress_announcement

logger = logging.getLogger(__name__)


class ProgressManager:
    """Manages progress announcements for MCP tools.

    Features:
    - Queues progress messages per tool
    - Speaks them asynchronously one at a time
    - Stops immediately when tool completes
    - Clears unspoken messages to avoid stale announcements
    - Deduplicates messages within a time window
    """

    def __init__(
        self,
        speak_callback: Callable[[str], None],
        enable_natural_language: bool = True,
        dedup_window_seconds: float = 3.0,
        model: str = "gpt-4o",
        temperature: float = 0.9,
        batch_window_seconds: float = 5.0
    ):
        """Initialize the progress manager.

        Args:
            speak_callback: Callback to speak text to the user
            enable_natural_language: If True, rephrase progress with LLM
            dedup_window_seconds: Don't repeat same message within this window
            model: LLM model to use for generating announcements (default: gpt-4o)
            temperature: Temperature for LLM generation (default: 0.9)
            batch_window_seconds: Wait this long to batch multiple progress messages (default: 5.0)
        """
        self.speak_callback = speak_callback
        self.enable_natural_language = enable_natural_language
        self.dedup_window_seconds = dedup_window_seconds
        self.model = model
        self.temperature = temperature
        self.batch_window_seconds = batch_window_seconds

        # Track announced messages to avoid duplicates
        self.announced_progress: Dict[str, float] = {}  # message -> timestamp

        # Track announcement history per tool for narrative flow
        self.announcement_history: Dict[str, List[str]] = {}  # Natural language announcements
        self.raw_message_history: Dict[str, List[str]] = {}   # Raw progress messages

        # Progress queues per tool
        self.progress_queues: Dict[str, deque] = {}
        self.active_speakers: Dict[str, asyncio.Task] = {}
        self.speaker_stop_flags: Dict[str, bool] = {}

    async def _speak_progress_queue(self, tool_name: str):
        """Asynchronously speak queued progress messages for a tool.

        Batches messages that arrive within batch_window_seconds to avoid being too chatty.
        Stops immediately if the tool completes (indicated by stop flag).
        """
        try:
            while True:
                # Check if tool has completed
                if self.speaker_stop_flags.get(tool_name, False):
                    logger.info(f"Tool {tool_name} completed, stopping progress announcements")
                    break

                # Check if there are messages to speak
                if tool_name in self.progress_queues and len(self.progress_queues[tool_name]) > 0:
                    # Collect the first message
                    batched_messages = [self.progress_queues[tool_name].popleft()]

                    # Wait for the batch window to collect more messages
                    await asyncio.sleep(self.batch_window_seconds)

                    # Collect any additional messages that arrived during the wait
                    while (tool_name in self.progress_queues and
                           len(self.progress_queues[tool_name]) > 0 and
                           len(batched_messages) < 5):  # Limit to 5 messages per batch
                        batched_messages.append(self.progress_queues[tool_name].popleft())

                    # Check again if tool completed while we were waiting
                    if self.speaker_stop_flags.get(tool_name, False):
                        logger.info(f"Tool {tool_name} completed during batch window, stopping")
                        break

                    # Generate a single announcement from the batched messages
                    if self.enable_natural_language:
                        try:
                            # Get conversation history for this tool
                            natural_history = self.announcement_history.get(tool_name, [])
                            raw_history = self.raw_message_history.get(tool_name, [])

                            # Track all the raw messages
                            if tool_name not in self.raw_message_history:
                                self.raw_message_history[tool_name] = []
                            self.raw_message_history[tool_name].extend(batched_messages)

                            # Generate announcement from batched messages
                            natural_message = await generate_progress_announcement(
                                batched_messages,  # Pass list of messages
                                previously_announced=natural_history,
                                raw_messages=raw_history,
                                model=self.model,
                                temperature=self.temperature
                            )
                            logger.info(f"Speaking batched progress for {tool_name}: {natural_message} (from {len(batched_messages)} messages)")

                            # Track what we've said for narrative flow
                            if tool_name not in self.announcement_history:
                                self.announcement_history[tool_name] = []
                            self.announcement_history[tool_name].append(natural_message)

                        except Exception as e:
                            logger.warning(f"Error generating natural progress message: {e}")
                            natural_message = batched_messages[-1]  # Fall back to last message
                    else:
                        # Without natural language, just use the last message
                        natural_message = batched_messages[-1]
                        logger.info(f"Speaking progress for {tool_name}: {natural_message}")

                    # Speak the message
                    self.speak_callback(natural_message)

                    # Small delay to avoid overwhelming the TTS
                    await asyncio.sleep(0.1)
                else:
                    # No messages, wait a bit and check again
                    await asyncio.sleep(0.1)

        except Exception as e:
            logger.warning(f"Error speaking progress for {tool_name}: {e}")
        finally:
            # Clean up when done
            if tool_name in self.progress_queues:
                remaining = len(self.progress_queues[tool_name])
                if remaining > 0:
                    logger.info(f"Cleared {remaining} unspoken progress messages for {tool_name}")
                del self.progress_queues[tool_name]
            if tool_name in self.speaker_stop_flags:
                del self.speaker_stop_flags[tool_name]
            if tool_name in self.active_speakers:
                del self.active_speakers[tool_name]
            if tool_name in self.announcement_history:
                del self.announcement_history[tool_name]
            if tool_name in self.raw_message_history:
                del self.raw_message_history[tool_name]

    def _should_announce(self, message: str) -> bool:
        """Determine if a progress message is worth announcing.

        Filters out very granular/technical progress that would be too chatty.
        """
        message_lower = message.lower()

        # Skip very technical/granular messages
        skip_patterns = [
            "selecting",
            "identifying",
            "gathering all",
            "calculating the total",
            "finalizing the",
            "compiling the final",
            "diving into",
            "let's break down",
            "exploring new patterns",
            "ready to save",
        ]

        for pattern in skip_patterns:
            if pattern in message_lower:
                return False

        return True

    def queue_progress(self, tool_name: str, message: str):
        """Queue a progress message for a tool.

        Args:
            tool_name: Name of the tool reporting progress
            message: Progress message to queue
        """
        try:
            # Filter out messages that are too granular
            if not self._should_announce(message):
                logger.debug(f"Skipped announcing (too granular): {message}")
                return

            # Check if we recently announced this exact message (deduplication)
            now = time.time()
            last_announced = self.announced_progress.get(message)

            if last_announced is None or (now - last_announced) > self.dedup_window_seconds:
                # Initialize queue if needed
                if tool_name not in self.progress_queues:
                    self.progress_queues[tool_name] = deque()
                    self.speaker_stop_flags[tool_name] = False

                    # Start the speaker task for this tool
                    task = asyncio.create_task(self._speak_progress_queue(tool_name))
                    self.active_speakers[tool_name] = task

                # Queue the message
                self.progress_queues[tool_name].append(message)
                self.announced_progress[message] = now
                logger.debug(f"Queued progress for {tool_name}: {message}")

                # Clean up old entries to prevent memory leak
                cutoff_time = now - (self.dedup_window_seconds * 2)
                to_remove = [msg for msg, ts in self.announced_progress.items() if ts < cutoff_time]
                for msg in to_remove:
                    del self.announced_progress[msg]
            else:
                # Skip duplicate within dedup window
                logger.debug(f"Skipped duplicate progress for {tool_name}: {message}")

        except Exception as e:
            logger.warning(f"Could not queue progress: {e}")

    def mark_completed(self, tool_name: str):
        """Mark a tool as completed, stopping its progress announcements.

        Args:
            tool_name: Name of the tool that completed
        """
        try:
            logger.info(f"Tool {tool_name} completed, setting stop flag")
            self.speaker_stop_flags[tool_name] = True
        except Exception as e:
            logger.warning(f"Error in completion callback for {tool_name}: {e}")

    def cleanup(self):
        """Clean up all resources."""
        # Cancel all active speaker tasks
        for tool_name, task in list(self.active_speakers.items()):
            if not task.done():
                task.cancel()

        self.progress_queues.clear()
        self.speaker_stop_flags.clear()
        self.active_speakers.clear()
        self.announced_progress.clear()
        self.announcement_history.clear()
        self.raw_message_history.clear()
