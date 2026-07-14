"""Bot state machine — tracks what the bot is currently doing."""
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class BotState(Enum):
    """All possible states the bot can be in."""
    STARTING = "starting"
    LOGGING_IN = "logging_in"
    IDLE = "idle"                    # Waiting between poll cycles
    SLEEPING = "sleeping"            # Outside active hours
    CHECKING = "checking"            # Polling the dashboard for invitations
    FOUND_TEST = "found_test"        # Invitation detected, about to accept
    ACCEPTING = "accepting"          # Clicking checkbox + accept button
    ACCEPTED = "accepted"            # Successfully joined a test
    FAILED = "failed"                # Acceptance failed (seats full, error)
    PAUSED = "paused"                # User paused via dashboard/telegram
    ERROR = "error"                  # Unrecoverable error, needs restart
    STOPPED = "stopped"              # Clean shutdown


@dataclass
class BotStatus:
    """Tracks the bot's current operational status."""
    state: BotState = BotState.STARTING
    started_at: datetime = field(default_factory=datetime.now)
    last_poll_at: datetime | None = None
    last_accept_at: datetime | None = None
    tests_accepted_today: int = 0
    tests_accepted_total: int = 0
    tests_failed: int = 0
    poll_count: int = 0
    current_test_name: str = ""
    last_error: str = ""
    session_valid: bool = False
    active_test_count: int = 0

    def set_state(self, new_state: BotState, detail: str = ""):
        """Update state with optional detail."""
        self.state = new_state
        if new_state == BotState.ERROR:
            self.last_error = detail
        elif new_state == BotState.ACCEPTED:
            self.tests_accepted_today += 1
            self.tests_accepted_total += 1
            self.last_accept_at = datetime.now()
        elif new_state == BotState.FAILED:
            self.tests_failed += 1
        elif new_state == BotState.CHECKING:
            self.poll_count += 1
            self.last_poll_at = datetime.now()

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def uptime_str(self) -> str:
        seconds = int(self.uptime_seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def to_dict(self) -> dict:
        """Serialize for API/dashboard."""
        return {
            "state": self.state.value,
            "uptime": self.uptime_str,
            "started_at": self.started_at.isoformat(),
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_accept_at": self.last_accept_at.isoformat() if self.last_accept_at else None,
            "tests_accepted_today": self.tests_accepted_today,
            "tests_accepted_total": self.tests_accepted_total,
            "tests_failed": self.tests_failed,
            "poll_count": self.poll_count,
            "current_test_name": self.current_test_name,
            "last_error": self.last_error,
            "session_valid": self.session_valid,
            "active_test_count": self.active_test_count,
        }
