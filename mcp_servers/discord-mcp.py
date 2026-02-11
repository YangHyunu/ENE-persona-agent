
import os
import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, List
from dotenv import load_dotenv
import discord
from discord.ext import commands
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord-mcp-server")

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is required")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variable to store the Discord client instance once the bot is ready.
discord_client = None
# Store the main event loop for cross-thread communication
main_event_loop = None

# Create FastMCP server instance
app = FastMCP("discord-server")

def format_reactions(reactions: List[dict]) -> str:
    """
    Format a list of reaction dictionaries into a human-readable string.
    Each reaction is shown as: emoji(count).
    If no reactions are present, returns "No reactions".
    """
    if not reactions:
        return "No reactions"
    return ", ".join(f"{r['emoji']}({r['count']})" for r in reactions)

@bot.event
async def on_ready():
    """
    Event handler called when the Discord bot successfully logs in.
    Sets the global discord_client variable and logs the bot's username.
    """
    global discord_client, main_event_loop
    discord_client = bot
    main_event_loop = asyncio.get_running_loop()
    logger.info(f"✅ Logged in as {bot.user.name}")

async def _send_message_impl(channel_id: str, content: str) -> str:
    """Implementation of send_message that runs in the main event loop"""
    channel = await discord_client.fetch_channel(int(channel_id))
    message = await channel.send(content)
    return f"Message sent successfully. Message ID: {message.id}"


@app.tool()
async def send_message(channel_id: str, content: str) -> str:
    """Send a message to a specific channel

    Args:
        channel_id: Discord channel ID where the message will be sent
        content: Content of the message to send

    Returns:
        Success message with the message ID
    """
    if not discord_client or not main_event_loop:
        raise RuntimeError("Discord client not ready")

    # Schedule the coroutine in the main event loop and wait for result
    future = asyncio.run_coroutine_threadsafe(
        _send_message_impl(channel_id, content),
        main_event_loop
    )
    return future.result(timeout=30)

async def _read_messages_impl(channel_id: str, limit: int) -> str:
    """Implementation of read_messages that runs in the main event loop"""
    channel = await discord_client.fetch_channel(int(channel_id))
    limit = min(int(limit), 100)
    messages = []

    async for message in channel.history(limit=limit):
        reaction_data = []

        # Iterate through reactions and collect emoji data.
        for reaction in message.reactions:
            emoji_str = (
                str(reaction.emoji.name)
                if hasattr(reaction.emoji, "name") and reaction.emoji.name
                else (
                    str(reaction.emoji.id)
                    if hasattr(reaction.emoji, "id")
                    else str(reaction.emoji)
                )
            )
            reaction_info = {"emoji": emoji_str, "count": reaction.count}
            logger.debug(f"Found reaction: {emoji_str}")
            reaction_data.append(reaction_info)

        messages.append(
            {
                "id": str(message.id),
                "author": str(message.author),
                "content": message.content,
                "timestamp": message.created_at.isoformat(),
                "reactions": reaction_data,
            }
        )

    # Format the messages for output.
    formatted_messages = "\n".join(
        f"{m['author']} ({m['timestamp']}): {m['content']}\nReactions: {format_reactions(m['reactions'])}"
        for m in messages
    )
    return f"Retrieved {len(messages)} messages:\n\n{formatted_messages}"


@app.tool()
async def read_messages(channel_id: str, limit: int = 10) -> str:
    """Read recent messages from a channel

    Args:
        channel_id: Discord channel ID from which to fetch messages
        limit: Number of messages to fetch (max 100, default 10)

    Returns:
        Formatted string containing retrieved messages with reactions
    """
    if not discord_client or not main_event_loop:
        raise RuntimeError("Discord client not ready")

    # Schedule the coroutine in the main event loop and wait for result
    future = asyncio.run_coroutine_threadsafe(
        _read_messages_impl(channel_id, limit),
        main_event_loop
    )
    return future.result(timeout=30)

async def _add_reaction_impl(channel_id: str, message_id: str, emoji: str) -> str:
    """Implementation of add_reaction that runs in the main event loop"""
    channel = await discord_client.fetch_channel(int(channel_id))
    message = await channel.fetch_message(int(message_id))
    await message.add_reaction(emoji)
    return f"Added reaction '{emoji}' to message {message.id}"


@app.tool()
async def add_reaction(channel_id: str, message_id: str, emoji: str) -> str:
    """Add a reaction to a message

    Args:
        channel_id: ID of the channel containing the message
        message_id: ID of the message to react to
        emoji: Emoji to react with (Unicode or custom emoji ID)

    Returns:
        Success message with reaction details
    """
    if not discord_client or not main_event_loop:
        raise RuntimeError("Discord client not ready")

    # Schedule the coroutine in the main event loop and wait for result
    future = asyncio.run_coroutine_threadsafe(
        _add_reaction_impl(channel_id, message_id, emoji),
        main_event_loop
    )
    return future.result(timeout=30)

def run_mcp_server():
    """Run FastMCP HTTP server in a separate thread with its own event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        logger.info("🌐 Starting FastMCP server on http://localhost:8000")
        loop.run_until_complete(
            # `FastMCP.run` defaults to the "stdio" transport when no
            # `transport` is provided. Passing HTTP kwargs without also
            # specifying `transport="http"` will forward those kwargs to
            # the stdio runner and raise a TypeError. Be explicit so the
            # correct transport is selected.
            app.run(
                transport="http",
                host="localhost",
                port=8001,
                log_level="info",
                path="/mcp/",
            )
        )
    finally:
        loop.close()

async def main():
    """Main entry point - Discord bot in main thread, MCP server in separate thread"""
    
    # Start FastMCP HTTP server in a background thread
    mcp_thread = threading.Thread(target=run_mcp_server, daemon=True)
    mcp_thread.start()
    logger.info("⏳ MCP server thread started")
    
    # Start Discord bot in the main asyncio event loop
    logger.info("⏳ Starting Discord bot...")
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")