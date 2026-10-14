from pathlib import Path
import pytest
from therapie_mcp.parsing import FILTERS

@pytest.fixture
def search_html():
    return (Path(__file__).parent / 'fixtures/search.html').read_text()

@pytest.fixture
def profile_html():
    return (Path(__file__).parent / 'fixtures/profile.html').read_text()

@pytest.fixture
def filters_html():
    fields = ''.join(f'<select name="{parameter}"><option value="">Choose</option><option value="1">Test Option</option><option value="2">Andere Option</option></select>' for parameter, _ in FILTERS.values())
    return '<form action="/therapeutensuche/ergebnisse/">' + fields + '</form>'
