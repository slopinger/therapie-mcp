import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from therapie_mcp.client import TherapieClient
from therapie_mcp.server import create_server

async def test_tool_schemas_and_dispatch(filters_html, search_html, profile_html):
    def handle(request):
        html = profile_html if request.url.path.startswith('/profil/') else filters_html if request.url.path == '/therapeutensuche/' else search_html
        return httpx.Response(200, text=html, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        server = create_server(TherapieClient(http, interval=0))
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {'get_search_filters', 'search_therapists', 'get_therapist'}
        for tool in tools:
            assert tool.annotations.read_only_hint is True
        result = await server.call_tool('search_therapists', {'location': 'Teststadt', 'billing': '1'})
        assert not result.is_error
        assert result.structured_content['therapists'][0]['profile_id'] == 'test.person'
        profile = await server.call_tool('get_therapist', {'profile': 'test.person'})
        assert not profile.is_error
        assert profile.structured_content['email'] == 'test@example.org'
        with pytest.raises(ToolError, match='Only HTTPS'):
            await server.call_tool('get_therapist', {'profile': 'https://evil.test/'})
