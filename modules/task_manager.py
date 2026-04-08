# modules/task_manager.py - Zeilus Task Management System
"""
Comprehensive task management with:
- Gated tasks (trigger after conditions are met)
- Escalating reminders (frequency increases as deadline approaches)
- Future-dated to-do list
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

from config import StorageConfig

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class TaskConfig:
    """Task management settings"""
    
    # Reminder escalation (reminders per week by weeks remaining)
    # Key = minimum weeks remaining, Value = reminders per week
    REMINDER_SCHEDULE = {
        4: 3,   # 4+ weeks: 3 reminders/week
        2: 5,   # 2-3 weeks: 5 reminders/week
        1: 7,   # 1 week: daily
        0: 7    # Past due: daily
    }
    
    # Gate check frequency
    CHECK_GATES_ON_STARTUP = True
    
    # Task storage
    TASK_FILE = StorageConfig.STORAGE_DIR / 'tasks.json'


# =============================================================================
# ENUMS
# =============================================================================

class GateType(Enum):
    """Types of gate conditions"""
    DATE = "date"           # Unlocks after a specific date
    EVENT = "event"         # Unlocks after an event is marked complete
    

class TaskStatus(Enum):
    """Task status"""
    PENDING = "pending"     # Not yet due / gate not met
    ACTIVE = "active"       # Gate met, task is active
    COMPLETED = "completed" # Task done
    CANCELLED = "cancelled" # Task cancelled


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GatedTask:
    """
    A task that only triggers after a gate condition is met.
    
    Example: "Remind me to learn Python internals after my exams in March"
    - gate_type: DATE
    - gate_condition: "2026-03-31"
    - title: "Learn Python internals"
    """
    id: str
    title: str
    description: str
    gate_type: str  # GateType value
    gate_condition: str  # Date string or event name
    gate_met: bool = False
    status: str = "pending"  # TaskStatus value
    target_date: Optional[str] = None  # When task should be done by
    reminder_frequency: str = "escalating"  # "escalating" or "fixed"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reminders_sent: List[str] = field(default_factory=list)  # Timestamps of sent reminders
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'GatedTask':
        return cls(**data)
    
    def is_gate_met(self, current_date: datetime = None) -> bool:
        """Check if the gate condition is met"""
        if self.gate_met:
            return True
            
        current = current_date or datetime.now()
        
        if self.gate_type == GateType.DATE.value:
            try:
                gate_date = datetime.fromisoformat(self.gate_condition)
                return current >= gate_date
            except ValueError:
                # Try parsing common date formats
                for fmt in ["%Y-%m-%d", "%B %Y", "%b %Y", "%Y-%m"]:
                    try:
                        gate_date = datetime.strptime(self.gate_condition, fmt)
                        return current >= gate_date
                    except ValueError:
                        continue
                logger.warning(f"Could not parse gate date: {self.gate_condition}")
                return False
                
        elif self.gate_type == GateType.EVENT.value:
            # Event gates must be manually marked as met
            return self.gate_met
            
        return False


@dataclass
class ScheduledTask:
    """
    A task scheduled for a specific future date.
    
    Example: "Research octopus on October 13th"
    """
    id: str
    title: str
    description: str
    scheduled_date: str  # ISO format date
    completed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reminder_sent: bool = False
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ScheduledTask':
        return cls(**data)
    
    def is_due(self, current_date: datetime = None) -> bool:
        """Check if task is due today"""
        current = current_date or datetime.now()
        try:
            task_date = datetime.fromisoformat(self.scheduled_date).date()
            return current.date() == task_date
        except ValueError:
            return False
    
    def is_upcoming(self, days: int = 3, current_date: datetime = None) -> bool:
        """Check if task is coming up within N days"""
        current = current_date or datetime.now()
        try:
            task_date = datetime.fromisoformat(self.scheduled_date).date()
            delta = (task_date - current.date()).days
            return 0 <= delta <= days
        except ValueError:
            return False


# =============================================================================
# TASK MANAGER
# =============================================================================

class TaskManager:
    """
    Central task management system.
    
    Handles:
    - Gated tasks with conditional triggers
    - Scheduled tasks for specific dates
    - Escalating reminder frequency
    - Task persistence
    """
    
    def __init__(self):
        self.gated_tasks: List[GatedTask] = []
        self.scheduled_tasks: List[ScheduledTask] = []
        self.completed_events: List[str] = []  # Track completed event gates
        self._load()
        logger.info(f"TaskManager initialized: {len(self.gated_tasks)} gated, {len(self.scheduled_tasks)} scheduled")
    
    # =========================================================================
    # GATED TASKS
    # =========================================================================
    
    def add_gated_task(
        self,
        title: str,
        gate_type: str,
        gate_condition: str,
        description: str = "",
        target_date: str = None,
        reminder_frequency: str = "escalating"
    ) -> GatedTask:
        """
        Add a new gated task.
        
        Args:
            title: Task title (e.g., "Learn Python internals")
            gate_type: "date" or "event"
            gate_condition: ISO date string or event name
            description: Optional detailed description
            target_date: When task should be completed by
            reminder_frequency: "escalating" or "fixed"
        
        Returns:
            The created GatedTask
        """
        task = GatedTask(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            gate_type=gate_type,
            gate_condition=gate_condition,
            target_date=target_date,
            reminder_frequency=reminder_frequency
        )
        
        self.gated_tasks.append(task)
        self._save()
        
        logger.info(f"Created gated task: {title} (gate: {gate_type} - {gate_condition})")
        return task
    
    def check_gates(self, current_date: datetime = None) -> List[GatedTask]:
        """
        Check all gates and update task statuses.
        
        Returns:
            List of tasks whose gates just became met
        """
        current = current_date or datetime.now()
        newly_unlocked = []
        
        for task in self.gated_tasks:
            if task.status == TaskStatus.PENDING.value and not task.gate_met:
                # Check event gates
                if task.gate_type == GateType.EVENT.value:
                    if task.gate_condition.lower() in [e.lower() for e in self.completed_events]:
                        task.gate_met = True
                        task.status = TaskStatus.ACTIVE.value
                        newly_unlocked.append(task)
                        logger.info(f"Gate met (event): {task.title}")
                
                # Check date gates
                elif task.is_gate_met(current):
                    task.gate_met = True
                    task.status = TaskStatus.ACTIVE.value
                    newly_unlocked.append(task)
                    logger.info(f"Gate met (date): {task.title}")
        
        if newly_unlocked:
            self._save()
        
        return newly_unlocked
    
    def complete_event(self, event_name: str) -> List[GatedTask]:
        """
        Mark an event as complete, potentially unlocking gated tasks.
        
        Args:
            event_name: Name of the completed event (e.g., "exams", "exams_complete")
        
        Returns:
            List of tasks that were unlocked
        """
        self.completed_events.append(event_name)
        
        # Also add common variations
        variations = [
            event_name,
            f"{event_name}_complete",
            f"{event_name}_done",
            event_name.replace("_", " "),
            event_name.replace(" ", "_")
        ]
        
        for var in variations:
            if var not in self.completed_events:
                self.completed_events.append(var)
        
        self._save()
        return self.check_gates()
    
    def get_active_gated_tasks(self) -> List[GatedTask]:
        """Get all gated tasks that are currently active (gate met, not completed)"""
        return [t for t in self.gated_tasks if t.status == TaskStatus.ACTIVE.value]
    
    def get_pending_gated_tasks(self) -> List[GatedTask]:
        """Get all gated tasks still waiting for gate"""
        return [t for t in self.gated_tasks if t.status == TaskStatus.PENDING.value]
    
    # =========================================================================
    # SCHEDULED TASKS
    # =========================================================================
    
    def add_scheduled_task(
        self,
        title: str,
        scheduled_date: str,
        description: str = ""
    ) -> ScheduledTask:
        """
        Add a task for a specific future date.
        
        Args:
            title: Task title (e.g., "Research octopus")
            scheduled_date: ISO format date (e.g., "2026-10-13")
            description: Optional detailed description
        
        Returns:
            The created ScheduledTask
        """
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            scheduled_date=scheduled_date
        )
        
        self.scheduled_tasks.append(task)
        self._save()
        
        logger.info(f"Created scheduled task: {title} for {scheduled_date}")
        return task
    
    def get_due_today(self, current_date: datetime = None) -> List[ScheduledTask]:
        """Get all scheduled tasks due today"""
        return [t for t in self.scheduled_tasks if t.is_due(current_date) and not t.completed]
    
    def get_upcoming_tasks(self, days: int = 7, current_date: datetime = None) -> List[ScheduledTask]:
        """Get scheduled tasks coming up within N days"""
        return [t for t in self.scheduled_tasks if t.is_upcoming(days, current_date) and not t.completed]
    
    # =========================================================================
    # REMINDER FREQUENCY
    # =========================================================================
    
    def calculate_reminder_frequency(self, task: GatedTask, current_date: datetime = None) -> int:
        """
        Calculate how many reminders per week based on time until target date.
        
        Returns:
            Number of reminders per week
        """
        if not task.target_date:
            return 3  # Default to lowest frequency
        
        current = current_date or datetime.now()
        
        try:
            target = datetime.fromisoformat(task.target_date)
            weeks_remaining = (target - current).days / 7
            
            # Find the appropriate frequency based on weeks remaining
            for min_weeks, frequency in sorted(TaskConfig.REMINDER_SCHEDULE.items(), reverse=True):
                if weeks_remaining >= min_weeks:
                    return frequency
            
            return 7  # Default to daily if past due
            
        except ValueError:
            return 3  # Default frequency
    
    def should_send_reminder(self, task: GatedTask, current_date: datetime = None) -> bool:
        """
        Determine if we should send a reminder for this task now.
        
        Based on:
        - Reminder frequency (reminders per week)
        - When last reminder was sent
        """
        if task.status != TaskStatus.ACTIVE.value:
            return False
        
        current = current_date or datetime.now()
        frequency = self.calculate_reminder_frequency(task, current)
        
        # Calculate minimum gap between reminders
        # 7 reminders/week = every day, 3/week = every 2-3 days
        min_days_between = 7 / frequency
        
        if not task.reminders_sent:
            return True  # First reminder
        
        try:
            last_reminder = datetime.fromisoformat(task.reminders_sent[-1])
            days_since = (current - last_reminder).days
            return days_since >= min_days_between
        except (ValueError, IndexError):
            return True
    
    def get_due_reminders(self, current_date: datetime = None) -> List[GatedTask]:
        """Get all active gated tasks that need a reminder"""
        return [t for t in self.get_active_gated_tasks() if self.should_send_reminder(t, current_date)]
    
    def mark_reminder_sent(self, task_id: str, current_date: datetime = None):
        """Record that a reminder was sent for a task"""
        current = current_date or datetime.now()
        
        for task in self.gated_tasks:
            if task.id == task_id:
                task.reminders_sent.append(current.isoformat())
                self._save()
                break
    
    # =========================================================================
    # TASK OPERATIONS
    # =========================================================================
    
    def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed"""
        for task in self.gated_tasks:
            if task.id == task_id:
                task.status = TaskStatus.COMPLETED.value
                self._save()
                logger.info(f"Completed gated task: {task.title}")
                return True
        
        for task in self.scheduled_tasks:
            if task.id == task_id:
                task.completed = True
                self._save()
                logger.info(f"Completed scheduled task: {task.title}")
                return True
        
        return False
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        for i, task in enumerate(self.gated_tasks):
            if task.id == task_id:
                del self.gated_tasks[i]
                self._save()
                return True
        
        for i, task in enumerate(self.scheduled_tasks):
            if task.id == task_id:
                del self.scheduled_tasks[i]
                self._save()
                return True
        
        return False
    
    def get_all_tasks(self) -> Dict[str, List]:
        """Get all tasks organized by type"""
        return {
            "gated_pending": [t.to_dict() for t in self.get_pending_gated_tasks()],
            "gated_active": [t.to_dict() for t in self.get_active_gated_tasks()],
            "scheduled_upcoming": [t.to_dict() for t in self.get_upcoming_tasks(30)],
            "scheduled_due": [t.to_dict() for t in self.get_due_today()]
        }
    
    def get_task_summary(self) -> str:
        """Get a human-readable summary of all tasks"""
        lines = []
        
        # Gated tasks waiting
        pending = self.get_pending_gated_tasks()
        if pending:
            lines.append("📋 **Gated Tasks (waiting for trigger):**")
            for t in pending:
                gate_info = f"after {t.gate_condition}" if t.gate_type == "date" else f"after '{t.gate_condition}' event"
                lines.append(f"  • {t.title} — unlocks {gate_info}")
        
        # Active gated tasks
        active = self.get_active_gated_tasks()
        if active:
            lines.append("\n🔔 **Active Tasks (ready to work on):**")
            for t in active:
                target = f" (due: {t.target_date})" if t.target_date else ""
                lines.append(f"  • {t.title}{target}")
        
        # Upcoming scheduled tasks
        upcoming = self.get_upcoming_tasks(14)
        if upcoming:
            lines.append("\n📅 **Upcoming Scheduled Tasks:**")
            for t in upcoming:
                lines.append(f"  • {t.title} — {t.scheduled_date}")
        
        # Due today
        due = self.get_due_today()
        if due:
            lines.append("\n⚡ **Due Today:**")
            for t in due:
                lines.append(f"  • {t.title}")
        
        if not lines:
            return "No tasks scheduled. You're all clear! 🎉"
        
        return "\n".join(lines)
    
    # =========================================================================
    # PERSISTENCE
    # =========================================================================
    
    def _save(self):
        """Save tasks to disk"""
        try:
            data = {
                "gated_tasks": [t.to_dict() for t in self.gated_tasks],
                "scheduled_tasks": [t.to_dict() for t in self.scheduled_tasks],
                "completed_events": self.completed_events,
                "saved_at": datetime.now().isoformat()
            }
            
            TaskConfig.TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            with open(TaskConfig.TASK_FILE, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")
    
    def _load(self):
        """Load tasks from disk"""
        try:
            if TaskConfig.TASK_FILE.exists():
                with open(TaskConfig.TASK_FILE, 'r') as f:
                    data = json.load(f)
                
                self.gated_tasks = [GatedTask.from_dict(t) for t in data.get("gated_tasks", [])]
                self.scheduled_tasks = [ScheduledTask.from_dict(t) for t in data.get("scheduled_tasks", [])]
                self.completed_events = data.get("completed_events", [])
                
                logger.info(f"Loaded {len(self.gated_tasks)} gated tasks, {len(self.scheduled_tasks)} scheduled tasks")
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            self.gated_tasks = []
            self.scheduled_tasks = []
            self.completed_events = []


# =============================================================================
# TESTING
# =============================================================================

def test_task_manager():
    """Test task manager functionality"""
    print("=" * 60)
    print("Testing TaskManager")
    print("=" * 60)
    
    # Create a fresh manager
    manager = TaskManager()
    
    # Test 1: Create a gated task
    print("\n1. Creating gated task (exam gate)...")
    task1 = manager.add_gated_task(
        title="Learn Python internals",
        gate_type="date",
        gate_condition="2026-03-31",
        target_date="2026-04-15",
        description="Deep dive into Python after exams"
    )
    print(f"   Created: {task1.title} (ID: {task1.id[:8]}...)")
    
    # Test 2: Create an event-gated task
    print("\n2. Creating event-gated task...")
    task2 = manager.add_gated_task(
        title="Start new project",
        gate_type="event",
        gate_condition="exams_complete",
        description="Begin after exams are done"
    )
    print(f"   Created: {task2.title}")
    
    # Test 3: Create a scheduled task
    print("\n3. Creating scheduled task...")
    task3 = manager.add_scheduled_task(
        title="Research octopus",
        scheduled_date="2026-10-13",
        description="Learn about octopus intelligence"
    )
    print(f"   Created: {task3.title} for {task3.scheduled_date}")
    
    # Test 4: Check gates (none should unlock yet)
    print("\n4. Checking gates (current date)...")
    unlocked = manager.check_gates()
    print(f"   Unlocked tasks: {len(unlocked)}")
    
    # Test 5: Simulate completing exams event
    print("\n5. Completing 'exams' event...")
    unlocked = manager.complete_event("exams_complete")
    print(f"   Unlocked tasks: {[t.title for t in unlocked]}")
    
    # Test 6: Get task summary
    print("\n6. Task summary:")
    print(manager.get_task_summary())
    
    # Test 7: Reminder frequency
    print("\n7. Testing reminder frequency...")
    for task in manager.gated_tasks:
        freq = manager.calculate_reminder_frequency(task)
        print(f"   {task.title}: {freq} reminders/week")
    
    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_task_manager()
