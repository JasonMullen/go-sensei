import pytest

from app.core.coordinates import human_to_point, point_to_human


def test_human_to_point_bottom_left() -> None:
    assert human_to_point("A1") == (18, 0)


def test_human_to_point_top_right() -> None:
    assert human_to_point("T19") == (0, 18)


def test_human_to_point_skips_i_column() -> None:
    assert human_to_point("J1") == (18, 8)


def test_point_to_human_bottom_left() -> None:
    assert point_to_human(18, 0) == "A1"


def test_point_to_human_top_right() -> None:
    assert point_to_human(0, 18) == "T19"


def test_invalid_coordinate_raises_error() -> None:
    with pytest.raises(ValueError):
        human_to_point("I5")