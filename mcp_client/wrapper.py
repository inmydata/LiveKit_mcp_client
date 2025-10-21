"""MCP server wrapper that unwraps tool results and handles progress callbacks."""

import json
import logging
from typing import Any, Optional
from livekit.agents.llm.mcp import MCPServer, MCPTool
from livekit.agents.llm.tool_context import ToolError, function_tool
from .progress_manager import ProgressManager

logger = logging.getLogger(__name__)


class MCPServerWrapper:
    """Wrapper for MCPServer that unwraps tool results and handles progress.

    LiveKit's default MCP integration returns tool results in the format:
    {"type":"text","text":"actual data"}

    This wrapper:
    1. Extracts just the "text" field so the LLM receives clean data
    2. Supports progress callbacks for long-running operations
    3. Notifies when tools complete for queue management
    """

    def __init__(
        self,
        mcp_server: MCPServer,
        progress_manager: Optional[ProgressManager] = None
    ):
        """Initialize the wrapper.

        Args:
            mcp_server: The MCP server to wrap
            progress_manager: Optional progress manager for handling announcements
        """
        self._server = mcp_server
        self._fixed_tools: list[MCPTool] | None = None
        self._progress_manager = progress_manager

    @property
    def initialized(self) -> bool:
        """Check if the server is initialized."""
        return self._server.initialized

    async def initialize(self) -> None:
        """Initialize the underlying MCP server."""
        await self._server.initialize()

    async def list_tools(self) -> list[MCPTool]:
        """List tools with fixed result unwrapping."""
        if self._fixed_tools is not None:
            return self._fixed_tools

        # Get original tools from the server
        original_tools = await self._server.list_tools()

        # Wrap each tool to fix result unwrapping
        fixed_tools = []
        for tool in original_tools:
            fixed_tool = self._wrap_tool(tool)
            fixed_tools.append(fixed_tool)

        self._fixed_tools = fixed_tools
        return fixed_tools

    def _wrap_tool(self, original_tool: MCPTool) -> MCPTool:
        """Wrap a tool to fix result unwrapping and add progress support.

        Args:
            original_tool: The original tool from the MCP server

        Returns:
            A wrapped tool that properly unwraps results and reports progress
        """
        # Get the original tool info (use getattr to avoid name mangling issues)
        tool_info = getattr(original_tool, '__livekit_raw_tool_info')
        tool_name = tool_info.raw_schema.get('name', 'unknown')

        async def _fixed_tool_called(raw_arguments: dict[str, Any]) -> Any:
            """Call the original tool with progress support and unwrap the result."""

            # Create a progress callback that announces updates
            async def progress_handler(progress: float, total: float | None, message: str | None) -> None:
                """Handle progress updates from the MCP server."""
                if message and self._progress_manager:
                    # Queue the progress message through the manager
                    self._progress_manager.queue_progress(tool_name, message)
                    logger.debug(f"Progress update for {tool_name}: {message} ({progress}/{total})")

            try:
                # We need to access the underlying MCP client to use progress callbacks
                # Unfortunately, LiveKit's wrapper doesn't expose this, so we need to
                # work around it by calling the MCP client directly
                if hasattr(self._server, '_client') and self._server._client is not None:
                    # Direct access to MCP client - can use progress callbacks
                    try:
                        from mcp.client.session import ClientSession

                        client: ClientSession = self._server._client

                        # Call the tool with progress callback
                        tool_result = await client.call_tool(
                            name=tool_name,
                            arguments=raw_arguments,
                            progress_callback=progress_handler if self._progress_manager else None
                        )

                        # Handle errors
                        if tool_result.isError:
                            error_str = "\n".join(str(part) for part in tool_result.content)
                            raise ToolError(error_str)

                        # Unwrap the result
                        if len(tool_result.content) == 1:
                            content_json = tool_result.content[0].model_dump_json()
                            parsed = json.loads(content_json)

                            if isinstance(parsed, dict) and "type" in parsed and "text" in parsed:
                                return parsed["text"]
                            elif isinstance(parsed, dict) and "text" in parsed:
                                return parsed["text"]

                            return content_json

                        elif len(tool_result.content) > 1:
                            return json.dumps([item.model_dump() for item in tool_result.content])

                        raise ToolError(
                            f"Tool '{tool_name}' completed without producing a result."
                        )

                    except AttributeError:
                        # Fall back to calling the wrapped tool without progress support
                        pass

                # Fallback: Call the original tool without progress support
                result = await original_tool(raw_arguments)

                # Result is a JSON string like '{"type":"text","text":"actual data"}'
                # Parse and unwrap it
                try:
                    parsed = json.loads(result)

                    # Extract the actual content
                    if isinstance(parsed, dict):
                        if "type" in parsed and "text" in parsed:
                            return parsed["text"]
                        elif "text" in parsed:
                            return parsed["text"]

                    return result

                except (json.JSONDecodeError, KeyError):
                    return result

            finally:
                # Signal that the tool has completed
                if self._progress_manager:
                    self._progress_manager.mark_completed(tool_name)
                    logger.debug(f"Tool {tool_name} completed, signaling to clear queue")

        # Create a new tool with the same metadata but fixed callback
        return function_tool(_fixed_tool_called, raw_schema=tool_info.raw_schema)

    async def aclose(self) -> None:
        """Close the underlying MCP server."""
        await self._server.aclose()
        self._fixed_tools = None

    def invalidate_cache(self) -> None:
        """Invalidate the tool cache."""
        self._server.invalidate_cache()
        self._fixed_tools = None
