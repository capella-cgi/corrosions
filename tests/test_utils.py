import math

import numpy as np
import pandas as pd
import pytest

from corrosions.utils import EARTH_RADIUS_M, calculate_distance


def test_scalar_known_distances():
    # 0.001 degree of latitude
    assert calculate_distance(-6.1, 106.1, -6.101, 106.1) == pytest.approx(
        111.195, abs=1e-3
    )
    # Jakarta -> Bandung, straight line
    assert calculate_distance(
        -6.2088, 106.8456, -6.9175, 107.6191
    ) == pytest.approx(116_236, rel=1e-4)


def test_scalar_returns_float():
    result = calculate_distance(-6.1, 106.1, -6.1, 106.1)
    assert type(result) is float
    assert result == 0.0


def test_antipodal_points_do_not_raise():
    assert calculate_distance(0.0, 0.0, 0.0, 180.0) == pytest.approx(
        math.pi * EARTH_RADIUS_M
    )


def test_nan_gives_nan():
    assert math.isnan(calculate_distance(float("nan"), 106.1, -6.1, 106.1))


def test_series_keeps_index():
    df = pd.DataFrame(
        {"Latitude": [-6.1, -6.101, -6.102], "Longitude": [106.1] * 3},
        index=[10, 20, 30],
    )
    distance = calculate_distance(
        df["Latitude"].shift(),
        df["Longitude"].shift(),
        df["Latitude"],
        df["Longitude"],
    )
    assert isinstance(distance, pd.Series)
    assert list(distance.index) == [10, 20, 30]
    assert math.isnan(distance.iloc[0])
    assert distance.iloc[1:].tolist() == pytest.approx([111.195] * 2, abs=1e-3)


def test_series_against_single_point():
    lat = pd.Series([-6.1, -6.101])
    lon = pd.Series([106.1, 106.1])
    distance = calculate_distance(lat, lon, -6.1, 106.1)
    assert distance.tolist() == pytest.approx([0.0, 111.195], abs=1e-3)


def test_numpy_arrays():
    distance = calculate_distance(
        np.array([-6.1, -6.1]),
        np.array([106.1, 106.1]),
        np.array([-6.1, -6.101]),
        np.array([106.1, 106.1]),
    )
    assert isinstance(distance, np.ndarray)
    assert distance.tolist() == pytest.approx([0.0, 111.195], abs=1e-3)
