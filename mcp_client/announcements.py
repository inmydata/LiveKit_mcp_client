"""Natural language announcement generation using LLM."""

import os
import logging
from typing import Set, Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)


async def generate_tool_announcement(
    user_query: str,
    tool_name: str,
    tool_description: str = "",
    tool_arguments: Optional[Dict[str, Any]] = None,
    previously_announced: Optional[Set[str]] = None,
    model: str = "gpt-4o",
    temperature: float = 0.9,
    max_tokens: int = 35
) -> str:
    """Generate a natural, conversational tool announcement using LLM.

    Args:
        user_query: The user's original question
        tool_name: Name of the tool being called
        tool_description: Description of what the tool does
        tool_arguments: Arguments being passed to the tool
        previously_announced: Set of phrases already announced (to avoid repetition)
        model: LLM model to use (default: gpt-4o)
        temperature: LLM temperature (default: 0.9 for variety)
        max_tokens: Maximum tokens to generate (default: 35)

    Returns:
        A natural, conversational phrase describing what the agent is doing
    """
    if previously_announced is None:
        previously_announced = set()
    if tool_arguments is None:
        tool_arguments = {}

    try:
        # Add context about previously announced phrases to avoid repetition
        avoid_phrases = ""
        if previously_announced:
            avoid_phrases = "\n\nIMPORTANT: You've already said these phrases in this conversation, so say something DIFFERENT:\n" + "\n".join([f"- {phrase}" for phrase in previously_announced])

        # Add tool details for more specific announcements
        tool_details = f"\n\nTool details:\n- Name: {tool_name}"
        if tool_description:
            tool_details += f"\n- Purpose: {tool_description}"

        # Extract the most specific/meaningful arguments to mention
        specific_values = []
        if tool_arguments:
            # Prioritize human-readable values like names, dates, specific filters
            priority_keys = ['name', 'person', 'salesperson', 'sales_person', 'store', 'product',
                           'customer', 'employee', 'user', 'id', 'date', 'period', 'year']

            # First add priority keys if they exist
            for key in priority_keys:
                if key in tool_arguments and tool_arguments[key]:
                    specific_values.append(f"{key}: {tool_arguments[key]}")

            # Then add other meaningful keys (skip very generic ones)
            skip_keys = ['subject', 'select', 'format', 'limit']
            for key, value in tool_arguments.items():
                if value and key not in skip_keys and key not in priority_keys:
                    # Limit long values
                    val_str = str(value)
                    if len(val_str) > 50:
                        val_str = val_str[:50] + "..."
                    specific_values.append(f"{key}: {val_str}")

            if specific_values:
                tool_details += f"\n- Specific parameters:\n  " + "\n  ".join(specific_values[:5])  # Top 5 most relevant

        # Check if this looks like a schema/metadata tool (don't announce these verbosely)
        is_metadata_tool = tool_name.lower() in ['get_schema', 'get_financial_periods', 'get_calendar_period_date_range']

        if is_metadata_tool:
            # For metadata tools, just say "one moment" or similar - don't narrate technical steps
            prompt = f"""You're helping someone and doing background prep work before answering.

The user asked: "{user_query}"

You're calling a technical tool ({tool_name}) to gather metadata needed to answer properly.

Say something VERY brief (4-8 words) that sounds like you're thinking/working:

Examples:
- "OK, I'm just gathering some information"
- "I'm just gathering some general information"
- "Bear with me, I won't be long"
- "Let me see"

Your response (4-8 words only):"""
        else:
            # For actual data tools, be more descriptive
            prompt = f"""You are a helpful voice assistant. The user just asked: "{user_query}"

You're about to call a tool to get their answer.{tool_details}

CRITICAL: If there are specific parameters (like a person's name, date, store name, etc.), MENTION THEM in your response!
Be SPECIFIC - don't just say "fetching data", say WHAT you're fetching and FOR WHOM/WHAT.

Generate a brief, natural phrase (6-12 words max) that:
1. Mentions any specific names, dates, or identifiers from the parameters
2. Connects to what the user asked for
3. Sounds like casual speech, not a technical description{avoid_phrases}

Good examples (notice the specifics):
- "I'm looking up Jerry Lewis's transaction details"
- "OK, now I'm checking Barry White's sales numbers now"
- "Thanks for your patience. Now I'm getting the data for Tony Goldsmith"
- "OK, now I'm looking up last week's numbers for the London store"
- "Nearly there! Just pulling up Sarah's performance metrics"

Bad examples (too generic):
- "Fetching that data for you"
- "Retrieving the information"
- "Getting those details"

Your response (just the phrase, nothing else):"""

        # Use OpenAI to generate the response
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )

        result = response.choices[0].message.content
        if result:
            result = result.strip()
            # Remove quotes if the LLM added them
            result = result.strip('"').strip("'")
            return result
        else:
            return "Let me check that for you."

    except Exception as e:
        logger.warning(f"Error generating tool announcement: {e}")
        return "Let me check that for you."


async def generate_progress_announcement(
    progress_message: Union[str, List[str]],
    previously_announced: Optional[List[str]] = None,
    raw_messages: Optional[List[str]] = None,
    model: str = "gpt-4o",
    temperature: float = 0.9,
    max_tokens: int = 20
) -> str:
    """Rephrase a technical progress message (or batch of messages) into natural language.

    Args:
        progress_message: Single raw message or list of batched messages from the MCP tool
        previously_announced: List of natural phrases already announced (to build narrative flow)
        raw_messages: List of raw progress messages received (to see what's actually changing)
        model: LLM model to use (default: gpt-4o)
        temperature: LLM temperature (default: 0.9 for variety)
        max_tokens: Maximum tokens to generate (default: 20)

    Returns:
        A natural, conversational rephrasing of the progress message(s)
    """
    if previously_announced is None:
        previously_announced = []
    if raw_messages is None:
        raw_messages = []

    # Convert single message to list for uniform handling
    if isinstance(progress_message, str):
        messages = [progress_message]
    else:
        messages = progress_message

    try:
        # Build context of conversation flow
        context = ""
        if previously_announced and len(previously_announced) > 0:
            recent = previously_announced[-3:]  # Last 3 messages for context
            context = "\n\nYou've already said to the user:\n" + "\n".join([f"- \"{msg}\"" for msg in recent])
            context += "\n\nIMPORTANT: Say something DIFFERENT this time. Build on the narrative, don't repeat."

        # Add info about what's actually changing in the raw messages
        if raw_messages and len(raw_messages) > 1:
            recent_raw = raw_messages[-3:]
            context += f"\n\nRecent progress updates from the system:\n" + "\n".join([f"- {msg}" for msg in recent_raw])
            context += f"\n\nNotice what's DIFFERENT in the latest update and reflect that change."

        # Format the messages for the prompt
        if len(messages) == 1:
            system_message = f'System message: "{messages[0]}"'
        else:
            system_message = f"System sent {len(messages)} quick updates:\n" + "\n".join([f'- "{msg}"' for msg in messages])
            system_message += f"\n\nSummarize what's happening overall (don't list each step)."

        prompt = f"""You're helping someone and giving them quick casual updates while you work.

{system_message}{context}

Turn this into a super casual, natural spoken update (3-6 words max).
Talk like you're thinking out loud while working, NOT like you're reading a procedure manual.
Be LAZY with words - just mention the overall progress, don't narrate every step.

DO (casual, minimal):
- "Got it"
- "Hmm, lots of rows"
- "Okay, comparing now"
- "Almost there"
- "Just checking something"

DON'T (too formal/procedural):
- "Gathering all sales records"
- "Calculating the total sales figure"
- "Finalizing the analysis"
- "Diving into the details"
- "Let's break down these rows"

Just say what you're actually seeing/doing right now (3-6 words):"""

        # Use OpenAI to generate the response
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )

        result = response.choices[0].message.content
        if result:
            result = result.strip()
            result = result.strip('"').strip("'")
            return result
        else:
            return "Still working on that."

    except Exception as e:
        logger.warning(f"Error generating progress announcement: {e}")
        return "Still working on that."


async def generate_query_intent_announcement(
    user_query: str,
    tools_involved: List[str],
    model: str = "gpt-4o",
    temperature: float = 0.8,
    max_tokens: int = 40
) -> str:
    """Generate initial announcement about what the agent will do.

    This creates an upfront, confident statement that sets context for the user
    about what work is about to be done.

    Args:
        user_query: The user's original question
        tools_involved: List of tool names that will be called
        model: LLM model to use (default: gpt-4o)
        temperature: LLM temperature (default: 0.8)
        max_tokens: Maximum tokens to generate (default: 40)

    Returns:
        A natural opening statement like "OK, I'm going to work through projecting the sales performance for you"

    Examples:
        - "OK, I'm going to work through projecting the sales performance for you"
        - "Let me analyze the year-over-year trends across all stores"
        - "I'll compare this year's performance to last year's numbers"
    """
    try:
        # Format tool names in a readable way
        tools_text = ""
        if tools_involved:
            tools_text = f"\n\nYou'll be using these tools: {', '.join(tools_involved[:3])}"  # Limit to 3

        prompt = f"""You are a helpful voice assistant. The user just asked: "{user_query}"{tools_text}

You're about to work through this request to help answer their question.

Generate a brief, natural opening statement (12-15 words) that:
1. Acknowledges what you're about to do
2. Sounds confident and helpful
3. Uses phrases like "OK, I'm going to...", "Let me...", "I'll...", "Alright, I'll..."
4. Mentions the key task in a natural way

Be specific about what you'll do, but keep it conversational and friendly.

Examples:
- "OK, I'm going to work through projecting the sales performance for you"
- "Let me analyze the year-over-year trends across all stores"
- "Alright, I'll compare this year's numbers to last year"
- "OK, let me pull together those sales figures for you"
- "I'll work through the store rankings based on that data"

Your response (just the opening statement, nothing else):"""

        # Use OpenAI to generate the response
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )

        result = response.choices[0].message.content
        if result:
            result = result.strip()
            # Remove quotes if the LLM added them
            result = result.strip('"').strip("'")
            return result
        else:
            return "OK, let me work on that for you."

    except Exception as e:
        logger.warning(f"Error generating query intent announcement: {e}")
        return "OK, let me work on that for you."
