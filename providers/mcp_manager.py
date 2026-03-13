import logging
import os

import mcp.types as mcp_types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("MCPManager")

# Transport type constants
TRANSPORT_STDIO = "stdio"
TRANSPORT_SSE = "sse"
TRANSPORT_HTTP = "http"

# Mapping of MCP server names to their required env var names
MCP_SERVER_ENV_VARS = {
    "exa_web_search": "EXA_API_KEY",
    "giphy": "GIPHY_API_KEY",
}


class MCPTool:
    """Represents a single tool from an MCP server, ready to pass to LiteLLM."""

    def __init__(self, tool: mcp_types.Tool, session: ClientSession):
        self.name = tool.name
        self.description = tool.description or ""
        self.input_schema = tool.inputSchema
        self._session = session

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    async def call(self, arguments: dict) -> str:
        result = await self._session.call_tool(self.name, arguments)
        parts = []
        for block in result.content:
            if isinstance(block, mcp_types.TextContent):
                parts.append(block.text)
            elif isinstance(block, mcp_types.ImageContent):
                parts.append(f"[image: {block.url}]")
        return "\n".join(parts) if parts else "(no output)"


class MCPServerConnection:
    """Manages the lifecycle of a single MCP server connection using a background task."""

    def __init__(self, config: dict):
        self.name = config.get("name", "unnamed")
        self.transport = config.get("transport", TRANSPORT_STDIO)
        self.config = config
        self._session = None
        self.tools: list[MCPTool] = []

        import asyncio

        self._shutdown_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._task = None

    def _create_client_ctx(self):
        transport = self.transport
        if transport == TRANSPORT_STDIO:
            command = self.config["command"]
            args = self.config.get("args", [])
            # Merge config env with required env vars from environment
            env = {**self.config.get("env", None)} if self.config.get("env") else {}
            required_env_var = MCP_SERVER_ENV_VARS.get(self.name)
            if required_env_var:
                env_value = os.getenv(required_env_var)
                if not env_value:
                    logger.warning(f"[MCP] {self.name} requires {required_env_var} env var not set")
                else:
                    env[required_env_var] = env_value
            params = StdioServerParameters(command=command, args=args, env=env if env else None)
            return stdio_client(params)
        elif transport == TRANSPORT_SSE:
            # Inject API key from env into URL query params if needed
            url = self.config["url"]
            required_env_var = MCP_SERVER_ENV_VARS.get(self.name)
            if required_env_var:
                env_value = os.getenv(required_env_var)
                if env_value:
                    # Append API key to URL
                    separator = "&" if "?" in url else "?"
                    url = f"{url}{separator}{required_env_var}={env_value}"
                else:
                    logger.warning(f"[MCP] {self.name} requires {required_env_var} env var not set")
            return sse_client(url)
        elif transport == TRANSPORT_HTTP:
            return streamable_http_client(self.config["url"])
        else:
            raise ValueError(f"Unknown MCP transport: {transport}")

    async def _run_loop(self):
        try:
            async with self._create_client_ctx() as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session

                    result = await session.list_tools()
                    self.tools = [MCPTool(t, self._session) for t in result.tools]
                    logger.info(
                        f"[MCP] Connected to '{self.name}' — {len(self.tools)} tools: "
                        f"{[t.name for t in self.tools]}"
                    )

                    # Signal that connection is ready
                    self._ready_event.set()

                    # Wait here until disconnect is called
                    await self._shutdown_event.wait()

        except Exception as e:
            logger.error(f"[MCP] Background connection failed for '{self.name}': {e}")
        finally:
            self._session = None
            self.tools = []
            self._ready_event.set()  # Ensure connect() doesn't hang if we crash early

    async def connect(self):
        import asyncio

        self._task = asyncio.create_task(self._run_loop())
        # Wait for the background task to either succeed in connecting, or fail fast
        await self._ready_event.wait()

    async def disconnect(self):
        self._shutdown_event.set()
        if self._task:
            try:
                import asyncio

                # Give it a moment to cleanup gracefully
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                pass
            self._task = None


class MCPManager:
    """
    Connects to all MCP servers defined in config and exposes a unified
    tool registry for use in the agentic loop.

    Config format (in bot config.json):
    "mcp_servers": [
        {
            "name": "filesystem",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        },
        {
            "name": "my-remote",
            "transport": "http",
            "url": "http://localhost:8000/mcp"
        }
    ]
    """

    def __init__(self, server_configs: list[dict]):
        self._configs = server_configs
        self._connections: list[MCPServerConnection] = []

    async def start(self):
        for cfg in self._configs:
            conn = MCPServerConnection(cfg)
            try:
                await conn.connect()
                self._connections.append(conn)
            except Exception as e:
                logger.error(f"[MCP] Failed to connect to '{cfg.get('name')}': {e}")

    async def stop(self):
        for conn in self._connections:
            await conn.disconnect()
        self._connections.clear()

    @property
    def tools(self) -> list[MCPTool]:
        all_tools = []
        for conn in self._connections:
            all_tools.extend(conn.tools)
        return all_tools

    def get_tool(self, name: str) -> MCPTool | None:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def openai_schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self.tools]

    async def call_tool(self, name: str, arguments: dict) -> str:
        tool = self.get_tool(name)
        if not tool:
            return f"Error: tool '{name}' not found"
        return await tool.call(arguments)
