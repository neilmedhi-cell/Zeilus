# core/tool_memory.py - Tool Usage Memory System
"""
Tracks tool usage patterns separately from main memory.
Helps the agent learn which tools work best for different tasks.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

from config import StorageConfig

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ToolSession:
    """A single tool usage instance."""
    id: str
    tool_name: str
    started_at: str
    ended_at: Optional[str] = None
    parameters: Dict = field(default_factory=dict)
    result: str = "pending"  # 'success', 'failed', 'partial', 'pending'
    duration_ms: int = 0
    error: Optional[str] = None
    context: str = ""  # What task/intent triggered this tool
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ToolSession':
        return cls(**data)


@dataclass
class ToolUsage:
    """Aggregated stats for a single tool."""
    tool_name: str
    usage_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_used: str = ""
    avg_duration_ms: float = 0
    common_parameters: Dict = field(default_factory=dict)  # param -> frequency
    user_preferences: Dict = field(default_factory=dict)   # Custom settings
    contexts: List[str] = field(default_factory=list)      # What contexts it's used in
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ToolUsage':
        return cls(**data)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0 - 1.0)."""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count


# =============================================================================
# TOOL MEMORY
# =============================================================================

class ToolMemory:
    """
    Manages tool usage memory.
    Tracks which tools are used, how often, with what parameters,
    and their success rates.
    """
    
    def __init__(self, storage_file: Optional[Path] = None):
        self.storage_file = storage_file or StorageConfig.STORAGE_DIR / 'tool_memory.json'
        self.tool_stats: Dict[str, ToolUsage] = {}
        self.recent_sessions: List[ToolSession] = []
        self.max_recent_sessions = 100
        self.current_session: Optional[ToolSession] = None
        self._load()
        logger.info(f"ToolMemory initialized with {len(self.tool_stats)} tools tracked")
    
    # -------------------------------------------------------------------------
    # Tool Logging
    # -------------------------------------------------------------------------
    
    def start_tool_use(self, tool_name: str, parameters: Dict = None, context: str = "") -> str:
        """
        Log the start of a tool usage.
        
        Args:
            tool_name: Name of the tool being used
            parameters: Parameters passed to the tool
            context: What triggered this tool usage
            
        Returns:
            Session ID for this tool use
        """
        import uuid
        
        session = ToolSession(
            id=str(uuid.uuid4()),
            tool_name=tool_name,
            started_at=datetime.now().isoformat(),
            parameters=parameters or {},
            context=context
        )
        
        self.current_session = session
        return session.id
    
    def end_tool_use(self, session_id: Optional[str] = None, result: str = "success", error: str = None):
        """
        Log the end of a tool usage.
        
        Args:
            session_id: The session to end (uses current if not provided)
            result: 'success', 'failed', or 'partial'
            error: Error message if failed
        """
        session = self.current_session
        if session_id:
            # Find specific session
            for s in self.recent_sessions:
                if s.id == session_id:
                    session = s
                    break
        
        if not session:
            return
        
        session.ended_at = datetime.now().isoformat()
        session.result = result
        session.error = error
        
        # Calculate duration
        if session.started_at and session.ended_at:
            start = datetime.fromisoformat(session.started_at)
            end = datetime.fromisoformat(session.ended_at)
            session.duration_ms = int((end - start).total_seconds() * 1000)
        
        # Add to recent sessions
        self.recent_sessions.append(session)
        if len(self.recent_sessions) > self.max_recent_sessions:
            self.recent_sessions = self.recent_sessions[-self.max_recent_sessions:]
        
        # Update aggregated stats
        self._update_tool_stats(session)
        
        if self.current_session and self.current_session.id == session.id:
            self.current_session = None
        
        self._save()
        logger.debug(f"Logged tool use: {session.tool_name} -> {result}")
    
    def log_tool_use(self, tool_name: str, parameters: Dict = None, 
                     result: str = "success", error: str = None, context: str = "",
                     duration_ms: int = 0):
        """
        Quick one-shot logging of a tool use.
        Use this when you don't need start/end tracking.
        """
        import uuid
        
        session = ToolSession(
            id=str(uuid.uuid4()),
            tool_name=tool_name,
            started_at=datetime.now().isoformat(),
            ended_at=datetime.now().isoformat(),
            parameters=parameters or {},
            result=result,
            error=error,
            context=context,
            duration_ms=duration_ms
        )
        
        self.recent_sessions.append(session)
        if len(self.recent_sessions) > self.max_recent_sessions:
            self.recent_sessions = self.recent_sessions[-self.max_recent_sessions:]
        
        self._update_tool_stats(session)
        self._save()
    
    def _update_tool_stats(self, session: ToolSession):
        """Update aggregated stats from a session."""
        tool_name = session.tool_name
        
        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolUsage(tool_name=tool_name)
        
        stats = self.tool_stats[tool_name]
        stats.usage_count += 1
        stats.last_used = session.ended_at or session.started_at
        
        if session.result == "success":
            stats.success_count += 1
        elif session.result == "failed":
            stats.fail_count += 1
        
        # Update average duration
        if session.duration_ms > 0:
            if stats.avg_duration_ms == 0:
                stats.avg_duration_ms = session.duration_ms
            else:
                # Rolling average
                stats.avg_duration_ms = (stats.avg_duration_ms * 0.8) + (session.duration_ms * 0.2)
        
        # Track common parameters
        for key, value in session.parameters.items():
            param_key = f"{key}:{value}"
            if param_key not in stats.common_parameters:
                stats.common_parameters[param_key] = 0
            stats.common_parameters[param_key] += 1
        
        # Track contexts
        if session.context and session.context not in stats.contexts:
            stats.contexts.append(session.context)
            if len(stats.contexts) > 20:
                stats.contexts = stats.contexts[-20:]
    
    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------
    
    def get_tool_stats(self, tool_name: str) -> Optional[Dict]:
        """
        Get stats for a specific tool.
        
        Returns:
            Dictionary with usage stats, or None if tool not tracked
        """
        if tool_name not in self.tool_stats:
            return None
        
        stats = self.tool_stats[tool_name]
        return {
            "tool_name": stats.tool_name,
            "usage_count": stats.usage_count,
            "success_rate": round(stats.success_rate * 100, 1),
            "avg_duration_ms": round(stats.avg_duration_ms),
            "last_used": stats.last_used,
            "common_parameters": dict(sorted(
                stats.common_parameters.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:10])  # Top 10 params
        }
    
    def get_all_tool_stats(self) -> List[Dict]:
        """Get stats for all tracked tools."""
        return [
            {
                "tool": stats.tool_name,
                "uses": stats.usage_count,
                "success_rate": f"{round(stats.success_rate * 100)}%",
                "last_used": stats.last_used[:10] if stats.last_used else "never"
            }
            for stats in sorted(
                self.tool_stats.values(),
                key=lambda x: x.usage_count,
                reverse=True
            )
        ]
    
    def get_preferred_tools(self, limit: int = 10) -> List[str]:
        """
        Get most frequently used tools (user's preferred tools).
        
        Returns:
            List of tool names sorted by usage
        """
        sorted_tools = sorted(
            self.tool_stats.values(),
            key=lambda x: x.usage_count,
            reverse=True
        )
        return [t.tool_name for t in sorted_tools[:limit]]
    
    def get_recent_tools(self, n: int = 10) -> List[Dict]:
        """Get the last N tool usages."""
        recent = self.recent_sessions[-n:]
        return [
            {
                "tool": s.tool_name,
                "time": s.started_at,
                "result": s.result,
                "context": s.context[:50] if s.context else ""
            }
            for s in reversed(recent)
        ]
    
    def get_tools_for_context(self, context: str) -> List[Dict]:
        """
        Suggest tools based on what's been successful for similar contexts.
        
        Args:
            context: The current task/intent context
            
        Returns:
            List of tool suggestions with stats
        """
        context_lower = context.lower()
        suggestions = []
        
        for stats in self.tool_stats.values():
            # Check if any tracked contexts match
            relevance = 0
            for ctx in stats.contexts:
                if context_lower in ctx.lower() or ctx.lower() in context_lower:
                    relevance += 1
            
            if relevance > 0:
                suggestions.append({
                    "tool": stats.tool_name,
                    "relevance": relevance,
                    "success_rate": stats.success_rate,
                    "usage_count": stats.usage_count
                })
        
        # Sort by relevance then success rate
        suggestions.sort(key=lambda x: (x["relevance"], x["success_rate"]), reverse=True)
        return suggestions[:5]
    
    def suggest_tool(self, task_type: str) -> Optional[str]:
        """
        Suggest the best tool for a task type based on history.
        
        Args:
            task_type: Type of task (e.g., 'search', 'code', 'file')
            
        Returns:
            Tool name or None if no suggestion
        """
        suggestions = self.get_tools_for_context(task_type)
        if suggestions:
            # Return the most successful tool for this context
            return suggestions[0]["tool"]
        return None
    
    # -------------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------------
    
    def set_tool_preference(self, tool_name: str, key: str, value: Any):
        """Set a user preference for a tool."""
        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolUsage(tool_name=tool_name)
        
        self.tool_stats[tool_name].user_preferences[key] = value
        self._save()
    
    def get_tool_preference(self, tool_name: str, key: str, default: Any = None) -> Any:
        """Get a user preference for a tool."""
        if tool_name in self.tool_stats:
            return self.tool_stats[tool_name].user_preferences.get(key, default)
        return default
    
    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    
    def generate_tool_summary(self) -> str:
        """Generate a human-readable summary of tool usage."""
        lines = [
            "# Tool Usage Summary",
            "",
            f"**Total tools tracked:** {len(self.tool_stats)}",
            f"**Total tool uses:** {sum(t.usage_count for t in self.tool_stats.values())}",
            ""
        ]
        
        if self.tool_stats:
            lines.append("## Most Used Tools")
            for stats in sorted(self.tool_stats.values(), key=lambda x: x.usage_count, reverse=True)[:5]:
                lines.append(
                    f"- **{stats.tool_name}**: {stats.usage_count} uses, "
                    f"{round(stats.success_rate * 100)}% success"
                )
            lines.append("")
        
        recent = self.get_recent_tools(5)
        if recent:
            lines.append("## Recent Tool Usage")
            for t in recent:
                lines.append(f"- {t['tool']} ({t['result']}) - {t['time'][:16]}")
        
        return "\n".join(lines)
    
    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------
    
    def _save(self):
        """Save to disk."""
        try:
            data = {
                "tool_stats": {k: v.to_dict() for k, v in self.tool_stats.items()},
                "recent_sessions": [s.to_dict() for s in self.recent_sessions[-50:]],
                "saved_at": datetime.now().isoformat()
            }
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tool memory: {e}")
    
    def _load(self):
        """Load from disk."""
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r') as f:
                    data = json.load(f)
                
                self.tool_stats = {
                    k: ToolUsage.from_dict(v)
                    for k, v in data.get("tool_stats", {}).items()
                }
                
                self.recent_sessions = [
                    ToolSession.from_dict(s)
                    for s in data.get("recent_sessions", [])
                ]
                
                logger.info(f"Loaded {len(self.tool_stats)} tool stats")
        except Exception as e:
            logger.error(f"Failed to load tool memory: {e}")
            self.tool_stats = {}
            self.recent_sessions = []
