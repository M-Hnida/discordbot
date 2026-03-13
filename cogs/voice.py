import discord
from discord import app_commands
from discord.ext import commands
from discord import FFmpegPCMAudio
import os
import asyncio
from providers import get_tts_provider, get_llm_provider


class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists("media/tts"):
            os.makedirs("media/tts")

        self.ffmpeg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ffmpeg-7.1.1-essentials_build",
            "bin",
            "ffmpeg.exe",
        )

        tts_name = self.bot.config.get("tts_provider", "fishaudio")
        llm_name = self.bot.config.get("llm_provider", "openrouter")

        try:
            self.tts_provider = get_tts_provider(
                tts_name,
                api_key=self.bot.config.get("fishaudio_api_key"),
                voice_id=self.bot.config.get("fishaudio_voice_id"),
            )
        except Exception as e:
            print(f"Failed to load TTS provider: {e}")
            self.tts_provider = get_tts_provider("fishaudio")

        try:
            self.llm_provider = get_llm_provider(llm_name)
        except:
            self.llm_provider = get_llm_provider("openrouter")

    async def _play_audio(self, interaction, audio_data):
        """Helper to play audio bytes."""
        temp_file = f"media/tts/voice_{interaction.id}.mp3"
        with open(temp_file, "wb") as f:
            f.write(audio_data)

        try:
            guild = interaction.guild
            if not guild:
                return

            voice_client = guild.voice_client
            if not voice_client:
                if interaction.user.voice:
                    voice_client = await interaction.user.voice.channel.connect()
                else:
                    return

            if voice_client.is_playing():
                voice_client.stop()

            source = FFmpegPCMAudio(temp_file, executable=self.ffmpeg_path)
            voice_client.play(source)

            while voice_client.is_playing():
                await asyncio.sleep(0.1)

        except Exception as e:
            print(f"Play Audio Error: {e}")
            await interaction.followup.send(f"audio error: {e}", ephemeral=True)
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    @app_commands.command(name="join", description="Join your voice channel.")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            return await interaction.response.send_message(
                "❌ You are not in a voice channel.", ephemeral=True
            )

        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.response.send_message(f"👋 Connected to **{channel.name}**!")

    @app_commands.command(name="leave", description="Leave the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("👋 Bye!", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ I'm not in a voice channel.", ephemeral=True
            )

    @app_commands.command(name="tts", description="Generate audio response from text.")
    async def tts(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()

        # 1. Ask AI
        conversation = [
            {"role": "system", "content": self.bot.system_prompt},
            {"role": "user", "content": text},
        ]

        # Use simple blocking call or robust async wrapper - reusing simple logic here
        response = await asyncio.to_thread(
            self.llm_provider.chat, messages=conversation
        )

        content = ""
        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]

        if not content:
            await interaction.followup.send("❌ AI gave no response.")
            return

        # 2. Generate Audio via Provider
        audio_data = await asyncio.to_thread(self.tts_provider.generate_audio, content)

        if not audio_data:
            await interaction.followup.send(
                f"🗣️ **Response:** {content}\n*(Audio generation failed)*"
            )
            return

        # 3. Send File
        temp_file = f"media/tts/temp_{interaction.id}.mp3"
        with open(temp_file, "wb") as f:
            f.write(audio_data)

        await interaction.followup.send(
            f"🗣️ **Response:** {content}", file=discord.File(temp_file, "tts.mp3")
        )
        os.remove(temp_file)


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
