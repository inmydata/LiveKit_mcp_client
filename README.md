# LiveKit Voice Agent with MCP Integration

A natural-sounding voice assistant built with LiveKit Agents that seamlessly integrates with any Model Context Protocol (MCP) server. Features LLM-generated conversational responses, intelligent progress announcements, and support for long-running operations.

## Key Features

- **Universal MCP Support**: Works with any MCP server (SSE, HTTP, stdio transports)
- **Natural Conversation**: LLM-generated tool announcements that sound human
- **Smart Progress Updates**: Queued, non-repetitive progress announcements
- **Long Operation Support**: Handles operations up to 5 minutes with streaming progress
- **Automatic Result Unwrapping**: Clean JSON data extracted from MCP responses
- **Voice-First Design**: Optimized for spoken interaction

## How It Works

### Natural Language Tool Announcements

Instead of robotic phrases like "Let me fetch that data", the agent uses GPT-4o-mini to generate contextual, conversational responses:

```text
User: "Which store had the best sales last year?"
Agent: "I'll look up last year's sales for you"    ← Natural, contextual
Agent: "Just pulling up the rankings"              ← Different each time
Agent: "Let me find which store performed best"    ← Relevant to question
```

### Intelligent Progress Management

Long-running operations provide streaming progress updates that:

- Are spoken naturally ("I'm analyzing the data now")
- Never repeat the same phrase twice
- Stop immediately when the operation completes
- Don't speak stale updates after the answer is ready

### Architecture

```text
User Voice Input
    ↓
Deepgram STT
    ↓
GPT-4o LLM (decides to use tools)
    ↓
Tool Announcement (GPT-4o-mini generates natural phrase)
    ↓
MCP Server (via wrapper)
    ↓ (progress updates)
Progress Queue → Natural Rephrasing → Speech
    ↓ (on completion, clear queue)
Clean Result → GPT-4o → OpenAI TTS
    ↓
User Hears Answer
```

## Installation

### Prerequisites

- Python 3.10+
- API keys for OpenAI and Deepgram
- An MCP server endpoint

### Setup

1. Clone this repository:

   ```bash
   git clone <repository-url>
   cd LiveKit_mcp_client
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file:

   ```env
   # API Keys
   OPENAI_API_KEY=your_openai_api_key
   DEEPGRAM_API_KEY=your_deepgram_api_key

   # LiveKit Configuration
   LIVEKIT_URL=wss://your-livekit-server.livekit.cloud
   LIVEKIT_API_KEY=your_livekit_api_key
   LIVEKIT_API_SECRET=your_livekit_api_secret

   # MCP Server
   MCP_SERVER_URL=https://your-mcp-server.com/mcp
   ```

## Usage

### Running the Agent

Development mode (with file watching):

```bash
python agent.py dev
```

Production mode:

```bash
python agent.py start
```

### Configuration

The agent supports three MCP transport types:

**HTTP (Streamable)**:

```python
MCPServerConfig(
    transport="streamable_http",
    url="https://mcp.example.com/mcp",
    client_session_timeout=300.0  # 5 minutes for slow operations
)
```

**SSE (Server-Sent Events)**:

```python
MCPServerConfig(
    transport="sse",
    url="https://mcp.example.com/sse",
    sse_read_timeout=300.0
)
```

**Stdio (Local Process)**:

```python
MCPServerConfig(
    transport="stdio",
    command="uvx",
    args=["mcp-server-sqlite", "--db-path", "/path/to/db.sqlite"]
)
```

## Project Structure

```text
LiveKit_mcp_client/
├── agent.py                    # Main agent with natural response generation
├── mcp_client/
│   ├── __init__.py            # Public API exports
│   ├── server.py              # MCP server configuration and factory
│   └── wrapper.py             # Result unwrapping and progress handling
├── requirements.txt
├── .env.example
└── README.md
```

## Technical Details

### MCP Server Wrapper

Wraps LiveKit's `MCPServer` to:

1. **Unwrap Results**: Extracts clean JSON from `{"type":"text","text":"data"}` format
2. **Progress Callbacks**: Intercepts MCP progress updates and queues them
3. **Completion Signals**: Notifies when tools finish to clear queues

### Natural Response Generation

Uses GPT-4o-mini to generate conversational phrases:

- **Tool Announcements**: Based on user query and tool name
- **Progress Updates**: Rephrases technical messages naturally
- **Deduplication**: Tracks previously used phrases to avoid repetition
- **Cost**: ~$0.000021 per announcement (negligible)
- **Latency**: ~200ms (barely noticeable)

### Progress Queue System

Asynchronous queue that:

- Stores progress messages per tool
- Speaks them one at a time with natural pacing
- Stops immediately when tool completes
- Clears unspoken messages to prevent stale announcements

### Configuration Options

**Agent Settings**:

```python
FunctionAgent(
    llm=openai.LLM(model="gpt-4o"),         # Main conversation LLM
    max_tool_steps=10,                       # Max tool calls per turn
    client_session_timeout=300.0             # 5 min timeout for tools
)
```

**Natural Response Settings**:

```python
generate_natural_response(
    model="gpt-4o-mini",                     # Fast, cheap rephrasing
    temperature=0.7,                         # Natural variety
    max_tokens=30                            # Brief (5-10 words)
)
```

**Progress Settings**:

```python
DEDUP_WINDOW_SECONDS = 3.0                  # Don't repeat within 3s
```

## Customization

### Adjusting Tool Announcements

Edit the prompt in `generate_natural_response()` to change the tone:

```python
prompt = f"""You are a [friendly/professional/energetic] voice assistant.
The user just asked: "{user_query}"
You're about to call a tool named "{tool_name}".

Generate a brief, [casual/formal] phrase..."""
```

### Changing Progress Pacing

Adjust the delay between progress messages:

```python
await asyncio.sleep(0.1)  # Default: 100ms between messages
```

### Using Different LLMs

The agent supports any OpenAI-compatible LLM:

```python
llm=openai.LLM(model="gpt-4o-mini")  # Faster, cheaper
# or
llm=openai.LLM(model="gpt-4")        # More capable
```

## Troubleshooting

### "Tool execution timed out"

Increase `client_session_timeout`:

```python
MCPServerConfig(client_session_timeout=600.0)  # 10 minutes
```

### "Maximum tool steps reached"

Increase `max_tool_steps`:

```python
AgentSession(max_tool_steps=20)
```

### Repetitive announcements

The agent now tracks phrases automatically, but you can adjust deduplication:

```python
DEDUP_WINDOW_SECONDS = 5.0  # Longer window
```

### Progress updates continue after answer

This should not happen with the queue system. Check logs for:

```text
Tool X completed, setting stop flag
Cleared N unspoken progress messages
```

## Performance

- **Tool Announcement Latency**: ~200ms (GPT-4o-mini generation)
- **Progress Update Latency**: ~200ms per message
- **Cost per Announcement**: ~$0.000021
- **Cost per 1000 conversations**: ~$0.05 (assuming 2-3 announcements each)

## Dependencies

- `livekit-agents` - Voice agent framework
- `livekit-plugins-openai` - OpenAI LLM and TTS
- `livekit-plugins-deepgram` - Speech-to-text
- `livekit-plugins-silero` - Voice activity detection
- `openai` - For natural response generation
- `mcp` - Model Context Protocol client
- `python-dotenv` - Environment variable management

## Acknowledgements

- [LiveKit](https://livekit.io/) - Real-time voice infrastructure
- [OpenAI](https://openai.com/) - GPT-4o and GPT-4o-mini
- [Deepgram](https://deepgram.com/) - Speech-to-text
- [Silero VAD](https://github.com/snakers4/silero-vad) - Voice activity detection
- [Model Context Protocol](https://modelcontextprotocol.io/) - Tool integration standard

## License

MIT License - see LICENSE file for details
