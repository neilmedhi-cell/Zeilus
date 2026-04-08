# zeilus.py - Main Agent Entry Point
"""
Zeilus - Memory-First Productivity Agent

Focus today: Memory + Understanding
Modules tomorrow: Morning Brief, Project Starter, etc.
"""

import logging
import sys
from pathlib import Path

# Setup logging FIRST
from config import LogConfig

logging.basicConfig(
    level=getattr(logging, LogConfig.LOG_LEVEL),
    format=LogConfig.LOG_FORMAT,
    handlers=[
        logging.FileHandler(LogConfig.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Now import everything else
from core.memory import MemorySystem
from core.brain import Brain, EmotionResponse
from core.understanding import UnderstandingEngine
from core.context import ContextManager
from core.context_bridge import ContextBridge  # NEW: Unified context aggregation
from core.voice import VoiceAgent  # NEW: Voice synthesis
from core.research_memory import ResearchMemory  # Research topic memory
from core.tool_memory import ToolMemory  # Tool usage memory
from modules.task_manager import TaskManager  # Task management system
from modules.automation_scheduler import AutomationScheduler, parse_schedule_from_text  # Recurring tasks
from integrations.screen_avatar import ScreenAvatar, get_screen_avatar  # On-screen VTuber avatar
from config import AgentConfig

# =============================================================================
# ZEILUS AGENT
# =============================================================================

class Zeilus:
    """
    Main agent class.
    Today: Memory + Understanding core
    Tomorrow: Add modules
    """
    
    def __init__(self):
        logger.info("=" * 60)
        logger.info(f"Initializing {AgentConfig.NAME}...")
        logger.info("=" * 60)
        
        # Core systems (order matters - dependencies!)
        self.memory = MemorySystem()
        self.context = ContextManager()
        
        # NEW: ContextBridge unifies memory + context for the Brain
        self.context_bridge = ContextBridge(self.memory, self.context)
        
        # Brain now receives unified context via ContextBridge
        self.brain = Brain(self.memory, context_bridge=self.context_bridge)
        
        # UnderstandingEngine also gets ContextBridge for dialog state tracking
        self.understanding = UnderstandingEngine(self.brain, self.memory, context_bridge=self.context_bridge)
        
        # Voice synthesis (optional - will be disabled if no API key)
        self.voice = VoiceAgent(auto_play=True)
        if self.voice.enabled:
            logger.info("Voice synthesis enabled")
        
        # Task management system
        self.task_manager = TaskManager()
        
        # Research and tool memory (separate tracking)
        self.research_memory = ResearchMemory()
        self.tool_memory = ToolMemory()
        
        # Automation scheduler for recurring tasks
        self.automation = AutomationScheduler()
        self._setup_automation_handlers()
        
        # Start background scheduler if enabled
        from modules.automation_scheduler import AutomationConfig
        if AutomationConfig.ENABLE_BACKGROUND_SCHEDULER:
            self.automation.start_background_scheduler()
        
        # On-screen VTuber avatar (optional - requires VTuber Studio running)
        self.avatar = get_screen_avatar()
        self._avatar_enabled = False  # Will be enabled if user calls 'avatar' command
        
        # Modules (add tomorrow)
        self.modules = {}
        
        logger.info(f"✅ {AgentConfig.NAME} initialized and ready!")
        
        # Welcome message
        self._show_welcome()
    
    def _show_welcome(self):
        """Show welcome message"""
        print(f"\n{'='*60}")
        print(f"  {AgentConfig.NAME} - Your Productivity Assistant")
        print(f"{'='*60}\n")
        
        # Show context if available
        continuation = self.context.get_continuation_context()
        if continuation != "No recent context":
            print("📋 Continuing from last session:\n")
            print(f"{continuation}\n")
        
        # Check for pending follow-ups from conversational memory
        followup = self._check_pending_followups()
        if followup:
            print(f"💭 {followup}\n")
        
        # Check for task reminders
        self._check_tasks_on_startup()
        
        print("Type your message (or 'help' for commands, 'quit' to exit)\n")
    
    def _check_pending_followups(self) -> str:
        """Check for pending follow-ups at session start"""
        if hasattr(self.memory, 'conversational') and self.memory.conversational:
            try:
                followup = self.memory.conversational.generate_followup_prompt()
                if followup:
                    # Mark the primary event as followed up
                    due_events = self.memory.conversational.get_due_followups()
                    if due_events:
                        self.memory.conversational.mark_followed_up(due_events[0].event_id)
                    return followup
            except Exception as e:
                logger.debug(f"Follow-up check error (non-critical): {e}")
        return ""
    
    def process(self, user_input: str) -> str:
        """
        Main processing pipeline.
        
        1. Understand input (intent, entities, confidence)
        2. Handle based on intent
        3. Update memory & context
        4. Return response
        """
        
        # Update memory with user input
        self.memory.add_interaction('user', user_input)
        
        # Understand the input
        understanding = self.understanding.understand(user_input)
        
        # Log understanding
        if AgentConfig.VERBOSE:
            logger.info(f"Intent: {understanding.intent} (confidence: {understanding.confidence:.2f})")
            if understanding.entities:
                logger.info(f"Entities: {understanding.entities}")
        
        # Check if clarification needed
        if understanding.ambiguous and understanding.clarification_question:
            response = understanding.clarification_question
            emotion_data = None
        else:
            # Route to appropriate handler
            result = self._route_intent(understanding)

            # If handler returned EmotionResponse, separate text + emotion
            if isinstance(result, EmotionResponse):
                response = result.text
                emotion_data = result
            else:
                response = result
                emotion_data = None
        
        # Update context
        self.context.update_from_understanding(understanding)
        
        # Update memory with response
        self.memory.add_interaction('assistant', response)
        
        # Drive avatar with LLM emotion metadata (if available)
        if self.voice.enabled and self._avatar_enabled and self.avatar.is_active:
            emotion_str = emotion_data.emotion if emotion_data and emotion_data.has_emotion else None
            self.avatar.speak_async_with_animation(
                self.voice.speak, response, emotion=emotion_str
            )
        elif self.voice.enabled:
            self.voice.speak_async(response)
        elif self._avatar_enabled and self.avatar.is_active:
            if emotion_data and emotion_data.has_emotion:
                self.avatar.react_to_emotion(
                    emotion_data.emotion,
                    duration=emotion_data.hold_duration,
                    intensity=emotion_data.intensity,
                )
            else:
                # Fallback: keyword detection
                detected = self.avatar.detect_emotion_from_text(response)
                if detected:
                    self.avatar.react_to_emotion(detected, duration=3.0)
        
        return response
    
    def _route_intent(self, understanding) -> str:
        """Route understanding to appropriate handler"""
        
        intent = understanding.intent
        entities = understanding.entities
        
        # Handle different intents
        if intent == 'conversation':
            return self._handle_conversation(understanding.raw_input)
        
        elif intent == 'search_web':
            return self._handle_search_web(entities)
        
        elif intent == 'search_github':
            return self._handle_search_github(entities)
        
        elif intent == 'start_project':
            return self._handle_start_project(entities)
        
        elif intent == 'help_code':
            return self._handle_help_code(entities)
        
        elif intent == 'remember_fact':
            return self._handle_remember_fact(entities)
        
        elif intent == 'recall_info':
            # Pass raw input so handler can detect session queries
            entities['_raw_input'] = understanding.raw_input
            return self._handle_recall_info(entities)
        
        elif intent == 'add_task':
            entities['_raw_input'] = understanding.raw_input
            return self._handle_add_task(entities)
        
        elif intent == 'check_tasks':
            return self._handle_check_tasks(entities)
        
        elif intent == 'complete_task':
            return self._handle_complete_task(entities)
        
        elif intent == 'complete_event':
            return self._handle_complete_event(entities)
        
        elif intent == 'start_research':
            entities['_raw_input'] = understanding.raw_input
            return self._handle_start_research(entities)
        
        elif intent == 'add_research_finding':
            entities['_raw_input'] = understanding.raw_input
            return self._handle_add_research_finding(entities)
        
        elif intent == 'get_research_summary':
            return self._handle_get_research_summary(entities)
        
        elif intent == 'schedule_automation':
            entities['_raw_input'] = understanding.raw_input
            return self._handle_schedule_automation(entities)
        
        elif intent == 'check_automations':
            return self._handle_check_automations(entities)
        
        else:
            # Fallback to conversation
            return self._handle_conversation(understanding.raw_input)
    
    def _handle_conversation(self, user_input: str):
        """Handle general conversation — returns EmotionResponse with emotion metadata."""
        return self.brain.chat_with_emotion(user_input, context_messages=5)
    
    def _handle_search_web(self, entities: dict) -> str:
        """Handle web search (module for tomorrow)"""
        query = entities.get('search_query', entities.get('query', ''))
        
        if not query:
            return "What would you like me to search for?"
        
        # TODO: Implement web search module tomorrow
        return f"🔍 Web search module coming tomorrow!\n\nFor now, I'll help you manually:\nSearch query: {query}\n\nYou can search at: https://duckduckgo.com/?q={query.replace(' ', '+')}"
    
    def _handle_search_github(self, entities: dict) -> str:
        """Handle GitHub search (module for tomorrow)"""
        query = entities.get('search_query', entities.get('query', ''))
        
        if not query:
            return "What kind of projects are you looking for on GitHub?"
        
        # TODO: Implement GitHub search module tomorrow
        return f"🔍 GitHub search module coming tomorrow!\n\nFor now, I'll help you manually:\nSearch query: {query}\n\nYou can search at: https://github.com/search?q={query.replace(' ', '+')}"
    
    def _handle_start_project(self, entities: dict) -> str:
        """Handle project creation (module for tomorrow)"""
        topic = entities.get('topic', '')
        project_type = entities.get('project_type', 'general')
        
        if not topic:
            return "What kind of project would you like to start?"
        
        # Set as current task
        self.context.set_current_task('project', f"Starting project: {topic}", topic)
        
        # TODO: Implement project starter module tomorrow
        return f"🚀 Project starter module coming tomorrow!\n\nFor now, here's what I recommend:\n\nProject: {topic}\nType: {project_type}\n\n1. Create directory: mkdir {topic.lower().replace(' ', '_')}\n2. Setup virtual environment: python -m venv venv\n3. Create README.md and main.py\n\nI'll have the automated version ready tomorrow!"
    
    def _handle_help_code(self, entities: dict) -> str:
        """Handle coding help (module for tomorrow)"""
        task = entities.get('task', entities.get('description', ''))
        file = entities.get('file', '')
        
        if file:
            self.context.add_active_file(file)
        
        if not task:
            return "What do you need help with?"
        
        # Use brain to help
        prompt = f"User needs help with: {task}"
        if file:
            prompt += f"\nFile: {file}"
        
        return self.brain.chat(prompt)
    
    def _handle_remember_fact(self, entities: dict) -> str:
        """Handle fact learning"""
        fact = entities.get('fact', '')
        category = entities.get('category', 'general')
        
        if not fact:
            return "What would you like me to remember?"
        
        # Store in semantic memory
        self.memory.learn_fact(fact, category, confidence=0.9)
        
        return f"✅ Remembered: {fact}"
    
    def _handle_recall_info(self, entities: dict) -> str:
        """Handle information recall - what did we talk about, etc."""
        query = entities.get('query', entities.get('about', entities.get('topic', '')))
        
        # Check for "last time", "last session", "previous" type queries
        raw_query = entities.get('_raw_input', '')
        is_session_query = any(term in raw_query.lower() for term in 
                               ['last time', 'last session', 'yesterday', 'before', 'previous', 'earlier', 'talked about'])
        
        if is_session_query or not query:
            # User is asking about past sessions - get session history
            return self._get_session_recap()
        
        # Search memory for specific topic
        results = self.memory.search_memory(query)
        
        # Format response
        response_parts = []
        
        # Facts
        if results['facts']:
            response_parts.append("💡 **What I remember:**")
            for fact in results['facts'][:3]:
                response_parts.append(f"  • {fact['fact']}")
        
        # Past sessions
        if results['sessions']:
            response_parts.append("\n📅 **Past conversations:**")
            for session in results['sessions'][:2]:
                response_parts.append(f"  • {session.get('summary', 'No summary')}")
        
        if not response_parts:
            return f"I don't have any information about '{query}' yet."
        
        return '\n'.join(response_parts)
    
    def _get_session_recap(self) -> str:
        """Get a recap of recent sessions for 'what did we talk about' queries."""
        sessions = self.memory.episodic.get_recent_sessions(n=5)
        
        if not sessions:
            return "We haven't had any previous conversations that I can recall."
        
        response_parts = ["📅 **Here's what we've discussed recently:**\n"]
        
        for session in reversed(sessions):  # Most recent first
            start_time = session.get('start_time', '')
            if start_time:
                # Parse and format nicely
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_time)
                    time_str = dt.strftime('%b %d at %I:%M %p')
                except:
                    time_str = start_time[:16]
            else:
                time_str = "Unknown time"
            
            # Get first few messages as summary
            messages = session.get('messages', [])
            if messages:
                # Get user messages to summarize what was discussed
                user_msgs = [m['content'][:80] for m in messages if m.get('role') == 'user'][:2]
                topic_hint = '; '.join(user_msgs) if user_msgs else session.get('summary', 'General conversation')
                response_parts.append(f"• **{time_str}**: {topic_hint}")
        
        return '\n'.join(response_parts)
    
    def _check_tasks_on_startup(self):
        """Check for task reminders on startup"""
        try:
            # Check gates (unlock date-based tasks)
            newly_unlocked = self.task_manager.check_gates()
            for task in newly_unlocked:
                print(f"🔓 Task unlocked: {task.title}")
            
            # Check for due reminders
            due_reminders = self.task_manager.get_due_reminders()
            if due_reminders:
                print("\n🔔 **Task Reminders:**")
                for task in due_reminders:
                    print(f"  • {task.title}")
                    self.task_manager.mark_reminder_sent(task.id)
            
            # Check scheduled tasks due today
            due_today = self.task_manager.get_due_today()
            if due_today:
                print("\n📅 **Tasks Due Today:**")
                for task in due_today:
                    print(f"  • {task.title}")
        except Exception as e:
            logger.debug(f"Task check error: {e}")
    
    def _handle_add_task(self, entities: dict) -> str:
        """Handle adding a new task (gated or scheduled)"""
        raw_input = entities.get('_raw_input', '')
        task_desc = entities.get('task', entities.get('description', ''))
        
        # Check for gated task indicators
        gate_condition = entities.get('gate_condition', entities.get('condition', ''))
        gate_type = entities.get('gate_type', 'date')  # Default to date
        target_date = entities.get('target_date', entities.get('deadline', ''))
        scheduled_date = entities.get('scheduled_date', entities.get('date', ''))
        
        # If there's a gate condition, create a gated task
        if gate_condition:
            task = self.task_manager.add_gated_task(
                title=task_desc,
                gate_type=gate_type,
                gate_condition=gate_condition,
                target_date=target_date,
                description=raw_input
            )
            gate_info = f"after {gate_condition}" if gate_type == "date" else f"after '{gate_condition}' event"
            return f"✅ Got it! I'll remind you to **{task.title}** {gate_info}. Reminders will escalate as the deadline approaches."
        
        # If there's a scheduled date, create a scheduled task
        elif scheduled_date:
            task = self.task_manager.add_scheduled_task(
                title=task_desc,
                scheduled_date=scheduled_date,
                description=raw_input
            )
            return f"✅ Scheduled: **{task.title}** for {scheduled_date}. I'll remind you when the day comes!"
        
        # Fallback - not enough info
        else:
            return "I'd love to help track that! Could you tell me:\n• When should I remind you? (e.g., 'after March', 'on October 13th')\n• Or is this after some event? (e.g., 'after exams are done')"
    
    def _handle_check_tasks(self, entities: dict) -> str:
        """Handle checking/listing tasks"""
        return self.task_manager.get_task_summary()
    
    def _handle_complete_task(self, entities: dict) -> str:
        """Handle completing a task"""
        task_name = entities.get('task', entities.get('title', ''))
        
        # Find matching task
        all_tasks = self.task_manager.gated_tasks + self.task_manager.scheduled_tasks
        for task in all_tasks:
            if task_name.lower() in task.title.lower():
                self.task_manager.complete_task(task.id)
                return f"✅ Marked **{task.title}** as complete. Nice work! 🎉"
        
        return f"I couldn't find a task matching '{task_name}'. Try 'tasks' to see your list."
    
    def _handle_complete_event(self, entities: dict) -> str:
        """Handle marking an event as complete (unlocks gated tasks)"""
        event_name = entities.get('event', entities.get('name', ''))
        
        if not event_name:
            return "Which event is complete? (e.g., 'exams are done', 'project finished')"
        
        unlocked = self.task_manager.complete_event(event_name)
        
        if unlocked:
            task_names = [t.title for t in unlocked]
            return f"🔓 Great! The following tasks are now unlocked:\n" + "\n".join(f"  • {name}" for name in task_names)
        else:
            return f"Noted that '{event_name}' is complete! No gated tasks were waiting for this event."
    
    def cleanup(self):
        """Cleanup and save state"""
        logger.info("Shutting down...")
        
        # Disconnect avatar
        if hasattr(self, 'avatar') and self._avatar_enabled:
            self.avatar.disconnect()
        
        # Stop background scheduler
        if hasattr(self, 'automation'):
            self.automation.stop_background_scheduler()
        
        # End current session
        self.memory.episodic.end_session()
        
        # End any active research session
        if hasattr(self, 'research_memory') and self.research_memory.active_session:
            self.research_memory.end_session(summary="Session ended on shutdown")
        
        # Save everything
        self.memory.save()
        self.task_manager._save()
        self.context.save()
        
        logger.info("✅ State saved. Goodbye!")
    
    # -------------------------------------------------------------------------
    # Automation Handlers Setup
    # -------------------------------------------------------------------------
    
    def _setup_automation_handlers(self):
        """Register action handlers for automation tasks."""
        
        def handle_research_automation(task):
            """Handle automated research tasks."""
            topic = task.action_config.get('topic', 'general')
            
            # Start or continue research session
            session = self.research_memory.start_session(topic)
            
            # Log that we performed automated research
            return {
                "session_id": session.id,
                "topic": topic,
                "message": f"Started automated research on {topic}"
            }
        
        def handle_summary_automation(task):
            """Handle summary generation tasks."""
            topic = task.action_config.get('topic', '')
            if topic:
                summary = self.research_memory.generate_topic_summary(topic)
                return {"summary": summary}
            return {"message": "Summary generated"}
        
        def handle_reminder_automation(task):
            """Handle reminder tasks."""
            message = task.action_config.get('message', task.name)
            return {"reminder": message}
        
        self.automation.register_action_handler('research', handle_research_automation)
        self.automation.register_action_handler('summary', handle_summary_automation)
        self.automation.register_action_handler('reminder', handle_reminder_automation)
    
    # -------------------------------------------------------------------------
    # Research Handlers
    # -------------------------------------------------------------------------
    
    def _handle_start_research(self, entities: dict) -> str:
        """Handle starting a research session."""
        topic = entities.get('topic', entities.get('query', ''))
        raw_input = entities.get('_raw_input', '')
        
        if not topic:
            # Try to extract from raw input
            topic = raw_input.replace('research', '').replace('start', '').strip()
        
        if not topic:
            return "What topic would you like to research?"
        
        # Log tool usage
        self.tool_memory.log_tool_use('research', context='start_research')
        
        session = self.research_memory.start_session(topic)
        
        # Check if we have prior research
        history = self.research_memory.get_topic_history(topic)
        if history and history['sessions_count'] > 1:
            return f"📚 Resuming research on **{topic}**!\n\nYou've researched this {history['sessions_count']} times before ({history['total_time_minutes']} minutes total).\n\nSession started. Use 'found: [finding]' to log insights."
        
        return f"📚 Started research session on **{topic}**!\n\nTips:\n- Say 'found: [insight]' to log findings\n- Say 'done researching' to end the session\n- I'll track your queries and findings"
    
    def _handle_add_research_finding(self, entities: dict) -> str:
        """Handle adding a finding to current research."""
        finding = entities.get('finding', entities.get('content', ''))
        raw_input = entities.get('_raw_input', '')
        
        if not finding:
            # Try to extract from raw input patterns like "found: X" or "I found X"
            for prefix in ['found:', 'found that', 'i found', 'discovered:', 'learned:']:
                if prefix in raw_input.lower():
                    finding = raw_input.lower().split(prefix, 1)[-1].strip()
                    break
        
        if not finding:
            return "What did you find? Say 'found: [your finding]'"
        
        if not self.research_memory.active_session:
            return "No active research session. Start one with 'research [topic]' first."
        
        self.research_memory.add_finding(finding)
        
        session = self.research_memory.active_session
        return f"✅ Logged finding for **{session.topic}** ({len(session.findings)} findings so far)"
    
    def _handle_get_research_summary(self, entities: dict) -> str:
        """Handle getting research summary."""
        topic = entities.get('topic', '')
        
        # If no topic specified and we have active session, use that
        if not topic and self.research_memory.active_session:
            topic = self.research_memory.active_session.topic
        
        if not topic:
            # List all topics
            topics = self.research_memory.get_all_topics()
            if not topics:
                return "No research recorded yet. Start with 'research [topic]'."
            
            lines = ["📚 **Your Research Topics:**"]
            for t in topics:
                lines.append(f"  • {t['name']} ({t['sessions']} sessions, {t['time_minutes']} min)")
            lines.append("\nSay 'research summary [topic]' for details.")
            return "\n".join(lines)
        
        summary = self.research_memory.generate_topic_summary(topic)
        return summary
    
    # -------------------------------------------------------------------------
    # Automation Handlers
    # -------------------------------------------------------------------------
    
    def _handle_schedule_automation(self, entities: dict) -> str:
        """Handle scheduling a recurring automation."""
        raw_input = entities.get('_raw_input', '')
        
        # Parse the natural language input
        schedule_params = parse_schedule_from_text(raw_input)
        
        # Try to extract name and action
        name = entities.get('name', '')
        action_type = entities.get('action', 'research')
        topic = entities.get('topic', '')
        
        if not name:
            # Generate name from context
            if 'wednesday' in raw_input.lower():
                name = "Wednesday Task"
            elif 'daily' in raw_input.lower():
                name = "Daily Task"
            else:
                name = "Scheduled Task"
        
        # Check for research-related keywords
        if 'research' in raw_input.lower():
            action_type = 'research'
            # Try to extract topic
            if 'on' in raw_input.lower():
                parts = raw_input.lower().split('on')
                if len(parts) > 1:
                    topic = parts[-1].strip().split()[0] if parts[-1].strip() else ''
        
        # Check for summary/report keywords
        summary_schedule = ""
        if 'summary' in raw_input.lower() or 'report' in raw_input.lower():
            # Generate summary at end time
            hour = int(schedule_params['end_time'].split(':')[0])
            if schedule_params['days_of_week']:
                days = ','.join(schedule_params['days_of_week'])
                summary_schedule = f"0 {hour} * * {days}"
            else:
                summary_schedule = f"0 {hour} * * *"
        
        # Log tool usage
        self.tool_memory.log_tool_use('automation_scheduler', context='schedule_automation')
        
        task_id = self.automation.add_recurring_task(
            name=name,
            action_type=action_type,
            action_config={'topic': topic} if topic else {},
            recurrence_type=schedule_params['recurrence_type'],
            days_of_week=schedule_params['days_of_week'],
            start_time=schedule_params['start_time'],
            end_time=schedule_params['end_time'],
            summary_schedule=summary_schedule,
            description=raw_input
        )
        
        task = self.automation.get_task(task_id)
        schedule_desc = self.automation._describe_schedule(task)
        
        response = f"✅ Scheduled: **{name}**\n\n"
        response += f"📅 Schedule: {schedule_desc}\n"
        response += f"🎯 Action: {action_type}\n"
        if task.next_run:
            response += f"⏰ Next run: {task.next_run[:16].replace('T', ' ')}\n"
        if summary_schedule:
            response += f"📊 Summary will be generated at end of each session\n"
        
        return response
    
    def _handle_check_automations(self, entities: dict) -> str:
        """Handle checking scheduled automations."""
        return self.automation.get_schedule_summary()


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def run_interactive():
    """Run Zeilus in interactive console mode"""
    
    try:
        agent = Zeilus()
        
        while True:
            try:
                # Get user input
                user_input = input(f"\n{AgentConfig.USER_NAME}: ").strip()
                
                if not user_input:
                    continue
                
                # Check for commands
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    print(f"\n{AgentConfig.NAME}: Goodbye! 👋")
                    break
                
                if user_input.lower() == 'help':
                    print(f"\n{AgentConfig.NAME} Commands:")
                    print("  help    - Show this help")
                    print("  stats   - Show memory stats")
                    print("  tasks   - Show all tasks")
                    print("  context - Show current context")
                    print("  avatar  - Toggle VTuber avatar on/off")
                    print("  clear   - Clear conversation (keeps facts)")
                    print("  quit    - Exit")
                    continue
                
                if user_input.lower() == 'tasks':
                    print(f"\n{agent.task_manager.get_task_summary()}")
                    continue
                
                if user_input.lower() == 'stats':
                    print(f"\n📊 Memory Statistics:")
                    print(f"  Working Memory: {len(agent.memory.working.messages)} messages")
                    print(f"  Sessions: {len(agent.memory.episodic.sessions)}")
                    print(f"  Facts Learned: {len(agent.memory.semantic.facts)}")
                    # Conversational memory stats
                    if hasattr(agent.memory, 'conversational') and agent.memory.conversational:
                        stats = agent.memory.conversational.get_stats()
                        print(f"  Conversational Events: {stats['total_events']} (pending: {stats['pending']})")
                    continue
                
                if user_input.lower() == 'context':
                    summary = agent.context.get_summary()
                    print(f"\n📋 Current Context:")
                    print(f"  Task: {summary['current_task'] or 'None'}")
                    print(f"  Active Files: {', '.join(summary['active_files']) or 'None'}")
                    print(f"  Active Projects: {', '.join(summary['active_projects']) or 'None'}")
                    print(f"  Topics: {', '.join(summary['recent_topics']) or 'None'}")
                    continue
                
                if user_input.lower() == 'avatar':
                    if agent._avatar_enabled:
                        agent.avatar.disconnect()
                        agent._avatar_enabled = False
                        print(f"\n{AgentConfig.NAME}: 🎭 Avatar disconnected.")
                    else:
                        print(f"\n{AgentConfig.NAME}: 🎭 Connecting to VTuber Studio...")
                        success = agent.avatar.connect()
                        if success:
                            agent._avatar_enabled = True
                            print(f"{AgentConfig.NAME}: ✅ Avatar connected! It will animate while I speak.")
                        else:
                            print(f"{AgentConfig.NAME}: ❌ Could not connect. Is VTuber Studio running with API enabled (port 8001)?")
                    continue
                
                if user_input.lower() == 'clear':
                    agent.memory.working.clear()
                    agent.context.reset()
                    print(f"\n{AgentConfig.NAME}: Conversation cleared (facts preserved)")
                    continue
                
                # Process normally
                response = agent.process(user_input)
                print(f"\n{AgentConfig.NAME}: {response}")
                
            except KeyboardInterrupt:
                print(f"\n\n{AgentConfig.NAME}: Use 'quit' to exit properly and save state.")
                continue
            
            except Exception as e:
                logger.error(f"Error processing input: {e}", exc_info=True)
                print(f"\n{AgentConfig.NAME}: I encountered an error. Check the log for details.")
        
        # Cleanup
        agent.cleanup()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted. Exiting without saving.")
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point"""
    
    # Check if API key is set
    from config import APIConfig
    
    if not APIConfig.GROQ_API_KEY or APIConfig.GROQ_API_KEY == 'your_groq_api_key_here':
        print("❌ Error: GROQ_API_KEY not set in .env file")
        print("\n1. Get your API key from: https://console.groq.com")
        print("2. Copy .env to .env and add your key")
        print("3. Run again\n")
        sys.exit(1)
    
    # Run interactive mode
    run_interactive()


if __name__ == '__main__':
    main()