# config.py - Zeilus Configuration
"""
All configuration in one place.
Modify these to tune Zeilus behavior.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# API CONFIGURATION
# =============================================================================

class APIConfig:
    """Groq API settings"""
    
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
    
    # Rate limiting (Groq free tier: 30 req/min)
    MAX_REQUESTS_PER_MINUTE = 25  # Stay under limit
    REQUEST_TIMEOUT = 30  # seconds
    
    # Token management (tuned for 128K context models)
    MAX_CONTEXT_TOKENS = 12000  # Generous context for long conversations
    MAX_RESPONSE_TOKENS = 2000
    
    # Temperature settings
    TEMP_CLASSIFICATION = 0.1  # Low temp for intent classification
    TEMP_CONVERSATION = 0.7    # Normal temp for chat
    TEMP_CREATIVE = 0.9        # High temp for creative tasks


# =============================================================================
# MEMORY CONFIGURATION
# =============================================================================

class MemoryConfig:
    """Memory system settings"""
    
    # Working memory (short-term, in RAM)
    WORKING_MEMORY_SIZE = 50  # Last N messages (increased from 10)
    
    # Compression settings
    ENABLE_COMPRESSION = True  # Summarize old messages to save tokens
    COMPRESSION_THRESHOLD = 40  # Summarize when > N messages
    SUMMARY_TARGET_TOKENS = 500  # Target size for summaries
    
    # Episodic memory (session history)
    MAX_SESSIONS = 100  # Keep more session history
    SESSION_TIMEOUT = 3600  # 1 hour of inactivity = new session
    
    # Semantic memory (facts & knowledge)
    MAX_FACTS = 1000  # Total facts to remember (increased)
    FACT_CONFIDENCE_THRESHOLD = 0.7  # Only store confident facts
    
    # Context tracking
    MAX_RECENT_ENTITIES = 50  # Track more entities
    CONTEXT_DECAY_HOURS = 72  # Slower decay (3 days)


# =============================================================================
# CONVERSATIONAL MEMORY CONFIGURATION
# =============================================================================

class ConversationalMemoryConfig:
    """Conversational memory settings - for human-like follow-ups"""
    
    MAX_PENDING_EVENTS = 50   # Max events to track
    EVENT_EXPIRY_DAYS = 14    # Events expire after 2 weeks
    FOLLOW_UP_DELAY_HOURS = 4 # Min hours before follow-up
    
    # Enable/disable features
    ENABLE_EVENT_DETECTION = True
    ENABLE_AUTOMATIC_FOLLOWUPS = True


# =============================================================================
# UNDERSTANDING CONFIGURATION
# =============================================================================

class UnderstandingConfig:
    """NLU settings"""
    
    # Intent classification
    MIN_CONFIDENCE = 0.7  # Ask for clarification below this
    
    # Entity extraction
    PRESERVE_PHRASES = True  # Keep multi-word entities together
    
    # Context resolution
    ENABLE_PRONOUN_RESOLUTION = True  # Resolve "it", "that", etc.
    ENABLE_CONTEXT_COMPLETION = True  # Fill in missing info from context
    
    # Ambiguity handling
    ASK_FOR_CLARIFICATION = True  # Ask when uncertain
    MAX_CLARIFICATION_ATTEMPTS = 2  # Give up after 2 tries


# =============================================================================
# STORAGE CONFIGURATION
# =============================================================================

class StorageConfig:
    """File storage settings"""
    
    # Base paths
    BASE_DIR = Path(__file__).parent
    STORAGE_DIR = BASE_DIR / 'storage'
    
    # Storage files
    MEMORY_FILE = STORAGE_DIR / 'memory.json'
    CONTEXT_FILE = STORAGE_DIR / 'context.json'
    KNOWLEDGE_FILE = STORAGE_DIR / 'knowledge.json'
    CONVERSATIONAL_MEMORY_FILE = STORAGE_DIR / 'conversational_memory.json'
    RESEARCH_MEMORY_FILE = STORAGE_DIR / 'research_memory.json'
    TOOL_MEMORY_FILE = STORAGE_DIR / 'tool_memory.json'
    AUTOMATION_FILE = STORAGE_DIR / 'automation.json'
    
    # Auto-save
    AUTO_SAVE = True
    SAVE_INTERVAL = 60  # Save every 60 seconds
    
    # Backups
    ENABLE_BACKUPS = True
    MAX_BACKUPS = 5


# =============================================================================
# AGENT CONFIGURATION
# =============================================================================

class AgentConfig:
    """General agent settings"""
    
    # Identity
    NAME = "Zeilus"
    USER_NAME = os.getenv('USER_NAME', 'User')
    
    # Behavior
    PROACTIVE = False  # Enable proactive suggestions (modules tomorrow)
    VERBOSE = True  # Show thinking process
    
    # Safety
    ENABLE_CONFIRMATIONS = False  # Ask before executing actions
    MAX_RETRIES = 3  # Retry failed operations


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

class LogConfig:
    """Logging settings"""
    
    LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
    LOG_FILE = 'zeilus.log'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # What to log
    LOG_API_CALLS = True
    LOG_MEMORY_OPS = False  # Too verbose
    LOG_UNDERSTANDING = True


# =============================================================================
# VALIDATION
# =============================================================================

def validate_config():
    """Validate configuration on startup"""
    errors = []
    
    # Check API key
    if not APIConfig.GROQ_API_KEY:
        errors.append("GROQ_API_KEY not set in .env file")
    
    # Check storage directory
    if not StorageConfig.STORAGE_DIR.exists():
        StorageConfig.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    if errors:
        raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))


# Validate on import
validate_config()