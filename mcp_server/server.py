# mcp_server/server.py - Zelius MCP Server
"""
Model Context Protocol server for Zeilus.
Exposes research memory, tool memory, automation features as MCP resources and tools.

Run with: python -m mcp_server.server
Or configure in Claude Desktop/Cursor.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("MCP not installed. Run: pip install mcp")
    sys.exit(1)

from config import StorageConfig, AgentConfig
from core.research_memory import ResearchMemory
from core.tool_memory import ToolMemory
from modules.automation_scheduler import AutomationScheduler, parse_schedule_from_text

# New integrations
from integrations.desktop_controller import DesktopController
from integrations.vtuber_bridge import VTuberBridge, get_vtuber_bridge
from integrations.web_browser import WebSearch, WebBrowser, PageFetcher
from integrations.screen_avatar import (
    ScreenAvatar, get_screen_avatar,
    show_avatar, hide_avatar, set_mood, get_avatar_status
)

logger = logging.getLogger(__name__)

# =============================================================================
# MCP SERVER SETUP
# =============================================================================

mcp = FastMCP(
    name="Zeilus",
    description="Zeilus AI Assistant - Memory, Automation, Desktop Control, VTuber Avatar capabilities"
)

# Initialize components
_research_memory: Optional[ResearchMemory] = None
_tool_memory: Optional[ToolMemory] = None
_automation: Optional[AutomationScheduler] = None
_desktop: Optional[DesktopController] = None
_web_browser: Optional[WebBrowser] = None


def get_research_memory() -> ResearchMemory:
    """Lazy initialization of research memory."""
    global _research_memory
    if _research_memory is None:
        _research_memory = ResearchMemory()
    return _research_memory


def get_tool_memory() -> ToolMemory:
    """Lazy initialization of tool memory."""
    global _tool_memory
    if _tool_memory is None:
        _tool_memory = ToolMemory()
    return _tool_memory


def get_automation() -> AutomationScheduler:
    """Lazy initialization of automation scheduler."""
    global _automation
    if _automation is None:
        _automation = AutomationScheduler()
    return _automation


def get_desktop() -> DesktopController:
    """Lazy initialization of desktop controller."""
    global _desktop
    if _desktop is None:
        _desktop = DesktopController()
    return _desktop


def get_web_browser() -> WebBrowser:
    """Lazy initialization of web browser."""
    global _web_browser
    if _web_browser is None:
        _web_browser = WebBrowser(headless=True)
        _web_browser.start()
    return _web_browser


# =============================================================================
# RESOURCES - Read-only data endpoints
# =============================================================================

@mcp.resource("zeilus://memory/research")
async def get_all_research() -> str:
    """
    Get all research topics and their summaries.
    Returns a JSON list of research topics with session counts and findings.
    """
    memory = get_research_memory()
    topics = memory.get_all_topics()
    return json.dumps(topics, indent=2)


@mcp.resource("zeilus://memory/research/{topic}")
async def get_research_topic(topic: str) -> str:
    """
    Get detailed research history for a specific topic.
    Includes all sessions, queries, and findings.
    """
    memory = get_research_memory()
    history = memory.get_topic_history(topic)
    if history:
        return json.dumps(history, indent=2)
    return json.dumps({"error": f"Topic '{topic}' not found"})


@mcp.resource("zeilus://memory/tools")
async def get_tool_stats() -> str:
    """
    Get tool usage statistics.
    Shows which tools are used most, success rates, and recent usage.
    """
    memory = get_tool_memory()
    stats = memory.get_all_tool_stats()
    return json.dumps(stats, indent=2)


@mcp.resource("zeilus://memory/tools/{tool_name}")
async def get_tool_detail(tool_name: str) -> str:
    """Get detailed stats for a specific tool."""
    memory = get_tool_memory()
    stats = memory.get_tool_stats(tool_name)
    if stats:
        return json.dumps(stats, indent=2)
    return json.dumps({"error": f"Tool '{tool_name}' not tracked"})


@mcp.resource("zeilus://automation/tasks")
async def get_scheduled_tasks() -> str:
    """
    Get all scheduled/recurring automation tasks.
    Shows task names, schedules, next run times, and status.
    """
    scheduler = get_automation()
    tasks = scheduler.get_all_tasks()
    return json.dumps(tasks, indent=2)


@mcp.resource("zeilus://automation/schedule")
async def get_schedule_overview() -> str:
    """Get a human-readable overview of the automation schedule."""
    scheduler = get_automation()
    return scheduler.get_schedule_summary()


# =============================================================================
# TOOLS - Actions that can be performed
# =============================================================================

@mcp.tool()
async def start_research(topic: str) -> str:
    """
    Start a new research session on a topic.
    
    Args:
        topic: The topic to research (e.g., "quantum computing", "machine learning")
    
    Returns:
        Confirmation with session ID
    """
    memory = get_research_memory()
    session = memory.start_session(topic)
    return json.dumps({
        "success": True,
        "session_id": session.id,
        "topic": topic,
        "message": f"Started research session on '{topic}'"
    })


@mcp.tool()
async def add_research_finding(finding: str, topic: Optional[str] = None) -> str:
    """
    Add a finding to the current research session.
    
    Args:
        finding: The finding or insight to record
        topic: Optional topic name (uses active session if not provided)
    
    Returns:
        Confirmation
    """
    memory = get_research_memory()
    
    if topic:
        # Find or create session for topic
        existing = memory.get_topic(topic)
        if existing:
            session = existing.get_active_session()
            if not session:
                session = memory.start_session(topic)
        else:
            session = memory.start_session(topic)
        memory.add_finding(finding, session.id)
    else:
        if memory.active_session:
            memory.add_finding(finding)
        else:
            return json.dumps({
                "success": False,
                "error": "No active research session. Start one with start_research first."
            })
    
    return json.dumps({
        "success": True,
        "message": f"Added finding to research"
    })


@mcp.tool()
async def end_research(summary: Optional[str] = None) -> str:
    """
    End the current research session.
    
    Args:
        summary: Optional summary of the session
    
    Returns:
        Session summary
    """
    memory = get_research_memory()
    session = memory.end_session(summary=summary)
    
    if session:
        return json.dumps({
            "success": True,
            "session_id": session.id,
            "topic": session.topic,
            "duration_minutes": session.duration_minutes,
            "findings_count": len(session.findings),
            "queries_count": len(session.queries)
        })
    
    return json.dumps({
        "success": False,
        "error": "No active session to end"
    })


@mcp.tool()
async def get_research_summary(topic: str) -> str:
    """
    Get a summary of all research on a topic.
    
    Args:
        topic: The topic to summarize
    
    Returns:
        Markdown-formatted summary
    """
    memory = get_research_memory()
    summary = memory.generate_topic_summary(topic)
    return summary


@mcp.tool()
async def search_research(query: str) -> str:
    """
    Search across all research (topics, queries, findings).
    
    Args:
        query: Search term
    
    Returns:
        Matching results
    """
    memory = get_research_memory()
    results = memory.search_research(query)
    return json.dumps(results, indent=2)


@mcp.tool()
async def schedule_automation(
    name: str,
    action: str,
    schedule_text: str,
    action_config: Optional[str] = None,
    summary_time: Optional[str] = None
) -> str:
    """
    Schedule a recurring automation task.
    
    Args:
        name: Task name (e.g., "Wednesday Research")
        action: Action type - 'research', 'summary', 'reminder', or 'custom'
        schedule_text: Natural language schedule (e.g., "every wednesday from 5 am to 6 pm")
        action_config: JSON string with action parameters (e.g., '{"topic": "AI"}')
        summary_time: When to send summary (e.g., "6 pm" or cron "0 18 * * WED")
    
    Returns:
        Task ID and confirmation
    """
    scheduler = get_automation()
    
    # Parse schedule from text
    schedule_params = parse_schedule_from_text(schedule_text)
    
    # Parse action config
    config = {}
    if action_config:
        try:
            config = json.loads(action_config)
        except json.JSONDecodeError:
            config = {"raw": action_config}
    
    # Parse summary schedule
    summary_schedule = ""
    if summary_time:
        if ":" in summary_time or "*" in summary_time:
            summary_schedule = summary_time  # Cron expression
        else:
            # Parse simple time like "6 pm"
            summary_params = parse_schedule_from_text(f"at {summary_time}")
            # Convert to cron for the same days
            hour = int(summary_params["end_time"].split(":")[0])
            if schedule_params["days_of_week"]:
                days = ",".join(schedule_params["days_of_week"])
                summary_schedule = f"0 {hour} * * {days}"
            else:
                summary_schedule = f"0 {hour} * * *"
    
    task_id = scheduler.add_recurring_task(
        name=name,
        action_type=action,
        action_config=config,
        recurrence_type=schedule_params["recurrence_type"],
        days_of_week=schedule_params["days_of_week"],
        start_time=schedule_params["start_time"],
        end_time=schedule_params["end_time"],
        summary_schedule=summary_schedule,
        description=f"Scheduled: {schedule_text}"
    )
    
    task = scheduler.get_task(task_id)
    
    return json.dumps({
        "success": True,
        "task_id": task_id,
        "name": name,
        "schedule": scheduler._describe_schedule(task),
        "next_run": task.next_run,
        "summary_enabled": bool(summary_schedule)
    })


@mcp.tool()
async def list_automations() -> str:
    """
    List all scheduled automation tasks.
    
    Returns:
        List of tasks with their schedules and status
    """
    scheduler = get_automation()
    tasks = scheduler.get_all_tasks()
    return json.dumps(tasks, indent=2)


@mcp.tool()
async def pause_automation(task_id: str) -> str:
    """
    Pause an automation task.
    
    Args:
        task_id: ID of the task to pause
    
    Returns:
        Confirmation
    """
    scheduler = get_automation()
    if scheduler.pause_task(task_id):
        return json.dumps({"success": True, "message": f"Paused task {task_id}"})
    return json.dumps({"success": False, "error": f"Task {task_id} not found"})


@mcp.tool()
async def resume_automation(task_id: str) -> str:
    """
    Resume a paused automation task.
    
    Args:
        task_id: ID of the task to resume
    
    Returns:
        Confirmation
    """
    scheduler = get_automation()
    if scheduler.resume_task(task_id):
        return json.dumps({"success": True, "message": f"Resumed task {task_id}"})
    return json.dumps({"success": False, "error": f"Task {task_id} not found"})


@mcp.tool()
async def delete_automation(task_id: str) -> str:
    """
    Delete an automation task.
    
    Args:
        task_id: ID of the task to delete
    
    Returns:
        Confirmation
    """
    scheduler = get_automation()
    if scheduler.delete_task(task_id):
        return json.dumps({"success": True, "message": f"Deleted task {task_id}"})
    return json.dumps({"success": False, "error": f"Task {task_id} not found"})


@mcp.tool()
async def get_tool_usage_summary() -> str:
    """
    Get a summary of tool usage patterns.
    
    Returns:
        Markdown summary of most used tools and recent usage
    """
    memory = get_tool_memory()
    return memory.generate_tool_summary()


@mcp.tool()
async def log_tool_usage(
    tool_name: str,
    result: str = "success",
    context: str = ""
) -> str:
    """
    Log a tool usage (for tracking patterns).
    
    Args:
        tool_name: Name of the tool used
        result: 'success', 'failed', or 'partial'
        context: What prompted this tool usage
    
    Returns:
        Confirmation
    """
    memory = get_tool_memory()
    memory.log_tool_use(tool_name, result=result, context=context)
    return json.dumps({
        "success": True,
        "message": f"Logged {tool_name} usage"
    })


# =============================================================================
# PROMPTS - Reusable interaction templates
# =============================================================================

@mcp.prompt()
async def research_deep_dive(topic: str) -> str:
    """
    Template for starting a comprehensive research session.
    Use this when you want to deeply research a topic with Zeilus tracking.
    """
    return f"""I want to do a deep research session on: {topic}

Please help me:
1. Start tracking this research session
2. Search for key information about {topic}
3. Record important findings as we go
4. At the end, provide a summary

Let's start by recording that we're beginning research on {topic}."""


@mcp.prompt()
async def schedule_recurring_task(task_description: str) -> str:
    """
    Template for setting up a recurring automation task.
    """
    return f"""I want to set up a recurring automated task: {task_description}

Please help me configure:
1. The schedule (when should it run?)
2. The action to perform
3. When to receive summaries
4. Any specific parameters

Parse my description and set up the automation."""


@mcp.prompt()
async def weekly_research_summary() -> str:
    """
    Template for generating a weekly research summary.
    """
    return """Please provide a summary of this week's research activities:

1. What topics were researched?
2. Key findings from each topic
3. Time spent on research
4. Suggested next steps

Pull this from the research memory and format it nicely."""


# =============================================================================
# DESKTOP CONTROL TOOLS
# =============================================================================

@mcp.tool()
async def open_application(app_name: str) -> str:
    """
    Open an application on the desktop.
    
    Args:
        app_name: Name of the app (e.g., 'notepad', 'chrome', 'vscode', 'discord', 'spotify')
    
    Returns:
        Confirmation with process info
    """
    desktop = get_desktop()
    result = desktop.open_app(app_name)
    return json.dumps(result)


@mcp.tool()
async def list_available_apps() -> str:
    """
    List all applications that can be opened by name.
    
    Returns:
        List of app names
    """
    desktop = get_desktop()
    apps = desktop.list_available_apps()
    return json.dumps({"apps": apps})


@mcp.tool()
async def run_system_command(command: str) -> str:
    """
    Run a system command (be careful!).
    
    Args:
        command: Command to run in the shell
    
    Returns:
        Command output
    """
    desktop = get_desktop()
    result = desktop.run_command(command)
    return json.dumps(result)


@mcp.tool()
async def take_desktop_screenshot(filename: Optional[str] = None) -> str:
    """
    Take a screenshot of the desktop.
    
    Args:
        filename: Optional filename for the screenshot
    
    Returns:
        Path to saved screenshot
    """
    desktop = get_desktop()
    result = desktop.take_screenshot(filename)
    return json.dumps(result)


@mcp.tool()
async def type_keyboard_text(text: str) -> str:
    """
    Type text using the keyboard.
    
    Args:
        text: Text to type
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.type_text(text)
    return json.dumps(result)


@mcp.tool()
async def press_keyboard_key(key: str) -> str:
    """
    Press a keyboard key.
    
    Args:
        key: Key to press (e.g., 'enter', 'tab', 'escape')
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.press_key(key)
    return json.dumps(result)


@mcp.tool()
async def keyboard_hotkey(keys: str) -> str:
    """
    Press a keyboard hotkey combination.
    
    Args:
        keys: Keys separated by + (e.g., 'ctrl+c', 'alt+tab', 'win+d')
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    key_list = [k.strip() for k in keys.split('+')]
    result = desktop.hotkey(*key_list)
    return json.dumps(result)


@mcp.tool()
async def list_open_windows() -> str:
    """
    List all open windows on the desktop.
    
    Returns:
        List of window titles
    """
    desktop = get_desktop()
    windows = desktop.list_windows()
    return json.dumps(windows)


@mcp.tool()
async def focus_window(title: str) -> str:
    """
    Focus/bring to front a window by title.
    
    Args:
        title: Window title (partial match)
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.focus_window(title)
    return json.dumps(result)


@mcp.tool()
async def close_application_window(title: str) -> str:
    """
    Close a window by title.
    
    Args:
        title: Window title (partial match)
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.close_window(title)
    return json.dumps(result)


@mcp.tool()
async def get_system_info() -> str:
    """
    Get system information (CPU, memory, disk usage).
    
    Returns:
        System stats
    """
    desktop = get_desktop()
    info = desktop.get_system_info()
    return json.dumps(info)


@mcp.tool()
async def open_url_in_browser(url: str, browser: Optional[str] = None) -> str:
    """
    Open a URL in the default or specified browser.
    
    Args:
        url: URL to open
        browser: Optional browser name (chrome, firefox, edge)
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.open_url(url, browser)
    return json.dumps(result)


@mcp.tool()
async def open_file(file_path: str) -> str:
    """
    Open a file with its default application.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.open_file(file_path)
    return json.dumps(result)


@mcp.tool()
async def open_folder(folder_path: str) -> str:
    """
    Open a folder in File Explorer.
    
    Args:
        folder_path: Path to the folder
    
    Returns:
        Confirmation
    """
    desktop = get_desktop()
    result = desktop.open_folder(folder_path)
    return json.dumps(result)


# =============================================================================
# VTUBER STUDIO TOOLS
# =============================================================================

@mcp.tool()
async def connect_vtuber_studio() -> str:
    """
    Connect to VTuber Studio.
    VTuber Studio must be running with API enabled (Settings > Start API).
    
    Returns:
        Connection status
    """
    bridge = get_vtuber_bridge()
    success = bridge.connect_and_auth()
    return json.dumps({
        "success": success,
        "status": bridge.get_status()
    })


@mcp.tool()
async def get_vtuber_status() -> str:
    """
    Get VTuber Studio connection status.
    
    Returns:
        Connection and model info
    """
    bridge = get_vtuber_bridge()
    return json.dumps(bridge.get_status())


@mcp.tool()
async def set_avatar_expression(expression: str) -> str:
    """
    Set the avatar's expression.
    
    Args:
        expression: Expression name (happy, sad, surprised, angry, thinking, wink, blush, neutral)
    
    Returns:
        Confirmation
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio. Call connect_vtuber_studio first."})
    result = bridge.set_expression(expression)
    return json.dumps(result)


@mcp.tool()
async def trigger_avatar_hotkey(hotkey_name: str) -> str:
    """
    Trigger a VTuber Studio hotkey.
    
    Args:
        hotkey_name: Name of the hotkey to trigger (partial match)
    
    Returns:
        Confirmation
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    result = bridge.trigger_hotkey_by_name(hotkey_name)
    return json.dumps(result)


@mcp.tool()
async def list_avatar_hotkeys() -> str:
    """
    List available hotkeys for the current VTuber model.
    
    Returns:
        List of hotkey names
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    hotkeys = bridge.get_hotkeys()
    names = [h.get("name", "") for h in hotkeys]
    return json.dumps({"hotkeys": names})


@mcp.tool()
async def get_avatar_model_info() -> str:
    """
    Get information about the currently loaded VTuber model.
    
    Returns:
        Model name and details
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    info = bridge.get_model_info()
    return json.dumps(info)


@mcp.tool()
async def start_avatar_talking() -> str:
    """
    Start the avatar's talking/lip-sync animation.
    Use this before speaking to make the avatar animate.
    
    Returns:
        Confirmation
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    bridge.set_expression("talking")
    bridge.start_lip_sync()
    return json.dumps({"success": True, "message": "Avatar is now talking"})


@mcp.tool()
async def stop_avatar_talking() -> str:
    """
    Stop the avatar's talking animation and return to neutral.
    
    Returns:
        Confirmation
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    bridge.stop_lip_sync()
    bridge.set_expression("neutral")
    return json.dumps({"success": True, "message": "Avatar stopped talking"})


@mcp.tool()
async def react_avatar_emotion(emotion: str) -> str:
    """
    Make the avatar react to an emotion.
    
    Args:
        emotion: Emotion to express (happy, sad, excited, confused, etc.)
    
    Returns:
        Confirmation
    """
    bridge = get_vtuber_bridge()
    if not bridge.is_connected():
        return json.dumps({"error": "Not connected to VTuber Studio"})
    result = bridge.react_to_emotion(emotion)
    return json.dumps(result)


# =============================================================================
# ON-SCREEN AVATAR TOOLS (VTuber Studio Presence)
# =============================================================================

@mcp.resource("zeilus://avatar/status")
async def get_avatar_status_resource() -> str:
    """
    Get the on-screen avatar status.
    Shows connection state, current expression, talking state, and model info.
    """
    status = get_avatar_status()
    return json.dumps(status, indent=2)


@mcp.tool()
async def show_screen_avatar() -> str:
    """
    Show the on-screen avatar by connecting to VTuber Studio.
    VTuber Studio must be running with API enabled (port 8001).

    Returns:
        Connection status and avatar info
    """
    result = show_avatar()
    return json.dumps(result)


@mcp.tool()
async def hide_screen_avatar() -> str:
    """
    Hide the on-screen avatar by disconnecting from VTuber Studio.

    Returns:
        Confirmation
    """
    result = hide_avatar()
    return json.dumps(result)


@mcp.tool()
async def set_screen_avatar_mood(mood: str, duration: float = 4.0) -> str:
    """
    Set the on-screen avatar's mood/expression.

    Args:
        mood: Mood to express (happy, sad, surprised, angry, thinking, wink, blush, neutral)
        duration: How long to hold the expression before reverting to neutral (seconds)

    Returns:
        Confirmation
    """
    result = set_mood(mood, duration)
    return json.dumps(result)


@mcp.tool()
async def screen_avatar_speak(
    text: str,
    emotion: Optional[str] = None,
    intensity: float = 0.5,
    valence: float = 0.5,
    arousal: float = 0.3,
) -> str:
    """
    Make the on-screen avatar speak with lip-sync animation.
    Uses ElevenLabs voice synthesis if available.

    Args:
        text: Text to speak
        emotion: Optional emotion to express while speaking (auto-detected if not provided)
        intensity: How strongly to express the emotion (0.0-1.0)
        valence: Emotional valence, negative (-1) to positive (+1)
        arousal: Emotional arousal, calm (0) to energetic (1)

    Returns:
        Confirmation
    """
    avatar = get_screen_avatar()
    if not avatar.is_active:
        return json.dumps({"error": "Avatar not active. Call show_screen_avatar first."})

    # Try to use voice agent for actual speech
    try:
        from core.voice import VoiceAgent
        voice = VoiceAgent(auto_play=True)
        if voice.enabled:
            avatar.speak_async_with_animation(voice.speak, text, emotion)
            return json.dumps({"success": True, "message": f"Avatar speaking: {text[:50]}..."})
    except Exception as e:
        logger.debug(f"Voice not available: {e}")

    # Fallback: just animate without actual audio
    if emotion:
        avatar.react_to_emotion(emotion, intensity=intensity)
    avatar.start_talking()

    import asyncio
    await asyncio.sleep(len(text) * 0.06)  # Approximate speech duration

    avatar.stop_talking()
    return json.dumps({"success": True, "message": f"Avatar animated for: {text[:50]}..."})


# =============================================================================
# WEB BROWSING TOOLS
# =============================================================================

@mcp.tool()
async def web_search(query: str, max_results: int = 10) -> str:
    """
    Search the web using DuckDuckGo.
    
    Args:
        query: Search query
        max_results: Maximum number of results (default 10)
    
    Returns:
        List of search results with title, link, snippet
    """
    results = WebSearch.search(query, max_results)
    return json.dumps(results, indent=2)


@mcp.tool()
async def search_news(query: str, max_results: int = 10) -> str:
    """
    Search for news articles.
    
    Args:
        query: Search query
        max_results: Maximum number of results
    
    Returns:
        List of news articles
    """
    results = WebSearch.search_news(query, max_results)
    return json.dumps(results, indent=2)


@mcp.tool()
async def search_images(query: str, max_results: int = 10) -> str:
    """
    Search for images.
    
    Args:
        query: Search query
        max_results: Maximum number of results
    
    Returns:
        List of image results
    """
    results = WebSearch.search_images(query, max_results)
    return json.dumps(results, indent=2)


@mcp.tool()
async def fetch_webpage(url: str) -> str:
    """
    Fetch and extract text from a webpage (no browser needed).
    
    Args:
        url: URL to fetch
    
    Returns:
        Page title and text content
    """
    result = PageFetcher.fetch(url)
    return json.dumps(result)


@mcp.tool()
async def browse_to_url(url: str) -> str:
    """
    Navigate to a URL using headless browser and get content.
    
    Args:
        url: URL to browse to
    
    Returns:
        Page content including title, headings, text, and links
    """
    browser = get_web_browser()
    result = browser.get_page_content(url)
    return json.dumps(result)


@mcp.tool()
async def browser_click(selector: str) -> str:
    """
    Click an element on the current web page.
    
    Args:
        selector: CSS selector of element to click
    
    Returns:
        Confirmation
    """
    browser = get_web_browser()
    result = browser.click(selector)
    return json.dumps(result)


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    """
    Type text into an input field on the current web page.
    
    Args:
        selector: CSS selector of input element
        text: Text to type
    
    Returns:
        Confirmation
    """
    browser = get_web_browser()
    result = browser.type_text(selector, text)
    return json.dumps(result)


@mcp.tool()
async def browser_screenshot(filename: Optional[str] = None) -> str:
    """
    Take a screenshot of the current web page.
    
    Args:
        filename: Optional filename for the screenshot
    
    Returns:
        Path to saved screenshot
    """
    browser = get_web_browser()
    result = browser.screenshot(filename)
    return json.dumps(result)


@mcp.tool()
async def browser_scroll(direction: str = "down") -> str:
    """
    Scroll the current web page.
    
    Args:
        direction: Scroll direction (up, down, top, bottom)
    
    Returns:
        Confirmation
    """
    browser = get_web_browser()
    result = browser.scroll(direction)
    return json.dumps(result)


# =============================================================================
# SERVER RUNNER
# =============================================================================

def run_server():
    """Run the MCP server via stdio."""
    import asyncio
    mcp.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()
