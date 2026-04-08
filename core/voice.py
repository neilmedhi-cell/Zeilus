# core/voice.py - ElevenLabs Text-to-Speech Integration
"""
Voice synthesis for Zeilus using ElevenLabs API.
Allows the agent to speak responses aloud.
"""

import os
import logging
import tempfile
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()


logger = logging.getLogger(__name__)

# Try to import elevenlabs
try:
    from elevenlabs import generate, play, set_api_key, save, voices
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False
    logger.warning("ElevenLabs not installed. Run: pip install elevenlabs")


class VoiceAgent:
    """
    ElevenLabs-powered voice synthesis for Zeilus.
    Converts text responses to speech.
    """
    
    # Default voice settings
    DEFAULT_VOICE_ID = "YIH3wSqjU6NkcdmkKksd"  # Rachel - a clear, pleasant voice
    DEFAULT_MODEL = "eleven_turbo_v2"
    
    # Alternative voices
    VOICES = {
        'changli': 'YIH3wSqjU6NkcdmkKksd',
        'domi': 'AZnzlk1XvdvUeBnXmlld',
        'bella': 'EXAVITQu4vr4xnSDxMaL',
        'antoni': 'ErXwobaYiN019PkySvjV',
        'elli': 'MF3mGyEYCl7XYWbV9V6O',
        'josh': 'TxGEqnHWrfWFTfGW9XjX',
        'arnold': 'VR6AewLTigWG4xSOukaG',
        'adam': 'pNInz6obpgDQGcFmaJgB',
        'sam': 'yoZ06aMxZJJ28mfd3POQ',
    }
    
    def __init__(self, api_key: str = None, voice_id: str = None, auto_play: bool = True):
        """
        Initialize the voice agent.
        
        Args:
            api_key: ElevenLabs API key (uses ELEVENLABS_API_KEY env var if not provided)
            voice_id: Voice ID to use (default: Rachel)
            auto_play: Whether to automatically play audio after generation
        """
        # Get API key from env if not provided
        self.api_key = api_key or os.getenv('ELEVENLABS_API_KEY') or os.getenv('ELLEVENLABS_API_KEY')
        
        if not self.api_key:
            logger.warning("ElevenLabs API key not found. Voice disabled.")
            self.enabled = False
            return
        
        if not ELEVENLABS_AVAILABLE:
            logger.warning("ElevenLabs library not available. Voice disabled.")
            self.enabled = False
            return
        
        self.enabled = True
        self.voice_id = voice_id or self.DEFAULT_VOICE_ID
        self.model_id = self.DEFAULT_MODEL
        self.auto_play = auto_play
        
        # Initialize SDK
        try:
            set_api_key(self.api_key)
            logger.info(f"VoiceAgent initialized with voice: {self.voice_id}")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            self.enabled = False
    
    def speak(self, text: str, save_path: str = None) -> Optional[str]:
        """
        Convert text to speech and optionally play it.
        
        Args:
            text: Text to convert to speech
            save_path: Optional path to save the audio file
        
        Returns:
            Path to saved audio file, or None if failed
        """
        if not self.enabled:
            logger.warning("Voice is not enabled. Cannot speak.")
            return None
        
        if not text or not text.strip():
            logger.warning("Empty text provided. Cannot speak.")
            return None
        
        try:
            # Generate audio data (bytes)
            audio = generate(
                text=text,
                voice=self.voice_id,
                model=self.model_id
            )
            
            # Determine save path
            if save_path is None:
                # Use temp file
                fd, save_path = tempfile.mkstemp(suffix='.mp3', prefix='zeilus_voice_')
                os.close(fd)
            
            # Save audio
            save(audio, save_path)
            
            logger.info(f"Audio saved to: {save_path}")
            
            # Auto-play if enabled
            if self.auto_play:
                play(audio)
            
            return save_path
            
        except Exception as e:
            logger.error(f"Failed to generate speech: {e}")
            return None
    
    def speak_async(self, text: str) -> None:
        """
        Speak text asynchronously (non-blocking).
        Useful for long responses.
        """
        import threading
        thread = threading.Thread(target=self.speak, args=(text,))
        thread.daemon = True
        thread.start()
    
    def set_voice(self, voice_name: str) -> bool:
        """
        Set the voice by name.
        
        Args:
            voice_name: Name of the voice (e.g., 'rachel', 'josh', 'bella')
        
        Returns:
            True if voice was set successfully
        """
        voice_name_lower = voice_name.lower()
        
        if voice_name_lower in self.VOICES:
            self.voice_id = self.VOICES[voice_name_lower]
            logger.info(f"Voice set to: {voice_name}")
            return True
        else:
            logger.warning(f"Unknown voice: {voice_name}. Available: {list(self.VOICES.keys())}")
            return False
    
    def list_voices(self) -> list:
        """List available voice names."""
        return list(self.VOICES.keys())
    
    def _play_audio(self, file_path: str) -> None:
        """
        Play audio file using system default player.
        """
        import platform
        import subprocess
        
        system = platform.system()
        
        try:
            if system == 'Windows':
                # Use Windows Media Player or default
                os.startfile(file_path)
            elif system == 'Darwin':  # macOS
                subprocess.run(['afplay', file_path], check=True)
            else:  # Linux
                # Try common players
                for player in ['mpv', 'mplayer', 'aplay', 'paplay']:
                    try:
                        subprocess.run([player, file_path], check=True)
                        break
                    except FileNotFoundError:
                        continue
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
    
    def get_status(self) -> dict:
        """Get voice agent status."""
        return {
            'enabled': self.enabled,
            'voice_id': self.voice_id if self.enabled else None,
            'auto_play': self.auto_play if self.enabled else False,
            'available_voices': list(self.VOICES.keys())
        }


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def create_voice_agent() -> VoiceAgent:
    """
    Create and return a configured VoiceAgent.
    Uses environment variables for configuration.
    """
    return VoiceAgent()


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    # Quick test
    voice = VoiceAgent()
    
    if voice.enabled:
        print("Voice agent is enabled!")
        print(f"Available voices: {voice.list_voices()}")
        
        # Test speech
        voice.speak("Hello! I am Zeilus, your productivity assistant. How can I help you today?")
    else:
        print("Voice agent is disabled. Check your API key.")
