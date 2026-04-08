# core/memory.py - Zeilus Memory System
"""
Human-like memory architecture:
- Working Memory: Last few messages (RAM-like)
- Episodic Memory: Session history (what happened when)
- Semantic Memory: Facts & knowledge (what we know)
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
import logging

from config import MemoryConfig, StorageConfig

logger = logging.getLogger(__name__)


# =============================================================================
# WORKING MEMORY - Short-term conversational context
# =============================================================================

class WorkingMemory:
    """
    Enhanced working memory with compression and importance scoring.
    Like human working memory - quick access, but smart about what to keep.
    """
    
    def __init__(self, max_size: int = MemoryConfig.WORKING_MEMORY_SIZE):
        self.messages: List[Dict] = []
        self.max_size = max_size
        self.summary: str = ""  # Summary of older compressed messages
        self.compression_enabled = getattr(MemoryConfig, 'ENABLE_COMPRESSION', True)
        self.compression_threshold = getattr(MemoryConfig, 'COMPRESSION_THRESHOLD', 40)
    
    def add_message(self, role: str, content: str, metadata: Dict = None):
        """Add message to working memory with importance scoring"""
        
        # Calculate importance score
        importance = self._calculate_importance(role, content)
        
        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {},
            'importance': importance
        }
        
        self.messages.append(message)
        
        # Check if we need to compress
        if self.compression_enabled and len(self.messages) > self.compression_threshold:
            self._compress_old_messages()
        
        # Hard limit - trim to max size (oldest messages removed)
        if len(self.messages) > self.max_size:
            self.messages = self.messages[-self.max_size:]
        
        logger.debug(f"Added to working memory: {role[:4]}... (importance: {importance}, count: {len(self.messages)}/{self.max_size})")
    
    def _calculate_importance(self, role: str, content: str) -> float:
        """
        Calculate importance score (0.0 - 1.0) for a message.
        High importance: questions, facts, decisions, code, errors
        Low importance: greetings, acknowledgments, filler
        """
        importance = 0.5  # Default
        content_lower = content.lower()
        
        # High importance patterns
        high_importance_patterns = [
            '?',  # Questions
            'remember', 'don\'t forget', 'important',
            'error', 'bug', 'issue', 'problem',
            'decision', 'choose', 'picked', 'selected',
            'file:', 'project:', 'task:',
            '```',  # Code blocks
            'my name is', 'i am', 'i\'m a', 'i work',  # Personal info
        ]
        
        for pattern in high_importance_patterns:
            if pattern in content_lower:
                importance = min(importance + 0.2, 1.0)
        
        # Low importance patterns
        low_importance_patterns = [
            'ok', 'okay', 'got it', 'thanks', 'thank you',
            'yes', 'no', 'sure', 'right', 'hmm',
            'hello', 'hi', 'hey', 'bye', 'goodbye'
        ]
        
        # Only reduce if it's a short message matching low patterns
        if len(content) < 20:
            for pattern in low_importance_patterns:
                if content_lower.strip() == pattern or content_lower.strip().startswith(pattern + ' '):
                    importance = max(importance - 0.3, 0.1)
        
        return round(importance, 2)
    
    def _compress_old_messages(self):
        """
        Compress older messages into a summary.
        Keeps recent messages verbatim, summarizes older ones.
        """
        if len(self.messages) <= self.compression_threshold:
            return
        
        # How many to compress (keep last 20 verbatim)
        keep_verbatim = 20
        compress_count = len(self.messages) - keep_verbatim
        
        if compress_count <= 0:
            return
        
        # Get messages to compress
        to_compress = self.messages[:compress_count]
        
        # Build simple summary (will be enhanced with LLM call in future)
        summary_parts = []
        
        # Extract high-importance items
        for msg in to_compress:
            if msg.get('importance', 0.5) >= 0.7:
                role = msg['role'].capitalize()
                content = msg['content'][:100]  # Truncate long messages
                if len(msg['content']) > 100:
                    content += "..."
                summary_parts.append(f"- {role}: {content}")
        
        if summary_parts:
            new_summary = f"[Earlier conversation summary]\n" + "\n".join(summary_parts[:10])
            self.summary = new_summary
        
        # Keep only recent messages
        self.messages = self.messages[-keep_verbatim:]
        
        logger.info(f"Compressed {compress_count} messages, kept {len(self.messages)} verbatim")
    
    def get_messages(self, n: Optional[int] = None) -> List[Dict]:
        """Get last N messages (or all if n=None)"""
        if n is None:
            return self.messages
        return self.messages[-n:]
    
    def get_context_string(self, n: Optional[int] = None, include_summary: bool = True) -> str:
        """Format messages as conversation string with optional summary"""
        parts = []
        
        # Include summary if available
        if include_summary and self.summary:
            parts.append(self.summary)
            parts.append("")  # Blank line separator
        
        messages = self.get_messages(n)
        
        for msg in messages:
            role = msg['role'].capitalize()
            content = msg['content']
            parts.append(f"{role}: {content}")
        
        return "\n".join(parts)
    
    def get_high_importance_messages(self, min_importance: float = 0.7) -> List[Dict]:
        """Get messages above importance threshold"""
        return [m for m in self.messages if m.get('importance', 0.5) >= min_importance]
    
    def clear(self):
        """Clear working memory"""
        self.messages = []
        self.summary = ""
        logger.info("Working memory cleared")
    
    def to_dict(self) -> Dict:
        """Serialize for storage"""
        return {
            'messages': self.messages,
            'max_size': self.max_size,
            'summary': self.summary
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'WorkingMemory':
        """Deserialize from storage"""
        memory = cls(max_size=data.get('max_size', MemoryConfig.WORKING_MEMORY_SIZE))
        memory.messages = data.get('messages', [])
        memory.summary = data.get('summary', '')
        return memory


# =============================================================================
# EPISODIC MEMORY - Session history (what happened when)
# =============================================================================

class EpisodicMemory:
    """
    Session-based memory: what happened during each interaction session.
    Like human episodic memory - remembers events in context.
    """
    
    def __init__(self, max_sessions: int = MemoryConfig.MAX_SESSIONS):
        self.sessions: List[Dict] = []
        self.max_sessions = max_sessions
        self.current_session: Optional[Dict] = None
    
    def start_session(self):
        """Start a new session"""
        if self.current_session:
            self.end_session()
        
        self.current_session = {
            'session_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'messages': [],
            'topics': set(),
            'entities': set(),
            'actions': [],
            'files_accessed': set()
        }
        
        logger.info(f"Started session: {self.current_session['session_id']}")
    
    def add_to_session(self, message: Dict):
        """Add message to current session"""
        if not self.current_session:
            self.start_session()
        
        self.current_session['messages'].append(message)
        
        # Extract entities/topics if metadata available
        if 'metadata' in message and message['metadata']:
            meta = message['metadata']
            
            if 'entities' in meta:
                self.current_session['entities'].update(meta['entities'])
            
            if 'topics' in meta:
                self.current_session['topics'].update(meta['topics'])
            
            if 'action' in meta:
                self.current_session['actions'].append(meta['action'])
            
            if 'files' in meta:
                self.current_session['files_accessed'].update(meta['files'])
    
    def end_session(self):
        """End current session and archive it"""
        if not self.current_session:
            return
        
        self.current_session['end_time'] = datetime.now().isoformat()
        
        # Convert sets to lists for JSON serialization
        self.current_session['topics'] = list(self.current_session['topics'])
        self.current_session['entities'] = list(self.current_session['entities'])
        self.current_session['files_accessed'] = list(self.current_session['files_accessed'])
        
        # Generate summary
        self.current_session['summary'] = self._generate_summary(self.current_session)
        
        # Archive
        self.sessions.append(self.current_session)
        
        # Trim old sessions
        if len(self.sessions) > self.max_sessions:
            self.sessions = self.sessions[-self.max_sessions:]
        
        logger.info(f"Ended session: {self.current_session['session_id']}")
        self.current_session = None
    
    def _generate_summary(self, session: Dict) -> str:
        """Generate human-readable session summary"""
        topics = session.get('topics', [])
        actions = session.get('actions', [])
        files = session.get('files_accessed', [])
        
        summary_parts = []
        
        if topics:
            summary_parts.append(f"Discussed: {', '.join(list(topics)[:3])}")
        
        if actions:
            summary_parts.append(f"Actions: {len(actions)}")
        
        if files:
            summary_parts.append(f"Files: {', '.join(list(files)[:2])}")
        
        return "; ".join(summary_parts) if summary_parts else "Brief conversation"
    
    def get_recent_sessions(self, n: int = 5) -> List[Dict]:
        """Get last N sessions"""
        return self.sessions[-n:]
    
    def search_sessions(self, query: str, n: int = 5) -> List[Dict]:
        """Search sessions by topic/entity"""
        query_lower = query.lower()
        
        matching = []
        for session in reversed(self.sessions):
            # Check topics
            topics = session.get('topics', [])
            if any(query_lower in str(t).lower() for t in topics):
                matching.append(session)
                continue
            
            # Check entities
            entities = session.get('entities', [])
            if any(query_lower in str(e).lower() for e in entities):
                matching.append(session)
                continue
            
            # Check summary
            summary = session.get('summary', '')
            if query_lower in summary.lower():
                matching.append(session)
        
        return matching[:n]
    
    def to_dict(self) -> Dict:
        """Serialize for storage"""
        # End current session before saving
        if self.current_session:
            self.end_session()
        
        return {
            'sessions': self.sessions,
            'max_sessions': self.max_sessions
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'EpisodicMemory':
        """Deserialize from storage"""
        memory = cls(max_sessions=data.get('max_sessions', MemoryConfig.MAX_SESSIONS))
        memory.sessions = data.get('sessions', [])
        return memory


# =============================================================================
# SEMANTIC MEMORY - Facts & knowledge about user
# =============================================================================

class SemanticMemory:
    """
    Long-term knowledge: facts learned about user, preferences, skills, etc.
    Like human semantic memory - conceptual knowledge without specific context.
    """
    
    def __init__(self, max_facts: int = MemoryConfig.MAX_FACTS):
        self.facts: List[Dict] = []
        self.max_facts = max_facts
        self.user_profile: Dict = {
            'name': 'User',
            'interests': [],
            'skills': {},
            'preferences': {},
            'active_projects': []
        }
    
    def add_fact(self, fact: str, category: str = 'general', 
                 confidence: float = 1.0, context: str = ''):
        """Add a fact to semantic memory"""
        
        if confidence < MemoryConfig.FACT_CONFIDENCE_THRESHOLD:
            logger.debug(f"Fact confidence too low ({confidence:.2f}), not storing")
            return
        
        fact_entry = {
            'fact': fact,
            'category': category,
            'confidence': confidence,
            'context': context,
            'learned': datetime.now().isoformat(),
            'access_count': 0
        }
        
        # Check for duplicates
        for existing in self.facts:
            if existing['fact'].lower() == fact.lower():
                # Update confidence if higher
                if confidence > existing['confidence']:
                    existing['confidence'] = confidence
                    logger.debug(f"Updated fact confidence: {fact}")
                return
        
        self.facts.append(fact_entry)
        
        # Trim if too many (remove least accessed)
        if len(self.facts) > self.max_facts:
            self.facts.sort(key=lambda x: x['access_count'])
            self.facts = self.facts[-self.max_facts:]
        
        logger.info(f"Learned fact: {fact} (confidence: {confidence:.2f})")
    
    def get_facts(self, category: Optional[str] = None, 
                  min_confidence: float = 0.0) -> List[Dict]:
        """Retrieve facts, optionally filtered"""
        filtered = self.facts
        
        if category:
            filtered = [f for f in filtered if f['category'] == category]
        
        if min_confidence > 0:
            filtered = [f for f in filtered if f['confidence'] >= min_confidence]
        
        # Mark as accessed
        for fact in filtered:
            fact['access_count'] += 1
        
        return filtered
    
    def search_facts(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        Search facts using TF-IDF semantic similarity.
        Falls back to keyword matching if TF-IDF isn't available.
        """
        if not self.facts:
            return []
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        results = []
        for fact in self.facts:
            fact_text = fact['fact'].lower()
            fact_words = set(fact_text.split())
            
            # Calculate relevance score using word overlap (simple TF-IDF proxy)
            common_words = query_words.intersection(fact_words)
            
            if common_words:
                # Score based on overlap ratio and IDF-like weighting
                overlap_ratio = len(common_words) / max(len(query_words), 1)
                
                # Boost for exact phrase match
                exact_match_boost = 1.5 if query_lower in fact_text else 1.0
                
                # Boost for shorter facts (more specific)
                length_boost = 1.0 / (1.0 + len(fact_words) / 20)
                
                relevance = overlap_ratio * exact_match_boost * (1 + length_boost)
                
                # Also factor in confidence
                final_score = relevance * fact['confidence']
                
                fact['access_count'] += 1
                results.append((fact, final_score))
            
            # Also check category match
            elif query_lower in fact.get('category', '').lower():
                fact['access_count'] += 1
                results.append((fact, 0.3 * fact['confidence']))
        
        # Sort by score and return top_k
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:top_k]]
    
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Alias for search_facts with semantic searching.
        Returns facts with relevance scores.
        """
        return self.search_facts(query, top_k)
    
    def get_related_facts(self, fact_text: str, top_k: int = 3) -> List[Dict]:
        """Find facts related to a given fact text."""
        # Extract key words from the fact
        words = fact_text.lower().split()
        # Filter common words
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'can', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
                     'from', 'as', 'into', 'through', 'during', 'before', 'after',
                     'above', 'below', 'between', 'under', 'about', 'that', 'this',
                     'i', 'my', 'me', 'we', 'our', 'you', 'your', 'he', 'she', 'it'}
        
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        
        if not keywords:
            return []
        
        # Search for related facts
        query = ' '.join(keywords[:5])  # Use top 5 keywords
        related = self.search_facts(query, top_k + 1)
        
        # Filter out the original fact
        return [f for f in related if f['fact'].lower() != fact_text.lower()][:top_k]
    
    def update_user_profile(self, key: str, value: Any):
        """Update user profile info"""
        self.user_profile[key] = value
        logger.info(f"Updated user profile: {key} = {value}")
    
    def get_user_profile(self) -> Dict:
        """Get full user profile"""
        return self.user_profile
    
    def to_dict(self) -> Dict:
        """Serialize for storage"""
        return {
            'facts': self.facts,
            'max_facts': self.max_facts,
            'user_profile': self.user_profile
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SemanticMemory':
        """Deserialize from storage"""
        memory = cls(max_facts=data.get('max_facts', MemoryConfig.MAX_FACTS))
        memory.facts = data.get('facts', [])
        memory.user_profile = data.get('user_profile', {
            'name': 'User',
            'interests': [],
            'skills': {},
            'preferences': {},
            'active_projects': []
        })
        return memory


# =============================================================================
# UNIFIED MEMORY SYSTEM
# =============================================================================

class MemorySystem:
    """
    Unified memory system combining all memory types.
    This is what the agent uses - one interface for all memory.
    """
    
    def __init__(self):
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        
        # Import ConversationalMemory here to avoid circular imports
        try:
            from core.conversational_memory import ConversationalMemory
            self.conversational = ConversationalMemory()
        except ImportError:
            self.conversational = None
            logger.warning("ConversationalMemory not available")
        
        self.last_save_time = time.time()
        
        # Load from disk if available
        self.load()
        
        # Start session
        self.episodic.start_session()
        
        logger.info("Memory system initialized")
    
    def add_interaction(self, role: str, content: str, metadata: Dict = None):
        """
        Add interaction to memory (updates all memory types).
        This is the main entry point for storing information.
        """
        
        # Add to working memory (short-term)
        self.working.add_message(role, content, metadata)
        
        # Add to episodic memory (session history)
        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        self.episodic.add_to_session(message)
        
        # Detect and store conversational events (for follow-ups)
        if role == 'user' and self.conversational:
            try:
                events = self.conversational.detect_events(content)
                for event in events:
                    self.conversational.add_pending_event(
                        event_type=event['event_type'],
                        original_message=content,
                        follow_up_template=event['follow_up_template'],
                        category=event['category'],
                        priority=event['priority'],
                        estimated_event_time=event.get('estimated_event_time'),
                        follow_up_after=event.get('follow_up_after')
                    )
            except Exception as e:
                logger.debug(f"Event detection error (non-critical): {e}")
        
        # Auto-save periodically
        if StorageConfig.AUTO_SAVE:
            current_time = time.time()
            if current_time - self.last_save_time > StorageConfig.SAVE_INTERVAL:
                self.save()
                self.last_save_time = current_time
    
    def get_context(self, n_messages: int = 5) -> str:
        """
        Get conversation context as string.
        Used for sending to LLM.
        """
        return self.working.get_context_string(n_messages)
    
    def learn_fact(self, fact: str, category: str = 'general', 
                   confidence: float = 1.0, context: str = ''):
        """Learn a new fact about the user"""
        self.semantic.add_fact(fact, category, confidence, context)
    
    def recall_facts(self, category: Optional[str] = None) -> List[str]:
        """Recall facts (returns just the fact strings)"""
        facts = self.semantic.get_facts(category, min_confidence=0.7)
        return [f['fact'] for f in facts]
    
    def search_memory(self, query: str) -> Dict:
        """
        Search all memory types for query.
        Returns combined results.
        """
        return {
            'facts': self.semantic.search_facts(query),
            'sessions': self.episodic.search_sessions(query),
            'recent_context': self.working.get_context_string()
        }
    
    def get_user_profile(self) -> Dict:
        """Get user profile from semantic memory"""
        return self.semantic.get_user_profile()
    
    def update_user_profile(self, key: str, value: Any):
        """Update user profile"""
        self.semantic.update_user_profile(key, value)
    
    def save(self):
        """Save all memory to disk"""
        try:
            memory_data = {
                'working': self.working.to_dict(),
                'episodic': self.episodic.to_dict(),
                'semantic': self.semantic.to_dict(),
                'saved_at': datetime.now().isoformat()
            }
            
            with open(StorageConfig.MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Memory saved to {StorageConfig.MEMORY_FILE}")
            
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
    
    def load(self):
        """Load memory from disk"""
        if not StorageConfig.MEMORY_FILE.exists():
            logger.info("No saved memory found, starting fresh")
            return
        
        try:
            with open(StorageConfig.MEMORY_FILE, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
            
            self.working = WorkingMemory.from_dict(memory_data.get('working', {}))
            self.episodic = EpisodicMemory.from_dict(memory_data.get('episodic', {}))
            self.semantic = SemanticMemory.from_dict(memory_data.get('semantic', {}))
            
            logger.info(f"Memory loaded from {StorageConfig.MEMORY_FILE}")
            
        except Exception as e:
            logger.error(f"Failed to load memory: {e}")
    
    def clear_all(self):
        """Clear all memory (use with caution!)"""
        self.working.clear()
        self.episodic.sessions = []
        self.semantic.facts = []
        self.save()
        logger.warning("All memory cleared")