from ..core import parse_clip

CASES = [
    (
        "https://looptube.io/video?videoId=123456&start=120&end=240",
        "My Loop",
        {"video_id": "123456", "start": "120", "end": "240", "title": "My Loop"},
    ),
    (
        "https://youtu.be/abc123?start=300",
        "My Video",
        {"video_id": "abc123", "start": "300", "end": None, "title": "My Video"},
    ),
    (
        "https://youtube.com/watch?v=def456&t=420",
        "Another Video",
        {"video_id": "def456", "start": "420", "end": None, "title": "Another Video"},
    ),
]


def test_parse_clip() -> None:
    for url, title, expected in CASES:
        clip = parse_clip(url, title)
        assert clip is not None
        assert clip.video_id == expected["video_id"]
        assert clip.start == expected["start"]
        assert clip.end == expected["end"]
        assert clip.title == expected["title"]
        assert clip.source_url == url


def test_parse_clip_rejects_unsupported_url() -> None:
    assert parse_clip("https://example.com/not-a-video", None) is None


def test_parse_clip_rejects_end_before_start() -> None:
    url = "https://looptube.io/video?videoId=123456&start=240&end=120"
    assert parse_clip(url, None) is None
