"""Basic usage examples for the MCP client adaptor."""

import asyncio
import os
from dotenv import load_dotenv
from mcp_client import MCPServerConfig, create_mcp_server, MCPToolsIntegration
from mcp_client.util import test_mcp_connection, list_server_tools, format_tool_info

load_dotenv()


async def example_http_server():
    """Example: Connect to an HTTP MCP server."""
    print("\n=== HTTP Server Example ===")

    config = MCPServerConfig(
        name="HTTP MCP Server",
        transport="streamable_http",
        url=os.environ.get("MCP_SERVER_URL", "https://api.example.com/mcp"),
        timeout=10.0,
        cache_tools=True,
    )

    server = create_mcp_server(config)

    # Test the connection
    if await test_mcp_connection(server):
        print("✓ Connection successful!")

        # List available tools
        server = create_mcp_server(config)  # Recreate after test
        await server.initialize()
        tools = await list_server_tools(server)
        print(format_tool_info(tools))
        await server.aclose()


async def example_sse_server():
    """Example: Connect to an SSE MCP server."""
    print("\n=== SSE Server Example ===")

    config = MCPServerConfig(
        name="SSE MCP Server",
        transport="sse",
        url="https://api.example.com/sse",
        sse_read_timeout=300.0,
        cache_tools=True,
    )

    server = create_mcp_server(config)

    if await test_mcp_connection(server):
        print("✓ SSE connection successful!")


async def example_stdio_server():
    """Example: Connect to a stdio MCP server."""
    print("\n=== Stdio Server Example ===")

    config = MCPServerConfig(
        name="Local MCP Server",
        transport="stdio",
        command="python",
        args=["-m", "my_mcp_server"],
        env={"PYTHONPATH": "."},
        cache_tools=True,
    )

    server = create_mcp_server(config)

    if await test_mcp_connection(server):
        print("✓ Stdio connection successful!")


async def example_multiple_servers():
    """Example: Use multiple MCP servers simultaneously."""
    print("\n=== Multiple Servers Example ===")

    # Configure multiple servers
    servers = [
        create_mcp_server(MCPServerConfig(
            name="Server 1",
            transport="streamable_http",
            url="https://api1.example.com/mcp",
        )),
        create_mcp_server(MCPServerConfig(
            name="Server 2",
            transport="sse",
            url="https://api2.example.com/sse",
        )),
    ]

    # Initialize all servers
    try:
        initialized = await MCPToolsIntegration.initialize_servers(servers)
        print(f"✓ Initialized {len(initialized)} servers")

        # Get all tools
        all_tools = await MCPToolsIntegration.get_all_tools(initialized)
        print(f"✓ Loaded {len(all_tools)} total tools")

    finally:
        await MCPToolsIntegration.cleanup_servers(servers)


async def example_agent_integration():
    """Example: Create a LiveKit agent with MCP tools."""
    print("\n=== Agent Integration Example ===")

    # This example shows the structure - actual agent creation
    # requires LiveKit context

    config = MCPServerConfig(
        name="MCP Tools Server",
        transport="streamable_http",
        url=os.environ.get("MCP_SERVER_URL", "https://api.example.com/mcp"),
        cache_tools=True,
    )

    server = create_mcp_server(config)

    print("Server configured and ready for agent integration")
    print("Use MCPToolsIntegration.create_agent_with_tools() in your LiveKit entrypoint")


async def main():
    """Run all examples."""
    print("MCP Client Adaptor - Usage Examples")
    print("=" * 50)

    # Run examples (most will fail without actual servers, but show the patterns)
    try:
        await example_http_server()
    except Exception as e:
        print(f"HTTP example error (expected): {e}")

    try:
        await example_sse_server()
    except Exception as e:
        print(f"SSE example error (expected): {e}")

    try:
        await example_stdio_server()
    except Exception as e:
        print(f"Stdio example error (expected): {e}")

    try:
        await example_multiple_servers()
    except Exception as e:
        print(f"Multiple servers example error (expected): {e}")

    await example_agent_integration()


if __name__ == "__main__":
    asyncio.run(main())
