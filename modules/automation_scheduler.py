# modules/automation_scheduler.py - Looped Automation Tasks
"""
Cron-like scheduling for recurring automated tasks.
Enables tasks like "research from 5 AM to 6 PM every Wednesday".
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import uuid

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
    logging.warning("croniter not installed. Using basic scheduling only.")

from config import StorageConfig

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & CONFIG
# =============================================================================

class ActionType(str, Enum):
    """Types of automated actions."""
    RESEARCH = "research"           # Start research on a topic
    SUMMARY = "summary"             # Generate and send a summary
    CHECK = "check"                 # Check something (tasks, events, etc.)
    REMINDER = "reminder"           # Send a reminder
    CUSTOM = "custom"               # Custom callback function


class RecurrenceType(str, Enum):
    """Simplified recurrence patterns."""
    DAILY = "daily"                 # Every day
    WEEKLY = "weekly"               # Every week
    WEEKDAYS = "weekdays"           # Monday-Friday
    MONTHLY = "monthly"             # Every month
    CRON = "cron"                   # Custom cron expression


class AutomationConfig:
    """Automation scheduler settings."""
    CHECK_INTERVAL_SECONDS = 60     # How often to check for due tasks
    MAX_RECURRING_TASKS = 50
    ENABLE_BACKGROUND_SCHEDULER = True
    STORAGE_FILE = StorageConfig.STORAGE_DIR / 'automation.json'


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TimeWindow:
    """Defines when a task should be active."""
    start_time: str = "00:00"       # HH:MM format
    end_time: str = "23:59"         # HH:MM format
    
    def is_active_now(self) -> bool:
        """Check if current time is within the window."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        return self.start_time <= current_time <= self.end_time
    
    def to_dict(self) -> Dict:
        return {"start_time": self.start_time, "end_time": self.end_time}
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TimeWindow':
        return cls(
            start_time=data.get("start_time", "00:00"),
            end_time=data.get("end_time", "23:59")
        )


@dataclass
class RecurringTask:
    """
    A task that runs on a schedule.
    
    Example: "Research AI from 5 AM to 6 PM every Wednesday"
    - schedule: "0 5 * * WED" (cron) or "weekly:WED" (simple)
    - time_window: TimeWindow(start="05:00", end="18:00")
    - action_type: "research"
    - action_config: {"topic": "AI developments"}
    """
    id: str
    name: str
    description: str = ""
    
    # Scheduling
    schedule: str = ""                          # Cron expression or simple pattern
    recurrence_type: str = "cron"               # RecurrenceType value
    time_window: TimeWindow = field(default_factory=TimeWindow)
    days_of_week: List[str] = field(default_factory=list)  # For weekly: ["MON", "WED"]
    
    # Action to perform
    action_type: str = "research"               # ActionType value
    action_config: Dict = field(default_factory=dict)  # Parameters for the action
    
    # Summary generation
    summary_enabled: bool = True
    summary_schedule: str = ""                  # When to generate summary (cron)
    summary_recipients: List[str] = field(default_factory=list)  # Where to send
    
    # State
    enabled: bool = True
    created_at: str = ""
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    last_summary: Optional[str] = None
    run_count: int = 0
    
    # Accumulated data for summary
    accumulated_data: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['time_window'] = self.time_window.to_dict()
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RecurringTask':
        time_window_data = data.pop('time_window', {})
        task = cls(**{k: v for k, v in data.items() if k != 'time_window'})
        task.time_window = TimeWindow.from_dict(time_window_data) if time_window_data else TimeWindow()
        return task
    
    def should_run_now(self) -> bool:
        """Check if task should run right now."""
        if not self.enabled:
            return False
        
        now = datetime.now()
        
        # Check time window
        if not self.time_window.is_active_now():
            return False
        
        # Check day of week for weekly recurrence
        if self.recurrence_type == RecurrenceType.WEEKLY.value and self.days_of_week:
            current_day = now.strftime("%a").upper()[:3]
            if current_day not in [d.upper()[:3] for d in self.days_of_week]:
                return False
        
        # Check weekdays only
        if self.recurrence_type == RecurrenceType.WEEKDAYS.value:
            if now.weekday() >= 5:  # Saturday=5, Sunday=6
                return False
        
        # For cron expressions, use croniter
        if self.recurrence_type == RecurrenceType.CRON.value and self.schedule:
            if HAS_CRONITER:
                try:
                    cron = croniter(self.schedule, now - timedelta(minutes=1))
                    next_time = cron.get_next(datetime)
                    # If next run is within the check interval, we should run
                    if next_time <= now + timedelta(seconds=AutomationConfig.CHECK_INTERVAL_SECONDS):
                        return True
                except Exception as e:
                    logger.error(f"Invalid cron expression '{self.schedule}': {e}")
                    return False
        
        # For simple patterns, check based on last run
        if self.last_run:
            last = datetime.fromisoformat(self.last_run)
            if self.recurrence_type == RecurrenceType.DAILY.value:
                if (now - last).days < 1:
                    return False
            elif self.recurrence_type == RecurrenceType.WEEKLY.value:
                if (now - last).days < 7:
                    return False
            elif self.recurrence_type == RecurrenceType.MONTHLY.value:
                if (now - last).days < 28:
                    return False
        
        return True
    
    def should_generate_summary(self) -> bool:
        """Check if it's time to generate a summary."""
        if not self.summary_enabled or not self.summary_schedule:
            return False
        
        now = datetime.now()
        
        # Check if we've already generated a summary recently
        if self.last_summary:
            last = datetime.fromisoformat(self.last_summary)
            if (now - last).total_seconds() < 3600:  # At least 1 hour between summaries
                return False
        
        if HAS_CRONITER and self.summary_schedule:
            try:
                cron = croniter(self.summary_schedule, now - timedelta(minutes=1))
                next_time = cron.get_next(datetime)
                if next_time <= now + timedelta(seconds=AutomationConfig.CHECK_INTERVAL_SECONDS):
                    return True
            except Exception:
                pass
        
        return False
    
    def calculate_next_run(self) -> Optional[str]:
        """Calculate next run time."""
        now = datetime.now()
        
        if self.recurrence_type == RecurrenceType.CRON.value and self.schedule and HAS_CRONITER:
            try:
                cron = croniter(self.schedule, now)
                next_time = cron.get_next(datetime)
                return next_time.isoformat()
            except Exception:
                pass
        
        # Simple calculation for other types
        if self.recurrence_type == RecurrenceType.DAILY.value:
            next_time = now + timedelta(days=1)
        elif self.recurrence_type == RecurrenceType.WEEKLY.value:
            next_time = now + timedelta(weeks=1)
        elif self.recurrence_type == RecurrenceType.MONTHLY.value:
            next_time = now + timedelta(days=30)
        else:
            next_time = now + timedelta(days=1)
        
        return next_time.replace(
            hour=int(self.time_window.start_time.split(":")[0]),
            minute=int(self.time_window.start_time.split(":")[1])
        ).isoformat()


@dataclass
class TaskRunResult:
    """Result of running an automated task."""
    task_id: str
    task_name: str
    started_at: str
    ended_at: Optional[str] = None
    success: bool = False
    result_data: Dict = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# AUTOMATION SCHEDULER
# =============================================================================

class AutomationScheduler:
    """
    Central scheduler for recurring automated tasks.
    
    Features:
    - Cron-like scheduling
    - Time windows (e.g., only run 5 AM - 6 PM)
    - Multiple action types (research, summary, reminder, etc.)
    - Summary generation at specified times
    - Background scheduler thread
    """
    
    def __init__(self, storage_file: Optional[Path] = None):
        self.storage_file = storage_file or AutomationConfig.STORAGE_FILE
        self.tasks: Dict[str, RecurringTask] = {}
        self.run_history: List[TaskRunResult] = []
        self.max_history = 100
        
        # Action handlers
        self._action_handlers: Dict[str, Callable] = {}
        
        # Background scheduler
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_scheduler = threading.Event()
        
        self._load()
        logger.info(f"AutomationScheduler initialized with {len(self.tasks)} tasks")
    
    # -------------------------------------------------------------------------
    # Task Management
    # -------------------------------------------------------------------------
    
    def add_recurring_task(
        self,
        name: str,
        action_type: str,
        action_config: Dict = None,
        schedule: str = None,
        recurrence_type: str = "weekly",
        days_of_week: List[str] = None,
        start_time: str = "00:00",
        end_time: str = "23:59",
        summary_schedule: str = None,
        description: str = ""
    ) -> str:
        """
        Add a new recurring task.
        
        Args:
            name: Task name
            action_type: Type of action (research, summary, reminder, etc.)
            action_config: Parameters for the action
            schedule: Cron expression (for cron type)
            recurrence_type: daily, weekly, weekdays, monthly, or cron
            days_of_week: ["MON", "WED", "FRI"] for weekly
            start_time: When to start each day (HH:MM)
            end_time: When to end each day (HH:MM)
            summary_schedule: Cron expression for summary generation
            description: Task description
            
        Returns:
            Task ID
            
        Example:
            # Research every Wednesday 5 AM - 6 PM, summary at 6 PM
            scheduler.add_recurring_task(
                name="Wednesday AI Research",
                action_type="research",
                action_config={"topic": "AI developments"},
                recurrence_type="weekly",
                days_of_week=["WED"],
                start_time="05:00",
                end_time="18:00",
                summary_schedule="0 18 * * WED"
            )
        """
        task_id = str(uuid.uuid4())
        
        task = RecurringTask(
            id=task_id,
            name=name,
            description=description,
            schedule=schedule or "",
            recurrence_type=recurrence_type,
            time_window=TimeWindow(start_time=start_time, end_time=end_time),
            days_of_week=days_of_week or [],
            action_type=action_type,
            action_config=action_config or {},
            summary_schedule=summary_schedule or "",
            summary_enabled=bool(summary_schedule),
            created_at=datetime.now().isoformat(),
            enabled=True
        )
        
        task.next_run = task.calculate_next_run()
        self.tasks[task_id] = task
        self._save()
        
        logger.info(f"Added recurring task '{name}' ({task_id})")
        return task_id
    
    def update_task(self, task_id: str, **updates) -> bool:
        """Update a task's properties."""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        self._save()
        return True
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a recurring task."""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save()
            logger.info(f"Deleted task {task_id}")
            return True
        return False
    
    def pause_task(self, task_id: str) -> bool:
        """Pause a task (disable without deleting)."""
        return self.update_task(task_id, enabled=False)
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task."""
        return self.update_task(task_id, enabled=True)
    
    def get_task(self, task_id: str) -> Optional[RecurringTask]:
        """Get a task by ID."""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Dict]:
        """Get all tasks as a list of dicts."""
        return [
            {
                "id": t.id,
                "name": t.name,
                "action_type": t.action_type,
                "schedule": f"{t.recurrence_type}: {t.days_of_week or t.schedule}",
                "time_window": f"{t.time_window.start_time} - {t.time_window.end_time}",
                "enabled": t.enabled,
                "last_run": t.last_run,
                "next_run": t.next_run,
                "run_count": t.run_count
            }
            for t in self.tasks.values()
        ]
    
    def find_tasks_by_action(self, action_type: str) -> List[RecurringTask]:
        """Find tasks by action type."""
        return [t for t in self.tasks.values() if t.action_type == action_type]
    
    # -------------------------------------------------------------------------
    # Scheduler Operations
    # -------------------------------------------------------------------------
    
    def check_due_tasks(self) -> List[RecurringTask]:
        """
        Check which tasks are due to run now.
        
        Returns:
            List of tasks that should run
        """
        due_tasks = []
        for task in self.tasks.values():
            if task.should_run_now():
                due_tasks.append(task)
        return due_tasks
    
    def run_task(self, task_id: str, force: bool = False) -> Optional[TaskRunResult]:
        """
        Run a specific task.
        
        Args:
            task_id: Task to run
            force: Run even if not scheduled
            
        Returns:
            TaskRunResult with outcome
        """
        task = self.tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return None
        
        if not force and not task.should_run_now():
            logger.debug(f"Task {task_id} not due to run")
            return None
        
        result = TaskRunResult(
            task_id=task.id,
            task_name=task.name,
            started_at=datetime.now().isoformat()
        )
        
        try:
            # Check if we have a handler for this action type
            if task.action_type in self._action_handlers:
                handler = self._action_handlers[task.action_type]
                result_data = handler(task)
                result.result_data = result_data or {}
                result.success = True
            else:
                # No handler - just log that it ran
                result.result_data = {"message": f"Action '{task.action_type}' has no handler"}
                result.success = True
                logger.warning(f"No handler for action type '{task.action_type}'")
            
        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.error(f"Error running task {task_id}: {e}")
        
        result.ended_at = datetime.now().isoformat()
        
        # Update task state
        task.last_run = result.started_at
        task.run_count += 1
        task.next_run = task.calculate_next_run()
        
        # Store result for summary
        if result.success and result.result_data:
            task.accumulated_data.append({
                "timestamp": result.started_at,
                "data": result.result_data
            })
        
        # Add to history
        self.run_history.append(result)
        if len(self.run_history) > self.max_history:
            self.run_history = self.run_history[-self.max_history:]
        
        self._save()
        logger.info(f"Ran task '{task.name}': {'success' if result.success else 'failed'}")
        
        return result
    
    def generate_summary(self, task_id: str) -> Optional[str]:
        """
        Generate a summary for a task's accumulated data.
        
        Returns:
            Summary text or None
        """
        task = self.tasks.get(task_id)
        if not task:
            return None
        
        if not task.accumulated_data:
            return f"No data accumulated for task '{task.name}'."
        
        lines = [
            f"# Summary: {task.name}",
            f"",
            f"**Period:** {task.accumulated_data[0]['timestamp'][:10]} to {task.accumulated_data[-1]['timestamp'][:10]}",
            f"**Runs:** {len(task.accumulated_data)}",
            f""
        ]
        
        # Aggregate findings (for research tasks)
        if task.action_type == ActionType.RESEARCH.value:
            all_findings = []
            for entry in task.accumulated_data:
                findings = entry.get("data", {}).get("findings", [])
                all_findings.extend(findings)
            
            if all_findings:
                lines.append("## Key Findings")
                for f in all_findings[-20:]:  # Last 20
                    lines.append(f"- {f}")
        else:
            lines.append("## Activity Log")
            for entry in task.accumulated_data[-10:]:  # Last 10 entries
                lines.append(f"- {entry['timestamp'][:16]}: {entry['data'].get('message', 'Completed')}")
        
        summary = "\n".join(lines)
        
        # Clear accumulated data after summary
        task.accumulated_data = []
        task.last_summary = datetime.now().isoformat()
        self._save()
        
        return summary
    
    def check_and_run_summaries(self) -> List[str]:
        """Check and generate any due summaries."""
        summaries = []
        for task in self.tasks.values():
            if task.should_generate_summary():
                summary = self.generate_summary(task.id)
                if summary:
                    summaries.append(summary)
        return summaries
    
    # -------------------------------------------------------------------------
    # Action Handlers
    # -------------------------------------------------------------------------
    
    def register_action_handler(self, action_type: str, handler: Callable):
        """
        Register a handler function for an action type.
        
        The handler receives the RecurringTask and should return a dict
        with any data to accumulate for summaries.
        """
        self._action_handlers[action_type] = handler
        logger.info(f"Registered handler for action type '{action_type}'")
    
    def unregister_action_handler(self, action_type: str):
        """Remove a registered action handler."""
        if action_type in self._action_handlers:
            del self._action_handlers[action_type]
    
    # -------------------------------------------------------------------------
    # Background Scheduler
    # -------------------------------------------------------------------------
    
    def start_background_scheduler(self):
        """Start the background scheduler thread."""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("Background scheduler already running")
            return
        
        self._stop_scheduler.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="AutomationScheduler"
        )
        self._scheduler_thread.start()
        logger.info("Started background scheduler")
    
    def stop_background_scheduler(self):
        """Stop the background scheduler thread."""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._stop_scheduler.set()
            self._scheduler_thread.join(timeout=5)
            logger.info("Stopped background scheduler")
    
    def _scheduler_loop(self):
        """Background loop that checks and runs due tasks."""
        logger.info("Scheduler loop started")
        
        while not self._stop_scheduler.is_set():
            try:
                # Check for due tasks
                due_tasks = self.check_due_tasks()
                for task in due_tasks:
                    self.run_task(task.id)
                
                # Check for due summaries
                self.check_and_run_summaries()
                
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            # Wait for next check
            self._stop_scheduler.wait(timeout=AutomationConfig.CHECK_INTERVAL_SECONDS)
        
        logger.info("Scheduler loop stopped")
    
    # -------------------------------------------------------------------------
    # Check on Startup
    # -------------------------------------------------------------------------
    
    def check_on_startup(self) -> List[str]:
        """
        Check for tasks that should have run while offline.
        
        Returns:
            List of notifications about missed/due tasks
        """
        notifications = []
        now = datetime.now()
        
        for task in self.tasks.values():
            if not task.enabled:
                continue
            
            # Check if task window is active now
            if task.time_window.is_active_now() and task.should_run_now():
                notifications.append(
                    f"🔄 Task '{task.name}' is due to run now"
                )
            
            # Check if we missed runs
            if task.last_run:
                last = datetime.fromisoformat(task.last_run)
                days_since = (now - last).days
                
                if task.recurrence_type == RecurrenceType.DAILY.value and days_since > 1:
                    notifications.append(
                        f"⚠️ Task '{task.name}' hasn't run in {days_since} days"
                    )
        
        return notifications
    
    # -------------------------------------------------------------------------
    # Summary for User
    # -------------------------------------------------------------------------
    
    def get_schedule_summary(self) -> str:
        """Get a human-readable summary of all scheduled tasks."""
        lines = [
            "# Automation Schedule",
            "",
            f"**Active tasks:** {len([t for t in self.tasks.values() if t.enabled])}",
            f"**Total runs today:** {sum(1 for r in self.run_history if r.started_at[:10] == datetime.now().strftime('%Y-%m-%d'))}",
            ""
        ]
        
        if not self.tasks:
            lines.append("No automated tasks scheduled.")
        else:
            lines.append("## Scheduled Tasks")
            for task in self.tasks.values():
                status = "✅" if task.enabled else "⏸️"
                schedule_desc = self._describe_schedule(task)
                lines.append(f"- {status} **{task.name}**: {schedule_desc}")
                if task.next_run:
                    lines.append(f"  - Next run: {task.next_run[:16].replace('T', ' ')}")
        
        return "\n".join(lines)
    
    def _describe_schedule(self, task: RecurringTask) -> str:
        """Create human-readable schedule description."""
        if task.recurrence_type == RecurrenceType.CRON.value:
            return f"Cron: {task.schedule}"
        elif task.recurrence_type == RecurrenceType.WEEKLY.value:
            days = ", ".join(task.days_of_week) if task.days_of_week else "weekly"
            return f"{days}, {task.time_window.start_time}-{task.time_window.end_time}"
        elif task.recurrence_type == RecurrenceType.DAILY.value:
            return f"Daily, {task.time_window.start_time}-{task.time_window.end_time}"
        elif task.recurrence_type == RecurrenceType.WEEKDAYS.value:
            return f"Weekdays, {task.time_window.start_time}-{task.time_window.end_time}"
        else:
            return task.recurrence_type
    
    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------
    
    def _save(self):
        """Save to disk."""
        try:
            data = {
                "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
                "run_history": [r.to_dict() for r in self.run_history[-50:]],
                "saved_at": datetime.now().isoformat()
            }
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save automation data: {e}")
    
    def _load(self):
        """Load from disk."""
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                
                self.tasks = {
                    k: RecurringTask.from_dict(v)
                    for k, v in data.get("tasks", {}).items()
                }
                
                self.run_history = [
                    TaskRunResult(**r) for r in data.get("run_history", [])
                ]
                
                logger.info(f"Loaded {len(self.tasks)} automation tasks")
        except Exception as e:
            logger.error(f"Failed to load automation data: {e}")
            self.tasks = {}
            self.run_history = []


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_schedule_from_text(text: str) -> Dict:
    """
    Parse natural language schedule into task parameters.
    
    Examples:
        "every wednesday from 5 am to 6 pm" -> 
            {recurrence_type: "weekly", days: ["WED"], start: "05:00", end: "18:00"}
        "daily at 9 am" ->
            {recurrence_type: "daily", start: "09:00", end: "09:00"}
    """
    text = text.lower()
    result = {
        "recurrence_type": "daily",
        "days_of_week": [],
        "start_time": "00:00",
        "end_time": "23:59"
    }
    
    # Days of week
    day_map = {
        "monday": "MON", "mon": "MON",
        "tuesday": "TUE", "tue": "TUE", "tues": "TUE",
        "wednesday": "WED", "wed": "WED",
        "thursday": "THU", "thu": "THU", "thurs": "THU",
        "friday": "FRI", "fri": "FRI",
        "saturday": "SAT", "sat": "SAT",
        "sunday": "SUN", "sun": "SUN"
    }
    
    for word, abbrev in day_map.items():
        if word in text:
            result["days_of_week"].append(abbrev)
            result["recurrence_type"] = "weekly"
    
    if "daily" in text or "every day" in text:
        result["recurrence_type"] = "daily"
        result["days_of_week"] = []
    
    if "weekday" in text:
        result["recurrence_type"] = "weekdays"
        result["days_of_week"] = []
    
    # Time parsing (basic)
    import re
    time_pattern = r'(\d{1,2})\s*(?::|\.)?(\d{2})?\s*(am|pm)?'
    times = re.findall(time_pattern, text)
    
    if times:
        parsed_times = []
        for hour, minute, ampm in times:
            h = int(hour)
            m = int(minute) if minute else 0
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            parsed_times.append(f"{h:02d}:{m:02d}")
        
        if len(parsed_times) >= 1:
            result["start_time"] = parsed_times[0]
        if len(parsed_times) >= 2:
            result["end_time"] = parsed_times[1]
        elif len(parsed_times) == 1:
            result["end_time"] = parsed_times[0]
    
    return result
