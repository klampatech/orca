"""Animated spinner with swimming whale emoji.

Usage:
    from orca.utils.spinner import WhaleSpinner
    
    with WhaleSpinner("Working..."):
        # do work
        pass
    
    # Or manually:
    spinner = WhaleSpinner()
    spinner.start()
    # ... work ...
    spinner.stop()
"""

from __future__ import annotations

import sys
import threading
import time


class WhaleSpinner:
    """Animate a swimming whale emoji back and forth while work is happening.
    
    Usage:
        with WhaleSpinner("Loading..."):
            do_work()
    """

    FRAMES = [" 🐋 ", "  🐋", "   🐋", "  🐋", " 🐋 "]
    DIRECTION_LEFT = -1
    DIRECTION_RIGHT = 1

    def __init__(
        self,
        message: str = "Working",
        interval: float = 0.15,
        width: int = 79,
    ):
        """Initialize the spinner.
        
        Args:
            message: Message to display next to the whale
            interval: Seconds between animation frames
            width: Terminal width for animation bounds
        """
        self.message = message
        self.interval = interval
        self.width = width
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_len = 0

    def _animate(self) -> None:
        """Run the animation loop in a background thread."""
        position = 0
        direction = self.DIRECTION_RIGHT
        
        while not self._stop_event.is_set():
            # Calculate whale position with padding for message
            msg_len = len(self.message)
            max_pos = max(0, self.width - msg_len - 6)
            
            # Build the line
            padding = " " * position
            line = f"\r{padding}🐋 {self.message}"
            
            # Clear any previous trailing content
            if self._last_len > len(line):
                line = line + " " * (self._last_len - len(line))
            self._last_len = len(line)
            
            sys.stdout.write(line)
            sys.stdout.flush()
            
            # Move whale
            position += direction
            if position >= max_pos:
                direction = self.DIRECTION_LEFT
            elif position <= 0:
                direction = self.DIRECTION_RIGHT
            
            # Wait for next frame, but check stop frequently
            for _ in range(int(self.interval * 100)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.01)
        
        # Clear the line on stop and move to fresh line
        # Use \r to return to start, spaces to overwrite, \r again, then \n for fresh line
        sys.stdout.write("\r" + " " * self._last_len + "\r\n")
        sys.stdout.flush()

    def start(self) -> None:
        """Start the animation in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._last_len = 0
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the animation."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None

    def __enter__(self) -> "WhaleSpinner":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()


def with_whale_spinner(message: str = "Working"):
    """Decorator to run a function with a whale spinner.
    
    Usage:
        @with_whale_spinner("Processing...")
        def my_function():
            do_work()
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with WhaleSpinner(message):
                return func(*args, **kwargs)
        return wrapper
    return decorator