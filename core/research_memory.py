# core/research_memory.py - Research Topic Memory System
"""
Tracks research topics, queries, findings, and sessions.
Separate from main memory to keep research context organized.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import StorageConfig

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ResearchSession:
    """A single research session on a topic."""
    id: str
    topic: str
    queries: List[str] = field(default_factory=list)        # Search queries made
    findings: List[str] = field(default_factory=list)       # Key findings/summaries
    sources: List[str] = field(default_factory=list)        # URLs, documents referenced
    notes: List[str] = field(default_factory=list)          # User notes
    started_at: str = ""
    ended_at: Optional[str] = None
    status: str = "active"  # 'active', 'completed', 'paused'
    duration_minutes: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ResearchSession':
        return cls(**data)
    
    def add_query(self, query: str):
        """Add a search query to this session."""
        if query not in self.queries:
            self.queries.append(query)
    
    def add_finding(self, finding: str):
        """Add a finding/insight to this session."""
        self.findings.append(finding)
    
    def add_source(self, source: str):
        """Add a source reference."""
        if source not in self.sources:
            self.sources.append(source)
    
    def add_note(self, note: str):
        """Add a user note."""
        self.notes.append(note)
    
    def complete(self, summary: Optional[str] = None):
        """Mark session as completed."""
        self.status = "completed"
        self.ended_at = datetime.now().isoformat()
        if summary:
            self.findings.append(f"[Summary] {summary}")
        
        # Calculate duration
        if self.started_at:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at)
            self.duration_minutes = int((end - start).total_seconds() / 60)


@dataclass
class ResearchTopic:
    """A research topic with all its sessions."""
    name: str
    sessions: List[ResearchSession] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    last_researched: str = ""
    total_time_minutes: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "sessions": [s.to_dict() for s in self.sessions],
            "related_topics": self.related_topics,
            "tags": self.tags,
            "created_at": self.created_at,
            "last_researched": self.last_researched,
            "total_time_minutes": self.total_time_minutes
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ResearchTopic':
        sessions = [ResearchSession.from_dict(s) for s in data.get("sessions", [])]
        return cls(
            name=data["name"],
            sessions=sessions,
            related_topics=data.get("related_topics", []),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            last_researched=data.get("last_researched", ""),
            total_time_minutes=data.get("total_time_minutes", 0)
        )
    
    def add_session(self, session: ResearchSession):
        """Add a session to this topic."""
        self.sessions.append(session)
        self.last_researched = datetime.now().isoformat()
    
    def get_active_session(self) -> Optional[ResearchSession]:
        """Get currently active session if any."""
        for session in reversed(self.sessions):
            if session.status == "active":
                return session
        return None
    
    def update_total_time(self):
        """Recalculate total research time."""
        self.total_time_minutes = sum(s.duration_minutes for s in self.sessions)
    
    def get_all_findings(self) -> List[str]:
        """Get all findings across sessions."""
        findings = []
        for session in self.sessions:
            findings.extend(session.findings)
        return findings
    
    def get_all_queries(self) -> List[str]:
        """Get all unique queries across sessions."""
        queries = set()
        for session in self.sessions:
            queries.update(session.queries)
        return list(queries)


# =============================================================================
# RESEARCH MEMORY
# =============================================================================

class ResearchMemory:
    """
    Manages research topic memory.
    Tracks research sessions, queries, findings, and topic relationships.
    """
    
    def __init__(self, storage_file: Optional[Path] = None):
        self.storage_file = storage_file or StorageConfig.STORAGE_DIR / 'research_memory.json'
        self.topics: Dict[str, ResearchTopic] = {}
        self.active_session: Optional[ResearchSession] = None
        self._load()
        logger.info(f"ResearchMemory initialized with {len(self.topics)} topics")
    
    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------
    
    def start_session(self, topic: str) -> ResearchSession:
        """
        Start a new research session on a topic.
        Creates the topic if it doesn't exist.
        
        Args:
            topic: The research topic name
            
        Returns:
            The new ResearchSession
        """
        # Normalize topic name
        topic_key = topic.lower().strip()
        
        # Create topic if new
        if topic_key not in self.topics:
            self.topics[topic_key] = ResearchTopic(
                name=topic,
                created_at=datetime.now().isoformat()
            )
            logger.info(f"Created new research topic: {topic}")
        
        # End any existing active session
        if self.active_session and self.active_session.status == "active":
            self.end_session(self.active_session.id, "Session paused to start new research")
        
        # Create new session
        session = ResearchSession(
            id=str(uuid.uuid4()),
            topic=topic,
            started_at=datetime.now().isoformat(),
            status="active"
        )
        
        self.topics[topic_key].add_session(session)
        self.active_session = session
        self._save()
        
        logger.info(f"Started research session {session.id} on '{topic}'")
        return session
    
    def add_query(self, query: str, session_id: Optional[str] = None):
        """
        Add a search query to a session.
        Uses active session if no session_id provided.
        """
        session = self._get_session(session_id)
        if session:
            session.add_query(query)
            self._save()
            logger.debug(f"Added query to session {session.id}: {query[:50]}...")
    
    def add_finding(self, finding: str, session_id: Optional[str] = None):
        """
        Add a finding/insight to a session.
        Uses active session if no session_id provided.
        """
        session = self._get_session(session_id)
        if session:
            session.add_finding(finding)
            self._save()
            logger.debug(f"Added finding to session {session.id}: {finding[:50]}...")
    
    def add_source(self, source: str, session_id: Optional[str] = None):
        """Add a source reference to a session."""
        session = self._get_session(session_id)
        if session:
            session.add_source(source)
            self._save()
    
    def add_note(self, note: str, session_id: Optional[str] = None):
        """Add a note to a session."""
        session = self._get_session(session_id)
        if session:
            session.add_note(note)
            self._save()
    
    def end_session(self, session_id: Optional[str] = None, summary: Optional[str] = None) -> Optional[ResearchSession]:
        """
        End a research session.
        
        Args:
            session_id: Session to end (uses active if not provided)
            summary: Optional summary of the session
            
        Returns:
            The ended session, or None if not found
        """
        session = self._get_session(session_id)
        if session:
            session.complete(summary)
            
            # Update topic stats
            topic_key = session.topic.lower().strip()
            if topic_key in self.topics:
                self.topics[topic_key].update_total_time()
            
            if self.active_session and self.active_session.id == session.id:
                self.active_session = None
            
            self._save()
            logger.info(f"Ended research session {session.id}")
            return session
        return None
    
    def pause_session(self, session_id: Optional[str] = None) -> Optional[ResearchSession]:
        """Pause a session without completing it."""
        session = self._get_session(session_id)
        if session:
            session.status = "paused"
            if self.active_session and self.active_session.id == session.id:
                self.active_session = None
            self._save()
            return session
        return None
    
    def resume_session(self, session_id: str) -> Optional[ResearchSession]:
        """Resume a paused session."""
        for topic in self.topics.values():
            for session in topic.sessions:
                if session.id == session_id and session.status == "paused":
                    session.status = "active"
                    self.active_session = session
                    self._save()
                    return session
        return None
    
    # -------------------------------------------------------------------------
    # Topic Management
    # -------------------------------------------------------------------------
    
    def get_topic(self, topic: str) -> Optional[ResearchTopic]:
        """Get a research topic by name."""
        return self.topics.get(topic.lower().strip())
    
    def get_topic_history(self, topic: str) -> Optional[Dict]:
        """
        Get complete history for a topic.
        
        Returns:
            Dictionary with topic info, sessions, findings, etc.
        """
        topic_obj = self.get_topic(topic)
        if not topic_obj:
            return None
        
        return {
            "name": topic_obj.name,
            "sessions_count": len(topic_obj.sessions),
            "total_time_minutes": topic_obj.total_time_minutes,
            "first_researched": topic_obj.created_at,
            "last_researched": topic_obj.last_researched,
            "all_queries": topic_obj.get_all_queries(),
            "all_findings": topic_obj.get_all_findings(),
            "related_topics": topic_obj.related_topics,
            "tags": topic_obj.tags
        }
    
    def link_topics(self, topic1: str, topic2: str):
        """Link two related topics."""
        t1 = self.get_topic(topic1)
        t2 = self.get_topic(topic2)
        
        if t1 and t2:
            if topic2 not in t1.related_topics:
                t1.related_topics.append(topic2)
            if topic1 not in t2.related_topics:
                t2.related_topics.append(topic1)
            self._save()
    
    def add_topic_tag(self, topic: str, tag: str):
        """Add a tag to a topic."""
        t = self.get_topic(topic)
        if t and tag not in t.tags:
            t.tags.append(tag)
            self._save()
    
    def get_all_topics(self) -> List[Dict]:
        """Get summary of all topics."""
        return [
            {
                "name": t.name,
                "sessions": len(t.sessions),
                "time_minutes": t.total_time_minutes,
                "last_researched": t.last_researched
            }
            for t in self.topics.values()
        ]
    
    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------
    
    def search_research(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search across all research (topics, queries, findings).
        
        Args:
            query: Search query
            limit: Max results to return
            
        Returns:
            List of matching items with context
        """
        query_lower = query.lower()
        results = []
        
        for topic in self.topics.values():
            # Check topic name
            if query_lower in topic.name.lower():
                results.append({
                    "type": "topic",
                    "topic": topic.name,
                    "match": topic.name,
                    "sessions": len(topic.sessions)
                })
            
            # Check sessions
            for session in topic.sessions:
                # Check queries
                for q in session.queries:
                    if query_lower in q.lower():
                        results.append({
                            "type": "query",
                            "topic": topic.name,
                            "session_id": session.id,
                            "match": q,
                            "date": session.started_at
                        })
                
                # Check findings
                for f in session.findings:
                    if query_lower in f.lower():
                        results.append({
                            "type": "finding",
                            "topic": topic.name,
                            "session_id": session.id,
                            "match": f,
                            "date": session.started_at
                        })
        
        return results[:limit]
    
    def get_recent_research(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """Get research sessions from the last N days."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        
        recent = []
        for topic in self.topics.values():
            for session in topic.sessions:
                if session.started_at:
                    session_date = datetime.fromisoformat(session.started_at)
                    if session_date >= cutoff:
                        recent.append({
                            "topic": topic.name,
                            "session_id": session.id,
                            "started": session.started_at,
                            "status": session.status,
                            "queries": len(session.queries),
                            "findings": len(session.findings)
                        })
        
        # Sort by date descending
        recent.sort(key=lambda x: x["started"], reverse=True)
        return recent[:limit]
    
    # -------------------------------------------------------------------------
    # Summary Generation
    # -------------------------------------------------------------------------
    
    def generate_topic_summary(self, topic: str) -> str:
        """Generate a human-readable summary of a research topic."""
        t = self.get_topic(topic)
        if not t:
            return f"No research found on '{topic}'."
        
        lines = [
            f"# Research Summary: {t.name}",
            f"",
            f"**Sessions:** {len(t.sessions)}",
            f"**Total time:** {t.total_time_minutes} minutes",
            f"**First researched:** {t.created_at[:10] if t.created_at else 'N/A'}",
            f"**Last researched:** {t.last_researched[:10] if t.last_researched else 'N/A'}",
            ""
        ]
        
        if t.related_topics:
            lines.append(f"**Related topics:** {', '.join(t.related_topics)}")
            lines.append("")
        
        findings = t.get_all_findings()
        if findings:
            lines.append("## Key Findings")
            for i, f in enumerate(findings[-10:], 1):  # Last 10 findings
                lines.append(f"{i}. {f}")
            lines.append("")
        
        queries = t.get_all_queries()
        if queries:
            lines.append("## Queries Made")
            for q in queries[-10:]:  # Last 10 queries
                lines.append(f"- {q}")
        
        return "\n".join(lines)
    
    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    
    def _get_session(self, session_id: Optional[str] = None) -> Optional[ResearchSession]:
        """Get session by ID or return active session."""
        if session_id:
            for topic in self.topics.values():
                for session in topic.sessions:
                    if session.id == session_id:
                        return session
            return None
        return self.active_session
    
    def _save(self):
        """Save to disk."""
        try:
            data = {
                "topics": {k: v.to_dict() for k, v in self.topics.items()},
                "active_session_id": self.active_session.id if self.active_session else None,
                "saved_at": datetime.now().isoformat()
            }
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save research memory: {e}")
    
    def _load(self):
        """Load from disk."""
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                
                self.topics = {
                    k: ResearchTopic.from_dict(v) 
                    for k, v in data.get("topics", {}).items()
                }
                
                # Restore active session
                active_id = data.get("active_session_id")
                if active_id:
                    self.active_session = self._get_session(active_id)
                
                logger.info(f"Loaded {len(self.topics)} research topics")
        except Exception as e:
            logger.error(f"Failed to load research memory: {e}")
            self.topics = {}
