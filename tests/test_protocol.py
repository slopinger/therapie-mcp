"""Launch the real stdio entry point and speak MCP JSON-RPC through the SDK."""
import sys
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def test_stdio_handshake_and_tools():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'therapie_mcp'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.server_info.name == 'therapie'
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == {'get_search_filters', 'search_therapists', 'get_therapist'}
            invalid = await session.call_tool('get_therapist', {'profile': 'https://evil.test/'})
            assert invalid.is_error
            assert "Only HTTPS" in invalid.content[0].text
            prompts = await session.list_prompts()
            assert prompts.prompts[0].name == 'therapeutensuche'
