# core/brain.py - Groq Client (The "Thinking" Module)
"""
Clean wrapper around Groq API.
Handles context management, token limits, rate limiting.
"""

import json
import re
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from groq import Groq
import tiktoken

from config import APIConfig, AgentConfig

logger = logging.getLogger(__name__)


# =============================================================================
# EMOTION RESPONSE
# =============================================================================

@dataclass
class EmotionResponse:
    """LLM response with structured emotion metadata."""
    text: str
    emotion: str = "neutral"
    intensity: float = 0.5
    valence: float = 0.5     # -1 negative .. +1 positive
    arousal: float = 0.3     # 0 calm .. 1 energetic

    @property
    def has_emotion(self) -> bool:
        return self.emotion != "neutral" and self.intensity > 0.2

    @property
    def hold_duration(self) -> float:
        """How long the avatar should hold this expression (seconds)."""
        return 2.0 + (self.intensity * 4.0)  # 2s–6s based on intensity


# =============================================================================
# BRAIN - Groq-powered reasoning
# =============================================================================

class Brain:
    """
    The "thinking" part of Zeilus.
    Uses Groq for natural language understanding and generation.
    """
    
    def __init__(self, memory, context_bridge=None):
        """
        Args:
            memory: MemorySystem instance for context
            context_bridge: Optional ContextBridge for unified context (recommended)
        """
        self.client = Groq(api_key=APIConfig.GROQ_API_KEY)
        self.model = APIConfig.GROQ_MODEL
        self.memory = memory
        self.context_bridge = context_bridge  # NEW: Unified context source
        
        # Rate limiting
        self.request_times: List[float] = []
        
        # Token counting (approximate)
        try:
            self.encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
        except:
            self.encoder = tiktoken.get_encoding("cl100k_base")
        
        logger.info(f"Brain initialized with model: {self.model}")
        if context_bridge:
            logger.info("ContextBridge connected - full context injection enabled")
    
    def generate(self, prompt: str, temperature: float = APIConfig.TEMP_CONVERSATION,
                 max_tokens: int = APIConfig.MAX_RESPONSE_TOKENS,
                 system_prompt: Optional[str] = None) -> str:
        """
        Generate response from Groq.
        
        Args:
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Max tokens in response
            system_prompt: Optional system prompt override
        
        Returns:
            Generated text
        """
        
        # Rate limiting
        self._rate_limit()
        
        # Build messages
        messages = []
        
        # System prompt
        if system_prompt is None:
            system_prompt = self._build_system_prompt()
        
        messages.append({
            'role': 'system',
            'content': system_prompt
        })
        
        messages.append({
            'role': 'user',
            'content': prompt
        })
        
        # Check token count
        total_tokens = self._count_tokens_messages(messages)
        
        if total_tokens > APIConfig.MAX_CONTEXT_TOKENS:
            logger.warning(f"Token count ({total_tokens}) exceeds limit, truncating context")
            # Truncate system prompt if needed
            system_prompt = self._truncate_system_prompt(system_prompt, prompt)
            messages[0]['content'] = system_prompt
        
        # Make API call
        try:
            logger.debug(f"Generating with temp={temperature}, max_tokens={max_tokens}")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=APIConfig.REQUEST_TIMEOUT
            )
            
            result = response.choices[0].message.content
            
            # Log usage
            usage = response.usage
            logger.info(f"Generated {usage.completion_tokens} tokens (total: {usage.total_tokens})")
            
            return result
            
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return f"I apologize, I encountered an error: {str(e)}"
    
    def chat(self, user_message: str, context_messages: int = 20) -> str:
        """
        Conversational response with memory context.
        
        Args:
            user_message: User's message
            context_messages: How many previous messages to include
        
        Returns:
            Response text (emotion tags stripped)
        """
        result = self.chat_with_emotion(user_message, context_messages)
        return result.text

    def chat_with_emotion(self, user_message: str, context_messages: int = 20) -> EmotionResponse:
        """
        Conversational response with structured emotion metadata.
        
        Args:
            user_message: User's message
            context_messages: How many previous messages to include
        
        Returns:
            EmotionResponse with .text and emotion fields
        """
        # Get conversation context
        if self.context_bridge:
            context = self.context_bridge.get_conversation_context()
        else:
            context = self.memory.get_context(n_messages=context_messages)
        
        prompt = f"""Recent conversation:
{context}

User: {user_message}

Zeilus:"""
        
        raw = self.generate(prompt, temperature=APIConfig.TEMP_CONVERSATION)
        return self._parse_emotion_tag(raw)

    @staticmethod
    def _parse_emotion_tag(raw_response: str) -> EmotionResponse:
        """
        Parse <EMOTION>{...}</EMOTION> tag from LLM output.
        
        Returns EmotionResponse; defaults to neutral if tag is missing or malformed.
        """
        pattern = r'<EMOTION>\s*(\{.*?\})\s*</EMOTION>'
        match = re.search(pattern, raw_response, re.DOTALL)
        
        # Strip the tag from the text regardless
        clean_text = re.sub(pattern, '', raw_response, flags=re.DOTALL).strip()
        
        if not match:
            return EmotionResponse(text=clean_text)
        
        try:
            data = json.loads(match.group(1))
            return EmotionResponse(
                text=clean_text,
                emotion=str(data.get('emotion', 'neutral')).lower(),
                intensity=float(data.get('intensity', 0.5)),
                valence=float(data.get('valence', 0.5)),
                arousal=float(data.get('arousal', 0.3)),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse emotion tag: {e}")
            return EmotionResponse(text=clean_text)
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with agent identity and full context"""
        
        # Get rich context from ContextBridge if available
        if self.context_bridge:
            context_block = self.context_bridge.get_system_prompt_context()
        else:
            # Fallback to basic user profile only
            user_profile = self.memory.get_user_profile()
            context_block = f"""## User Profile
- Name: {user_profile.get('name', 'User')}
- Interests: {', '.join(user_profile.get('interests', ['coding', 'learning']))}
- Active projects: {', '.join(user_profile.get('active_projects', []))}"""
        
        # Add conversational memory context (pending follow-ups)
        conversational_context = ""
        if hasattr(self.memory, 'conversational') and self.memory.conversational:
            try:
                conv_ctx = self.memory.conversational.get_context_for_prompt()
                if conv_ctx:
                    conversational_context = f"\n\n{conv_ctx}"
            except Exception as e:
                pass  # Non-critical, skip if unavailable
        
        # Add personalization context if available
        personalization_context = ""
        try:
            from integrations.personalization_engine import PersonalizationEngine
            from integrations.user_analytics import UserAnalytics
            
            analytics = UserAnalytics(self.memory)
            engine = PersonalizationEngine(
                analytics=analytics, 
                memory=self.memory,
                conversational_memory=getattr(self.memory, 'conversational', None)
            )
            pers_ctx = engine.get_personalization_context()
            if pers_ctx:
                personalization_context = f"\n\n{pers_ctx}"
        except ImportError:
            pass  # Optional, skip if not available
        except Exception as e:
            pass  # Non-critical, skip on error
        
        system_prompt = f"""You are Zeilus, a highly capable productivity assistant with excellent memory.

# Your Capabilities
- Remember ALL context from our conversation
- Track active files, projects, and tasks
- Recall facts learned about the user
- Understand references like "it", "that project", "the file"
- Follow up on things the user mentioned (interviews, trips, meetings)
- Provide clear, actionable responses

# Current Context
{context_block}{conversational_context}{personalization_context}

# Emotion Metadata
At the END of every response, append an emotion tag that describes HOW you feel about what you just said. Use this exact format:
<EMOTION>{{"emotion": "<name>", "intensity": <0.0-1.0>, "valence": <-1.0 to 1.0>, "arousal": <0.0-1.0>}}</EMOTION>

Emotion names: neutral, happy, excited, sad, surprised, angry, thinking, confused, proud, embarrassed, wink
- intensity: how strongly you feel it (0.1 = subtle, 0.9 = very strong)
- valence: negative (-1) to positive (+1)
- arousal: calm (0) to energetic (1)

Pick the emotion that matches YOUR tone — not the user's mood. Be expressive!
Examples:
- Delivering great news → {{"emotion": "excited", "intensity": 0.8, "valence": 0.9, "arousal": 0.7}}
- Apologizing for an error → {{"emotion": "sad", "intensity": 0.6, "valence": -0.4, "arousal": 0.2}}
- Explaining something complex → {{"emotion": "thinking", "intensity": 0.5, "valence": 0.3, "arousal": 0.4}}
- Casual chat → {{"emotion": "happy", "intensity": 0.4, "valence": 0.5, "arousal": 0.3}}

# Guidelines
- Be concise but thorough
- Reference the current context when relevant
- Use specific names (files, projects) when you know them
- If you see pending follow-ups, ask about them naturally in conversation
- Admit when you don't know something
- Default to action over discussion

Current date: {time.strftime('%Y-%m-%d %H:%M')}"""
        
        return system_prompt
    
    def _truncate_system_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Truncate system prompt to fit token limit"""
        
        # Calculate tokens available for system prompt
        user_tokens = self._count_tokens(user_prompt)
        available_tokens = APIConfig.MAX_CONTEXT_TOKENS - user_tokens - APIConfig.MAX_RESPONSE_TOKENS
        
        # Truncate system prompt
        system_tokens = self._count_tokens(system_prompt)
        
        if system_tokens > available_tokens:
            # Simple truncation (could be smarter)
            ratio = available_tokens / system_tokens
            truncate_to = int(len(system_prompt) * ratio)
            return system_prompt[:truncate_to] + "\n\n[Context truncated to fit token limit]"
        
        return system_prompt
    
    def _rate_limit(self):
        """Implement rate limiting to stay under Groq limits"""
        
        current_time = time.time()
        
        # Remove requests older than 1 minute
        self.request_times = [t for t in self.request_times if current_time - t < 60]
        
        # Check if we're at limit
        if len(self.request_times) >= APIConfig.MAX_REQUESTS_PER_MINUTE:
            # Calculate wait time
            oldest_request = min(self.request_times)
            wait_time = 60 - (current_time - oldest_request) + 1
            
            if wait_time > 0:
                logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
        
        # Record this request
        self.request_times.append(current_time)
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text (approximate)"""
        try:
            return len(self.encoder.encode(text))
        except:
            # Fallback: rough estimate
            return len(text) // 4
    
    def _count_tokens_messages(self, messages: List[Dict]) -> int:
        """Count tokens in message list"""
        total = 0
        for msg in messages:
            total += self._count_tokens(msg['content'])
            total += 4  # Message formatting overhead
        
        return total
    
    def quick_classify(self, text: str, categories: List[str]) -> str:
        """
        Quick classification into one of the given categories.
        Optimized for speed.
        
        Args:
            text: Text to classify
            categories: List of category names
        
        Returns:
            Category name
        """
        
        prompt = f"""Classify this into ONE category: {', '.join(categories)}

Text: "{text}"

Respond with ONLY the category name:"""
        
        result = self.generate(
            prompt,
            temperature=APIConfig.TEMP_CLASSIFICATION,
            max_tokens=20
        )
        
        return result.strip().lower()
    
    def extract_info(self, text: str, info_type: str) -> str:
        """
        Extract specific information from text.
        
        Args:
            text: Text to extract from
            info_type: What to extract (e.g., "file names", "topic", "person names")
        
        Returns:
            Extracted information
        """
        
        prompt = f"""Extract {info_type} from this text.

Text: "{text}"

Respond with ONLY the extracted information (or "none" if nothing found):"""
        
        result = self.generate(
            prompt,
            temperature=APIConfig.TEMP_CLASSIFICATION,
            max_tokens=100
        )
        
        return result.strip()
    
    def summarize(self, text: str, max_length: int = 100) -> str:
        """
        Summarize text.
        
        Args:
            text: Text to summarize
            max_length: Max length in words
        
        Returns:
            Summary
        """
        
        prompt = f"""Summarize this in {max_length} words or less:

{text}

Summary:"""
        
        result = self.generate(
            prompt,
            temperature=APIConfig.TEMP_CONVERSATION,
            max_tokens=max_length * 2  # Tokens ≈ 0.75 * words
        )
        
        return result.strip()
    
    def expand_abbreviation(self, abbrev: str, context: str = "") -> str:
        """
        Expand abbreviation based on context.
        
        Args:
            abbrev: Abbreviation to expand
            context: Context to help with expansion
        
        Returns:
            Expanded form
        """
        
        prompt = f"""What does "{abbrev}" stand for?

Context: {context if context else 'General'}

Respond with ONLY the expansion:"""
        
        result = self.generate(
            prompt,
            temperature=APIConfig.TEMP_CLASSIFICATION,
            max_tokens=50
        )
        
        return result.strip()