import os
import discord
from discord.ext import commands
from discord import app_commands
import re
import traceback
from providers import get_llm_provider
from providers.mcp_manager import MCPManager


class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.llm_provider = None
        self.mcp: MCPManager | None = None
        self._init_providers()

    def _init_providers(self):
        provider_name = self.bot.config.get("llm_provider", "openrouter")
        api_key = self.bot.config.get("api_key") or os.getenv(
            self.bot.config.get("api_key_env", ""), None
        )
        try:
            self.llm_provider = get_llm_provider(
                provider_name,
                base_url=self.bot.config.get("base_url"),
                api_key=api_key,
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"LLM provider init failed: {e}")

    async def cog_load(self):
        mcp_configs = self.bot.config.get("mcp_servers", [])
        if mcp_configs:
            self.mcp = MCPManager(mcp_configs)
            await self.mcp.start()

    async def cog_unload(self):
        if self.mcp:
            await self.mcp.stop()

    def _get_provider(self, user_id: int):
        return self.llm_provider

    async def _call_ai_api(self, conversation, images=None, user_id: int = None, channel=None):
        provider = self._get_provider(user_id)
        if not provider:
            return None, "No AI provider configured"

        # 1. Gather Tools
        mcp_tools = self.mcp.openai_schemas() if self.mcp and self.mcp.tools else []

        local_tools = [
            {
                "type": "function",
                "function": {
                    "name": "update_user_preferences",
                    "description": "Store or update permanent factual notes about a user (e.g., their name, interests, job, preferences). Use clearly formatted bullet points.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "notes": {
                                "type": "string",
                                "description": "The updated set of notes for this user. This overrides previous notes, so include existing info if it's still relevant.",
                            }
                        },
                        "required": ["notes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_image",
                    "description": "Send an image to the Discord channel. Use this when you want to show the user a relevant image, meme, chart, diagram, or any visual content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_url": {
                                "type": "string",
                                "description": "The URL of the image to send. Must be a direct link to an image (jpg, png, gif, webp).",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Optional caption to accompany the image.",
                            },
                        },
                        "required": ["image_url"],
                    },
                },
            },
        ]

        all_tools = mcp_tools + local_tools
        tools = all_tools if all_tools else None

        # 2. Define Unified Tool Executor
        async def unified_executor(name: str, arguments: dict) -> str:
            if name == "update_user_preferences":
                if not user_id:
                    return "Error: No user_id provided to store preferences."
                notes = arguments.get("notes", "")
                await self.bot.database.update_user_notes(str(user_id), notes)
                return f"Successfully updated preferences for user {user_id}."

            if name == "send_image":
                if not channel:
                    return "Error: No channel context available."
                image_url = arguments.get("image_url", "")
                caption = arguments.get("caption", "")
                if not image_url:
                    return "Error: No image_url provided."

                try:
                    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
                    if not any(image_url.lower().endswith(ext) for ext in image_extensions):
                        pass

                    embed = discord.Embed()
                    embed.set_image(url=image_url)
                    if caption:
                        embed.description = caption

                    await channel.send(embed=embed)
                    return f"Image sent successfully: {image_url}"
                except Exception as e:
                    return f"Error sending image: {e}"

            # Fallback to MCP tools
            if self.mcp:
                return await self.mcp.call_tool(name, arguments)
            return f"Error: Tool '{name}' not found."

        try:
            model = getattr(self.bot, "model", None)
            response = await provider.chat(
                messages=conversation,
                images=images,
                model=model,
                tools=tools,
                tool_executor=unified_executor,
            )

            if not response or "error" in response:
                error_msg = (
                    response.get("error", {}).get("message", "Unknown Error")
                    if response
                    else "No response"
                )
                return None, f"⚠️ Error from AI: {error_msg}"

            choices = response.get("choices", [])
            if not choices:
                return None, "⚠️ AI returned no content."

            content = choices[0].get("message", {}).get("content", "")
            chunks = response.get("additional_chunks", [])
            return content, chunks

        except Exception as e:
            traceback.print_exc()
            return None, f"⚠️ Critical Error: {e}"

    @commands.Cog.listener()
    async def on_ready(self):
        if not getattr(self.bot, "is_primary", False):
            return

        print(f"[Sync] Checking message history for {self.bot.user}...")
        try:
            for guild in self.bot.guilds:
                if not guild:
                    continue
                for channel in guild.text_channels:
                    try:
                        # Fetch last 30 messages in the channel natively
                        recent_msgs = [m async for m in channel.history(limit=30)]
                        if not recent_msgs:
                            continue

                        discord_ids = {str(m.id) for m in recent_msgs}
                        oldest_discord_id = recent_msgs[-1].id

                        bot_id = str(channel.id)
                        db_ids = await self.bot.database.get_recent_message_ids(
                            bot_id, str(channel.id), limit=30
                        )
                        db_id_set = set(db_ids)

                        # Delete messages that were deleted on discord while bot was offline
                        for db_id in db_ids:
                            # if it's strictly newer than the oldest message we fetched, but missing entirely, it was deleted
                            if (
                                int(db_id) >= oldest_discord_id
                                and db_id not in discord_ids
                            ):
                                await self.bot.database.delete_message_by_discord_id(
                                    db_id
                                )

                        # Add messages that happened while bot was offline
                        recent_msgs.reverse()  # Sort chronologically
                        for m in recent_msgs:
                            m_id = str(m.id)
                            if m_id not in db_id_set:
                                # Need to sync this missing message
                                role = (
                                    "assistant"
                                    if m.author.id == self.bot.user.id
                                    else "user"
                                )
                                image_urls = (
                                    [
                                        att.url
                                        for att in m.attachments
                                        if att.content_type
                                        and att.content_type.startswith("image/")
                                    ]
                                    if not m.author.bot
                                    else None
                                )

                                await self.bot.database.add_message(
                                    bot_id=bot_id,
                                    channel_id=str(channel.id),
                                    role=role,
                                    content=m.content,
                                    user_id=str(m.author.id),
                                    user_name=m.author.display_name,
                                    message_id=m_id,
                                    image_urls=image_urls if image_urls else None,
                                )
                    except Exception:
                        # Silently skip channels with no read permissions
                        pass
        except Exception as e:
            print(f"[Sync] Error: {e}")
        print("[Sync] History sync complete.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Keyword Check
        msg_lower = message.content.lower()
        keyword_responses = self.bot.config.get("keyword_responses", {})

        for keyword, data in keyword_responses.items():
            if keyword.lower() in msg_lower:
                try:
                    if data["type"] == "text":
                        await message.channel.send(data["content"])
                    elif data["type"] == "file":
                        await message.channel.send(file=discord.File(data["path"]))
                    return
                except Exception as e:
                    print(f"[Error] Keyword response failed: {e}")

        # AI Chat Trigger
        is_reply = (
            message.reference
            and message.reference.resolved
            and message.reference.resolved.author.id == self.bot.user.id
        )

        if self.bot.user.mentioned_in(message) or is_reply:
            await self.process_ai_chat(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Syncs Discord message deletions with the database."""
        try:
            await self.bot.database.delete_message_by_discord_id(str(message.id))
        except Exception as e:
            print(f"[Error] Failed to delete message from DB: {e}")

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Classic 'Stalk' feature."""
        stalk_id = self.bot.config.get("stalk_id")
        if not stalk_id:
            return

        # Check if target came online
        if (
            before.id == stalk_id
            and before.status != discord.Status.online
            and after.status == discord.Status.online
        ):
            channel_id = self.bot.config.get("general_channel_id")
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send(
                        f"👀 **{after.name}** is ONLINE! <@{after.id}> come voice! 🎙️"
                    )

    async def process_ai_chat(self, message: discord.Message):
        if not self.bot.system_prompt:
            await message.reply("❌ System prompt is missing.")
            return

        user_message = re.sub(
            r"<@!?{}>".format(self.bot.user.id), "", message.content
        ).strip()

        image_urls = [
            att.url
            for att in message.attachments
            if att.content_type and att.content_type.startswith("image/")
        ]

        # Download images as bytes for Gemini
        import httpx
        image_data = []
        for url in image_urls:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        image_data.append(resp.content)
            except Exception as e:
                print(f"Failed to download image: {e}")

        # 1. Save USER message (with user_name and image URLs!)
        await self.bot.database.add_message(
            bot_id=str(message.channel.id),
            channel_id=str(message.channel.id),
            role="user",
            content=user_message,
            user_id=str(message.author.id),
            user_name=message.author.display_name,
            message_id=str(message.id),
            image_urls=image_urls if image_urls else None,
        )

        async with message.channel.typing():
            # 2. Fetch context & Preferences
            history = await self.bot.database.get_context(
                bot_id=str(message.channel.id),
                channel_id=str(message.channel.id),
                limit=15,
                bot_name=self.bot.user.name,
            )
            user_notes = await self.bot.database.get_user_notes(str(message.author.id))

            # 3. Build Payload
            from datetime import datetime

            now = datetime.now()

            sys_info = (
                f"\n\n[System Context]\n"
                f"Current Time: {now.strftime('%H:%M:%S')}\n"
                f"Current Date: {now.strftime('%Y-%m-%d')}\n"
                f"Day: {now.strftime('%A')}\n\n"
            )

            if user_notes:
                sys_info += f"[User Preferences for {message.author.display_name}]\n{user_notes}\n\n"

            sys_info += (
                "MEME TRENDS & EXPRESSION:\n"
                "1. Use `exa_web_search` + 'Know Your Meme' to check for current trends.\n"
                "2. If you learn something permanent about the user, call `update_user_preferences` to remember it."
            )

            conversation = [
                {"role": "system", "content": self.bot.system_prompt + sys_info}
            ]

            # Add history but strip image_urls - we only pass current images to API
            for msg in history:
                conversation.append({"role": msg["role"], "content": msg["content"]})

            content, chunks = await self._call_ai_api(
                conversation, image_data, user_id=message.author.id, channel=message.channel
            )

            if not content:
                error_text = str(chunks)[:2000]
                await message.reply(error_text)
                return

            # If there were images, create a brief description to add to the user message in history
            if image_urls:
                # Extract key info from the assistant's response for context
                # Use first sentence or first 100 chars as a brief description
                brief_desc = (
                    content.split(".")[0][:100] if content else "image analysis"
                )
                updated_content = f"{user_message} [Image shown: {brief_desc}]"

                # Update the user message in database with the image context
                await self.bot.database.update_last_user_message(
                    bot_id=str(message.channel.id),
                    channel_id=str(message.channel.id),
                    new_content=updated_content,
                )

            # Send the main chunk
            reply_msg = await message.reply(content)

            # 4. Save ASSISTANT response
            await self.bot.database.add_message(
                bot_id=str(message.channel.id),
                channel_id=str(message.channel.id),
                role="assistant",
                content=content,
                message_id=str(reply_msg.id),
                user_name=self.bot.user.display_name,
            )

            # Send additional chunks if they exist
            for chunk in chunks:
                await message.channel.send(chunk)

    @app_commands.command(
        name="clear_memory", description="Clears memory for this channel."
    )
    async def clear_memory(self, interaction: discord.Interaction):
        await self.bot.database.clear_history(
            str(interaction.channel_id), str(interaction.channel_id)
        )
        await interaction.response.send_message("🧠 Memory wiped.", ephemeral=True)

    @app_commands.command(name="analyze_chat", description="Analyzes chat history.")
    async def analyze_chat(self, interaction: discord.Interaction, limit: int = 20):
        await interaction.response.defer()
        messages = [
            f"{m.author.display_name}: {m.content}"
            async for m in interaction.channel.history(limit=limit)
        ]
        messages.reverse()
        prompt = "Analyze:\n" + "\n".join(messages)
        conversation = [
            {"role": "system", "content": "You are an analyzer."},
            {"role": "user", "content": prompt},
        ]
        content, _ = await self._call_ai_api(conversation, channel=interaction.channel)
        if content:
            await interaction.followup.send(content)
        else:
            await interaction.followup.send("Failed.")

    @app_commands.command(
        name="analyze_image", description="Analyzes an attached image."
    )
    async def analyze_image(
        self,
        interaction: discord.Interaction,
        prompt: str = "Describe this image in detail.",
    ):
        await interaction.response.defer()

        # Check for attached images in the interaction
        # Slash commands don't directly support attachments, so we need to look for recent messages or tell user to attach
        # For now, we'll check the channel history for the user's recent message with image

        # Get the user's last message in the channel
        user_messages = []
        async for msg in interaction.channel.history(limit=10):
            if msg.author == interaction.user and msg.attachments:
                image_urls = [
                    att.url
                    for att in msg.attachments
                    if att.content_type and att.content_type.startswith("image/")
                ]
                if image_urls:
                    user_messages.append((msg, image_urls))
                    break  # Use the most recent one

        if not user_messages:
            await interaction.followup.send(
                "Please attach an image to your message and use this command, or reply to a message with an image."
            )
            return

        msg, image_urls = user_messages[0]

        conversation = [
            {
                "role": "system",
                "content": "You are an image analyzer. Describe images accurately and in detail.",
            },
            {"role": "user", "content": prompt},
        ]

        content, chunks = await self._call_ai_api(conversation, image_urls, channel=interaction.channel)

        if not content:
            await interaction.followup.send("Failed to analyze the image.")
            return

        response = f"**Analysis of your image:**\n{content}"
        if len(response) > 2000:
            response = response[:1997] + "..."

        await interaction.followup.send(response)
        for chunk in chunks:
            await interaction.channel.send(chunk)


async def setup(bot):
    await bot.add_cog(ChatCog(bot))
