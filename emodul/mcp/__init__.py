"""MCP (Model Context Protocol) server for emodul.

Exposes ~15 tools so chat-based AI agents (Claude Desktop, Cursor, Continue,
Cline, Zed, JetBrains, OpenCode, Gemini CLI, etc.) can drive the heating
system through their MCP client without needing a CLI.

Entry point: `emodul mcp` (subcommand on the main CLI) or the standalone
`emodul-mcp` console script. Both call `emodul.mcp.server:main`.
"""
