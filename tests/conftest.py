import pytest
import respx

from tests.soundcloud_fake import FakeSoundCloud
from tests.spotify_fake import FakeSpotify


@pytest.fixture
def router():
    with respx.mock(assert_all_called=False) as mock_router:
        yield mock_router


@pytest.fixture
def fake_spotify(router):
    return FakeSpotify(router)


@pytest.fixture
def fake_soundcloud(router):
    return FakeSoundCloud(router)
