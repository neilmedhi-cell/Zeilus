# core/conversational_memory.py - Human-like Conversational Memory
"""
Tracks conversational events and generates follow-ups across sessions.
Examples:
- User: "I have a job interview tomorrow"
- Next session: "How was your interview?"

This is a SEPARATE layer from main memory - does not modify WorkingMemory,
EpisodicMemory, or SemanticMemory.
"""

import json
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT PATTERNS - What to detect in conversation
# =============================================================================

EVENT_PATTERNS = {
    'job_interview': {
        'patterns': [
            r'\b(?:have|got|going to|scheduled|have an?)\s+(?:a\s+)?(?:job\s+)?interview\b',
            r'\binterview\s+(?:tomorrow|today|next|on|at)\b',
            r'\bgoing\s+(?:for|to)\s+(?:an?\s+)?interview\b',
        ],
        'follow_up_templates': [
            "How did your interview go?",
            "How was the interview?",
            "Did the interview go well?",
        ],
        'category': 'career',
        'priority': 'high',
    },
    'trip': {
        'patterns': [
            r'\bgoing\s+(?:on\s+)?(?:a\s+)?(?:trip|vacation|holiday)\b',
            r'\b(?:trip|vacation|holiday)\s+(?:to|next|tomorrow|this)\b',
            r'\btraveling\s+to\b',
            r'\bflying\s+(?:to|out)\b',
        ],
        'follow_up_templates': [
            "How was your trip?",
            "Did you enjoy your vacation?",
            "How did the trip go?",
        ],
        'category': 'personal',
        'priority': 'medium',
    },
    'meeting': {
        'patterns': [
            r'\b(?:have|got|scheduled)\s+(?:a\s+)?(?:big\s+)?meeting\b',
            r'\bmeeting\s+(?:with|at|tomorrow|today)\b',
            r'\bpresentation\s+(?:tomorrow|today|at)\b',
        ],
        'follow_up_templates': [
            "How did the meeting go?",
            "Did the meeting go well?",
            "How was your presentation?",
        ],
        'category': 'work',
        'priority': 'medium',
    },
    'exam': {
        'patterns': [
            r'\b(?:have|got|taking)\s+(?:an?\s+)?(?:exam|test|quiz)\b',
            r'\b(?:exam|test)\s+(?:tomorrow|today|on|next)\b',
            r'\bfinals?\s+(?:week|coming|tomorrow)\b',
        ],
        'follow_up_templates': [
            "How did your exam go?",
            "Did the test go well?",
            "How was the exam?",
        ],
        'category': 'education',
        'priority': 'high',
    },
    'appointment': {
        'patterns': [
            r'\b(?:doctor|dentist|therapy|therapist)\s+(?:appointment|visit)\b',
            r'\bappointment\s+(?:tomorrow|today|at|with)\b',
            r'\bgoing\s+to\s+(?:the\s+)?(?:doctor|dentist)\b',
        ],
        'follow_up_templates': [
            "How did your appointment go?",
            "Everything alright after your visit?",
            "How was the appointment?",
        ],
        'category': 'health',
        'priority': 'medium',
    },
    'date_event': {
        'patterns': [
            r'\b(?:going\s+on\s+)?(?:a\s+)?date\s+(?:tonight|tomorrow|with)\b',
            r'\bfirst\s+date\b',
            r'\bdate\s+with\b',
        ],
        'follow_up_templates': [
            "How did your date go?",
            "Did you have a nice time on your date?",
        ],
        'category': 'personal',
        'priority': 'medium',
    },
    'project_deadline': {
        'patterns': [
            r'\bdeadline\s+(?:is\s+)?(?:tomorrow|today|next|on)\b',
            r'\b(?:project|work)\s+(?:due|deadline)\b',
            r'\bsubmitting\s+(?:the\s+)?(?:project|work)\b',
        ],
        'follow_up_templates': [
            "Did you meet your deadline?",
            "How did the project submission go?",
            "Did everything work out with your deadline?",
        ],
        'category': 'work',
        'priority': 'high',
    },
    'celebration': {
        'patterns': [
            r'\b(?:my|our)\s+(?:birthday|anniversary)\b',
            r'\bbirthday\s+(?:party|celebration|tomorrow|today)\b',
            r'\bcelebrating\b',
        ],
        'follow_up_templates': [
            "How was the celebration?",
            "Did you have a good time?",
            "How was the party?",
        ],
        'category': 'personal',
        'priority': 'low',
    },
}

# Time-related patterns for extracting when events occur
TIME_PATTERNS = {
    'tomorrow': timedelta(days=1),
    'today': timedelta(hours=0),
    'tonight': timedelta(hours=0),
    'next week': timedelta(days=7),
    'this week': timedelta(days=3),
    'in a few days': timedelta(days=3),
    'soon': timedelta(days=2),
    'later': timedelta(hours=4),
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ConversationalEvent:
    """Represents a detected conversational event"""
    event_id: str
    event_type: str
    category: str
    priority: str
    original_message: str
    detected_at: str
    estimated_event_time: str
    follow_up_after: str
    follow_up_template: str
    status: str  # 'pending', 'followed_up', 'expired', 'resolved'
    followed_up_at: Optional[str] = None
    user_response: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ConversationalEvent':
        return cls(**data)


# =============================================================================
# CONVERSATIONAL MEMORY
# =============================================================================

class ConversationalMemory:
    """
    Human-like memory for tracking events and generating follow-ups.
    Completely separate from main memory system.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        # Import here to avoid circular imports
        from config import StorageConfig
        
        self.storage_path = storage_path or StorageConfig.STORAGE_DIR / 'conversational_memory.json'
        self.events: List[ConversationalEvent] = []
        self.max_events = 50
        self.event_expiry_days = 14
        self.follow_up_delay_hours = 4  # Minimum hours before follow-up
        
        # Load from disk
        self.load()
        
        logger.info("ConversationalMemory initialized")
    
    def detect_events(self, message: str) -> List[Dict]:
        """
        Detect events in a user message.
        Returns list of detected events with type and details.
        """
        detected = []
        message_lower = message.lower()
        
        for event_type, config in EVENT_PATTERNS.items():
            for pattern in config['patterns']:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    # Extract timing information
                    estimated_time, follow_up_after = self._extract_timing(message_lower)
                    
                    # Choose a follow-up template
                    import random
                    follow_up = random.choice(config['follow_up_templates'])
                    
                    detected.append({
                        'event_type': event_type,
                        'category': config['category'],
                        'priority': config['priority'],
                        'follow_up_template': follow_up,
                        'estimated_event_time': estimated_time.isoformat(),
                        'follow_up_after': follow_up_after.isoformat(),
                    })
                    break  # Only one match per event type
        
        if detected:
            logger.info(f"Detected {len(detected)} events: {[d['event_type'] for d in detected]}")
        
        return detected
    
    def _extract_timing(self, message: str) -> Tuple[datetime, datetime]:
        """
        Extract timing information from message.
        Returns (estimated_event_time, follow_up_after).
        """
        now = datetime.now()
        event_delta = timedelta(days=1)  # Default: assume tomorrow
        
        # Check for time patterns
        for pattern, delta in TIME_PATTERNS.items():
            if pattern in message:
                event_delta = delta
                break
        
        # Try dateparser for more complex expressions
        try:
            import dateparser
            parsed_date = dateparser.parse(message, settings={
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': now
            })
            if parsed_date and parsed_date > now:
                event_delta = parsed_date - now
        except ImportError:
            pass  # dateparser not available, use default
        except Exception:
            pass  # Parsing failed, use default
        
        estimated_event_time = now + event_delta
        
        # Follow-up should be after the event, with a delay
        follow_up_delay = timedelta(hours=self.follow_up_delay_hours)
        follow_up_after = estimated_event_time + follow_up_delay
        
        return estimated_event_time, follow_up_after
    
    def add_pending_event(self, event_type: str, original_message: str, 
                          follow_up_template: str, category: str = 'general',
                          priority: str = 'medium', 
                          estimated_event_time: Optional[str] = None,
                          follow_up_after: Optional[str] = None):
        """Add a new event to track for follow-up."""
        
        now = datetime.now()
        
        # Check for duplicate (same event type within last 24 hours)
        for event in self.events:
            if (event.event_type == event_type and 
                event.status == 'pending' and
                datetime.fromisoformat(event.detected_at) > now - timedelta(hours=24)):
                logger.debug(f"Skipping duplicate event: {event_type}")
                return
        
        event = ConversationalEvent(
            event_id=str(uuid.uuid4())[:8],
            event_type=event_type,
            category=category,
            priority=priority,
            original_message=original_message[:200],  # Truncate
            detected_at=now.isoformat(),
            estimated_event_time=estimated_event_time or (now + timedelta(days=1)).isoformat(),
            follow_up_after=follow_up_after or (now + timedelta(hours=self.follow_up_delay_hours + 24)).isoformat(),
            follow_up_template=follow_up_template,
            status='pending'
        )
        
        self.events.append(event)
        
        # Trim old events
        self._cleanup_old_events()
        
        # Save
        self.save()
        
        logger.info(f"Added pending event: {event_type} (ID: {event.event_id})")
    
    def get_due_followups(self) -> List[ConversationalEvent]:
        """
        Get events that are due for follow-up.
        Returns events where:
        - Status is 'pending'
        - Current time is after follow_up_after
        """
        now = datetime.now()
        due = []
        
        for event in self.events:
            if event.status != 'pending':
                continue
            
            follow_up_time = datetime.fromisoformat(event.follow_up_after)
            if now >= follow_up_time:
                due.append(event)
        
        # Sort by priority (high first) then by time
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        due.sort(key=lambda e: (priority_order.get(e.priority, 1), e.follow_up_after))
        
        return due
    
    def mark_followed_up(self, event_id: str, user_response: Optional[str] = None):
        """Mark an event as followed up."""
        for event in self.events:
            if event.event_id == event_id:
                event.status = 'followed_up'
                event.followed_up_at = datetime.now().isoformat()
                if user_response:
                    event.user_response = user_response[:500]
                self.save()
                logger.info(f"Marked event {event_id} as followed up")
                return
    
    def mark_resolved(self, event_id: str):
        """Mark an event as resolved (conversation concluded)."""
        for event in self.events:
            if event.event_id == event_id:
                event.status = 'resolved'
                self.save()
                return
    
    def generate_followup_prompt(self) -> Optional[str]:
        """
        Generate a greeting that includes follow-up questions.
        Returns None if no follow-ups are due.
        """
        due = self.get_due_followups()
        
        if not due:
            return None
        
        # Only follow up on the most important event to avoid overwhelming
        primary_event = due[0]
        
        prompt = primary_event.follow_up_template
        
        # Add context if multiple events
        if len(due) > 1:
            other_events = [e.event_type.replace('_', ' ') for e in due[1:3]]
            prompt += f" Also, I remember you mentioned something about {' and '.join(other_events)}."
        
        return prompt
    
    def get_context_for_prompt(self) -> str:
        """
        Get conversational memory context to inject into system prompt.
        """
        pending = [e for e in self.events if e.status == 'pending']
        recent_followed = [e for e in self.events 
                          if e.status == 'followed_up' 
                          and e.followed_up_at 
                          and datetime.fromisoformat(e.followed_up_at) > datetime.now() - timedelta(days=2)]
        
        if not pending and not recent_followed:
            return ""
        
        context_parts = []
        
        if pending:
            context_parts.append("## Pending User Events (ask about these when appropriate)")
            for event in pending[:5]:
                context_parts.append(f"- {event.event_type.replace('_', ' ').title()}: \"{event.original_message[:100]}...\" (follow up with: \"{event.follow_up_template}\")")
        
        if recent_followed:
            context_parts.append("\n## Recently Discussed Events")
            for event in recent_followed[:3]:
                response = f" - User said: {event.user_response[:100]}..." if event.user_response else ""
                context_parts.append(f"- {event.event_type.replace('_', ' ').title()}{response}")
        
        return "\n".join(context_parts)
    
    def _cleanup_old_events(self):
        """Remove expired and old events."""
        now = datetime.now()
        cutoff = now - timedelta(days=self.event_expiry_days)
        
        original_count = len(self.events)
        
        # Mark old pending events as expired
        for event in self.events:
            if event.status == 'pending':
                detected = datetime.fromisoformat(event.detected_at)
                if detected < cutoff:
                    event.status = 'expired'
        
        # Remove old non-pending events
        self.events = [e for e in self.events 
                       if e.status == 'pending' 
                       or datetime.fromisoformat(e.detected_at) > cutoff]
        
        # Trim to max events
        if len(self.events) > self.max_events:
            # Keep pending first, then most recent
            pending = [e for e in self.events if e.status == 'pending']
            others = [e for e in self.events if e.status != 'pending']
            others.sort(key=lambda e: e.detected_at, reverse=True)
            self.events = pending + others[:self.max_events - len(pending)]
        
        if len(self.events) != original_count:
            logger.debug(f"Cleaned up events: {original_count} -> {len(self.events)}")
    
    def save(self):
        """Save to disk."""
        try:
            data = {
                'events': [e.to_dict() for e in self.events],
                'saved_at': datetime.now().isoformat()
            }
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Saved conversational memory to {self.storage_path}")
            
        except Exception as e:
            logger.error(f"Failed to save conversational memory: {e}")
    
    def load(self):
        """Load from disk."""
        if not self.storage_path.exists():
            logger.info("No saved conversational memory found, starting fresh")
            return
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.events = [ConversationalEvent.from_dict(e) for e in data.get('events', [])]
            
            # Cleanup on load
            self._cleanup_old_events()
            
            logger.info(f"Loaded {len(self.events)} conversational events")
            
        except Exception as e:
            logger.error(f"Failed to load conversational memory: {e}")
            self.events = []
    
    def to_dict(self) -> Dict:
        """Serialize for storage."""
        return {
            'events': [e.to_dict() for e in self.events],
            'max_events': self.max_events,
            'event_expiry_days': self.event_expiry_days
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ConversationalMemory':
        """Deserialize from storage."""
        memory = cls()
        memory.events = [ConversationalEvent.from_dict(e) for e in data.get('events', [])]
        memory.max_events = data.get('max_events', 50)
        memory.event_expiry_days = data.get('event_expiry_days', 14)
        return memory
    
    def get_stats(self) -> Dict:
        """Get statistics about conversational memory."""
        return {
            'total_events': len(self.events),
            'pending': len([e for e in self.events if e.status == 'pending']),
            'followed_up': len([e for e in self.events if e.status == 'followed_up']),
            'expired': len([e for e in self.events if e.status == 'expired']),
            'resolved': len([e for e in self.events if e.status == 'resolved']),
            'by_category': self._count_by_field('category'),
            'by_type': self._count_by_field('event_type'),
        }
    
    def _count_by_field(self, field: str) -> Dict[str, int]:
        """Count events by a field."""
        counts = {}
        for event in self.events:
            value = getattr(event, field, 'unknown')
            counts[value] = counts.get(value, 0) + 1
        return counts
