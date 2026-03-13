import discord
from discord.ext import commands
import asyncio
import json
import os
import platform
import logging
from dotenv import load_dotenv
from database import Database

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")


class MyBot(commands.Bot):
    def __init__(self, bot_name: str, config: dict, database: Database):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True

        super().__init__(command_prefix="!", intents=intents)

        self.bot_name = bot_name
        self.config = config
        self.database = database
        self.bot_dir = os.path.join("bots", bot_name)
        self.system_prompt = self._load_prompt()
        self.model = config.get("model")
        self.is_primary = config.get("is_primary", False)

    def _load_prompt(self):
        prompt_path = os.path.join(self.bot_dir, "prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        logger.warning(f"Prompt file not found for {self.bot_name} at {prompt_path}")
        return "You are a helpful assistant."

    async def setup_hook(self):
        cogs_to_load = ["cogs.chat", "cogs.admin", "cogs.voice"]
        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
            except Exception as e:
                logger.error(f"Failed to load core cog {cog}: {e}")

        plugins_dir = os.path.join(self.bot_dir, "plugins")
        if os.path.exists(plugins_dir):
            for filename in os.listdir(plugins_dir):
                if filename.endswith(".py") and not filename.startswith("_"):
                    plugin_path = f"bots.{self.bot_name}.plugins.{filename[:-3]}"
                    try:
                        await self.load_extension(plugin_path)
                        logger.info(f"Loaded plugin {plugin_path} for {self.bot_name}")
                    except Exception as e:
                        logger.error(f"Failed to load plugin {plugin_path}: {e}")

        commands_count = len(self.tree.get_commands())
        logger.info(f"Tree has {commands_count} commands registered before sync.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id}) [{self.bot_name}]")


ARRAY_MERGE_KEYS = {"mcp_servers"}

# Keys that must only come from environment variables, not config files
ENV_ONLY_KEYS = {"api_key"}


def load_global_config() -> dict:
    path = "config.json"
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Strip comment keys and env-only keys
            return {k: v for k, v in cfg.items() if not k.startswith("_") and k not in ENV_ONLY_KEYS}
    except Exception as e:
        logger.error(f"Failed to load global config: {e}")
        return {}


def merge_configs(global_cfg: dict, bot_cfg: dict) -> dict:
    """
    Merge global config with bot-specific config.
    - Bot values override global for scalar fields.
    - Array fields in ARRAY_MERGE_KEYS are concatenated: global + bot.
    """
    merged = {**global_cfg, **bot_cfg}
    for key in ARRAY_MERGE_KEYS:
        global_list = global_cfg.get(key, [])
        bot_list = bot_cfg.get(key, [])
        merged[key] = global_list + bot_list
    return merged


def load_bot_configs(global_cfg: dict) -> dict:
    bots_dir = "bots"
    configs = {}

    if not os.path.exists(bots_dir):
        return configs

    for bot_folder in os.listdir(bots_dir):
        bot_path = os.path.join(bots_dir, bot_folder)
        if os.path.isdir(bot_path) and not bot_folder.startswith("_"):
            config_file = os.path.join(bot_path, "config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        bot_cfg = json.load(f)
                        # Strip env-only keys from bot config
                        bot_cfg = {k: v for k, v in bot_cfg.items() if k not in ENV_ONLY_KEYS}
                        configs[bot_folder] = merge_configs(global_cfg, bot_cfg)
                except Exception as e:
                    logger.error(f"Failed to load config for {bot_folder}: {e}")

    return configs


async def main():
    db = Database()
    await db.initialize()

    global_cfg = load_global_config()
    bot_configs = load_bot_configs(global_cfg)
    bots_to_run = []

    for bot_name, config in bot_configs.items():
        if config.get("active", False):
            token = config.get("token")
            if not token:
                logger.warning(f"Skipping {bot_name}: No token found.")
                continue

            bot = MyBot(bot_name, config, db)
            bots_to_run.append((bot, token))

    if not bots_to_run:
        logger.error("No active bots configured!")
        return

    async with asyncio.TaskGroup() as tg:
        for bot, token in bots_to_run:
            tg.create_task(bot.start(token))


if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown.")
