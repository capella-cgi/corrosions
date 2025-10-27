import json
import math
import os
import glob
import sys, argparse
import pandas as pd
from typing import Any, List, Tuple, Dict

NORMALIZE_DIR = os.path.join(os.getcwd(), "normalize")


def validate_column(columns: List[str]) -> Tuple[bool, List[str]]:
    """Validate columns.

    Args:
        columns (list[str]): list of column names.

    Returns:
        bool: column validated.
        list[str]: list of column names.
    """

    missing_columns: List[str] = []

    columns_validated = [
        "Data No",
        "Latitude",
        "Longitude",
        "DCP/Feature/DCVG Anomaly",
    ]

    for column_validated in columns_validated:
        if column_validated not in columns:
            missing_columns.append(column_validated)

    if ("Voltage" not in columns) and ("Off Voltage" not in columns):
        missing_columns.append("Voltage/Off Voltage")

    if len(missing_columns) > 0:
        return False, missing_columns

    return True, missing_columns


def worksheets(file: str) -> List[str]:
    """Extract worksheets from a file.

    Args:
        file (str): path to file.

    Returns:
        list[str]: list of worksheets.
    """
    with pd.ExcelFile(file) as excel:
        sheets = excel.sheet_names
        return sheets


def get_df(file: str) -> pd.DataFrame:
    """Extract data from a file.

    Args:
        file (str): path to file.

    Returns:
        pd.DataFrame: data extracted.
    """
    df = pd.read_excel(file)

    if "Off Voltage" in df.columns:
        # iccp - impress current cathodic protection
        df = df[
            [
                "Data No",
                "Off Voltage",
                "Latitude",
                "Longitude",
                "DCP/Feature/DCVG Anomaly",
            ]
        ].copy(deep=True)
        df["protection"] = "ICCP"
        df.rename(columns={"Off Voltage": "Voltage"}, inplace=True)
        return df

    # sacp - sacrificial anode catodhic protection
    df = df[
        ["Data No", "Voltage", "Latitude", "Longitude", "DCP/Feature/DCVG Anomaly"]
    ].copy(deep=True)
    df["protection"] = "SACP"
    return df


def condition(voltage: float) -> str:
    """Get condition based on voltage.

    Args:
        voltage (float): voltage.

    Returns:
        str: condition.
    """
    if -1.2 < voltage <= -0.85:
        return "PROTECTED"
    if voltage <= -1.2:
        return "OVER PROTECTED"
    return "UNPROTECTED"


def calculate_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate distance between two points using haversine formula.

    Args:
        lat1: latitude.
        lon1: longitude.
        lat2: latitude.
        lon2: longitude.

    Returns:
        float: distance between two points.
    """
    radius = 6371000

    # convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    # haversine formula
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    return radius * c


def normalize_file(
    file: str, normalize_filename: str, sheet_name: str = "Sheet1"
) -> str:
    """Normalize a file.

    Args:
        file (str): path to file.
        normalize_filename (str): filename to normalize.
        sheet_name (str): sheet name.

    Returns:
        str: normalized file.
    """
    df = get_df(file)

    df["condition"] = df["Voltage"].apply(lambda x: condition(x))
    df["voltage_inverse"] = df["Voltage"] * -1

    df["type"] = "PCM" if "4Hz Current (A)" in df.columns else "CIPS"
    df["interpolated"] = df["Latitude"].isna() & df["Longitude"].isna()
    df["Latitude"] = df["Latitude"].interpolate(method="linear")
    df["Longitude"] = df["Longitude"].interpolate(method="linear")

    for index in df.index:
        if index == 0:
            df["Distance"] = 0.0
            df["Real Distance"] = 0.0
            continue

        # if index == len(df) - 1:
        #     continue

        lat_1 = df.loc[index - 1, "Latitude"]
        lon_1 = df.loc[index - 1, "Longitude"]
        lat_2 = df.loc[index, "Latitude"]
        lon_2 = df.loc[index, "Longitude"]

        distance = calculate_distance(lat_1, lon_1, lat_2, lon_2)
        df.loc[index, "Distance"] = distance
        df.loc[index, "Real Distance"] = distance + df.loc[index - 1, "Real Distance"]

    df.set_index("Data No", inplace=True)
    df.to_excel(normalize_filename, sheet_name=sheet_name, index=True)

    return normalize_filename


def process_file(
    file: str, sheet_name: str = "Sheet1", overwrite: bool = False
) -> Dict[str, Any]:
    """Process a file.

    Args:
        file (str): path to file.
        sheet_name (str): sheet name.
        overwrite (bool): overwrite existing file.

    Returns:
        dict[str, Any]: processed file.
    """
    basename = os.path.basename(file).split(".")[0]
    basename = f"{basename}__{sheet_name}.xlsx"

    os.makedirs(NORMALIZE_DIR, exist_ok=True)
    normalize_filename = os.path.join(NORMALIZE_DIR, basename)

    if os.path.exists(normalize_filename) and not overwrite:
        return {
            "success": True,
            "message": "File already normalized",
            "file": normalize_filename,
            "sheet": sheet_name,
        }

    try:
        return {
            "success": True,
            "message": "File normalized",
            "file": normalize_file(file, normalize_filename, sheet_name=sheet_name),
            "sheet": sheet_name,
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "file": file,
            "sheet": None,
        }


def main(file_or_dir: str, overwrite: bool = False, verbose: bool = False):
    files = []
    results = []

    if os.path.isfile(file_or_dir):
        files.append(file_or_dir)

    if os.path.isdir(file_or_dir):
        files = glob.glob(
            os.path.join(r"D:\Projects\extract-kml\DATA IDDA24\Data CIPS", "*.xlsx")
        )

    if len(files) > 0:
        for file in files:
            sheets = worksheets(file)
            dfs = pd.read_excel(file, sheet_name=None)
            for sheet in sheets:
                columns = dfs[sheet].columns.tolist()
                ok, missing_columns = validate_column(columns)
                if ok:
                    result = process_file(file, sheet_name=sheet, overwrite=overwrite)
                    results.append(result)
                else:
                    if verbose:
                        print(
                            f"{ok}. {file}. Sheet: {sheet}. Missing columns: {missing_columns}"
                        )

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", help="File to normalize", type=str)
    parser.add_argument(
        "-o", "--overwrite", help="Overwrite existing files", action="store_true"
    )
    parser.add_argument(
        "-v", "--verbose", help="Verbose information", action="store_true"
    )

    args = parser.parse_args()
    _file = args.file
    _overwrite = args.overwrite
    _verbose = args.verbose

    _results = main(_file, overwrite=_overwrite, verbose=_verbose)

    if len(_results) == 0:
        _results = [{
            "success": False,
            "message": "File not found",
            "file": _file,
        }]
        print(json.dumps(_results))
        sys.exit(1)

    print(json.dumps(_results))
    sys.exit(0)
