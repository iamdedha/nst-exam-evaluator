"""Thread-safe progress tracking for evaluation runs."""
import threading
import queue
import json
from datetime import datetime


class RunProgress:
    """Tracks progress of an evaluation run with SSE event support."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.phase = "idle"
        self.total_students = 0
        self.current_index = 0
        self.current_roll = ""
        self.current_name = ""
        self.current_step = ""
        self.messages = []
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.phase_results = {}
        self._event_queue = queue.Queue(maxsize=2000)
        self._lock = threading.Lock()
        self._subscribers = []

    def update(self, **kwargs):
        """Update progress and push SSE event."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            event = self.to_dict()
        self._event_queue.put(event)

    def log(self, message: str):
        """Add a log message."""
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S")
            entry = f"[{ts}] {message}"
            self.messages.append(entry)
            if len(self.messages) > 500:
                self.messages = self.messages[-500:]
        self._event_queue.put({"type": "log", "message": entry})

    def to_dict(self) -> dict:
        """Serialize current state."""
        with self._lock:
            return {
                "type": "progress",
                "run_id": self.run_id,
                "phase": self.phase,
                "total_students": self.total_students,
                "current_index": self.current_index,
                "current_roll": self.current_roll,
                "current_name": self.current_name,
                "current_step": self.current_step,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "error": self.error,
                "message_count": len(self.messages),
                "phase_results": self.phase_results,
            }

    def get_events(self, timeout=30):
        """Generator yielding SSE events."""
        while True:
            try:
                event = self._event_queue.get(timeout=timeout)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("phase") in ("complete", "error"):
                    break
            except queue.Empty:
                yield ": keepalive\n\n"


# Global registry
_runs = {}
_lock = threading.Lock()


def create_progress(run_id: str) -> RunProgress:
    with _lock:
        p = RunProgress(run_id)
        _runs[run_id] = p
        return p


def get_progress(run_id: str) -> RunProgress:
    with _lock:
        return _runs.get(run_id)


def remove_progress(run_id: str):
    with _lock:
        _runs.pop(run_id, None)
