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
        assert {'get_search_filters', 'search_therapists', 'get_therapist', 'draft_enquiry', 'export_email_draft', 'workflow_overview'} <= {tool.name for tool in tools}
        for tool in tools:
            if tool.name in {'get_search_filters', 'search_therapists', 'get_therapist', 'compare_therapists'}:
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.open_world_hint is True
            else:
                assert tool.annotations.open_world_hint is False
        result = await server.call_tool('search_therapists', {'location': 'Teststadt', 'billing': '1'})
        assert not result.is_error
        assert result.structured_content['therapists'][0]['profile_id'] == 'test.person'
        profile = await server.call_tool('get_therapist', {'profile': 'test.person'})
        assert not profile.is_error
        assert profile.structured_content['email'] == 'test@example.org'
        with pytest.raises(ToolError, match='Only HTTPS'):
            await server.call_tool('get_therapist', {'profile': 'https://evil.test/'})

async def test_complete_private_contact_workflow(tmp_path, profile_html):
    from therapie_mcp.workflow import Store
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, text=profile_html, headers={'content-type': 'text/html'})
    store = Store(tmp_path / 'workflow.sqlite3')
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            server = create_server(TherapieClient(http, interval=0), store)
            async def call(name, arguments):
                result = await server.call_tool(name, arguments)
                assert not result.is_error
                return result.structured_content
            await call('save_therapist', {'profile': 'test.person', 'notes': 'Private preference'})
            await call('update_preferences', {'fields': {'sender_name': 'Example User', 'sender_email': 'user@example.org'}})
            draft = await call('draft_enquiry', {'profile_id': 'test.person'})
            await call('update_email_draft', {'draft_id': draft['id'], 'body': 'Reviewed and edited enquiry'})
            exported = await call('export_email_draft', {'draft_id': draft['id']})
            assert 'Reviewed and edited enquiry' in exported['eml']
            contact = await call('log_contact', {'profile_id': 'test.person', 'channel': 'email', 'outcome': 'enquiry', 'follow_up_on': '2026-01-01'})
            overview = await call('workflow_overview', {})
            assert len(overview['follow_ups_due']) == 1
            await call('complete_follow_up', {'contact_id': contact['id']})
            await call('delete_saved_therapist', {'profile_id': 'test.person'})
            assert (await call('workflow_overview', {}))['shortlist'] == []
            assert len(calls) == 1  # all contact operations stayed local
    finally:
        store.close()
