import pytest
import respx

from tests.spotify_fake import FakeSpotify


@pytest.fixture
def fake_spotify():
    with respx.mock(assert_all_called=False) as router:
        yield FakeSpotify(router)
