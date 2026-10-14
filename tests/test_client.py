import httpx
import pytest
from therapie_mcp.client import TherapieClient, MAX_RESPONSE_BYTES
from therapie_mcp.parsing import TherapieError

async def test_search_filter_resolution_and_cache(filters_html, search_html):
    requests = []
    def handle(request):
        requests.append(request)
        html = filters_html if request.url.path == '/therapeutensuche/' else search_html
        return httpx.Response(200, text=html, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = TherapieClient(http, interval=0)
        first = await client.search('Teststadt', radius_km=25, billing='Test Option', language='2')
        again = await client.search('Teststadt', radius_km=25, billing='Test Option', language='2')
    assert first == again
    assert len(requests) == 2
    assert requests[1].url.params['abrechnungsverfahren'] == '1'
    assert requests[1].url.params['sprache'] == '2'
    assert requests[1].url.params['search_radius'] == '25'

async def test_unknown_filter_rejected_before_search(filters_html):
    def handle(request):
        assert request.url.path == '/therapeutensuche/'
        return httpx.Response(200, text=filters_html, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(TherapieError, match='Unknown billing'):
            await TherapieClient(http, interval=0).search('Teststadt', billing='invented')

async def test_external_redirect_not_followed():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(TherapieError, match='Only HTTPS'):
            await TherapieClient(http, interval=0).profile('test')
    assert len(requests) == 1

@pytest.mark.parametrize('status, message', [(404, 'not found'), (403, 'refused access'), (429, 'rate limit')])
async def test_http_errors(status, message):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as http:
        with pytest.raises(TherapieError, match=message):
            await TherapieClient(http, interval=0).profile('test')

async def test_response_size_limit():
    response = httpx.Response(200, content=b'x' * (MAX_RESPONSE_BYTES + 1), headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
        with pytest.raises(TherapieError, match='size limit'):
            await TherapieClient(http, interval=0).profile('test')

@pytest.mark.parametrize('kwargs', [{'location': ''}, {'location': 'Berlin', 'page': 0}, {'location': 'Berlin', 'radius_km': True}])
async def test_invalid_search(kwargs):
    with pytest.raises(TherapieError):
        await TherapieClient(interval=0).search(**kwargs)
