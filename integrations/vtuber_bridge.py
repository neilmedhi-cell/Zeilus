# integrations/vtuber_bridge.py - VTuber Studio Integration
"""
Bridge to VTuber Studio for avatar control, lip-sync, and expressions.
Uses the VTuber Studio API via WebSocket (port 8001).

Architecture:
    The bridge owns a dedicated background thread running its own asyncio
    event loop ("bridge loop"). All WebSocket I/O is submitted to that loop
    via asyncio.run_coroutine_threadsafe(), making every public method
    thread-safe and callable from ANY context — sync code, other threads,
    or even from inside another running event loop (e.g. the MCP server).
"""

import asyncio
import json
import logging
import math
import random
import time
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logging.warning("websockets not installed. VTuber integration disabled.")

logger = logging.getLogger(__name__)


# =============================================================================
# EXPRESSIONS & ANIMATIONS
# =============================================================================

class Expression(str, Enum):
    """Common VTuber expressions."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    SURPRISED = "surprised"
    ANGRY = "angry"
    THINKING = "thinking"
    TALKING = "talking"
    WINK = "wink"
    BLUSH = "blush"


# =============================================================================
# BRIDGE EVENT LOOP (internal)
# =============================================================================

class _BridgeLoop:
    """
    Manages a dedicated asyncio event loop on a daemon thread.

    All coroutines are submitted via run_coro() which returns a
    concurrent.futures.Future, safe to call from any thread or from
    inside another running event loop.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the bridge loop thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="vtuber-bridge-loop"
        )
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self):
        """Stop the loop and join the thread."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._loop and not self._loop.is_closed():
            self._loop.close()
            self._loop = None

    @property
    def running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def run_coro(self, coro, timeout: float = 10.0):
        """
        Submit a coroutine to the bridge loop and block until it completes.

        Returns the coroutine result. Safe to call from any thread, including
        from inside another running event loop.

        Raises TimeoutError if the operation takes longer than *timeout*.
        """
        if not self.running:
            raise RuntimeError("Bridge loop is not running. Call start() first.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def run_coro_async(self, coro, timeout: float = 10.0):
        """
        Submit a coroutine to the bridge loop and await the result.

        Use this from async callers who want to await instead of blocking.
        """
        if not self.running:
            raise RuntimeError("Bridge loop is not running. Call start() first.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(future)


# =============================================================================
# VTUBER BRIDGE
# =============================================================================

class VTuberBridge:
    """
    Bridge to VTuber Studio for avatar control.

    Features:
    - Connect to VTuber Studio API
    - Trigger hotkeys/expressions
    - Lip-sync with audio
    - Parameter control
    - Automatic reconnection with exponential backoff
    - Thread-safe: callable from any context
    """

    PLUGIN_NAME = "Zeilus"
    PLUGIN_DEVELOPER = "ZeilusTeam"
    PLUGIN_ICON = None  # Can be base64 encoded icon

    # Reconnection settings
    MAX_RECONNECT_RETRIES = 5
    RECONNECT_BACKOFF_BASE = 1.0  # seconds; doubles each retry

    # Lip-sync settings
    LIP_SYNC_INTERVAL = 0.08  # 80 ms (~12.5 FPS) — gentler than 50 ms
    LIP_SYNC_MAX_ERRORS = 3   # trigger reconnect after N consecutive errors
    LIP_SYNC_ERROR_BACKOFF = 0.5  # extra sleep per consecutive error

    def __init__(self, host: str = "localhost", port: int = 8001):
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}"

        self._ws = None
        self._connected = False
        self._authenticated = False
        self._auth_token = None

        # Cached data
        self._model_info = {}
        self._hotkeys: List[Dict] = []
        self._expressions: List = []
        self._parameters: List[Dict] = []

        # Lip sync state
        self._lip_sync_active = False
        self._lip_sync_thread: Optional[threading.Thread] = None
        self._lip_sync_errors = 0

        # Reconnection state
        self._reconnecting = False
        self._reconnect_lock = threading.Lock()

        # Dedicated event loop
        self._loop = _BridgeLoop()
        self._loop.start()

        logger.info(f"VTuberBridge initialized (target: {self.ws_url})")

    # -------------------------------------------------------------------------
    # Connection (async core)
    # -------------------------------------------------------------------------

    async def _connect_async(self) -> bool:
        """Async connection to VTuber Studio."""
        if not HAS_WEBSOCKETS:
            logger.error("websockets library not installed")
            return False

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
            self._connected = True
            logger.info("Connected to VTuber Studio")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to VTuber Studio: {e}")
            self._connected = False
            return False

    def connect(self) -> bool:
        """Connect to VTuber Studio (thread-safe)."""
        try:
            return self._loop.run_coro(self._connect_async())
        except Exception as e:
            logger.error(f"Connect error: {e}")
            return False

    async def _disconnect_async(self):
        """Async disconnect."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        self._authenticated = False

    def disconnect(self):
        """Disconnect from VTuber Studio (thread-safe)."""
        self.stop_lip_sync()
        try:
            self._loop.run_coro(self._disconnect_async(), timeout=5)
        except Exception as e:
            logger.debug(f"Disconnect error: {e}")
        logger.info("Disconnected from VTuber Studio")

    def shutdown(self):
        """Disconnect and stop the bridge loop entirely."""
        self.disconnect()
        self._loop.stop()

    def is_connected(self) -> bool:
        """Check if connected to VTuber Studio."""
        return self._connected and self._ws is not None

    # -------------------------------------------------------------------------
    # Reconnection
    # -------------------------------------------------------------------------

    def _try_reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.
        Thread-safe; only one reconnection attempt runs at a time.
        """
        if not self._reconnect_lock.acquire(blocking=False):
            return False  # another thread is already reconnecting

        try:
            self._reconnecting = True
            logger.warning("Starting reconnection sequence...")

            for attempt in range(1, self.MAX_RECONNECT_RETRIES + 1):
                delay = self.RECONNECT_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.info(f"Reconnect attempt {attempt}/{self.MAX_RECONNECT_RETRIES} "
                            f"in {delay:.1f}s...")
                time.sleep(delay)

                try:
                    self._loop.run_coro(self._disconnect_async(), timeout=5)
                except Exception:
                    pass

                if self.connect():
                    if self._auth_token:
                        self.authenticate()
                    if self._connected:
                        logger.info("Reconnected successfully!")
                        self._lip_sync_errors = 0
                        return True

            logger.error("All reconnection attempts failed.")
            return False
        finally:
            self._reconnecting = False
            self._reconnect_lock.release()

    # -------------------------------------------------------------------------
    # API Communication
    # -------------------------------------------------------------------------

    async def _send_request(self, request_type: str, data: Dict = None) -> Dict:
        """Send a request to VTuber Studio API."""
        if not self._ws:
            return {"error": "Not connected"}

        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"zeilus_{int(time.time()*1000)}",
            "messageType": request_type,
            "data": data or {}
        }

        try:
            await self._ws.send(json.dumps(request))
            response = await self._ws.recv()
            return json.loads(response)
        except Exception as e:
            logger.error(f"API request failed ({request_type}): {e}")
            self._connected = False
            return {"error": str(e)}

    def _send_request_sync(self, request_type: str, data: Dict = None) -> Dict:
        """Thread-safe synchronous request wrapper."""
        try:
            return self._loop.run_coro(self._send_request(request_type, data))
        except Exception as e:
            logger.error(f"Sync request error ({request_type}): {e}")
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def _authenticate_async(self) -> bool:
        """Authenticate with VTuber Studio API."""
        # First, request authentication token
        response = await self._send_request("AuthenticationTokenRequest", {
            "pluginName": self.PLUGIN_NAME,
            "pluginDeveloper": self.PLUGIN_DEVELOPER
        })

        if "error" in response:
            logger.error(f"Auth token request failed: {response}")
            return False

        # Check if we got a token
        data = response.get("data", {})
        token = data.get("authenticationToken")

        if not token:
            # User needs to approve in VTuber Studio
            logger.info("Waiting for user approval in VTuber Studio...")
            return False

        self._auth_token = token

        # Now authenticate with the token
        auth_response = await self._send_request("AuthenticationRequest", {
            "pluginName": self.PLUGIN_NAME,
            "pluginDeveloper": self.PLUGIN_DEVELOPER,
            "authenticationToken": token
        })

        auth_data = auth_response.get("data", {})
        if auth_data.get("authenticated"):
            self._authenticated = True
            logger.info("Authenticated with VTuber Studio")
            return True

        logger.error(f"Authentication failed: {auth_response}")
        return False

    def authenticate(self) -> bool:
        """Authenticate with VTuber Studio (thread-safe)."""
        try:
            return self._loop.run_coro(self._authenticate_async())
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False

    def connect_and_auth(self) -> bool:
        """Connect and authenticate in one call (thread-safe)."""
        if not self.connect():
            return False
        return self.authenticate()

    # -------------------------------------------------------------------------
    # Model Info
    # -------------------------------------------------------------------------

    async def _get_model_info_async(self) -> Dict:
        """Get current model information."""
        response = await self._send_request("CurrentModelRequest")
        data = response.get("data", {})
        self._model_info = data
        return data

    def get_model_info(self) -> Dict:
        """Get current model info (thread-safe)."""
        try:
            return self._loop.run_coro(self._get_model_info_async())
        except Exception as e:
            logger.error(f"Get model info error: {e}")
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Hotkeys (Expressions)
    # -------------------------------------------------------------------------

    async def _get_hotkeys_async(self) -> List[Dict]:
        """Get available hotkeys."""
        response = await self._send_request("HotkeysInCurrentModelRequest")
        data = response.get("data", {})
        hotkeys = data.get("availableHotkeys", [])
        self._hotkeys = hotkeys
        return hotkeys

    def get_hotkeys(self) -> List[Dict]:
        """Get available hotkeys (thread-safe)."""
        try:
            return self._loop.run_coro(self._get_hotkeys_async())
        except Exception as e:
            logger.error(f"Get hotkeys error: {e}")
            return []

    async def _trigger_hotkey_async(self, hotkey_id: str) -> Dict:
        """Trigger a hotkey by ID."""
        response = await self._send_request("HotkeyTriggerRequest", {
            "hotkeyID": hotkey_id
        })
        return response.get("data", {})

    def trigger_hotkey(self, hotkey_id: str) -> Dict:
        """Trigger a hotkey (thread-safe)."""
        try:
            return self._loop.run_coro(self._trigger_hotkey_async(hotkey_id))
        except Exception as e:
            logger.error(f"Trigger hotkey error: {e}")
            return {"error": str(e)}

    def trigger_hotkey_by_name(self, name: str) -> Dict:
        """Trigger a hotkey by name (partial match)."""
        if not self._hotkeys:
            self.get_hotkeys()

        for hotkey in self._hotkeys:
            if name.lower() in hotkey.get("name", "").lower():
                return self.trigger_hotkey(hotkey["hotkeyID"])

        return {"error": f"Hotkey '{name}' not found"}

    # -------------------------------------------------------------------------
    # Expression Control
    # -------------------------------------------------------------------------

    def set_expression(self, expression: str) -> Dict:
        """
        Set avatar expression.
        Tries to find a matching hotkey for the expression.
        """
        # Common expression mappings
        expression_keywords = {
            "happy": ["happy", "smile", "joy"],
            "sad": ["sad", "cry", "tear"],
            "surprised": ["surprise", "shock", "wow"],
            "angry": ["angry", "mad", "rage"],
            "thinking": ["think", "hmm", "ponder"],
            "wink": ["wink", "eye"],
            "blush": ["blush", "embarrass"],
            "neutral": ["neutral", "normal", "reset", "idle"]
        }

        # Get keywords for requested expression
        keywords = expression_keywords.get(expression.lower(), [expression.lower()])

        if not self._hotkeys:
            self.get_hotkeys()

        # Find matching hotkey
        for hotkey in self._hotkeys:
            hotkey_name = hotkey.get("name", "").lower()
            for keyword in keywords:
                if keyword in hotkey_name:
                    return self.trigger_hotkey(hotkey["hotkeyID"])

        return {"error": f"No hotkey found for expression '{expression}'"}

    # -------------------------------------------------------------------------
    # Parameter Control
    # -------------------------------------------------------------------------

    async def _get_parameters_async(self) -> List[Dict]:
        """Get input parameters."""
        response = await self._send_request("InputParameterListRequest")
        data = response.get("data", {})
        params = data.get("defaultParameters", []) + data.get("customParameters", [])
        self._parameters = params
        return params

    def get_parameters(self) -> List[Dict]:
        """Get available parameters (thread-safe)."""
        try:
            return self._loop.run_coro(self._get_parameters_async())
        except Exception as e:
            logger.error(f"Get parameters error: {e}")
            return []

    async def _set_parameter_async(self, param_name: str, value: float) -> Dict:
        """Set a parameter value."""
        response = await self._send_request("InjectParameterDataRequest", {
            "parameterValues": [
                {
                    "id": param_name,
                    "value": value
                }
            ]
        })
        return response.get("data", {})

    def set_parameter(self, param_name: str, value: float) -> Dict:
        """Set a parameter value (thread-safe)."""
        try:
            return self._loop.run_coro(self._set_parameter_async(param_name, value))
        except Exception as e:
            logger.error(f"Set parameter error: {e}")
            return {"error": str(e)}

    # -------------------------------------------------------------------------
    # Lip Sync
    # -------------------------------------------------------------------------

    def start_lip_sync(self, audio_callback: Callable = None):
        """
        Start lip sync animation.

        Args:
            audio_callback: Optional callback that returns audio level (0.0-1.0)
        """
        if self._lip_sync_active:
            return

        self._lip_sync_active = True
        self._lip_sync_errors = 0

        def lip_sync_loop():
            """Animate mouth based on audio or simulated talking."""
            mouth_param = "MouthOpen"

            while self._lip_sync_active:
                try:
                    if audio_callback:
                        level = audio_callback()
                    else:
                        # Simulate talking with random mouth movements
                        level = random.uniform(0.2, 0.8)

                    # Submit to the bridge loop (thread-safe)
                    self._loop.run_coro(
                        self._set_parameter_async(mouth_param, level),
                        timeout=2.0,
                    )

                    # Reset error counter on success
                    self._lip_sync_errors = 0

                except Exception as e:
                    self._lip_sync_errors += 1
                    logger.warning(
                        f"Lip sync error ({self._lip_sync_errors}/"
                        f"{self.LIP_SYNC_MAX_ERRORS}): {e}"
                    )

                    if self._lip_sync_errors >= self.LIP_SYNC_MAX_ERRORS:
                        logger.error(
                            "Too many lip sync errors — stopping lip sync "
                            "and attempting reconnection."
                        )
                        self._lip_sync_active = False
                        # Trigger reconnect in a separate thread to avoid
                        # blocking lip sync shutdown
                        threading.Thread(
                            target=self._try_reconnect, daemon=True
                        ).start()
                        break

                    # Back off on errors
                    time.sleep(self.LIP_SYNC_ERROR_BACKOFF * self._lip_sync_errors)
                    continue

                # Normal interval
                time.sleep(self.LIP_SYNC_INTERVAL)

            # Close mouth when done
            try:
                self._loop.run_coro(
                    self._set_parameter_async(mouth_param, 0),
                    timeout=2.0,
                )
            except Exception:
                pass

        self._lip_sync_thread = threading.Thread(
            target=lip_sync_loop, daemon=True, name="vtuber-lip-sync"
        )
        self._lip_sync_thread.start()
        logger.info("Started lip sync")

    def stop_lip_sync(self):
        """Stop lip sync animation."""
        self._lip_sync_active = False
        if self._lip_sync_thread:
            self._lip_sync_thread.join(timeout=2)
            self._lip_sync_thread = None
        logger.info("Stopped lip sync")

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def speak_with_animation(self, speak_func: Callable, text: str):
        """
        Speak text with lip sync animation.

        Args:
            speak_func: Function that speaks the text (blocks while speaking)
            text: Text to speak
        """
        self.set_expression("talking")
        self.start_lip_sync()

        try:
            speak_func(text)
        finally:
            self.stop_lip_sync()
            self.set_expression("neutral")

    def react_to_emotion(self, emotion: str):
        """
        Set expression based on detected emotion in conversation.

        Args:
            emotion: Detected emotion (happy, sad, surprised, etc.)
        """
        emotion_map = {
            "happy": "happy",
            "joy": "happy",
            "excited": "happy",
            "sad": "sad",
            "disappointed": "sad",
            "angry": "angry",
            "frustrated": "angry",
            "surprised": "surprised",
            "confused": "thinking",
            "curious": "thinking",
            "embarrassed": "blush",
            "shy": "blush"
        }

        expression = emotion_map.get(emotion.lower(), "neutral")
        return self.set_expression(expression)

    def get_status(self) -> Dict:
        """Get current bridge status."""
        return {
            "connected": self._connected,
            "authenticated": self._authenticated,
            "reconnecting": self._reconnecting,
            "model": self._model_info.get("modelName", "Unknown") if self._model_info else "Not loaded",
            "hotkeys_loaded": len(self._hotkeys),
            "lip_sync_active": self._lip_sync_active,
            "bridge_loop_alive": self._loop.running,
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_vtuber_bridge: Optional[VTuberBridge] = None


def get_vtuber_bridge() -> VTuberBridge:
    """Get or create the VTuber bridge singleton."""
    global _vtuber_bridge
    if _vtuber_bridge is None:
        _vtuber_bridge = VTuberBridge()
    return _vtuber_bridge


# =============================================================================
# SIMPLE API
# =============================================================================

def connect_vtuber() -> Dict:
    """Connect to VTuber Studio."""
    bridge = get_vtuber_bridge()
    success = bridge.connect_and_auth()
    return {"success": success, "status": bridge.get_status()}


def set_expression(expression: str) -> Dict:
    """Set avatar expression."""
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return {"error": "Not connected to VTuber Studio"}
    return bridge.set_expression(expression)


def start_talking():
    """Start talking animation."""
    bridge = get_vtuber_bridge()
    if bridge.is_connected():
        bridge.set_expression("talking")
        bridge.start_lip_sync()


def stop_talking():
    """Stop talking animation."""
    bridge = get_vtuber_bridge()
    if bridge.is_connected():
        bridge.stop_lip_sync()
        bridge.set_expression("neutral")


def get_available_expressions() -> List[str]:
    """Get list of available expressions."""
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return list(Expression)

    hotkeys = bridge.get_hotkeys()
    return [h.get("name", "") for h in hotkeys]
