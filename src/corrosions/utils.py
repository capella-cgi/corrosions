import pandas as pd
import os
import math
from slugify import slugify
from typing import List


def worksheets(file: str) -> List[str]:
    """Extract worksheets from a file.

    Args:
        file (str): path to file.

    Returns:
        list[str]: list of worksheets.
    """
    excel = pd.ExcelFile(file)
    sheets = excel.sheet_names
    return sheets


def basename(filename: str) -> str:
    """Extract basename from filename.

    Args:
        filename (str): filename.

    Returns:
        str: basename of filename.
    """
    name = os.path.basename(filename).split(".x")[0]
    return slugify(name)


def calculate_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate distance between two points using haversine formula.

    Args:
        lat1: First latitude.
        lon1: First longitude.
        lat2: Second latitude.
        lon2: Second longitude.

    Returns:
        float: distance between two points.
    """
    radius = 6371000

    # convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    distance_phi = math.radians(lat2 - lat1)
    distance_lambda = math.radians(lon2 - lon1)

    # haversine formula
    a = (
        math.sin(distance_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(distance_lambda / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    return radius * c