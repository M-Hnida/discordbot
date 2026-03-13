import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal, Optional


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="remove", description="Deletes the last N messages from the bot."
    )
    @app_commands.describe(amount="Number of messages to delete (1-50).")
    async def remove(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 50] = 1,
    ):
        """Deletes messages sent by the bot."""
        if not isinstance(
            interaction.channel, (discord.TextChannel, discord.DMChannel)
        ):
            await interaction.response.send_message(
                "Not available here.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Find bot messages
            def is_me(m):
                return m.author == self.bot.user

            deleted = 0
            if isinstance(interaction.channel, discord.TextChannel):
                # Bulk delete
                deleted_msgs = await interaction.channel.purge(
                    limit=amount + 20, check=is_me
                )
                deleted = len(deleted_msgs)
            else:
                # Manual delete (DMs)
                async for msg in interaction.channel.history(limit=50):
                    if is_me(msg) and deleted < amount:
                        await msg.delete()
                        deleted += 1

            await interaction.followup.send(
                f"Deleted {deleted} messages.", ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to delete messages.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    # --- PREFIX COMMAND FOR INSTANT SYNC ---
    # This must be invoked with !sync (or your prefix) in chat, NOT slash /sync
    @commands.command()
    @commands.is_owner()
    async def sync(
        self, ctx: commands.Context, spec: Optional[Literal["~", "*", "^"]] = None
    ) -> None:
        """
        !sync -> global sync (slow)
        !sync ~ -> sync current guild (fast)
        !sync * -> copy global to current guild (fast)
        !sync ^ -> clear current guild
        """
        if spec == "~":
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced = []
        else:
            synced = await ctx.bot.tree.sync()

        await ctx.send(
            f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild'}."
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
