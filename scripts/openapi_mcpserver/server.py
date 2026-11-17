"""Run the MCP project selected by the adjacent .env file."""
import asyncio

from curl_mcp.__main__ import main


if __name__ == "__main__":
    asyncio.run(main())
