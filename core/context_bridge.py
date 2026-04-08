# core/context_bridge.py - Unified Context Aggregation
"""
The single source of truth for ALL context passed to the LLM.
Bridges ContextManager, MemorySystem, and session state.

This solves the core problem: ContextManager data was never reaching Brain.
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from config import APIConfig, MemoryConfig

logger = logging.getLogger(__name__)


# =============================================================================
# CONTEXT SNAPSHOT - Immutable view of current context
# =============================================================================

@dataclass
class ContextSnapshot:
    """
    Immutable snapshot of all context at a given moment.
    Used to build prompts for the LLM.
    """
    
    # User identity
    user_name: str = "User"
    user_interests: List[str] = field(default_factory=list)
    user_skills: Dict[str, Any] = field(default_factory=dict)
    
    # Current work context
    current_task: Optional[Dict] = None
    active_files: List[str] = field(default_factory=list)
    active_projects: List[str] = field(default_factory=list)
    
    # Conversation context
    recent_topics: List[str] = field(default_factory=list)
    recent_entities: List[Dict] = field(default_factory=list)
    conversation_thread: Dict = field(default_factory=dict)
    
    # Memory context
    relevant_facts: List[str] = field(default_factory=list)
    conversation_history: str = ""
    conversation_summary: str = ""
    
    # Metadata
    timestamp: str = ""
    token_estimate: int = 0


# =============================================================================
# CONTEXT BRIDGE - The Unifier
# =============================================================================

class ContextBridge:
    """
    Unifies all context sources into a single interface for the Brain.
    
    Sources:
    - ContextManager: Active files, tasks, projects, topics
    - MemorySystem: Facts, conversation history, user profile
    - Session state: Current dialog state, slots
    
    Outputs:
    - System prompt context (injected into system message)
    - Conversation context (injected into user/assistant history)
    - Retrieved facts (relevant semantic memory)
    """
    
    def __init__(self, memory_system, context_manager):
        """
        Args:
            memory_system: MemorySystem instance
            context_manager: ContextManager instance
        """
        self.memory = memory_system
        self.context = context_manager
        
        # Dialog state tracking (slots that persist across turns)
        self.dialog_state: Dict[str, Any] = {
            'slots': {},           # Named entities that persist (e.g., "the project" = "Zeilus")
            'topic_stack': [],     # Stack of topics (for "back to X" type queries)
            'last_intent': None,
            'turn_count': 0
        }
        
        # Token estimation (rough: 1 token ≈ 4 chars)
        self.chars_per_token = 4
        
        logger.info("ContextBridge initialized")
    
    def get_snapshot(self) -> ContextSnapshot:
        """
        Get a complete snapshot of current context.
        This is the main method for understanding what context is available.
        """
        
        # Get user profile from semantic memory
        user_profile = self.memory.get_user_profile()
        
        # Get context manager state
        context_summary = self.context.get_summary()
        
        # Get conversation history
        conversation_history = self.memory.get_context(n_messages=20)
        
        # Get relevant facts (simple keyword match for now, will upgrade to semantic)
        relevant_facts = self._get_relevant_facts()
        
        snapshot = ContextSnapshot(
            # User identity
            user_name=user_profile.get('name', 'User'),
            user_interests=user_profile.get('interests', []),
            user_skills=user_profile.get('skills', {}),
            
            # Current work context
            current_task=context_summary.get('current_task'),
            active_files=context_summary.get('active_files', []),
            active_projects=context_summary.get('active_projects', []),
            
            # Conversation context
            recent_topics=context_summary.get('recent_topics', []),
            recent_entities=self.context.recent_entities[-5:] if hasattr(self.context, 'recent_entities') else [],
            conversation_thread=context_summary.get('conversation_thread', {}),
            
            # Memory context
            relevant_facts=relevant_facts,
            conversation_history=conversation_history,
            conversation_summary="",  # Will be populated by compression
            
            # Metadata
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
            token_estimate=self._estimate_tokens(conversation_history)
        )
        
        return snapshot
    
    def get_system_prompt_context(self) -> str:
        """
        Build the context block for the system prompt.
        This is injected into Brain._build_system_prompt().
        
        Returns structured context that the LLM can reference.
        """
        
        snapshot = self.get_snapshot()
        
        sections = []
        
        # User Profile Section
        sections.append("## User Profile")
        sections.append(f"- Name: {snapshot.user_name}")
        
        if snapshot.user_interests:
            sections.append(f"- Interests: {', '.join(snapshot.user_interests)}")
        
        if snapshot.user_skills:
            skills_str = ', '.join(f"{k}: {v}" for k, v in snapshot.user_skills.items())
            sections.append(f"- Skills: {skills_str}")
        
        # Current Work Context Section
        if snapshot.current_task or snapshot.active_files or snapshot.active_projects:
            sections.append("\n## Current Work Context")
            
            if snapshot.current_task:
                task = snapshot.current_task
                sections.append(f"- Current Task: {task.get('description', 'Unknown')}")
                if task.get('target'):
                    sections.append(f"  - Target: {task.get('target')}")
            
            if snapshot.active_files:
                sections.append(f"- Active Files: {', '.join(snapshot.active_files)}")
            
            if snapshot.active_projects:
                sections.append(f"- Active Projects: {', '.join(snapshot.active_projects)}")
        
        # Dialog State Section (for reference resolution)
        if self.dialog_state['slots']:
            sections.append("\n## Dialog State (Reference Resolution)")
            for slot_name, slot_value in self.dialog_state['slots'].items():
                sections.append(f"- \"{slot_name}\" refers to: {slot_value}")
        
        # Recent Topics Section
        if snapshot.recent_topics:
            sections.append(f"\n## Recent Topics")
            sections.append(f"- {', '.join(snapshot.recent_topics[-5:])}")
        
        # Relevant Facts Section
        if snapshot.relevant_facts:
            sections.append("\n## Relevant Remembered Facts")
            for fact in snapshot.relevant_facts[:5]:
                sections.append(f"- {fact}")
        
        context_block = '\n'.join(sections)
        
        logger.debug(f"System prompt context: {len(context_block)} chars, ~{self._estimate_tokens(context_block)} tokens")
        
        return context_block
    
    def get_conversation_context(self, max_tokens: int = None) -> str:
        """
        Get conversation history formatted for the LLM.
        Applies smart truncation if over token limit.
        
        Args:
            max_tokens: Maximum tokens to use for conversation context
        
        Returns:
            Formatted conversation history string
        """
        
        if max_tokens is None:
            max_tokens = APIConfig.MAX_CONTEXT_TOKENS // 2  # Use half for conversation
        
        # Get full history
        full_history = self.memory.get_context(n_messages=50)
        
        # Check if we need to truncate
        estimated_tokens = self._estimate_tokens(full_history)
        
        if estimated_tokens <= max_tokens:
            return full_history
        
        # Need to compress - get summary + recent messages
        return self._compress_conversation(full_history, max_tokens)
    
    def get_full_context_for_generation(self, user_message: str) -> Dict[str, str]:
        """
        Get all context needed for a generation call.
        
        Returns:
            Dict with 'system_context' and 'conversation_context'
        """
        
        return {
            'system_context': self.get_system_prompt_context(),
            'conversation_context': self.get_conversation_context(),
            'user_message': user_message,
            'dialog_state': self.dialog_state.copy()
        }
    
    def update_dialog_state(self, intent: str, entities: Dict[str, Any]):
        """
        Update dialog state after understanding a message.
        
        Args:
            intent: The classified intent
            entities: Extracted entities
        """
        
        self.dialog_state['last_intent'] = intent
        self.dialog_state['turn_count'] += 1
        
        # Update slots with new entities
        for entity_type, entity_value in entities.items():
            if entity_type in ['file', 'project', 'topic', 'task']:
                # These are "sticky" - they persist until replaced
                self.dialog_state['slots'][f"the {entity_type}"] = entity_value
                self.dialog_state['slots'][entity_type] = entity_value
        
        logger.debug(f"Dialog state updated: {self.dialog_state}")
    
    def resolve_reference(self, reference: str) -> Optional[str]:
        """
        Resolve a reference using dialog state and context.
        
        Args:
            reference: The reference to resolve (e.g., "it", "the project")
        
        Returns:
            Resolved value or None
        """
        
        reference_lower = reference.lower().strip()
        
        # Check dialog state slots first (most recent context)
        if reference_lower in self.dialog_state['slots']:
            return self.dialog_state['slots'][reference_lower]
        
        # Check context manager
        resolved = self.context.resolve_reference(reference)
        if resolved:
            return resolved
        
        # Generic pronouns - use most recent relevant entity
        if reference_lower in ['it', 'that', 'this']:
            # Try to infer from recent entities
            if self.context.recent_entities:
                return self.context.recent_entities[-1].get('value')
        
        return None
    
    def add_topic(self, topic: str):
        """Add a topic to the topic stack."""
        if topic and topic not in self.dialog_state['topic_stack'][-3:]:
            self.dialog_state['topic_stack'].append(topic)
            # Keep last 10 topics
            if len(self.dialog_state['topic_stack']) > 10:
                self.dialog_state['topic_stack'] = self.dialog_state['topic_stack'][-10:]
    
    def get_current_topic(self) -> Optional[str]:
        """Get the current active topic."""
        if self.dialog_state['topic_stack']:
            return self.dialog_state['topic_stack'][-1]
        return None
    
    def _get_relevant_facts(self, query: str = None) -> List[str]:
        """
        Get facts relevant to current context.
        Uses recent topics and entities as query if none provided.
        """
        
        if query is None:
            # Build query from recent context
            query_parts = []
            
            # Add recent topics
            if hasattr(self.context, 'recent_topics') and self.context.recent_topics:
                query_parts.extend(self.context.recent_topics[-3:])
            
            # Add current task
            if self.context.current_task:
                query_parts.append(self.context.current_task.get('description', ''))
            
            query = ' '.join(query_parts)
        
        if not query:
            return []
        
        # Search semantic memory
        results = self.memory.search_memory(query)
        facts = results.get('facts', [])
        
        return [f['fact'] for f in facts[:5]]
    
    def _compress_conversation(self, history: str, max_tokens: int) -> str:
        """
        Compress conversation history to fit token limit.
        Keeps recent messages verbatim, summarizes older ones.
        
        For now, simple truncation. Full summarization will be added in Phase 3.
        """
        
        lines = history.split('\n')
        
        # Keep last N lines that fit
        result_lines = []
        current_tokens = 0
        
        for line in reversed(lines):
            line_tokens = self._estimate_tokens(line)
            if current_tokens + line_tokens > max_tokens:
                break
            result_lines.insert(0, line)
            current_tokens += line_tokens
        
        if len(result_lines) < len(lines):
            # Add indicator that history was truncated
            result_lines.insert(0, "[Earlier conversation summarized]")
        
        return '\n'.join(result_lines)
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from text length."""
        if not text:
            return 0
        return len(text) // self.chars_per_token
    
    def reset_dialog_state(self):
        """Reset dialog state (e.g., for new conversation)."""
        self.dialog_state = {
            'slots': {},
            'topic_stack': [],
            'last_intent': None,
            'turn_count': 0
        }
        logger.info("Dialog state reset")
    
    def get_debug_info(self) -> Dict:
        """Get debug information about current context state."""
        snapshot = self.get_snapshot()
        
        return {
            'dialog_state': self.dialog_state,
            'active_files': snapshot.active_files,
            'active_projects': snapshot.active_projects,
            'current_task': snapshot.current_task,
            'recent_topics': snapshot.recent_topics,
            'relevant_facts_count': len(snapshot.relevant_facts),
            'conversation_token_estimate': snapshot.token_estimate,
            'system_context_tokens': self._estimate_tokens(self.get_system_prompt_context())
        }
