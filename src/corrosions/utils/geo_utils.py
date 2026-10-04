import re

import numpy as np
import pandas as pd


# Mean Earth radius (IUGG), in meters.
EARTH_RADIUS_M: float = 6_371_000.0

Coordinate = float | np.ndarray | pd.Series


def calculate_distance(
    lat1: Coordinate,
    lon1: Coordinate,
    lat2: Coordinate,
    lon2: Coordinate,
) -> Coordinate:
    """Return the great-circle distance in meters between two points.

    Uses the haversine formula on a sphere of radius ``EARTH_RADIUS_M``.
    Works on scalars, numpy arrays and pandas Series. Inputs broadcast, so
    one side can be a single point. Series results keep their index. A NaN
    coordinate gives a NaN distance.

    Args:
        lat1 (Coordinate): Latitude of the first point, in degrees.
        lon1 (Coordinate): Longitude of the first point, in degrees.
        lat2 (Coordinate): Latitude of the second point, in degrees.
        lon2 (Coordinate): Longitude of the second point, in degrees.

    Returns:
        Coordinate: Distance in meters. A float for scalar inputs, otherwise
            the same shape as the broadcast inputs.

    Example:
        >>> calculate_distance(-6.1, 106.1, -6.101, 106.1)
        111.19492664459587
        >>> # distance from each reading to the previous one (first is NaN)
        >>> df["distance"] = calculate_distance(
        ...     df["Latitude"].shift(), df["Longitude"].shift(),
        ...     df["Latitude"], df["Longitude"],
        ... )
    """
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)

    a = (
        np.sin(delta_phi / 2) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2) ** 2
    )
    # Rounding can push ``a`` just above 1 for near-antipodal points.
    c = 2 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))

    distance = EARTH_RADIUS_M * c
    if np.ndim(distance) == 0 and not isinstance(distance, pd.Series):
        return float(distance)
    return distance


# Degrees, minutes, seconds and a hemisphere letter, with any separators
# (e.g. 6°15'16.8"S, or 6�15'16.8"S when the degree sign was mangled).
_DMS = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)\D+(\d+(?:\.\d+)?)\D*?([NSEWnsew])\s*$"
)


def parse_coordinate(value) -> float | None:
    """Return a latitude/longitude as decimal degrees, or ``None``.

    Accepts numbers, numeric strings (``"-6.587569"``) and degrees-minutes-
    seconds text with a hemisphere letter (``6°15'16.8"S``,
    ``106°59'58.7"E``; any separator between the parts, so a mangled degree
    sign still works). ``S`` and ``W`` give negative values. Anything else
    (empty, ``NaN``, ``"N/A"``, ``"-"``) gives ``None``.

    Args:
        value: Raw cell value.

    Returns:
        float | None: Decimal degrees, or ``None`` when it cannot be read.

    Example:
        >>> parse_coordinate("6°15'16.8\"S")
        -6.254666666666667
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.number)):
        number = float(value)
        return None if np.isnan(number) else number

    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        pass
    else:
        return None if np.isnan(number) else number

    match = _DMS.match(text)
    if match is None:
        return None
    degrees, minutes, seconds, hemisphere = match.groups()
    decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    return -decimal if hemisphere.upper() in "SW" else decimal
