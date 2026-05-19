"""`emodul mcp` subcommand — runs the MCP server on stdio.

Thin Click wrapper so users can launch the server with the same binary as
the rest of the CLI: `emodul mcp`. The same code is also reachable as the
standalone `emodul-mcp` console script (see pyproject.toml).
"""
from __future__ import annotations

import click


def register(cli: click.Group, wrap) -> None:
    @cli.command("mcp")
    def mcp_cmd() -> None:
        """Run the emodul MCP server on stdio (for Claude Desktop, Cursor, etc.).

        Configure your MCP client to spawn this command. Example for Claude
        Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):

            {"mcpServers": {"emodul": {"command": "emodul", "args": ["mcp"]}}}

        Debug locally with the MCP Inspector:

            npx @modelcontextprotocol/inspector emodul mcp
        """
        from emodul.mcp.server import main

        main()
