import os
import logging
import json
from pathlib import Path
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import ChatChunk
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero
from mcp_client import (
    MCPServerConfig,
    create_mcp_server,
    MCPServerWrapper,
    ProgressManager,
    generate_tool_announcement,
    generate_query_intent_announcement
)

load_dotenv()


class FunctionAgent(Agent):
    """A LiveKit agent that uses MCP tools from one or more MCP servers."""

    def __init__(
        self,
        mcp_servers=None,
        enable_tool_announcements=True,
        enable_query_intent_announcement=True,
        announcement_model="gpt-4o",
        announcement_temperature=0.9
    ):
        super().__init__(
            instructions="""
                You are a helpful assistant communicating through voice.

                CRITICAL: Before querying data, you MUST first discover the available schema:
                1. ALWAYS call get_schema() first to see available subjects and columns
                2. Use the EXACT column names and subject names from the schema response
                3. NEVER guess or assume column names like "Sales Value" or "Financial Year"
                4. Match the user's intent to the actual column names from get_schema()

                Example workflow:
                - User asks: "top stores by sales"
                - Step 1: Call get_schema() to discover column names
                - Step 2: Use actual column names from schema in get_top_n_fast()

                Use the available MCP tools to answer questions accurately.
            """,
            # Use standard LLM for tool announcements to work
            # (Realtime model bypasses llm_node override)
            stt=deepgram.STT(),
            llm=openai.LLM(model="gpt-5"),
            tts=openai.TTS(
                voice="echo"
            ),
            # Note: Realtime model doesn't support custom llm_node
            # llm=openai.realtime.RealtimeModel(
            #     voice="echo",
            #     temperature=0.8
            # ),
            #vad=silero.VAD.load(),
            mcp_servers=mcp_servers,
            allow_interruptions=True
        )
        self.enable_tool_announcements = enable_tool_announcements
        self.enable_query_intent_announcement = enable_query_intent_announcement
        self.announcement_model = announcement_model
        self.announcement_temperature = announcement_temperature
        self.announced_phrases = set()  # Track phrases to avoid repetition
        self.current_user_query = ""  # Track the current user query across tool calls
        self.query_intent_announced = False  # Track if we've announced the query intent

    def llm_node(self, chat_ctx, tools, model_settings):
        """Override the llm_node to announce tool calls with natural, LLM-generated messages."""
        async def _llm_node_impl():
            activity = self._get_activity_or_raise()
            announced_tools = set()

            # Get the user's last message for context
            user_query = ""
            try:
                logging.debug(f"[QUERY INTENT] chat_ctx type: {type(chat_ctx)}, has items: {hasattr(chat_ctx, 'items')}")
                if hasattr(chat_ctx, 'items'):
                    logging.debug(f"[QUERY INTENT] chat_ctx.items length: {len(chat_ctx.items) if chat_ctx.items else 0}")

                if hasattr(chat_ctx, 'items') and chat_ctx.items:
                    # Find the last user message
                    for i, item in enumerate(reversed(chat_ctx.items)):
                        item_role = getattr(item, 'role', None)
                        logging.debug(f"[QUERY INTENT] Item {i}: role={item_role}")

                        # Skip non-user items
                        if item_role != "user":
                            continue

                        # Found a user item, try to extract content
                        item_content = getattr(item, 'content', None)
                        logging.debug(f"[QUERY INTENT] User item content type: {type(item_content)}")

                        if item_content:
                            if isinstance(item_content, list) and len(item_content) > 0:
                                logging.debug(f"[QUERY INTENT] Content is list with {len(item_content)} items")
                                first_content = item_content[0]
                                logging.debug(f"[QUERY INTENT] First content type: {type(first_content)}")

                                # Extract text - could be a string directly or an object with .text attribute
                                if isinstance(first_content, str):
                                    text = first_content
                                else:
                                    text = getattr(first_content, 'text', None)

                                logging.debug(f"[QUERY INTENT] Extracted text: {text}")
                                if text:
                                    user_query = str(text)
                                    # Save the user query for subsequent tool calls
                                    if user_query:
                                        # If this is a new query, reset the announcement flag
                                        if user_query != self.current_user_query:
                                            self.query_intent_announced = False
                                        self.current_user_query = user_query
                                    logging.debug(f"[QUERY INTENT] Successfully extracted query: {user_query[:50]}")
                                    break
                            elif isinstance(item_content, str):
                                logging.debug(f"[QUERY INTENT] Content is string: {item_content[:50]}")
                                user_query = item_content
                                # Save the user query for subsequent tool calls
                                if user_query:
                                    # If this is a new query, reset the announcement flag
                                    if user_query != self.current_user_query:
                                        self.query_intent_announced = False
                                    self.current_user_query = user_query
                                logging.debug(f"[QUERY INTENT] Successfully extracted query: {user_query[:50]}")
                                break
                        else:
                            logging.debug(f"[QUERY INTENT] User item has no content")
            except Exception as e:
                logging.debug(f"Error extracting user query: {e}")
                user_query = ""

            # If we didn't find a user query in this invocation, use the saved one
            if not user_query and self.current_user_query:
                user_query = self.current_user_query
                logging.debug(f"[QUERY INTENT] Using saved user query: {user_query[:50]}")
            elif user_query:
                logging.debug(f"[QUERY INTENT] Found new user query: {user_query[:50]}")

            # Log that we're starting LLM generation
            logging.debug(f"[QUERY INTENT] Starting LLM generation for query: {user_query[:100]}")
            logging.debug(f"[QUERY INTENT] Feature enabled: {self.enable_query_intent_announcement}")

            # Get the original response from the default implementation
            try:
                chunk_count = 0
                async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                    chunk_count += 1
                    if chunk_count == 1:
                        logging.debug("Received first chunk from LLM")

                    # Check if this chunk contains a tool call
                    if isinstance(chunk, ChatChunk) and chunk.delta and chunk.delta.tool_calls:
                        logging.debug(f"[QUERY INTENT] Tool call detected, announced={self.query_intent_announced}, enabled={self.enable_query_intent_announcement}, has_query={bool(user_query)}")

                        # Announce query intent on first tool call
                        if not self.query_intent_announced and self.enable_query_intent_announcement and user_query:
                            self.query_intent_announced = True
                            logging.debug(f"[QUERY INTENT] Generating announcement...")
                            try:
                                # Get list of all tool names from the available tools
                                tool_names = []
                                for tool in tools:
                                    if hasattr(tool, '__livekit_raw_tool_info'):
                                        info = getattr(tool, '__livekit_raw_tool_info')
                                        tool_names.append(info.raw_schema.get('name', 'unknown'))

                                logging.debug(f"[QUERY INTENT] Found {len(tool_names)} tools")

                                intent_message = await generate_query_intent_announcement(
                                    user_query=user_query,
                                    tools_involved=tool_names,
                                    model=self.announcement_model,
                                    temperature=self.announcement_temperature
                                )
                                logging.debug(f"[QUERY INTENT] Generated message: {intent_message}")
                                activity.say(intent_message)
                                logging.debug(f"[QUERY INTENT] SUCCESS: Said '{intent_message}'")
                            except Exception as e:
                                logging.error(f"[QUERY INTENT] ERROR: {e}", exc_info=True)
                        else:
                            if self.query_intent_announced:
                                logging.debug(f"[QUERY INTENT] Already announced")
                            elif not self.enable_query_intent_announcement:
                                logging.debug(f"[QUERY INTENT] Feature is disabled")
                            elif not user_query:
                                logging.debug(f"[QUERY INTENT] No user query extracted")

                        for tool_call in chunk.delta.tool_calls:
                            tool_name = getattr(tool_call, 'name', None)

                            # Only announce each tool once
                            if tool_name and tool_name not in announced_tools:
                                announced_tools.add(tool_name)
                                logging.debug(f"[TOOL ANNOUNCEMENT] Processing tool: {tool_name}, enabled={self.enable_tool_announcements}")

                                # Extract tool arguments and description for announcements
                                tool_arguments = {}
                                tool_description = ""

                                if self.enable_tool_announcements:
                                    try:
                                        # Try to get arguments from the tool call
                                        raw_arguments = getattr(tool_call, 'raw_arguments', None)
                                        logging.debug(f"[TOOL ANNOUNCEMENT] raw_arguments type: {type(raw_arguments)}, value: {raw_arguments}")
                                        if raw_arguments:
                                            if isinstance(raw_arguments, str):
                                                tool_arguments = json.loads(raw_arguments)
                                            elif isinstance(raw_arguments, dict):
                                                tool_arguments = raw_arguments
                                            logging.debug(f"[TOOL ANNOUNCEMENT] Parsed arguments: {tool_arguments}")
                                        else:
                                            logging.debug(f"[TOOL ANNOUNCEMENT] No arguments available yet for {tool_name}")
                                    except Exception as e:
                                        logging.error(f"[TOOL ANNOUNCEMENT] Could not extract tool arguments: {e}", exc_info=True)

                                    try:
                                        # Try to get tool description from the tools list
                                        for tool in tools:
                                            if hasattr(tool, '__livekit_raw_tool_info'):
                                                info = getattr(tool, '__livekit_raw_tool_info')
                                                if info.raw_schema.get('name') == tool_name:
                                                    tool_description = info.raw_schema.get('description', '')
                                                    break
                                    except Exception as e:
                                        logging.debug(f"Could not extract tool description: {e}")

                                    logging.debug(f"[TOOL ANNOUNCEMENT] Generating announcement for {tool_name}")
                                    logging.debug(f"[TOOL ANNOUNCEMENT] Args: {tool_arguments}, Desc: {tool_description[:50] if tool_description else 'none'}")

                                    # Generate a natural message using the LLM
                                    try:
                                        message = await generate_tool_announcement(
                                            user_query=user_query,
                                            tool_name=tool_name,
                                            tool_description=tool_description,
                                            tool_arguments=tool_arguments,
                                            previously_announced=self.announced_phrases,
                                            model=self.announcement_model,
                                            temperature=self.announcement_temperature
                                        )

                                        # Track this phrase to avoid repeating it
                                        self.announced_phrases.add(message)

                                        activity.say(message)
                                        logging.debug(f"[TOOL ANNOUNCEMENT] SUCCESS: Said '{message}'")
                                    except Exception as e:
                                        logging.error(f"[TOOL ANNOUNCEMENT] ERROR: {e}", exc_info=True)
                                        activity.say("Let me check that for you.")
                                else:
                                    logging.debug(f"[TOOL ANNOUNCEMENT] Skipped (disabled) for {tool_name}")

                    yield chunk

                logging.debug(f"LLM generation completed, yielded {chunk_count} chunks")

            except Exception as e:
                logging.error(f"Error in llm_node: {e}", exc_info=True)
                raise

        return _llm_node_impl()


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the LiveKit agent application."""
    # Create MCP server configuration
    mcp_server_url = os.environ.get("MCP_SERVER_URL")
    if not mcp_server_url:
        raise ValueError("MCP_SERVER_URL environment variable is required")

    # Configuration options
    # Note: Tool announcements disabled by default because arguments aren't available during streaming
    # Use query intent + progress announcements instead for better UX
    enable_tool_announcements = os.environ.get("ENABLE_TOOL_ANNOUNCEMENTS", "false").lower() == "true"
    enable_query_intent_announcement = os.environ.get("ENABLE_QUERY_INTENT_ANNOUNCEMENT", "true").lower() == "true"
    enable_progress_announcements = os.environ.get("ENABLE_PROGRESS_ANNOUNCEMENTS", "true").lower() == "true"
    enable_natural_language = os.environ.get("ENABLE_NATURAL_LANGUAGE", "true").lower() == "true"

    # Model configuration for announcements
    announcement_model = os.environ.get("ANNOUNCEMENT_MODEL", "gpt-4o")
    announcement_temperature = float(os.environ.get("ANNOUNCEMENT_TEMPERATURE", "0.9"))
    batch_window_seconds = float(os.environ.get("BATCH_WINDOW_SECONDS", "5.0"))

    # Create server using the universal adaptor
    server_config = MCPServerConfig(
        transport="streamable_http",  # or "sse" or "stdio"
        url=mcp_server_url,
        client_session_timeout=300.0,  # 5 minutes for very slow operations
    )
    mcp_server = create_mcp_server(server_config)

    # Create progress manager if progress announcements are enabled
    # We'll set up the callback after agent is created
    progress_manager = None
    speak_callback_ref: dict = {"callback": None}  # Use dict to allow closure modification

    if enable_progress_announcements:
        def speak_callback(text: str):
            """Callback to speak progress updates."""
            cb = speak_callback_ref.get("callback")
            if cb:
                cb(text)

        progress_manager = ProgressManager(
            speak_callback=speak_callback,
            enable_natural_language=enable_natural_language,
            dedup_window_seconds=3.0,
            model=announcement_model,
            temperature=announcement_temperature,
            batch_window_seconds=batch_window_seconds
        )

    # Wrap the server with progress support
    wrapped_server = MCPServerWrapper(
        mcp_server,
        progress_manager=progress_manager
    )

    # Create the agent with the wrapped MCP server
    agent = FunctionAgent(
        mcp_servers=[wrapped_server],
        enable_tool_announcements=enable_tool_announcements,
        enable_query_intent_announcement=enable_query_intent_announcement,
        announcement_model=announcement_model,
        announcement_temperature=announcement_temperature
    )

    # Now set up the speak callback to use the agent
    if enable_progress_announcements:
        def agent_speak_callback(text: str):
            if hasattr(agent, '_activity') and agent._activity is not None:
                agent._activity.say(text)
        speak_callback_ref["callback"] = agent_speak_callback

    await ctx.connect()

    # Create session with increased max_tool_steps
    session = AgentSession(max_tool_steps=10)
    await session.start(agent=agent, room=ctx.room)

    await session.generate_reply(instructions="Briefly, tell the user you can answer questions about the in-my-store sales data and ask what they would like to know.")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
