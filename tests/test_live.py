import pytest
from therapie_mcp.client import TherapieClient

pytestmark = pytest.mark.live

async def test_live_search_filters_and_profile():
    client = TherapieClient()
    try:
        filters = await client.filters()
        assert len(filters['filters']) == 7
        # Filter IDs are resolved from the current website form, not assumed.
        result = await client.search('Berlin', radius_km=25, billing='GKV: Kassenleistung', method='Verhaltenstherapie')
        assert result['total_results'] > 0
        assert result['radius_km'] == 25
        assert result['therapists']
        profile = await client.profile(result['therapists'][0]['profile_id'])
        assert profile['name']
        assert profile['methods']
        assert profile['source_url'].startswith('https://www.therapie.de/profil/')
    finally:
        await client.aclose()
