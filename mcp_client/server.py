"""MCP server connection handlers supporting SSE, stdio, and HTTP."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from livekit.agents.llm.mcp import MCPServer, MCPServerHTTP, MCPServerStdio


TransportType = Literal["sse", "streamable_http", "stdio"]


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection.

    Attributes:
        transport: Type of transport ("sse", "streamable_http", or "stdio")
        url: Server URL (for SSE and HTTP transports)
        command: Command to execute (for stdio transport)
        args: Command arguments (for stdio transport)
        env: Environment variables (for stdio transport)
        cwd: Working directory (for stdio transport)
        headers: HTTP headers (for HTTP transports)
        timeout: Connection timeout in seconds
        sse_read_timeout: SSE read timeout in seconds
        client_session_timeout: Client session timeout in seconds

    Note:
        Tool caching is automatically enabled by the MCP server implementation.
    """
    transport: TransportType

    # HTTP/SSE parameters
    url: str | None = None
    headers: dict[str, str] | None = None
    timeout: float = 5.0
    sse_read_timeout: float = 300.0

    # Stdio parameters
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | Path | None = None

    # Common parameters
    client_session_timeout: float = 5.0

    def validate(self) -> None:
        """Validate the configuration."""
        if self.transport in ("sse", "streamable_http"):
            if not self.url:
                raise ValueError(f"URL is required for {self.transport} transport")
        elif self.transport == "stdio":
            if not self.command:
                raise ValueError("Command is required for stdio transport")
        else:
            raise ValueError(f"Invalid transport type: {self.transport}")


def create_mcp_server(config: MCPServerConfig) -> MCPServer:
    """Create an MCP server instance from configuration.

    Args:
        config: Server configuration

    Returns:
        Configured MCPServer instance (MCPServerHTTP or MCPServerStdio)

    Raises:
        ValueError: If configuration is invalid

    Examples:
        >>> # SSE server
        >>> config = MCPServerConfig(
        ...     name="SSE Server",
        ...     transport="sse",
        ...     url="https://example.com/sse"
        ... )
        >>> server = create_mcp_server(config)

        >>> # Streamable HTTP server
        >>> config = MCPServerConfig(
        ...     name="HTTP Server",
        ...     transport="streamable_http",
        ...     url="https://example.com/mcp"
        ... )
        >>> server = create_mcp_server(config)

        >>> # Stdio server
        >>> config = MCPServerConfig(
        ...     name="Stdio Server",
        ...     transport="stdio",
        ...     command="python",
        ...     args=["-m", "my_mcp_server"]
        ... )
        >>> server = create_mcp_server(config)
    """
    config.validate()

    if config.transport in ("sse", "streamable_http"):
        # For HTTP transports, the MCPServerHTTP class auto-detects
        # the transport type based on the URL path
        url = config.url
        assert url is not None

        # Ensure URL path ends with correct suffix for transport type
        # Don't modify URLs that already have the correct suffix
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        if config.transport == "sse" and not path.endswith("/sse"):
            parsed = parsed._replace(path=path + "/sse")
        elif config.transport == "streamable_http" and not path.endswith("/mcp"):
            parsed = parsed._replace(path=path + "/mcp")

        url = urlunparse(parsed)

        return MCPServerHTTP(
            url=url,
            headers=config.headers,
            timeout=config.timeout,
            sse_read_timeout=config.sse_read_timeout,
            client_session_timeout_seconds=config.client_session_timeout,
        )

    elif config.transport == "stdio":
        command = config.command
        assert command is not None

        return MCPServerStdio(
            command=command,
            args=config.args or [],
            env=config.env,
            cwd=config.cwd,
            client_session_timeout_seconds=config.client_session_timeout,
        )

    else:
        raise ValueError(f"Unsupported transport type: {config.transport}")


def create_mcp_server_from_env(
    url_env_var: str = "MCP_SERVER_URL",
    transport: TransportType = "streamable_http",
    **kwargs: Any
) -> MCPServer:
    """Create an MCP server from environment variables.

    Args:
        url_env_var: Environment variable containing the server URL
        transport: Transport type to use
        **kwargs: Additional configuration parameters

    Returns:
        Configured MCPServer instance

    Raises:
        ValueError: If URL environment variable is not set

    Example:
        >>> server = create_mcp_server_from_env(
        ...     url_env_var="MY_MCP_URL",
        ...     transport="sse"
        ... )
    """
    url = os.environ.get(url_env_var)
    if not url:
        raise ValueError(f"Environment variable {url_env_var} is not set")

    config = MCPServerConfig(
        transport=transport,
        url=url,
        **kwargs
    )

    return create_mcp_server(config)
