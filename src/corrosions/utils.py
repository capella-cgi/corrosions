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


def get_basename(
    filename: str,
    sheet_name: str,
    prefix: str = "cips",
) -> str:
    """Extract basename from filename.

    Args:
        filename (str): filename.
        sheet_name (str): sheet name.
        prefix (str): prefix.

    Returns:
        str: basename of filename.
    """
    _basename = os.path.basename(filename).split(".x")[0]
    _basename = f"{_basename}__{sheet_name}"

    if _basename[0 : len(prefix)].lower() != prefix:
        _basename = f"{prefix}_{_basename}"

    return _basename


def sequential_file(sheet_names: list[str]) -> str | None:
    """Check if sheet name called Sequential File exists.

    Args:
        sheet_names (list[str]): sheet names.

    Returns:
        str | None: sequential file name.
    """
    if len(sheet_names) == 1:
        return sheet_names[0]

    if "Sequential File" in sheet_names:
        return "Sequential File"

    if "Sequential Files" in sheet_names:
        return "Sequential Files"

    if "Sheet1" in sheet_names:
        return "Sheet1"

    return None
