"""Advanced usage examples for the MCP client adaptor."""

import asyncio
import os
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import ChatChunk
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero
from mcp_client import MCPToolsIntegration, MCPServerConfig, create_mcp_server
from mcp_client.agent_tools import MCPAgentContext
from mcp_client.util import validate_server_config

load_dotenv()


class CustomVoiceAgent(Agent):
    """Custom agent with enhanced MCP tool handling."""

    def __init__(self, tool_servers: list = None):
        """Initialize agent with custom instructions.

        Args:
            tool_servers: List of MCP server names for logging
        """
        self.tool_servers = tool_servers or []

        instructions = f"""
        You are a helpful assistant with access to tools from:
        {', '.join(self.tool_servers)}

        When using tools, always:
        1. Explain what you're doing
        2. Show the results clearly
        3. Handle errors gracefully
        """

        super().__init__(
            instructions=instructions,
            stt=deepgram.STT(),
            llm=openai.LLM(model="gpt-4o"),
            tts=openai.TTS(),
            vad=silero.VAD.load(),
            allow_interruptions=True
        )

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Enhanced llm_node with detailed tool call feedback."""
        activity = self._activity
        tool_call_detected = False
        tool_name = None

        async for chunk in super().llm_node(chat_ctx, tools, model_settings):
            if isinstance(chunk, ChatChunk) and chunk.delta and chunk.delta.tool_calls:
                for tool_call in chunk.delta.tool_calls:
                    if not tool_call_detected:
                        tool_call_detected = True
                        tool_name = getattr(tool_call, 'name', 'a tool')
                        activity.agent.say(f"Let me use {tool_name} to help with that.")

            yield chunk


async def example_with_validation():
    """Example: Validate server configurations before using them."""
    print("\n=== Server Validation Example ===")

    configs = [
        MCPServerConfig(
            name="Primary Server",
            transport="streamable_http",
            url=os.environ.get("MCP_SERVER_URL", "https://api.example.com/mcp"),
        ),
        MCPServerConfig(
            name="Backup Server",
            transport="sse",
            url=os.environ.get("MCP_SERVER_URL_BACKUP", "https://backup.example.com/sse"),
        ),
    ]

    validated_servers = []

    for config in configs:
        server = create_mcp_server(config)
        result = await validate_server_config(server)

        if result["valid"]:
            print(f"✓ {config.name}: {result['tool_count']} tools available")
            validated_servers.append(server)
        else:
            print(f"✗ {config.name}: {result['error']}")

    return validated_servers


async def example_with_context_manager():
    """Example: Use context manager for automatic cleanup."""
    print("\n=== Context Manager Example ===")

    server_config = MCPServerConfig(
        name="MCP Tools",
        transport="streamable_http",
        url=os.environ.get("MCP_SERVER_URL", "https://api.example.com/mcp"),
    )

    server = create_mcp_server(server_config)

    # This pattern ensures cleanup even if errors occur
    async with MCPAgentContext(
        agent_class=CustomVoiceAgent,
        mcp_servers=[server],
        agent_kwargs={"tool_servers": [server_config.name]}
    ) as agent:
        print(f"✓ Agent created with tools from {server_config.name}")
        # Agent is ready to use
        # Cleanup happens automatically when exiting the context


async def example_conditional_servers():
    """Example: Conditionally load servers based on environment."""
    print("\n=== Conditional Server Loading Example ===")

    servers = []

    # Primary HTTP server
    if primary_url := os.environ.get("MCP_SERVER_URL"):
        servers.append(create_mcp_server(MCPServerConfig(
            name="Primary HTTP Server",
            transport="streamable_http",
            url=primary_url,
        )))

    # Optional SSE server
    if sse_url := os.environ.get("MCP_SSE_URL"):
        servers.append(create_mcp_server(MCPServerConfig(
            name="SSE Server",
            transport="sse",
            url=sse_url,
        )))

    # Optional local stdio server
    if os.environ.get("ENABLE_LOCAL_MCP") == "true":
        servers.append(create_mcp_server(MCPServerConfig(
            name="Local Tools",
            transport="stdio",
            command="python",
            args=["-m", "local_mcp_server"],
        )))

    print(f"✓ Configured {len(servers)} server(s)")
    return servers


async def example_custom_headers():
    """Example: Use custom authentication headers."""
    print("\n=== Custom Headers Example ===")

    api_key = os.environ.get("MCP_API_KEY", "your_api_key")

    config = MCPServerConfig(
        name="Authenticated Server",
        transport="streamable_http",
        url="https://api.example.com/mcp",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Client-Version": "1.0.0",
            "X-Custom-Header": "custom-value",
        },
    )

    server = create_mcp_server(config)
    print(f"✓ Server configured with authentication")


async def example_stdio_with_custom_env():
    """Example: Stdio server with custom environment variables."""
    print("\n=== Stdio with Custom Environment Example ===")

    config = MCPServerConfig(
        name="Local Python Server",
        transport="stdio",
        command="python",
        args=["-m", "my_mcp_server"],
        env={
            "PYTHONPATH": ".",
            "MCP_LOG_LEVEL": "DEBUG",
            "CUSTOM_CONFIG": "/path/to/config.json",
        },
        cwd="/path/to/server/directory",
    )

    server = create_mcp_server(config)
    print(f"✓ Stdio server configured with custom environment")


async def example_error_handling():
    """Example: Robust error handling for MCP operations."""
    print("\n=== Error Handling Example ===")

    config = MCPServerConfig(
        name="Test Server",
        transport="streamable_http",
        url=os.environ.get("MCP_SERVER_URL", "https://api.example.com/mcp"),
        timeout=5.0,
    )

    server = create_mcp_server(config)

    try:
        # Initialize with timeout
        await server.initialize()
        print("✓ Server initialized successfully")

        try:
            # List tools with error handling
            tools = await server.list_tools()
            print(f"✓ Found {len(tools)} tools")

        except Exception as e:
            print(f"✗ Failed to list tools: {e}")
            # Could fall back to another server here

    except asyncio.TimeoutError:
        print("✗ Server initialization timed out")
        # Could implement retry logic here

    except Exception as e:
        print(f"✗ Server initialization failed: {e}")

    finally:
        # Always clean up
        try:
            await server.aclose()
            print("✓ Server connection closed")
        except Exception as e:
            print(f"⚠ Error during cleanup: {e}")


async def entrypoint_with_fallback(ctx: JobContext):
    """Advanced entrypoint with server fallback and validation."""

    # Try primary server first
    server_configs = [
        MCPServerConfig(
            name="Primary Server",
            transport="streamable_http",
            url=os.environ.get("MCP_SERVER_URL"),
            timeout=5.0,
        ),
        MCPServerConfig(
            name="Fallback Server",
            transport="sse",
            url=os.environ.get("MCP_FALLBACK_URL"),
            timeout=10.0,
        ),
    ]

    active_servers = []

    for config in server_configs:
        if not config.url:
            continue

        server = create_mcp_server(config)
        result = await validate_server_config(server)

        if result["valid"]:
            print(f"Using {config.name} with {result['tool_count']} tools")
            active_servers.append(create_mcp_server(config))
            break
        else:
            print(f"Failed to use {config.name}: {result['error']}")

    if not active_servers:
        raise RuntimeError("No MCP servers available")

    # Create agent with validated servers
    agent = await MCPToolsIntegration.create_agent_with_tools(
        agent_class=CustomVoiceAgent,
        mcp_servers=active_servers,
        agent_kwargs={
            "tool_servers": [s.name for s in active_servers]
        }
    )

    await ctx.connect()
    session = AgentSession()
    await session.start(agent=agent, room=ctx.room)


async def main():
    """Run advanced examples."""
    print("MCP Client Adaptor - Advanced Examples")
    print("=" * 50)

    try:
        await example_with_validation()
    except Exception as e:
        print(f"Validation example error: {e}")

    try:
        await example_with_context_manager()
    except Exception as e:
        print(f"Context manager example error: {e}")

    try:
        await example_conditional_servers()
    except Exception as e:
        print(f"Conditional servers example error: {e}")

    await example_custom_headers()
    await example_stdio_with_custom_env()

    try:
        await example_error_handling()
    except Exception as e:
        print(f"Error handling example error: {e}")


if __name__ == "__main__":
    # To run examples
    asyncio.run(main())

    # To run as LiveKit agent with fallback
    # cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint_with_fallback))
