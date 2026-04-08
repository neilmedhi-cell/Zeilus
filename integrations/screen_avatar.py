# integrations/screen_avatar.py - On-Screen Avatar Presence via VTuber Studio
"""
On-screen speaking head coordinator for Zeilus.
Uses VTuber Studio as the rendering engine for avatar display, expressions,
and lip-sync animation. This module ties the avatar to Zeilus's voice output
and conversation emotion detection.

VTuber Studio must be running with:
  - API enabled (Settings > Start API on port 8001)
  - A model loaded
  - The window visible (preferably always-on-top / pinned)

This module provides:
  - Automatic connection to VTuber Studio on startup
  - Expression changes based on conversation emotion
  - Lip-sync animation synchronized with ElevenLabs voice output
  - Simple API for show/hide/mood/speak
"""

import logging
import threading
import time
import math
import random
from typing import Optional, Dict, Callable, Any

from integrations.vtuber_bridge import (
    VTuberBridge,
    get_vtuber_bridge,
    Expression,
)

logger = logging.getLogger(__name__)


# =============================================================================
# EMOTION → EXPRESSION MAPPING
# =============================================================================

EMOTION_MAP = {
    # Positive
    "happy": Expression.HAPPY,
    "joy": Expression.HAPPY,
    "excited": Expression.HAPPY,
    "grateful": Expression.HAPPY,
    "cheerful": Expression.HAPPY,
    "proud": Expression.HAPPY,
    # Negative
    "sad": Expression.SAD,
    "disappointed": Expression.SAD,
    "sorry": Expression.SAD,
    "melancholy": Expression.SAD,
    # Anger
    "angry": Expression.ANGRY,
    "frustrated": Expression.ANGRY,
    "annoyed": Expression.ANGRY,
    # Surprise
    "surprised": Expression.SURPRISED,
    "amazed": Expression.SURPRISED,
    "shocked": Expression.SURPRISED,
    "wow": Expression.SURPRISED,
    # Thinking
    "thinking": Expression.THINKING,
    "confused": Expression.THINKING,
    "curious": Expression.THINKING,
    "pondering": Expression.THINKING,
    "hmm": Expression.THINKING,
    # Misc
    "embarrassed": Expression.BLUSH,
    "shy": Expression.BLUSH,
    "flirty": Expression.WINK,
    "wink": Expression.WINK,
    # Default
    "neutral": Expression.NEUTRAL,
    "calm": Expression.NEUTRAL,
    "normal": Expression.NEUTRAL,
}

# Keywords to scan in response text for implicit emotion detection
EMOTION_KEYWORDS = {
    Expression.HAPPY: ["great", "awesome", "wonderful", "nice", "glad", "😊", "🎉", "✅", "love"],
    Expression.SAD: ["sorry", "unfortunately", "sadly", "😔", "😢"],
    Expression.SURPRISED: ["wow", "amazing", "incredible", "whoa", "😮", "🤯"],
    Expression.THINKING: ["hmm", "let me think", "interesting", "consider", "🤔"],
    Expression.ANGRY: ["error", "failed", "❌", "broken"],
}


# =============================================================================
# SCREEN AVATAR COORDINATOR
# =============================================================================

class ScreenAvatar:
    """
    Coordinates VTuber Studio avatar for on-screen presence.

    Manages:
    - Connection lifecycle to VTuber Studio
    - Expression state machine (with auto-revert to neutral)
    - Lip-sync animation during voice output
    - Idle animations (subtle breathing / blinking)
    - Emotion detection from response text
    """

    def __init__(self, auto_connect: bool = False):
        """
        Initialize the screen avatar coordinator.

        Args:
            auto_connect: If True, attempt to connect to VTuber Studio immediately.
        """
        self._bridge: VTuberBridge = get_vtuber_bridge()
        self._active = False
        self._current_expression = Expression.NEUTRAL
        self._talking = False
        self._idle_thread: Optional[threading.Thread] = None
        self._expression_timer: Optional[threading.Timer] = None

        # Lip-sync configuration
        self._lip_sync_fps = 20  # Frames per second for mouth animation
        self._lip_sync_thread: Optional[threading.Thread] = None
        
        # Idle animation config
        self._idle_enabled = True
        self._idle_interval = 8.0  # Seconds between idle actions

        # Audio level callback (set externally for real audio-level lip sync)
        self._audio_level_callback: Optional[Callable[[], float]] = None

        if auto_connect:
            self.connect()

        logger.info("ScreenAvatar coordinator initialized")

    # -------------------------------------------------------------------------
    # Connection
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Connect to VTuber Studio and prepare the avatar.

        Returns:
            True if connected and authenticated.
        """
        try:
            success = self._bridge.connect_and_auth()
            if success:
                self._active = True
                logger.info("ScreenAvatar connected to VTuber Studio")
                # Load hotkeys / parameters so expressions work
                try:
                    self._bridge.get_hotkeys()
                except Exception as e:
                    logger.warning(f"Could not load hotkeys: {e}")
                try:
                    self._bridge.get_parameters()
                except Exception as e:
                    logger.warning(f"Could not load parameters: {e}")
                # Start idle animations
                self._start_idle_loop()
                # Set neutral expression
                try:
                    self.set_expression(Expression.NEUTRAL)
                except Exception:
                    pass
                return True
            else:
                logger.warning("ScreenAvatar failed to connect to VTuber Studio")
                return False
        except Exception as e:
            logger.error(f"ScreenAvatar connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from VTuber Studio and clean up."""
        self._active = False
        self._stop_idle_loop()
        self.stop_talking()
        try:
            self._bridge.disconnect()
        except Exception as e:
            logger.debug(f"Disconnect error: {e}")
        logger.info("ScreenAvatar disconnected")

    @property
    def is_active(self) -> bool:
        """Whether the avatar is currently active and connected."""
        return self._active and self._bridge.is_connected()

    # -------------------------------------------------------------------------
    # Expression Control
    # -------------------------------------------------------------------------

    def set_expression(self, expression: str, duration: float = 0) -> Dict:
        """
        Set the avatar's expression.

        Args:
            expression: Expression name (from Expression enum or emotion string).
            duration: If > 0, revert to neutral after this many seconds.

        Returns:
            Result dict from VTuber Studio.
        """
        if not self.is_active:
            return {"error": "Avatar not active"}

        # Cancel any pending expression revert
        if self._expression_timer:
            self._expression_timer.cancel()
            self._expression_timer = None

        # Resolve emotion string to expression
        if expression in EMOTION_MAP:
            expression = EMOTION_MAP[expression]

        self._current_expression = expression
        result = self._bridge.set_expression(expression)

        # Schedule revert to neutral if duration is set
        if duration > 0:
            self._expression_timer = threading.Timer(
                duration, self._revert_expression
            )
            self._expression_timer.daemon = True
            self._expression_timer.start()

        return result

    def _revert_expression(self):
        """Revert expression to neutral."""
        if self.is_active and self._current_expression != Expression.NEUTRAL:
            self._current_expression = Expression.NEUTRAL
            self._bridge.set_expression(Expression.NEUTRAL)

    def react_to_emotion(self, emotion: str, duration: float = 4.0, intensity: float = 0.5) -> Dict:
        """
        Set expression based on detected emotion, with auto-revert.

        Args:
            emotion: Emotion string (happy, sad, surprised, etc.)
            duration: How long to hold the expression before reverting.
            intensity: How strong the emotion is (0.0-1.0). Scales duration
                       if no explicit duration override was given.

        Returns:
            Result dict.
        """
        # Scale duration by intensity when using the default
        if duration == 4.0:
            duration = 2.0 + (intensity * 4.0)  # 2s-6s

        logger.info(f"Avatar emotion: {emotion} (intensity={intensity:.2f}, hold={duration:.1f}s)")
        return self.set_expression(emotion, duration=duration)

    def detect_emotion_from_text(self, text: str) -> Optional[str]:
        """
        Detect the dominant emotion from response text using keyword matching.

        Args:
            text: The response text to analyze.

        Returns:
            Detected Expression string, or None if neutral.
        """
        text_lower = text.lower()
        scores = {}

        for expression, keywords in EMOTION_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[expression] = score

        if scores:
            # Return the expression with the highest keyword match count
            best = max(scores, key=scores.get)
            return best

        return None

    # -------------------------------------------------------------------------
    # Lip Sync (Talking Animation)
    # -------------------------------------------------------------------------

    def start_talking(self, audio_level_callback: Callable = None):
        """
        Start lip-sync talking animation.

        Args:
            audio_level_callback: Optional callable that returns current audio
                                  level as float 0.0-1.0. If None, uses
                                  simulated natural speech patterns.
        """
        if not self.is_active:
            logger.warning("Cannot start talking: avatar not active")
            return

        if self._talking:
            return

        self._talking = True
        self._audio_level_callback = audio_level_callback

        # Set talking expression
        try:
            self._bridge.set_expression(Expression.TALKING)
        except Exception as e:
            logger.warning(f"Could not set talking expression: {e}")

        # Start lip sync via the bridge
        try:
            self._bridge.start_lip_sync(audio_callback=self._get_mouth_level)
        except Exception as e:
            logger.warning(f"Could not start lip sync: {e}")
            self._talking = False
            return

        logger.info("Avatar started talking")

    def stop_talking(self):
        """Stop lip-sync animation and return to previous expression."""
        if not self._talking:
            return

        self._talking = False
        self._audio_level_callback = None

        # Stop bridge lip sync
        try:
            self._bridge.stop_lip_sync()
        except Exception as e:
            logger.warning(f"Error stopping lip sync: {e}")

        # Revert to neutral (or previous expression)
        if self.is_active:
            try:
                self._bridge.set_expression(self._current_expression)
            except Exception as e:
                logger.warning(f"Error reverting expression: {e}")

        logger.info("Avatar stopped talking")

    def _get_mouth_level(self) -> float:
        """
        Get the current mouth open level for lip sync.

        Returns:
            Float 0.0 (closed) to 1.0 (wide open).
        """
        if self._audio_level_callback:
            try:
                return self._audio_level_callback()
            except Exception:
                pass

        # Simulated natural speech pattern
        # Uses a combination of sine waves for natural-looking mouth movement
        t = time.time()
        # Primary speech rhythm (~4-5 syllables/sec)
        primary = abs(math.sin(t * 12.0)) * 0.6
        # Secondary variation (word boundaries)
        secondary = abs(math.sin(t * 3.5)) * 0.3
        # Random micro-variations
        noise = random.uniform(-0.1, 0.1)

        level = primary + secondary + noise
        return max(0.0, min(1.0, level))

    # -------------------------------------------------------------------------
    # Convenience: Speak with Animation
    # -------------------------------------------------------------------------

    def speak_with_animation(
        self,
        speak_func: Callable,
        text: str,
        emotion: str = None,
    ):
        """
        Speak text with lip-sync animation and optional emotion.

        This is the main integration point with VoiceAgent. It:
        1. Sets emotion expression if detected
        2. Starts lip-sync
        3. Calls the speak function (blocks while audio plays)
        4. Stops lip-sync
        5. Reverts expression

        Args:
            speak_func: Blocking function that plays audio (e.g., voice.speak)
            text: Text being spoken (for emotion detection)
            emotion: Explicit emotion, or auto-detect from text
        """
        # Detect or use provided emotion
        if not emotion:
            detected = self.detect_emotion_from_text(text)
            if detected:
                emotion = detected

        # Set emotion expression
        if emotion:
            try:
                self.set_expression(emotion)
            except Exception as e:
                logger.warning(f"Could not set emotion expression: {e}")

        # Start talking animation
        self.start_talking()

        try:
            # Call the blocking speak function
            speak_func(text)
        except Exception as e:
            logger.error(f"Speak function error: {e}")
        finally:
            # Always stop animation
            self.stop_talking()
            # Revert to neutral after a moment
            time.sleep(0.3)
            if emotion:
                try:
                    self.set_expression(Expression.NEUTRAL)
                except Exception:
                    pass

    def speak_async_with_animation(
        self,
        speak_func: Callable,
        text: str,
        emotion: str = None,
    ):
        """
        Non-blocking version of speak_with_animation.
        Runs in a background thread.
        """
        thread = threading.Thread(
            target=self.speak_with_animation,
            args=(speak_func, text, emotion),
            daemon=True,
        )
        thread.start()
        return thread

    # -------------------------------------------------------------------------
    # Idle Animations
    # -------------------------------------------------------------------------

    def _start_idle_loop(self):
        """Start subtle idle animations (blink, breathing)."""
        if self._idle_thread and self._idle_thread.is_alive():
            return

        def idle_loop():
            consecutive_errors = 0
            while self._active and self._idle_enabled:
                try:
                    if not self._talking and self.is_active:
                        # Subtle parameter changes for breathing effect
                        t = time.time()
                        # Gentle up-down for breathing
                        breath = math.sin(t * 0.8) * 0.02
                        try:
                            self._bridge.set_parameter("FacePositionY", breath)
                            consecutive_errors = 0
                        except Exception as e:
                            consecutive_errors += 1
                            if consecutive_errors >= 5:
                                logger.warning(
                                    "Idle loop: too many errors, pausing for 30s"
                                )
                                time.sleep(30)
                                consecutive_errors = 0

                    time.sleep(self._idle_interval)

                except Exception as e:
                    logger.debug(f"Idle loop error: {e}")
                    time.sleep(5)

        self._idle_thread = threading.Thread(target=idle_loop, daemon=True)
        self._idle_thread.start()

    def _stop_idle_loop(self):
        """Stop idle animations."""
        self._idle_enabled = False
        if self._idle_thread:
            self._idle_thread.join(timeout=2)
            self._idle_thread = None
        self._idle_enabled = True  # Reset for next start

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def get_status(self) -> Dict:
        """Get the current avatar status."""
        bridge_status = self._bridge.get_status()
        return {
            "active": self._active,
            "connected": bridge_status.get("connected", False),
            "authenticated": bridge_status.get("authenticated", False),
            "current_expression": self._current_expression,
            "talking": self._talking,
            "model": bridge_status.get("model", "Unknown"),
            "idle_animations": self._idle_enabled,
        }


# =============================================================================
# SINGLETON
# =============================================================================

_screen_avatar: Optional[ScreenAvatar] = None


def get_screen_avatar() -> ScreenAvatar:
    """Get or create the ScreenAvatar singleton."""
    global _screen_avatar
    if _screen_avatar is None:
        _screen_avatar = ScreenAvatar()
    return _screen_avatar


# =============================================================================
# SIMPLE API
# =============================================================================

def show_avatar() -> Dict:
    """Connect and show the avatar via VTuber Studio."""
    avatar = get_screen_avatar()
    success = avatar.connect()
    return {"success": success, "status": avatar.get_status()}


def hide_avatar() -> Dict:
    """Disconnect and hide the avatar."""
    avatar = get_screen_avatar()
    avatar.disconnect()
    return {"success": True, "message": "Avatar hidden"}


def set_mood(mood: str, duration: float = 4.0) -> Dict:
    """Set the avatar's mood/expression."""
    avatar = get_screen_avatar()
    if not avatar.is_active:
        return {"error": "Avatar not active. Call show_avatar() first."}
    result = avatar.react_to_emotion(mood, duration)
    return {"success": True, "mood": mood, "result": result}


def avatar_speak(speak_func: Callable, text: str, emotion: str = None):
    """Make the avatar speak with lip-sync animation."""
    avatar = get_screen_avatar()
    if avatar.is_active:
        avatar.speak_async_with_animation(speak_func, text, emotion)
    else:
        # Fallback: just speak without animation
        speak_func(text)


def get_avatar_status() -> Dict:
    """Get current avatar status."""
    avatar = get_screen_avatar()
    return avatar.get_status()
