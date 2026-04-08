# mcp_server/__init__.py
"""
Zelius MCP Server - Exposes Zelius capabilities via Model Context Protocol.
"""

from .server import mcp, run_server

__all__ = ['mcp', 'run_server']
