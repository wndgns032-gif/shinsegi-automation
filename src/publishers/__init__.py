from .bluesky import BlueskyPublisher
from .facebook import FacebookPublisher
from .instagram import InstagramPublisher
from .mastodon import MastodonPublisher
from .pinterest import PinterestPublisher
from .telegram import TelegramPublisher
from .threads_pub import ThreadsPublisher

PUBLISHERS = [
    InstagramPublisher(),
    ThreadsPublisher(),
    BlueskyPublisher(),
    FacebookPublisher(),
    TelegramPublisher(),
    MastodonPublisher(),
    PinterestPublisher(),
]
