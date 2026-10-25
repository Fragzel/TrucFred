import pytest
import respx

from tests.soundcloud_fake import FakeSoundCloud
from tests.spotify_fake import FakeSpotify
from tests.youtube_fake import FakeYouTube


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


@pytest.fixture
def fake_youtube(router):
    return FakeYouTube(router)
