import os

import pandas as pd


def get_sheets(filepath: str) -> list[int | str]:
    """Return a list of sheet names in an Excel file.

    Args:
        filepath (str): Path to the Excel file.

    Returns:
        list[int | str]: List of sheet names in the Excel file.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    xls = pd.ExcelFile(filepath)
    sheet_names = xls.sheet_names

    if len(sheet_names) == 0:
        raise ValueError(f"No sheets found in Excel file: {filepath}")

    return sheet_names


def get_sheet_columns(filepath: str) -> dict[str, list[str]]:
    """Return the header row of every sheet in an Excel file.

    Only the first row of each sheet is parsed, so this is cheap even for
    large workbooks. Column names are converted to ``str`` and stripped of
    surrounding whitespace.

    Args:
        filepath (str): Path to the Excel file.

    Returns:
        dict[str, list[str]]: Sheet name -> column names, in workbook order.
            Empty sheets map to an empty list.

    Raises:
        FileNotFoundError: If ``filepath`` does not exist.

    Example:
        >>> get_sheet_columns("survey.xlsx")
        {'Data': ['Data No', 'Latitude', ...], 'Grafik': []}
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with pd.ExcelFile(filepath) as xls:
        return {
            str(sheet): [str(c).strip() for c in xls.parse(sheet, nrows=0).columns]
            for sheet in xls.sheet_names
        }
