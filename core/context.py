# core/context.py - Context Tracking & Management
"""
Track current state: what files, projects, tasks are active.
Enables "continue from yesterday" and "improve it" type commands.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from pathlib import Path

from config import StorageConfig, MemoryConfig

logger = logging.getLogger(__name__)


# =============================================================================
# CONTEXT MANAGER
# =============================================================================

class ContextManager:
    """
    Track current conversation and work context.
    Enables understanding of references and continuity.
    """
    
    def __init__(self):
        self.current_task: Optional[Dict] = None
        self.active_files: Set[str] = set()
        self.active_projects: Set[str] = set()
        self.recent_topics: List[str] = []
        self.recent_entities: List[Dict] = []
        
        self.conversation_thread: Dict = {
            'main_topic': None,
            'sub_topics': [],
            'unresolved_questions': []
        }
        
        # Load from disk
        self.load()
        
        logger.info("Context manager initialized")
    
    def update_from_understanding(self, understanding):
        """Update context based on what was understood"""
        
        # Add entities to recent entities
        for key, value in understanding.entities.items():
            self._add_entity(key, value)
        
        # Update topics based on intent
        if understanding.intent in ['start_project', 'search_github', 'search_web']:
            topic = understanding.entities.get('topic') or understanding.entities.get('search_query')
            if topic:
                self._add_topic(topic)
        
        # Track files mentioned
        if 'file' in understanding.entities:
            self.active_files.add(understanding.entities['file'])
        
        # Track projects
        if 'project' in understanding.entities:
            self.active_projects.add(understanding.entities['project'])
    
    def set_current_task(self, task_type: str, description: str, target: str = None):
        """Set what user is currently working on"""
        self.current_task = {
            'type': task_type,
            'description': description,
            'target': target,
            'started': datetime.now().isoformat(),
            'progress': 0
        }
        
        logger.info(f"Current task set: {task_type} - {description}")
    
    def get_current_task(self) -> Optional[Dict]:
        """Get current task"""
        return self.current_task
    
    def complete_task(self):
        """Mark current task as complete"""
        if self.current_task:
            logger.info(f"Task completed: {self.current_task['description']}")
            self.current_task = None
    
    def add_active_file(self, file_path: str):
        """Add file to active context"""
        self.active_files.add(file_path)
        self._trim_active_files()
        logger.debug(f"Active file added: {file_path}")
    
    def add_active_project(self, project_path: str):
        """Add project to active context"""
        self.active_projects.add(project_path)
        logger.debug(f"Active project added: {project_path}")
    
    def get_active_files(self) -> List[str]:
        """Get list of active files"""
        return list(self.active_files)
    
    def get_active_projects(self) -> List[str]:
        """Get list of active projects"""
        return list(self.active_projects)
    
    def _add_entity(self, entity_type: str, entity_value: str):
        """Track recently mentioned entities"""
        entity = {
            'type': entity_type,
            'value': entity_value,
            'timestamp': datetime.now().isoformat()
        }
        
        self.recent_entities.append(entity)
        
        # Trim old entities
        if len(self.recent_entities) > MemoryConfig.MAX_RECENT_ENTITIES:
            self.recent_entities = self.recent_entities[-MemoryConfig.MAX_RECENT_ENTITIES:]
    
    def _add_topic(self, topic: str):
        """Track recently discussed topics"""
        if topic not in self.recent_topics:
            self.recent_topics.append(topic)
        
        # Trim to last 10 topics
        if len(self.recent_topics) > 10:
            self.recent_topics = self.recent_topics[-10:]
        
        # Update conversation thread
        if not self.conversation_thread['main_topic']:
            self.conversation_thread['main_topic'] = topic
        else:
            if topic not in self.conversation_thread['sub_topics']:
                self.conversation_thread['sub_topics'].append(topic)
    
    def _trim_active_files(self):
        """Keep only recent active files"""
        if len(self.active_files) > 5:
            # Keep 5 most recent (in practice, would track timestamps)
            self.active_files = set(list(self.active_files)[-5:])
    
    def resolve_reference(self, reference: str) -> Optional[str]:
        """
        Resolve a reference like "it", "that", "the project".
        Returns the most likely target.
        """
        
        reference_lower = reference.lower()
        
        # File references
        if 'file' in reference_lower or 'code' in reference_lower:
            if self.active_files:
                return list(self.active_files)[-1]  # Most recent file
        
        # Project references
        if 'project' in reference_lower or 'app' in reference_lower:
            if self.active_projects:
                return list(self.active_projects)[-1]  # Most recent project
        
        # Task references
        if 'task' in reference_lower or 'work' in reference_lower:
            if self.current_task:
                return self.current_task.get('target') or self.current_task.get('description')
        
        # Generic "it", "that", "this" - use most recent entity
        if reference_lower in ['it', 'that', 'this']:
            if self.recent_entities:
                return self.recent_entities[-1]['value']
        
        return None
    
    def get_continuation_context(self) -> str:
        """
        Get context for "continue from yesterday" type queries.
        Returns summary of recent work.
        """
        
        context_parts = []
        
        # Current task
        if self.current_task:
            context_parts.append(f"Current task: {self.current_task['description']}")
        
        # Active projects
        if self.active_projects:
            projects = ', '.join(self.active_projects)
            context_parts.append(f"Active projects: {projects}")
        
        # Recent topics
        if self.recent_topics:
            topics = ', '.join(self.recent_topics[-3:])
            context_parts.append(f"Recent topics: {topics}")
        
        # Active files
        if self.active_files:
            files = ', '.join(self.active_files)
            context_parts.append(f"Working on files: {files}")
        
        return '\n'.join(context_parts) if context_parts else "No recent context"
    
    def get_summary(self) -> Dict:
        """Get full context summary"""
        return {
            'current_task': self.current_task,
            'active_files': list(self.active_files),
            'active_projects': list(self.active_projects),
            'recent_topics': self.recent_topics,
            'conversation_thread': self.conversation_thread,
            'recent_entities_count': len(self.recent_entities)
        }
    
    def clear_stale_context(self):
        """Clear context that's too old"""
        
        # Clear entities older than decay time
        decay_time = datetime.now() - timedelta(hours=MemoryConfig.CONTEXT_DECAY_HOURS)
        
        self.recent_entities = [
            e for e in self.recent_entities
            if datetime.fromisoformat(e['timestamp']) > decay_time
        ]
        
        # Clear current task if inactive for too long
        if self.current_task:
            task_start = datetime.fromisoformat(self.current_task['started'])
            if datetime.now() - task_start > timedelta(hours=MemoryConfig.CONTEXT_DECAY_HOURS):
                logger.info("Clearing stale task")
                self.current_task = None
        
        logger.debug("Stale context cleared")
    
    def save(self):
        """Save context to disk"""
        try:
            context_data = {
                'current_task': self.current_task,
                'active_files': list(self.active_files),
                'active_projects': list(self.active_projects),
                'recent_topics': self.recent_topics,
                'recent_entities': self.recent_entities,
                'conversation_thread': self.conversation_thread,
                'saved_at': datetime.now().isoformat()
            }
            
            with open(StorageConfig.CONTEXT_FILE, 'w', encoding='utf-8') as f:
                json.dump(context_data, f, indent=2, ensure_ascii=False)
            
            logger.debug("Context saved")
            
        except Exception as e:
            logger.error(f"Failed to save context: {e}")
    
    def load(self):
        """Load context from disk"""
        if not StorageConfig.CONTEXT_FILE.exists():
            logger.debug("No saved context found")
            return
        
        try:
            with open(StorageConfig.CONTEXT_FILE, 'r', encoding='utf-8') as f:
                context_data = json.load(f)
            
            self.current_task = context_data.get('current_task')
            self.active_files = set(context_data.get('active_files', []))
            self.active_projects = set(context_data.get('active_projects', []))
            self.recent_topics = context_data.get('recent_topics', [])
            self.recent_entities = context_data.get('recent_entities', [])
            self.conversation_thread = context_data.get('conversation_thread', {
                'main_topic': None,
                'sub_topics': [],
                'unresolved_questions': []
            })
            
            # Clear stale context after loading
            self.clear_stale_context()
            
            logger.info("Context loaded")
            
        except Exception as e:
            logger.error(f"Failed to load context: {e}")
    
    def reset(self):
        """Reset all context (new conversation start)"""
        self.current_task = None
        self.active_files.clear()
        self.recent_topics = []
        self.recent_entities = []
        self.conversation_thread = {
            'main_topic': None,
            'sub_topics': [],
            'unresolved_questions': []
        }
        
        logger.info("Context reset")