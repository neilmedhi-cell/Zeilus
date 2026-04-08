# integrations/desktop_controller.py - Desktop Automation
"""
Desktop automation for opening apps, controlling windows, and running commands.
Provides autonomous control over the Windows desktop.
"""

import os
import subprocess
import logging
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False
    logging.warning("pyautogui not installed. Some desktop features disabled.")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


# =============================================================================
# APP REGISTRY - Common applications and their paths
# =============================================================================

class AppRegistry:
    """Registry of common applications and their executable paths."""
    
    # Common Windows applications
    APPS = {
        # System tools
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "terminal": "wt.exe",  # Windows Terminal
        "task_manager": "taskmgr.exe",
        "control_panel": "control.exe",
        "settings": "ms-settings:",
        
        # Browsers
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "brave": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        
        # Development
        "vscode": r"C:\Users\{username}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        "code": "code",  # If in PATH
        "git_bash": r"C:\Program Files\Git\git-bash.exe",
        
        # Communication
        "discord": r"C:\Users\{username}\AppData\Local\Discord\Update.exe --processStart Discord.exe",
        "slack": r"C:\Users\{username}\AppData\Local\slack\slack.exe",
        "teams": r"C:\Users\{username}\AppData\Local\Microsoft\Teams\current\Teams.exe",
        "zoom": r"C:\Users\{username}\AppData\Roaming\Zoom\bin\Zoom.exe",
        
        # Media
        "spotify": r"C:\Users\{username}\AppData\Roaming\Spotify\Spotify.exe",
        "vlc": r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        
        # Productivity
        "word": r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        "excel": r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        "powerpoint": r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        
        # Gaming/VTubing
        "steam": r"C:\Program Files (x86)\Steam\steam.exe",
        "obs": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        "vtuber_studio": r"C:\Program Files (x86)\Steam\steamapps\common\VTube Studio\VTube Studio.exe",
        
        # Utilities
        "paint": "mspaint.exe",
        "snipping_tool": "SnippingTool.exe",
    }
    
    @classmethod
    def get_path(cls, app_name: str) -> Optional[str]:
        """Get the path for an app, with username substitution."""
        app_key = app_name.lower().replace(" ", "_").replace("-", "_")
        
        if app_key in cls.APPS:
            path = cls.APPS[app_key]
            # Substitute username
            username = os.environ.get('USERNAME', os.environ.get('USER', 'User'))
            path = path.replace("{username}", username)
            return path
        
        # Try alternative names
        for key, value in cls.APPS.items():
            if app_name.lower() in key or key in app_name.lower():
                path = value.replace("{username}", os.environ.get('USERNAME', 'User'))
                return path
        
        return None
    
    @classmethod
    def list_apps(cls) -> List[str]:
        """Get list of registered app names."""
        return list(cls.APPS.keys())


# =============================================================================
# DESKTOP CONTROLLER
# =============================================================================

@dataclass
class WindowInfo:
    """Information about a window."""
    title: str
    pid: int
    executable: str
    visible: bool = True


class DesktopController:
    """
    Controls desktop automation on Windows.
    Opens apps, manages windows, runs commands.
    """
    
    def __init__(self):
        self.app_registry = AppRegistry()
        self._screenshot_dir = Path("screenshots")
        self._screenshot_dir.mkdir(exist_ok=True)
        
        # Configure pyautogui safety
        if HAS_PYAUTOGUI:
            pyautogui.PAUSE = 0.5  # Pause between actions
            pyautogui.FAILSAFE = True  # Move mouse to corner to abort
        
        logger.info("DesktopController initialized")
    
    # -------------------------------------------------------------------------
    # App Launching
    # -------------------------------------------------------------------------
    
    def open_app(self, app_name: str, args: List[str] = None) -> Dict[str, Any]:
        """
        Open an application by name.
        
        Args:
            app_name: Name of the app (e.g., "notepad", "chrome", "vscode")
            args: Optional arguments to pass to the app
            
        Returns:
            Dict with success status and process info
        """
        # Try to get path from registry
        app_path = self.app_registry.get_path(app_name)
        
        if not app_path:
            # Try running directly (might be in PATH)
            app_path = app_name
        
        try:
            # Handle URL-style launchers (like ms-settings:)
            if app_path.startswith("ms-"):
                subprocess.Popen(["start", "", app_path], shell=True)
                return {
                    "success": True,
                    "app": app_name,
                    "method": "url_launcher"
                }
            
            # Build command
            cmd = [app_path]
            if args:
                cmd.extend(args)
            
            # Special handling for some apps
            if "--processStart" in app_path:
                # Discord-style launcher
                parts = app_path.split()
                process = subprocess.Popen(parts, shell=True)
            else:
                process = subprocess.Popen(cmd, shell=True if ".exe" not in app_path.lower() else False)
            
            logger.info(f"Opened {app_name} (PID: {process.pid})")
            
            return {
                "success": True,
                "app": app_name,
                "pid": process.pid,
                "path": app_path
            }
            
        except FileNotFoundError:
            # Try with 'start' command as fallback
            try:
                subprocess.Popen(f'start "" "{app_path}"', shell=True)
                return {
                    "success": True,
                    "app": app_name,
                    "method": "start_command"
                }
            except Exception as e:
                logger.error(f"Failed to open {app_name}: {e}")
                return {
                    "success": False,
                    "error": f"Could not find or open '{app_name}'"
                }
        except Exception as e:
            logger.error(f"Error opening {app_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def open_url(self, url: str, browser: str = None) -> Dict[str, Any]:
        """Open a URL in the default or specified browser."""
        try:
            if browser:
                result = self.open_app(browser, [url])
            else:
                # Use default browser
                import webbrowser
                webbrowser.open(url)
                result = {"success": True, "url": url, "method": "default_browser"}
            
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def open_file(self, file_path: str) -> Dict[str, Any]:
        """Open a file with its default application."""
        try:
            os.startfile(file_path)
            return {"success": True, "file": file_path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def open_folder(self, folder_path: str) -> Dict[str, Any]:
        """Open a folder in Explorer."""
        try:
            subprocess.Popen(["explorer", folder_path])
            return {"success": True, "folder": folder_path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Window Management
    # -------------------------------------------------------------------------
    
    def list_windows(self) -> List[Dict]:
        """Get list of open windows."""
        if not HAS_PSUTIL:
            return [{"error": "psutil not installed"}]
        
        windows = []
        try:
            import ctypes
            from ctypes import wintypes
            
            user32 = ctypes.windll.user32
            EnumWindows = user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            GetWindowText = user32.GetWindowTextW
            GetWindowTextLength = user32.GetWindowTextLengthW
            IsWindowVisible = user32.IsWindowVisible
            
            def callback(hwnd, lParam):
                if IsWindowVisible(hwnd):
                    length = GetWindowTextLength(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        GetWindowText(hwnd, buff, length + 1)
                        if buff.value:
                            windows.append({
                                "title": buff.value,
                                "hwnd": hwnd,
                                "visible": True
                            })
                return True
            
            EnumWindows(EnumWindowsProc(callback), 0)
            
        except Exception as e:
            logger.error(f"Error listing windows: {e}")
            return [{"error": str(e)}]
        
        return windows
    
    def focus_window(self, title: str) -> Dict[str, Any]:
        """Focus a window by title (partial match)."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            
            windows = self.list_windows()
            for win in windows:
                if title.lower() in win.get("title", "").lower():
                    hwnd = win.get("hwnd")
                    if hwnd:
                        user32.SetForegroundWindow(hwnd)
                        return {"success": True, "window": win["title"]}
            
            return {"success": False, "error": f"Window '{title}' not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def minimize_window(self, title: str) -> Dict[str, Any]:
        """Minimize a window by title."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SW_MINIMIZE = 6
            
            windows = self.list_windows()
            for win in windows:
                if title.lower() in win.get("title", "").lower():
                    hwnd = win.get("hwnd")
                    if hwnd:
                        user32.ShowWindow(hwnd, SW_MINIMIZE)
                        return {"success": True, "window": win["title"]}
            
            return {"success": False, "error": f"Window '{title}' not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def close_window(self, title: str) -> Dict[str, Any]:
        """Close a window by title."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            WM_CLOSE = 0x0010
            
            windows = self.list_windows()
            for win in windows:
                if title.lower() in win.get("title", "").lower():
                    hwnd = win.get("hwnd")
                    if hwnd:
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        return {"success": True, "window": win["title"]}
            
            return {"success": False, "error": f"Window '{title}' not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Screenshot
    # -------------------------------------------------------------------------
    
    def take_screenshot(self, filename: str = None, region: tuple = None) -> Dict[str, Any]:
        """
        Take a screenshot.
        
        Args:
            filename: Optional filename (auto-generated if not provided)
            region: Optional (x, y, width, height) tuple for partial screenshot
            
        Returns:
            Dict with path to screenshot
        """
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            if not filename:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
            
            filepath = self._screenshot_dir / filename
            
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()
            
            screenshot.save(filepath)
            
            return {
                "success": True,
                "path": str(filepath),
                "size": (screenshot.width, screenshot.height)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Keyboard & Mouse
    # -------------------------------------------------------------------------
    
    def type_text(self, text: str, interval: float = 0.05) -> Dict[str, Any]:
        """Type text using keyboard."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            pyautogui.typewrite(text, interval=interval)
            return {"success": True, "typed": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            pyautogui.press(key)
            return {"success": True, "key": key}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def hotkey(self, *keys) -> Dict[str, Any]:
        """Press a hotkey combination (e.g., ctrl+c)."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            pyautogui.hotkey(*keys)
            return {"success": True, "keys": keys}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def click(self, x: int = None, y: int = None, button: str = "left") -> Dict[str, Any]:
        """Click at coordinates or current position."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            if x is not None and y is not None:
                pyautogui.click(x, y, button=button)
            else:
                pyautogui.click(button=button)
            return {"success": True, "position": (x, y), "button": button}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def move_mouse(self, x: int, y: int, duration: float = 0.5) -> Dict[str, Any]:
        """Move mouse to coordinates."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"success": True, "position": (x, y)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # System Commands
    # -------------------------------------------------------------------------
    
    def run_command(self, command: str, shell: bool = True, timeout: int = 30) -> Dict[str, Any]:
        """
        Run a system command.
        
        Args:
            command: Command to run
            shell: Whether to run in shell
            timeout: Timeout in seconds
            
        Returns:
            Dict with output and return code
        """
        try:
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_running_processes(self, name_filter: str = None) -> List[Dict]:
        """Get list of running processes."""
        if not HAS_PSUTIL:
            return [{"error": "psutil not installed"}]
        
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'status']):
                info = proc.info
                if name_filter:
                    if name_filter.lower() not in info['name'].lower():
                        continue
                processes.append(info)
        except Exception as e:
            logger.error(f"Error getting processes: {e}")
        
        return processes
    
    def kill_process(self, pid: int = None, name: str = None) -> Dict[str, Any]:
        """Kill a process by PID or name."""
        if not HAS_PSUTIL:
            return {"success": False, "error": "psutil not installed"}
        
        try:
            if pid:
                proc = psutil.Process(pid)
                proc.terminate()
                return {"success": True, "killed_pid": pid}
            elif name:
                killed = []
                for proc in psutil.process_iter(['pid', 'name']):
                    if name.lower() in proc.info['name'].lower():
                        proc.terminate()
                        killed.append(proc.info['pid'])
                return {"success": True, "killed_pids": killed}
            else:
                return {"success": False, "error": "Provide pid or name"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # System Info
    # -------------------------------------------------------------------------
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        info = {
            "platform": os.name,
            "username": os.environ.get("USERNAME", "unknown"),
            "home": os.environ.get("USERPROFILE", "unknown"),
        }
        
        if HAS_PSUTIL:
            info.update({
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent if os.name != 'nt' else psutil.disk_usage('C:').percent
            })
        
        return info
    
    def get_screen_size(self) -> Dict[str, int]:
        """Get screen dimensions."""
        if HAS_PYAUTOGUI:
            size = pyautogui.size()
            return {"width": size.width, "height": size.height}
        return {"width": 1920, "height": 1080}  # Default fallback
    
    # -------------------------------------------------------------------------
    # Available Apps
    # -------------------------------------------------------------------------
    
    def list_available_apps(self) -> List[str]:
        """Get list of apps that can be opened."""
        return self.app_registry.list_apps()
