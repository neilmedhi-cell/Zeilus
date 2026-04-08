# integrations/user_analytics.py - User Behavior Analytics
"""
Analyzes conversation patterns and user behavior to understand preferences.

IMPORTANT: This module only READS from memory. It never modifies main memory.
All insights are suggestions only.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)


class UserAnalytics:
    """
    Analyzes user conversation patterns and behavior.
    Read-only access to memory - never modifies anything.
    """
    
    def __init__(self, memory_system=None):
        """
        Args:
            memory_system: MemorySystem instance to analyze (optional, can set later)
        """
        self.memory = memory_system
        logger.info("UserAnalytics initialized")
    
    def set_memory(self, memory_system):
        """Set or update the memory system to analyze."""
        self.memory = memory_system
    
    def analyze_conversation_times(self) -> Dict:
        """
        Analyze when the user typically has conversations.
        Returns hourly and daily distribution.
        """
        if not self.memory:
            return {'error': 'No memory system connected'}
        
        hourly_counts = Counter()
        daily_counts = Counter()
        
        # Analyze episodic sessions
        for session in self.memory.episodic.sessions:
            try:
                start_time = datetime.fromisoformat(session.get('start_time', ''))
                hourly_counts[start_time.hour] += 1
                daily_counts[start_time.strftime('%A')] += 1
            except (ValueError, KeyError):
                continue
        
        # Find peak hours
        peak_hours = hourly_counts.most_common(3)
        peak_days = daily_counts.most_common(3)
        
        # Categorize time preference
        morning_hours = sum(hourly_counts.get(h, 0) for h in range(5, 12))
        afternoon_hours = sum(hourly_counts.get(h, 0) for h in range(12, 17))
        evening_hours = sum(hourly_counts.get(h, 0) for h in range(17, 22))
        night_hours = sum(hourly_counts.get(h, 0) for h in list(range(22, 24)) + list(range(0, 5)))
        
        time_preference = max([
            ('morning', morning_hours),
            ('afternoon', afternoon_hours),
            ('evening', evening_hours),
            ('night', night_hours)
        ], key=lambda x: x[1])[0]
        
        return {
            'hourly_distribution': dict(hourly_counts),
            'daily_distribution': dict(daily_counts),
            'peak_hours': peak_hours,
            'peak_days': peak_days,
            'time_preference': time_preference,
            'total_sessions': len(self.memory.episodic.sessions)
        }
    
    def analyze_topic_preferences(self) -> Dict:
        """
        Analyze what topics the user frequently discusses.
        """
        if not self.memory:
            return {'error': 'No memory system connected'}
        
        topic_counts = Counter()
        keyword_counts = Counter()
        
        # Keywords to look for (expandable)
        topic_keywords = {
            'coding': ['code', 'programming', 'python', 'javascript', 'debug', 'error', 'function'],
            'learning': ['learn', 'study', 'course', 'tutorial', 'understand', 'explain'],
            'career': ['job', 'interview', 'resume', 'career', 'work', 'salary'],
            'projects': ['project', 'build', 'create', 'develop', 'implement'],
            'technology': ['tech', 'ai', 'machine learning', 'chip', 'hardware', 'software'],
            'personal': ['feel', 'thinking', 'life', 'help', 'advice'],
            'productivity': ['task', 'schedule', 'organize', 'plan', 'deadline'],
        }
        
        # Analyze working memory messages
        for msg in self.memory.working.messages:
            if msg.get('role') == 'user':
                content_lower = msg.get('content', '').lower()
                
                for topic, keywords in topic_keywords.items():
                    for keyword in keywords:
                        if keyword in content_lower:
                            topic_counts[topic] += 1
                            keyword_counts[keyword] += 1
        
        # Analyze episodic sessions
        for session in self.memory.episodic.sessions:
            for msg in session.get('messages', []):
                if msg.get('role') == 'user':
                    content_lower = msg.get('content', '').lower()
                    
                    for topic, keywords in topic_keywords.items():
                        for keyword in keywords:
                            if keyword in content_lower:
                                topic_counts[topic] += 1
                                keyword_counts[keyword] += 1
        
        return {
            'topic_distribution': dict(topic_counts),
            'top_topics': topic_counts.most_common(5),
            'top_keywords': keyword_counts.most_common(10),
            'primary_interest': topic_counts.most_common(1)[0][0] if topic_counts else 'general'
        }
    
    def analyze_interaction_style(self) -> Dict:
        """
        Analyze how the user interacts - message length, formality, etc.
        """
        if not self.memory:
            return {'error': 'No memory system connected'}
        
        message_lengths = []
        question_count = 0
        command_count = 0
        casual_count = 0
        formal_count = 0
        total_messages = 0
        
        # Casual indicators
        casual_patterns = ['hey', 'hi', 'yo', 'lol', 'haha', 'cool', 'yeah', 'yep', 'nope', 'bro']
        # Formal indicators
        formal_patterns = ['please', 'could you', 'would you', 'kindly', 'i would like']
        
        all_messages = list(self.memory.working.messages)
        for session in self.memory.episodic.sessions:
            all_messages.extend(session.get('messages', []))
        
        for msg in all_messages:
            if msg.get('role') != 'user':
                continue
            
            content = msg.get('content', '')
            content_lower = content.lower()
            total_messages += 1
            
            # Length
            message_lengths.append(len(content.split()))
            
            # Question vs command
            if '?' in content:
                question_count += 1
            elif content_lower.startswith(('do ', 'make ', 'create ', 'show ', 'find ', 'search ')):
                command_count += 1
            
            # Casual vs formal
            if any(p in content_lower for p in casual_patterns):
                casual_count += 1
            if any(p in content_lower for p in formal_patterns):
                formal_count += 1
        
        avg_length = sum(message_lengths) / len(message_lengths) if message_lengths else 0
        
        # Determine preferences
        length_preference = 'concise' if avg_length < 10 else 'moderate' if avg_length < 25 else 'detailed'
        formality = 'casual' if casual_count > formal_count else 'formal' if formal_count > casual_count else 'neutral'
        interaction_type = 'questions' if question_count > command_count else 'commands' if command_count > question_count else 'mixed'
        
        return {
            'average_message_length': round(avg_length, 1),
            'length_preference': length_preference,
            'formality': formality,
            'interaction_type': interaction_type,
            'question_ratio': round(question_count / max(total_messages, 1), 2),
            'total_messages_analyzed': total_messages
        }
    
    def analyze_session_patterns(self) -> Dict:
        """
        Analyze session behavior - duration, frequency, etc.
        """
        if not self.memory:
            return {'error': 'No memory system connected'}
        
        session_durations = []
        messages_per_session = []
        session_gaps = []
        
        sessions = self.memory.episodic.sessions
        
        for i, session in enumerate(sessions):
            try:
                start = datetime.fromisoformat(session.get('start_time', ''))
                end = datetime.fromisoformat(session.get('end_time', '')) if session.get('end_time') else start
                
                duration = (end - start).total_seconds() / 60  # in minutes
                session_durations.append(duration)
                messages_per_session.append(len(session.get('messages', [])))
                
                # Gap between sessions
                if i > 0:
                    prev_end = datetime.fromisoformat(sessions[i-1].get('end_time', sessions[i-1].get('start_time', '')))
                    gap = (start - prev_end).total_seconds() / 3600  # in hours
                    if gap > 0 and gap < 720:  # Ignore gaps > 30 days
                        session_gaps.append(gap)
                        
            except (ValueError, KeyError):
                continue
        
        avg_duration = sum(session_durations) / len(session_durations) if session_durations else 0
        avg_messages = sum(messages_per_session) / len(messages_per_session) if messages_per_session else 0
        avg_gap = sum(session_gaps) / len(session_gaps) if session_gaps else 0
        
        return {
            'average_session_duration_minutes': round(avg_duration, 1),
            'average_messages_per_session': round(avg_messages, 1),
            'average_hours_between_sessions': round(avg_gap, 1),
            'total_sessions': len(sessions),
            'session_type': 'quick' if avg_duration < 5 else 'moderate' if avg_duration < 15 else 'extended'
        }
    
    def generate_insights_report(self) -> str:
        """
        Generate a comprehensive insights report.
        """
        if not self.memory:
            return "No memory system connected for analysis."
        
        times = self.analyze_conversation_times()
        topics = self.analyze_topic_preferences()
        style = self.analyze_interaction_style()
        sessions = self.analyze_session_patterns()
        
        report = []
        report.append("=" * 50)
        report.append("USER ANALYTICS INSIGHTS REPORT")
        report.append("=" * 50)
        report.append("")
        
        # Time patterns
        report.append("📅 CONVERSATION TIMING")
        report.append(f"  • Preferred time: {times.get('time_preference', 'unknown')}")
        report.append(f"  • Total sessions analyzed: {times.get('total_sessions', 0)}")
        if times.get('peak_hours'):
            hours = [f"{h[0]}:00" for h in times['peak_hours'][:3]]
            report.append(f"  • Peak hours: {', '.join(hours)}")
        report.append("")
        
        # Topic preferences
        report.append("🎯 TOPIC PREFERENCES")
        report.append(f"  • Primary interest: {topics.get('primary_interest', 'general')}")
        if topics.get('top_topics'):
            for topic, count in topics['top_topics'][:3]:
                report.append(f"  • {topic}: {count} mentions")
        report.append("")
        
        # Interaction style
        report.append("💬 INTERACTION STYLE")
        report.append(f"  • Formality: {style.get('formality', 'neutral')}")
        report.append(f"  • Message length: {style.get('length_preference', 'moderate')}")
        report.append(f"  • Interaction type: {style.get('interaction_type', 'mixed')}")
        report.append(f"  • Average message: {style.get('average_message_length', 0)} words")
        report.append("")
        
        # Session patterns
        report.append("📊 SESSION PATTERNS")
        report.append(f"  • Session type: {sessions.get('session_type', 'moderate')}")
        report.append(f"  • Avg duration: {sessions.get('average_session_duration_minutes', 0)} min")
        report.append(f"  • Avg messages/session: {sessions.get('average_messages_per_session', 0)}")
        report.append("")
        
        report.append("=" * 50)
        
        return "\n".join(report)
    
    def get_all_insights(self) -> Dict:
        """Get all analytics as a dictionary."""
        return {
            'conversation_times': self.analyze_conversation_times(),
            'topic_preferences': self.analyze_topic_preferences(),
            'interaction_style': self.analyze_interaction_style(),
            'session_patterns': self.analyze_session_patterns()
        }
