# MCP Client for LiveKit Agents

A universal MCP (Model Context Protocol) client adaptor for LiveKit Agents with intelligent voice announcements. This package provides seamless integration of MCP tools into LiveKit voice agents with natural language progress updates and query intent announcements.

## Features

- **Universal MCP Integration**: Connect to any MCP server (HTTP, SSE, or stdio transport)
- **Voice Announcements**: Natural language announcements for tool usage and progress
- **Query Intent Detection**: Announces what the agent will do before executing tools
- **Progress Updates**: Real-time progress notifications during long-running operations
- **Smart Batching**: Time-based message batching to reduce chattiness
- **Conversation Context**: Tracks announcement history to avoid repetition

## Installation

```bash
pip install -e .
```

Or install from requirements.txt:

```bash
pip install -r requirements.txt
```

## Quick Start

```python
from livekit.agents import JobContext
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai
from mcp_client import (
    MCPServerConfig,
    create_mcp_server,
    MCPServerWrapper,
    ProgressManager
)

# Configure your MCP server
server_config = MCPServerConfig(
    transport="streamable_http",  # or "sse" or "stdio"
    url="https://your-mcp-server.com",
    client_session_timeout=300.0
)

# Create the MCP server
mcp_server = create_mcp_server(server_config)

# Create progress manager for voice announcements
def speak_callback(text: str):
    """Callback to speak progress updates."""
    # Your implementation here
    pass

progress_manager = ProgressManager(
    speak_callback=speak_callback,
    enable_natural_language=True,
    batch_window_seconds=5.0
)

# Wrap the server
wrapped_server = MCPServerWrapper(
    mcp_server,
    progress_manager=progress_manager
)

# Create your agent with the wrapped server
agent = Agent(
    instructions="You are a helpful assistant.",
    stt=deepgram.STT(),
    llm=openai.LLM(model="gpt-4o"),
    tts=openai.TTS(voice="echo"),
    mcp_servers=[wrapped_server]
)
```

## Components

### MCPServerConfig

Configuration for connecting to MCP servers:

```python
from mcp_client import MCPServerConfig

config = MCPServerConfig(
    transport="streamable_http",  # Transport type: "streamable_http", "sse", or "stdio"
    url="https://your-server.com",  # Server URL (for HTTP/SSE)
    command="/path/to/command",  # Command path (for stdio)
    args=["arg1", "arg2"],  # Command arguments (for stdio)
    env={"KEY": "value"},  # Environment variables (for stdio)
    client_session_timeout=300.0  # Timeout in seconds
)
```

### ProgressManager

Manages progress announcements with batching and natural language generation.

```python
from mcp_client import ProgressManager

progress_manager = ProgressManager(
    speak_callback=your_speak_function,
    enable_natural_language=True,  # Use LLM for natural rephrasing
    dedup_window_seconds=3.0,  # Deduplication window
    model="gpt-4o",  # Model for announcements
    temperature=0.9,  # Temperature for variety
    batch_window_seconds=5.0  # Batch messages over 5 seconds
)
```

### Announcement Functions

Generate natural language announcements for different scenarios:

```python
from mcp_client import (
    generate_tool_announcement,
    generate_progress_announcement,
    generate_query_intent_announcement
)

# Query intent announcement
intent_msg = await generate_query_intent_announcement(
    user_query="What were the top stores last week?",
    tools_involved=["get_schema", "get_top_n_fast"],
    model="gpt-4o",
    temperature=0.9
)

# Progress announcement
progress_msg = await generate_progress_announcement(
    progress_message="Fetching financial data",
    previously_announced=["Checking the schema"],
    model="gpt-4o",
    temperature=0.9
)

# Tool announcement
tool_msg = await generate_tool_announcement(
    user_query="Show me sales for Jerry Lewis",
    tool_name="get_rows_fast",
    tool_description="Fetch rows from database",
    tool_arguments={"salesperson": "Jerry Lewis"},
    model="gpt-4o",
    temperature=0.9
)
```

## Configuration Options

### Environment Variables

Control announcement behavior via environment variables:

```bash
# Enable/disable features
ENABLE_TOOL_ANNOUNCEMENTS=false  # Default: false (args not available during streaming)
ENABLE_QUERY_INTENT_ANNOUNCEMENT=true  # Default: true
ENABLE_PROGRESS_ANNOUNCEMENTS=true  # Default: true
ENABLE_NATURAL_LANGUAGE=true  # Default: true

# Model configuration
ANNOUNCEMENT_MODEL=gpt-4o  # Default: gpt-4o
ANNOUNCEMENT_TEMPERATURE=0.9  # Default: 0.9
BATCH_WINDOW_SECONDS=5.0  # Default: 5.0

# MCP Server
MCP_SERVER_URL=https://your-server.com
```

### Announcement Types

1. **Query Intent Announcements**: "OK, I'll find the top ten stores based on sales last week"
      - Triggered once at the start of a query
      - Requires user query extraction
      - Provides context about what the agent will do

2. **Progress Announcements**: "Checking the available data fields"
      - Sent during long-running operations
      - Batched over time windows to reduce chattiness
      - Rephrased with conversation history for variety

3. **Tool Announcements**: "Looking up Jerry Lewis's details"
      - Announces individual tool usage
      - Disabled by default (arguments not available during streaming)
      - Can be enabled via `ENABLE_TOOL_ANNOUNCEMENTS=true`

## Advanced Usage

### Custom LLM Node Override

For advanced control over announcements, override the `llm_node` method:

```python
from livekit.agents.voice import Agent
from livekit.agents.llm import ChatChunk

class CustomAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_intent_announced = False
        self.current_user_query = ""

    def llm_node(self, chat_ctx, tools, model_settings):
        async def _llm_node_impl():
            # Extract user query from chat context
            user_query = ""
            if hasattr(chat_ctx, 'items') and chat_ctx.items:
                for item in reversed(chat_ctx.items):
                    if getattr(item, 'role', None) == "user":
                        content = getattr(item, 'content', None)
                        if isinstance(content, list) and len(content) > 0:
                            text = content[0] if isinstance(content[0], str) else getattr(content[0], 'text', None)
                            if text:
                                user_query = str(text)
                                break

            # Generate announcements before tool execution
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                if isinstance(chunk, ChatChunk) and chunk.delta and chunk.delta.tool_calls:
                    if not self.query_intent_announced and user_query:
                        # Your announcement logic here
                        self.query_intent_announced = True
                yield chunk

        return _llm_node_impl()
```

### Progress Notifications

MCP servers can send progress notifications during tool execution:

```python
# In your MCP server implementation
@mcp.tool()
async def long_running_operation(args) -> str:
    # Send progress updates
    await send_progress_notification(
        progress_token="token",
        progress=0.5,
        total=1.0
    )
    # Continue processing...
```

The `ProgressManager` will automatically convert these into natural language announcements.

## Architecture

```text
┌─────────────────────────────────────────┐
│         LiveKit Agent                   │
│  ┌───────────────────────────────────┐  │
│  │  Custom llm_node Override          │  │
│  │  - Query Intent Detection          │  │
│  │  - Announcement Triggering         │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      MCPServerWrapper                   │
│  - Wraps MCP server tools               │
│  - Integrates ProgressManager           │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      ProgressManager                    │
│  - Batches progress messages            │
│  - Generates natural language           │
│  - Tracks announcement history          │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│      Announcement Functions             │
│  - Query Intent Announcements           │
│  - Progress Announcements               │
│  - Tool Announcements                   │
└─────────────────────────────────────────┘
```

## Troubleshooting

### Query Intent Announcements Not Working

1. Ensure you're using the standard LLM pipeline (not OpenAI Realtime Model)
2. Check that `ENABLE_QUERY_INTENT_ANNOUNCEMENT=true`
3. Verify user query extraction with debug logging: `--log-level debug`

### Progress Announcements Too Repetitive

1. Increase `BATCH_WINDOW_SECONDS` (default: 5.0)
2. Ensure `ENABLE_NATURAL_LANGUAGE=true`
3. Check that conversation history is being tracked

### No Announcements at All

1. Verify `speak_callback` is properly connected to agent
2. Check feature flags are enabled
3. Review debug logs for errors

## Examples

See the parent directory for a complete example agent implementation using this package.

## Contributing

Contributions are welcome! Please submit issues and pull requests on GitHub.

## License

MIT License - See LICENSE file for details
