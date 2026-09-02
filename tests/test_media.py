from capturer.media import frame_timestamps


def test_frame_timestamps_spread_inside_video():
    ts = frame_timestamps(70.0, 6)
    assert len(ts) == 6
    assert ts[0] == 10.0 and ts[-1] == 60.0
    assert all(0 < t < 70 for t in ts)


def test_frame_timestamps_edge_cases():
    assert frame_timestamps(0, 5) == []
    assert frame_timestamps(10, 0) == []
    assert frame_timestamps(10, 1) == [5.0]
