# integrations/personalization_engine.py - Personalization Suggestions
"""
Generates personalization suggestions based on analytics.

IMPORTANT: This module ONLY provides suggestions. It never modifies main memory.
The Brain/Agent decides whether to use these suggestions.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PersonalizationEngine:
    """
    Generates personalization suggestions based on user analytics.
    All methods return SUGGESTIONS only - never modifies memory.
    """
    
    def __init__(self, analytics=None, memory=None, conversational_memory=None):
        """
        Args:
            analytics: UserAnalytics instance
            memory: MemorySystem instance
            conversational_memory: ConversationalMemory instance (optional)
        """
        self.analytics = analytics
        self.memory = memory
        self.conversational_memory = conversational_memory
        logger.info("PersonalizationEngine initialized")
    
    def set_dependencies(self, analytics=None, memory=None, conversational_memory=None):
        """Set or update dependencies."""
        if analytics:
            self.analytics = analytics
        if memory:
            self.memory = memory
        if conversational_memory:
            self.conversational_memory = conversational_memory
    
    def suggest_greeting_style(self) -> Dict:
        """
        Suggest a greeting style based on user patterns.
        Returns a suggestion dict, NOT applied automatically.
        """
        suggestion = {
            'greeting': 'Hello!',
            'tone': 'neutral',
            'include_time_reference': False,
            'reasoning': 'Default greeting'
        }
        
        if not self.analytics or not self.memory:
            return suggestion
        
        try:
            times = self.analytics.analyze_conversation_times()
            style = self.analytics.analyze_interaction_style()
            
            # Time-aware greeting
            current_hour = datetime.now().hour
            
            if 5 <= current_hour < 12:
                time_greeting = "Good morning"
            elif 12 <= current_hour < 17:
                time_greeting = "Good afternoon"
            elif 17 <= current_hour < 21:
                time_greeting = "Good evening"
            else:
                time_greeting = "Hey"  # Late night is more casual
            
            # Formality adjustment
            formality = style.get('formality', 'neutral')
            
            if formality == 'casual':
                greetings = {
                    'morning': "Hey! Good morning",
                    'afternoon': "Hey there",
                    'evening': "Hey! How's it going",
                    'night': "Hey, burning the midnight oil?"
                }
                suggestion['greeting'] = greetings.get(times.get('time_preference', 'morning'), "Hey!")
                suggestion['tone'] = 'casual'
            elif formality == 'formal':
                suggestion['greeting'] = f"{time_greeting}. How may I assist you today?"
                suggestion['tone'] = 'formal'
            else:
                suggestion['greeting'] = f"{time_greeting}!"
                suggestion['tone'] = 'friendly'
            
            suggestion['include_time_reference'] = True
            suggestion['reasoning'] = f"Based on {formality} interaction style and {times.get('time_preference', 'neutral')} preference"
            
        except Exception as e:
            logger.error(f"Error generating greeting suggestion: {e}")
        
        return suggestion
    
    def suggest_response_tone(self) -> Dict:
        """
        Suggest response tone based on user's interaction patterns.
        """
        suggestion = {
            'verbosity': 'moderate',
            'formality': 'neutral',
            'use_emojis': False,
            'technical_level': 'moderate',
            'reasoning': 'Default tone'
        }
        
        if not self.analytics:
            return suggestion
        
        try:
            style = self.analytics.analyze_interaction_style()
            topics = self.analytics.analyze_topic_preferences()
            
            # Verbosity based on message length preference
            length_pref = style.get('length_preference', 'moderate')
            if length_pref == 'concise':
                suggestion['verbosity'] = 'brief'
            elif length_pref == 'detailed':
                suggestion['verbosity'] = 'comprehensive'
            else:
                suggestion['verbosity'] = 'balanced'
            
            # Formality
            suggestion['formality'] = style.get('formality', 'neutral')
            
            # Emoji usage (casual users might appreciate them)
            suggestion['use_emojis'] = style.get('formality') == 'casual'
            
            # Technical level based on topics
            primary_topic = topics.get('primary_interest', 'general')
            if primary_topic in ['coding', 'technology', 'projects']:
                suggestion['technical_level'] = 'high'
            elif primary_topic in ['learning', 'personal']:
                suggestion['technical_level'] = 'moderate'
            else:
                suggestion['technical_level'] = 'accessible'
            
            suggestion['reasoning'] = f"User prefers {length_pref} messages with {style.get('formality', 'neutral')} tone"
            
        except Exception as e:
            logger.error(f"Error generating tone suggestion: {e}")
        
        return suggestion
    
    def suggest_topics_of_interest(self) -> List[Dict]:
        """
        Suggest topics the user might want updates on.
        """
        suggestions = []
        
        if not self.analytics:
            return suggestions
        
        try:
            topics = self.analytics.analyze_topic_preferences()
            
            top_topics = topics.get('top_topics', [])
            
            topic_suggestions = {
                'coding': {
                    'suggestion': 'Share coding tips or new programming resources',
                    'prompt': 'Would you like to hear about any new coding techniques?'
                },
                'learning': {
                    'suggestion': 'Recommend learning resources',
                    'prompt': 'I found some interesting learning resources you might like.'
                },
                'career': {
                    'suggestion': 'Share career development tips',
                    'prompt': 'Any updates on your career goals I should know about?'
                },
                'technology': {
                    'suggestion': 'Share tech news relevant to interests',
                    'prompt': 'Would you like updates on technology topics you\'re interested in?'
                },
                'projects': {
                    'suggestion': 'Check in on project progress',
                    'prompt': 'How are your projects coming along?'
                },
                'productivity': {
                    'suggestion': 'Offer productivity tips',
                    'prompt': 'Would you like some productivity suggestions?'
                }
            }
            
            for topic, count in top_topics[:3]:
                if topic in topic_suggestions:
                    suggestions.append({
                        'topic': topic,
                        'mention_count': count,
                        **topic_suggestions[topic]
                    })
            
        except Exception as e:
            logger.error(f"Error generating topic suggestions: {e}")
        
        return suggestions
    
    def suggest_facts_to_learn(self) -> List[Dict]:
        """
        Suggest facts that could be added to user profile.
        These are SUGGESTIONS - agent should confirm with user before storing.
        """
        suggestions = []
        
        if not self.analytics or not self.memory:
            return suggestions
        
        try:
            topics = self.analytics.analyze_topic_preferences()
            style = self.analytics.analyze_interaction_style()
            times = self.analytics.analyze_conversation_times()
            
            current_profile = self.memory.semantic.get_user_profile()
            current_interests = current_profile.get('interests', [])
            
            # Suggest interests based on topic preferences
            primary_interest = topics.get('primary_interest')
            if primary_interest and primary_interest not in current_interests:
                suggestions.append({
                    'type': 'interest',
                    'value': primary_interest,
                    'confidence': 0.8,
                    'source': 'topic_analysis',
                    'prompt': f"It seems like you're interested in {primary_interest}. Should I remember that?"
                })
            
            # Suggest communication preferences
            if style.get('formality') and style.get('formality') != 'neutral':
                suggestions.append({
                    'type': 'preference',
                    'key': 'communication_style',
                    'value': style['formality'],
                    'confidence': 0.7,
                    'source': 'interaction_analysis',
                    'prompt': f"I notice you prefer {style['formality']} communication. Should I adjust my responses?"
                })
            
            # Suggest active time preference
            time_pref = times.get('time_preference')
            if time_pref:
                suggestions.append({
                    'type': 'preference',
                    'key': 'active_time',
                    'value': time_pref,
                    'confidence': 0.6,
                    'source': 'time_analysis',
                    'prompt': f"You seem most active in the {time_pref}. Good to know!"
                })
            
        except Exception as e:
            logger.error(f"Error generating fact suggestions: {e}")
        
        return suggestions
    
    def get_personalization_context(self) -> str:
        """
        Generate a context string for the Brain's system prompt.
        This provides personalization hints to the LLM.
        """
        context_parts = []
        
        try:
            # Greeting suggestion
            greeting = self.suggest_greeting_style()
            if greeting.get('tone') != 'neutral':
                context_parts.append(f"User prefers {greeting['tone']} communication style.")
            
            # Response tone
            tone = self.suggest_response_tone()
            context_parts.append(f"Recommended response verbosity: {tone.get('verbosity', 'moderate')}.")
            if tone.get('technical_level') == 'high':
                context_parts.append("User is comfortable with technical content.")
            
            # Topics of interest
            topics = self.suggest_topics_of_interest()
            if topics:
                topic_names = [t['topic'] for t in topics[:3]]
                context_parts.append(f"User frequently discusses: {', '.join(topic_names)}.")
            
            # Conversational memory - pending follow-ups
            if self.conversational_memory:
                conv_context = self.conversational_memory.get_context_for_prompt()
                if conv_context:
                    context_parts.append("")
                    context_parts.append(conv_context)
            
        except Exception as e:
            logger.error(f"Error generating personalization context: {e}")
        
        if not context_parts:
            return ""
        
        return "## Personalization Hints\n" + "\n".join(context_parts)
    
    def get_session_start_message(self) -> Optional[str]:
        """
        Generate a message for session start, including follow-ups.
        Returns None if nothing special to say.
        """
        parts = []
        
        # Check for pending follow-ups from conversational memory
        if self.conversational_memory:
            followup = self.conversational_memory.generate_followup_prompt()
            if followup:
                parts.append(followup)
        
        # Add a personalized greeting touch
        if not parts:
            try:
                greeting = self.suggest_greeting_style()
                # Only add if we have good analytics data
                if greeting.get('tone') != 'neutral':
                    return None  # Let normal greeting handle it
            except:
                pass
        
        return " ".join(parts) if parts else None
    
    def get_all_suggestions(self) -> Dict:
        """Get all personalization suggestions as a dictionary."""
        return {
            'greeting_style': self.suggest_greeting_style(),
            'response_tone': self.suggest_response_tone(),
            'topics_of_interest': self.suggest_topics_of_interest(),
            'facts_to_learn': self.suggest_facts_to_learn(),
            'personalization_context': self.get_personalization_context()
        }
