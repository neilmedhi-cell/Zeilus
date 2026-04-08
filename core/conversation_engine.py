# core/conversation_engine.py - Production Conversation Management
"""
Handles advanced conversation features:
- Sliding window with smart summarization
- Topic tracking and segmentation
- Response quality validation
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from config import MemoryConfig, APIConfig

logger = logging.getLogger(__name__)


# =============================================================================
# TOPIC SEGMENT - Track conversation topics
# =============================================================================

@dataclass
class TopicSegment:
    """A segment of conversation about a specific topic."""
    topic: str
    start_turn: int
    end_turn: Optional[int] = None
    messages: List[Dict] = field(default_factory=list)
    summary: str = ""
    importance: float = 0.5


# =============================================================================
# CONVERSATION ENGINE
# =============================================================================

class ConversationEngine:
    """
    Manages conversation flow with:
    - Smart context windowing
    - Topic tracking
    - Response quality checks
    """
    
    def __init__(self, memory_system, context_bridge, brain=None):
        """
        Args:
            memory_system: MemorySystem instance
            context_bridge: ContextBridge instance
            brain: Optional Brain instance for summarization
        """
        self.memory = memory_system
        self.context_bridge = context_bridge
        self.brain = brain
        
        # Topic tracking
        self.topic_segments: List[TopicSegment] = []
        self.current_topic: Optional[TopicSegment] = None
        self.turn_count: int = 0
        
        # Quality metrics
        self.response_history: List[Dict] = []
        
        logger.info("ConversationEngine initialized")
    
    def process_turn(self, user_input: str, understanding, response: str) -> str:
        """
        Process a conversation turn.
        Updates topic tracking, checks response quality.
        
        Args:
            user_input: User's message
            understanding: Understanding result from NLU
            response: Generated response
        
        Returns:
            Potentially enhanced response
        """
        
        self.turn_count += 1
        
        # Track topic
        self._update_topic_tracking(user_input, understanding)
        
        # Check for topic shift
        if self._detect_topic_shift(understanding):
            self._start_new_topic(understanding.entities.get('topic', 'new topic'))
        
        # Validate response coherence
        coherence_issues = self._check_coherence(user_input, response)
        
        if coherence_issues:
            logger.warning(f"Coherence issues detected: {coherence_issues}")
            # Could enhance response here in future
        
        # Record response metrics
        self._record_response(user_input, response, understanding)
        
        return response
    
    def get_context_for_generation(self, max_tokens: int = None) -> str:
        """
        Get optimized conversation context for generation.
        Uses sliding window with summarization.
        
        Args:
            max_tokens: Maximum tokens for context
        
        Returns:
            Formatted context string
        """
        
        if max_tokens is None:
            max_tokens = APIConfig.MAX_CONTEXT_TOKENS // 2
        
        # Get recent messages (verbatim)
        recent_messages = self.memory.working.get_messages(n=20)
        
        # Get summary of older messages
        summary = self.memory.working.summary
        
        # Build context
        parts = []
        
        if summary:
            parts.append(f"[Earlier conversation summary]\n{summary}\n")
        
        for msg in recent_messages:
            role = msg['role'].capitalize()
            content = msg['content']
            parts.append(f"{role}: {content}")
        
        context = "\n".join(parts)
        
        # Truncate if needed (simple for now)
        estimated_tokens = len(context) // 4
        if estimated_tokens > max_tokens:
            # Keep summary + last N messages that fit
            context = self._truncate_context(context, max_tokens)
        
        return context
    
    def _update_topic_tracking(self, user_input: str, understanding):
        """Update topic tracking based on new message."""
        
        # Extract topic from understanding
        topic = understanding.entities.get('topic') or understanding.entities.get('query')
        
        if topic and self.current_topic:
            # Add to current topic segment
            self.current_topic.messages.append({
                'role': 'user',
                'content': user_input,
                'turn': self.turn_count
            })
    
    def _detect_topic_shift(self, understanding) -> bool:
        """Detect if this message represents a topic shift."""
        
        # Intent-based detection
        shift_intents = ['start_project', 'search_web', 'search_github', 'continuation']
        
        if understanding.intent in shift_intents:
            new_topic = understanding.entities.get('topic') or understanding.entities.get('query')
            
            if new_topic and self.current_topic:
                # Check if significantly different from current topic
                current_words = set(self.current_topic.topic.lower().split())
                new_words = set(new_topic.lower().split())
                
                overlap = len(current_words.intersection(new_words))
                if overlap < 2:  # Little overlap = topic shift
                    return True
        
        return False
    
    def _start_new_topic(self, topic: str):
        """Start tracking a new topic segment."""
        
        # End current topic
        if self.current_topic:
            self.current_topic.end_turn = self.turn_count - 1
            self.topic_segments.append(self.current_topic)
        
        # Start new topic
        self.current_topic = TopicSegment(
            topic=topic,
            start_turn=self.turn_count
        )
        
        logger.info(f"New topic started: {topic}")
    
    def _check_coherence(self, user_input: str, response: str) -> List[str]:
        """
        Check response coherence with conversation.
        Returns list of potential issues.
        """
        
        issues = []
        
        # Check for very short responses to complex questions
        if '?' in user_input and len(user_input) > 50:
            if len(response) < 50:
                issues.append("Short response to complex question")
        
        # Check for repetition of recent responses
        for prev in self.response_history[-3:]:
            if response == prev.get('response'):
                issues.append("Repeated response")
                break
        
        return issues
    
    def _record_response(self, user_input: str, response: str, understanding):
        """Record response for quality tracking."""
        
        self.response_history.append({
            'turn': self.turn_count,
            'user_input': user_input[:100],
            'response': response[:100],
            'intent': understanding.intent,
            'confidence': understanding.confidence,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep last 20 responses
        if len(self.response_history) > 20:
            self.response_history = self.response_history[-20:]
    
    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """Truncate context to fit token limit."""
        
        target_chars = max_tokens * 4  # Rough conversion
        
        if len(context) <= target_chars:
            return context
        
        # Split into lines and keep from end
        lines = context.split('\n')
        result_lines = []
        current_chars = 0
        
        for line in reversed(lines):
            if current_chars + len(line) > target_chars:
                break
            result_lines.insert(0, line)
            current_chars += len(line) + 1
        
        if len(result_lines) < len(lines):
            result_lines.insert(0, "[Context truncated]")
        
        return '\n'.join(result_lines)
    
    def get_topic_summary(self) -> str:
        """Get summary of topics discussed."""
        
        if not self.topic_segments and not self.current_topic:
            return "No topics tracked yet."
        
        topics = [seg.topic for seg in self.topic_segments]
        if self.current_topic:
            topics.append(f"{self.current_topic.topic} (current)")
        
        return f"Topics discussed: {', '.join(topics)}"
    
    def reset(self):
        """Reset conversation tracking."""
        self.topic_segments = []
        self.current_topic = None
        self.turn_count = 0
        self.response_history = []
        logger.info("ConversationEngine reset")
