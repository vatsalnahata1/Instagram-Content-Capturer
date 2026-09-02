from capturer.urls import extract_instagram_urls, shortcode_from_url


def test_extracts_reel_post_and_tv_urls():
    text = (
        "look at this https://www.instagram.com/reel/AbC123_-x/?igsh=abc and "
        "https://instagram.com/p/Zz9/ plus https://www.instagram.com/tv/QqQ/"
    )
    assert extract_instagram_urls(text) == [
        "https://www.instagram.com/reel/AbC123_-x/",
        "https://www.instagram.com/p/Zz9/",
        "https://www.instagram.com/tv/QqQ/",
    ]


def test_handles_username_prefixed_and_plural_reels_paths():
    assert extract_instagram_urls("https://www.instagram.com/someuser/reels/XYZ/") == [
        "https://www.instagram.com/reel/XYZ/"
    ]


def test_dedupes_and_ignores_non_instagram():
    text = "https://www.instagram.com/reel/A1/ https://www.instagram.com/reel/A1/?x=1 https://youtube.com/watch?v=A1"
    assert extract_instagram_urls(text) == ["https://www.instagram.com/reel/A1/"]


def test_shortcode_from_url():
    assert shortcode_from_url("https://www.instagram.com/reel/AbC/") == "AbC"
    assert shortcode_from_url("not a url") is None
    assert extract_instagram_urls("") == []
