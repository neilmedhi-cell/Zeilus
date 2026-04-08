# core/understanding.py - Natural Language Understanding
"""
Solves the "because" ≠ "use" problem.
No regex hell - uses Groq for ALL understanding.
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from config import UnderstandingConfig

logger = logging.getLogger(__name__)


# =============================================================================
# UNDERSTANDING RESULT
# =============================================================================

@dataclass
class Understanding:
    """Result of understanding user input"""
    
    # Core understanding
    intent: str  # What user wants to do
    entities: Dict[str, any]  # Extracted entities
    confidence: float  # How confident (0-1)
    
    # Context tracking
    needs_context: bool  # Does this need context resolution?
    references: List[str]  # Pronouns/references found ("it", "that")
    
    # Clarification
    ambiguous: bool  # Is this ambiguous?
    clarification_question: Optional[str]  # Question to ask user
    
    # Raw data
    raw_input: str
    
    def __str__(self) -> str:
        return f"Intent: {self.intent} (confidence: {self.confidence:.2f})"


# =============================================================================
# UNDERSTANDING ENGINE
# =============================================================================

class UnderstandingEngine:
    """
    Enhanced NLU engine with single-call understanding.
    Handles intent classification, entity extraction, context resolution in ONE call.
    """
    
    def __init__(self, brain, memory, context_bridge=None):
        """
        Args:
            brain: Brain instance (Groq client)
            memory: MemorySystem instance
            context_bridge: Optional ContextBridge for dialog state
        """
        self.brain = brain
        self.memory = memory
        self.context_bridge = context_bridge
        
        # Common pronouns/references that need resolution
        self.reference_words = {
            'it', 'that', 'this', 'these', 'those',
            'them', 'its', 'the project', 'the file',
            'the code', 'the app', 'the agent'
        }
        
        # Expanded intent taxonomy
        self.intent_categories = [
            'conversation',      # General chat, questions, explanations
            'search_web',        # Search the internet
            'search_github',     # Search GitHub for projects/code
            'start_project',     # Start a new project/learn something
            'help_code',         # Help with code (implementation, debugging)
            'remember_fact',     # User stating something to remember
            'recall_info',       # User asking about past conversations
            'system_control',    # Control system (volume, brightness, etc)
            'file_operation',    # File/folder operations
            'add_task',          # User wants to add/schedule a task or reminder
            'check_tasks',       # User asking about their tasks/to-do list
            'complete_task',     # User marking a task as done
            'complete_event',    # User saying an event is done (unlocks gated tasks)
            'clarification',     # User is clarifying something
            'continuation',      # User wants to continue previous work
        ]
        
        logger.info("Enhanced NLU engine initialized")
    
    def understand(self, user_input: str) -> Understanding:
        """
        Single-call understanding pipeline.
        Combines intent + entities + reference resolution into ONE LLM call.
        """
        
        logger.info(f"Understanding: '{user_input[:60]}...'")
        
        # Step 1: Detect references locally (fast, no LLM)
        references = self._detect_references(user_input)
        needs_context = len(references) > 0
        
        # Step 2: Get conversation context
        if self.context_bridge:
            context = self.context_bridge.get_conversation_context()
            dialog_state = self.context_bridge.dialog_state
        else:
            context = self.memory.get_context(n_messages=10)
            dialog_state = {}
        
        # Step 3: Single unified understanding call
        understanding_result = self._unified_understand(user_input, context, dialog_state)
        
        # Step 4: Update dialog state if we have context bridge
        if self.context_bridge and understanding_result.get('entities'):
            self.context_bridge.update_dialog_state(
                understanding_result.get('intent', 'conversation'),
                understanding_result.get('entities', {})
            )
        
        # Step 5: Check confidence and ambiguity
        confidence = understanding_result.get('confidence', 0.5)
        ambiguous = confidence < UnderstandingConfig.MIN_CONFIDENCE
        
        clarification = None
        if ambiguous and UnderstandingConfig.ASK_FOR_CLARIFICATION:
            clarification = understanding_result.get('clarification_question')
            if not clarification:
                clarification = self._generate_clarification(user_input, understanding_result)
        
        # Build result
        understanding = Understanding(
            intent=understanding_result.get('intent', 'conversation'),
            entities=understanding_result.get('entities', {}),
            confidence=confidence,
            needs_context=needs_context,
            references=references,
            ambiguous=ambiguous,
            clarification_question=clarification,
            raw_input=user_input
        )
        
        logger.info(f"Understood: {understanding}")
        
        return understanding
    
    def _unified_understand(self, user_input: str, context: str, dialog_state: Dict) -> Dict:
        """
        Single LLM call to understand input completely.
        Extracts: intent, sub_intent, entities, resolved_references, confidence.
        """
        import re
        
        # Build slot context from dialog state
        slot_context = ""
        if dialog_state.get('slots'):
            slot_context = "\nActive references from conversation:\n"
            for slot, value in dialog_state['slots'].items():
                slot_context += f"- \"{slot}\" refers to: {value}\n"
        
        # Simplified prompt with clean JSON template (no comments!)
        prompt = f"""You are an NLU system for Zeilus, a productivity assistant.

Recent conversation:
{context}
{slot_context}
Current user input: "{user_input}"

Analyze this input and respond with ONLY valid JSON (no markdown, no explanation):

{{"intent": "conversation", "confidence": 0.9, "entities": {{}}, "sub_intent": null}}

Valid intents:
- conversation: General chat, questions, greetings, explanations
- search_web: Search the internet
- search_github: Search GitHub for projects/code
- start_project: User wants to start a new project/learn something
- help_code: User needs help with code
- remember_fact: User stating something to remember about themselves
- recall_info: User asking about past conversations or learned facts
- add_task: User wants to add a reminder, schedule something, or create a task
  * Extract: task, gate_condition (date or event trigger), gate_type ("date" or "event"), target_date, scheduled_date
  * Examples: "remind me to X after Y", "schedule X on October 13", "after exams remind me to learn python"
- check_tasks: User asking about tasks, to-do list, what's scheduled
  * Examples: "what tasks do I have", "show my reminders", "what's on my to-do"
- complete_task: User marking a task as done
  * Extract: task (the task title/name)
  * Examples: "mark X as done", "completed the python task"
- complete_event: User indicating an event is finished (unlocks gated tasks)
  * Extract: event (the event name)
  * Examples: "exams are done", "project finished", "interview is over"

Rules:
- For add_task: if user says "after X" or "when X is done", X is the gate_condition. If "on October 13" or specific date, use scheduled_date
- Extract entities like "query", "topic", "file", "task", "fact", "gate_condition", "scheduled_date" as needed
- confidence should be 0.8-1.0 for clear inputs, lower for ambiguous
- Respond with ONLY the JSON object, nothing else"""
        
        try:
            response = self.brain.generate(
                prompt,
                temperature=0.1,
                max_tokens=300
            )
            
            # Clean response - extract JSON
            response = response.strip()
            
            # Try to extract JSON from various formats
            json_str = response
            
            # Remove markdown code blocks
            if '```json' in response:
                json_str = response.split('```json')[1].split('```')[0].strip()
            elif '```' in response:
                json_str = response.split('```')[1].split('```')[0].strip()
            
            # Try to find JSON object with regex as fallback
            if not json_str.startswith('{'):
                match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
                if match:
                    json_str = match.group(0)
            
            result = json.loads(json_str)
            
            # Merge resolved references into entities
            if result.get('resolved_references'):
                if 'entities' not in result:
                    result['entities'] = {}
                result['entities'].update(result['resolved_references'])
            
            # Validate and set defaults
            if 'intent' not in result:
                result['intent'] = 'conversation'
            if 'confidence' not in result:
                result['confidence'] = 0.85  # Higher default
            if 'entities' not in result:
                result['entities'] = {}
            
            # Ensure confidence is a float
            try:
                result['confidence'] = float(result['confidence'])
            except:
                result['confidence'] = 0.85
            
            logger.debug(f"NLU result: intent={result['intent']}, confidence={result['confidence']}")
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response was: {response[:200]}...")
            # Fallback with reasonable confidence for conversation
            return {
                'intent': 'conversation',
                'confidence': 0.75,  # Higher than before
                'entities': {},
                'reasoning': f'JSON parse failed, defaulting to conversation'
            }
        except Exception as e:
            logger.error(f"Unified understanding failed: {e}")
            return {
                'intent': 'conversation',
                'confidence': 0.75,
                'entities': {},
                'reasoning': f'Understanding failed: {e}'
            }
    
    def _detect_references(self, text: str) -> List[str]:
        """Detect pronouns and references that need resolution"""
        text_lower = text.lower()
        
        found_references = []
        for ref in self.reference_words:
            if f" {ref} " in f" {text_lower} " or text_lower.startswith(ref + " "):
                found_references.append(ref)
        
        return found_references
    
    def _classify_intent(self, user_input: str, context: str) -> Dict:
        """
        Use Groq to classify intent.
        NO REGEX - pure LLM understanding.
        """
        
        prompt = f"""You are an intent classifier for Zeilus, a productivity agent.

Recent conversation:
{context}

Current user input: "{user_input}"

Classify the intent into ONE category:
- conversation: General chat, questions, explanations
- search_web: Search the internet for information
- search_github: Search GitHub for projects/code
- start_project: User wants to start a new project/learn something
- help_code: User needs help with code (implementation, debugging, docs)
- remember_fact: User stated something to remember about themselves
- recall_info: User asking about past conversations or learned facts
- system_control: Control system (volume, brightness, etc)
- file_operation: File/folder operations (move, copy, etc)
- unclear: Cannot determine intent clearly

Respond with ONLY valid JSON:
{{
  "intent": "the_intent_category",
  "confidence": 0.95,
  "reasoning": "brief explanation"
}}"""
        
        try:
            response = self.brain.generate(
                prompt,
                temperature=UnderstandingConfig.TEMP_CLASSIFICATION,
                max_tokens=200
            )
            
            # Clean response
            response = response.strip()
            if response.startswith('```json'):
                response = response.split('```json')[1].split('```')[0].strip()
            elif response.startswith('```'):
                response = response.split('```')[1].split('```')[0].strip()
            
            result = json.loads(response)
            
            # Validate
            if 'intent' not in result or 'confidence' not in result:
                raise ValueError("Missing required fields")
            
            return result
            
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return {
                'intent': 'conversation',
                'confidence': 0.3,
                'reasoning': f'Classification failed: {e}'
            }
    
    def _extract_entities(self, user_input: str, context: str, intent: str) -> Dict:
        """
        Extract entities from input based on intent.
        Uses Groq to preserve phrases and understand context.
        """
        
        # Different entity types based on intent
        entity_instructions = {
            'search_web': 'Extract the search query (preserve full phrase)',
            'search_github': 'Extract: search_query (what to search), filters (optional)',
            'start_project': 'Extract: topic (what to build/learn), project_type (web/ml/hardware/etc)',
            'help_code': 'Extract: task (what help is needed), file (if mentioned)',
            'remember_fact': 'Extract: fact (what to remember), category (skill/preference/etc)',
            'file_operation': 'Extract: operation (move/copy/delete), source, destination (if applicable)',
        }
        
        instruction = entity_instructions.get(intent, 'Extract relevant entities')
        
        prompt = f"""Extract entities from user input.

Intent: {intent}
Instructions: {instruction}

Recent context:
{context}

User input: "{user_input}"

Respond with ONLY valid JSON:
{{
  "entity1": "value1",
  "entity2": "value2"
}}

If nothing to extract, return: {{}}"""
        
        try:
            response = self.brain.generate(
                prompt,
                temperature=UnderstandingConfig.TEMP_CLASSIFICATION,
                max_tokens=300
            )
            
            # Clean response
            response = response.strip()
            if response.startswith('```json'):
                response = response.split('```json')[1].split('```')[0].strip()
            elif response.startswith('```'):
                response = response.split('```')[1].split('```')[0].strip()
            
            entities = json.loads(response)
            
            return entities
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return {}
    
    def _resolve_references(self, entities: Dict, references: List[str], 
                           context: str) -> Dict:
        """
        Resolve pronouns using context.
        "improve it" → "improve circuit_optimizer.py"
        """
        
        if not references:
            return entities
        
        # Use Groq to resolve references
        prompt = f"""Resolve pronoun references using context.

Recent conversation:
{context}

User mentioned: {', '.join(references)}

Current entities extracted: {json.dumps(entities)}

What do these references refer to? Update the entities with resolved values.

Respond with ONLY valid JSON (updated entities):
{{
  "resolved_entity": "actual_value"
}}"""
        
        try:
            response = self.brain.generate(
                prompt,
                temperature=UnderstandingConfig.TEMP_CLASSIFICATION,
                max_tokens=300
            )
            
            # Clean and parse
            response = response.strip()
            if response.startswith('```json'):
                response = response.split('```json')[1].split('```')[0].strip()
            elif response.startswith('```'):
                response = response.split('```')[1].split('```')[0].strip()
            
            resolved = json.loads(response)
            
            # Merge with original entities
            entities.update(resolved)
            
            logger.info(f"Resolved references: {references} → {resolved}")
            
            return entities
            
        except Exception as e:
            logger.error(f"Reference resolution failed: {e}")
            return entities
    
    def _generate_clarification(self, user_input: str, intent_result: Dict) -> str:
        """
        Generate clarification question when intent is unclear.
        """
        
        prompt = f"""The user said: "{user_input}"

We classified it as: {intent_result['intent']} (confidence: {intent_result['confidence']:.2f})
Reasoning: {intent_result.get('reasoning', 'N/A')}

This is ambiguous. Generate ONE clarifying question to ask the user.
Be natural and conversational.

Example good questions:
- "Do you mean [option A] or [option B]?"
- "I'm not sure if you want to [action]. Is that right?"
- "What kind of [thing] are you looking for?"

Your clarifying question:"""
        
        try:
            response = self.brain.generate(
                prompt,
                temperature=0.7,
                max_tokens=100
            )
            
            question = response.strip().strip('"')
            
            return question
            
        except Exception as e:
            logger.error(f"Clarification generation failed: {e}")
            return "I'm not sure I understood. Could you rephrase that?"
    
    def quick_intent(self, user_input: str) -> str:
        """
        Quick intent classification without full understanding.
        Used for simple routing.
        """
        
        context = self.memory.get_context(n_messages=3)
        result = self._classify_intent(user_input, context)
        return result['intent']
    
    def is_question(self, user_input: str) -> bool:
        """Check if input is a question"""
        question_words = ['what', 'why', 'how', 'when', 'where', 'who', 'which', 'can', 'do', 'does', 'is', 'are']
        
        text_lower = user_input.lower().strip()
        
        # Ends with ?
        if text_lower.endswith('?'):
            return True
        
        # Starts with question word
        if any(text_lower.startswith(word + ' ') for word in question_words):
            return True
        
        return False


# =============================================================================
# TESTING
# =============================================================================

def test_understanding():
    """Test understanding with example inputs"""
    
    # Mock brain and memory for testing
    class MockBrain:
        def generate(self, prompt, temperature=0.7, max_tokens=500):
            # Simulate responses for testing
            if 'intent' in prompt.lower():
                return '{"intent": "search_github", "confidence": 0.9, "reasoning": "User wants to find projects"}'
            elif 'entities' in prompt.lower():
                return '{"search_query": "circuit optimization projects"}'
            else:
                return '{}'
    
    class MockMemory:
        def get_context(self, n_messages=5):
            return "User: I'm working on circuit optimization\nZeilus: Great! What aspect?"
    
    # Create engine
    engine = UnderstandingEngine(MockBrain(), MockMemory())
    
    # Test cases
    test_inputs = [
        "Find projects like this because I want to learn",
        "Can you improve it?",
        "What did we discuss yesterday?",
    ]
    
    for inp in test_inputs:
        print(f"\nInput: {inp}")
        result = engine.understand(inp)
        print(f"Result: {result}")
        print(f"Entities: {result.entities}")
        if result.ambiguous:
            print(f"Clarification needed: {result.clarification_question}")


if __name__ == '__main__':
    test_understanding()