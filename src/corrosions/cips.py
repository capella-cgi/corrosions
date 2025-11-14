import glob
import pandas as pd
from typing import Self, Any, Optional
from .utils import *
from .const import *


class CIPS:
    def __init__(
        self,
        file_or_dir: str,
        overwrite: bool = False,
        verbose: bool = False,
    ):
        self.file_or_dir = file_or_dir
        self.overwrite = overwrite
        self.prefix = "cips"
        self.excel_dir = CIPS_EXCEL_DIR
        self.json_dir = CIPS_JSON_DIR
        self.results = []

        self.COLUMNS_VALIDATED = [
            "Data No",
            "Latitude",
            "Longitude",
            "DCP/Feature/DCVG Anomaly",
        ]

        self.check_sequential_file = False
        self.verbose = verbose

    @property
    def files(self) -> List[str]:
        files = []
        if os.path.isfile(self.file_or_dir):
            files.append(self.file_or_dir)

        if os.path.isdir(self.file_or_dir):
            files = glob.glob(os.path.join(self.file_or_dir, "*.xlsx"))

        return files

    def validate_column(self, columns: list[str]) -> tuple[bool, list[str]]:
        """Validate columns.

        Args:
            columns (list[str]): list of column names.

        Returns:
            bool: column validated.
            list[str]: list of column names.
        """

        missing_columns: list[str] = []

        for column_validated in self.COLUMNS_VALIDATED:
            if column_validated not in columns:
                missing_columns.append(column_validated)

        if ("Voltage" not in columns) and ("Off Voltage" not in columns):
            missing_columns.append("Voltage/Off Voltage")

        if len(missing_columns) > 0:
            return False, missing_columns

        return True, missing_columns

    @staticmethod
    def transform_df(df: pd.DataFrame) -> pd.DataFrame:
        """Extract data from a file.

        Args:
            df (pd.DataFrame): data frame.

        Returns:
            pd.DataFrame: data extracted.
        """
        if "Off Voltage" in df.columns:
            # iccp - impress current cathodic protection
            df = df[
                [
                    "Data No",
                    "Off Voltage",
                    "Latitude",
                    "Longitude",
                    "Comment",
                    "DCP/Feature/DCVG Anomaly",
                ]
            ].copy(deep=True)
            df["protection"] = "ICCP"
            df.rename(columns={"Off Voltage": "Voltage"}, inplace=True)
            return df

        # sacp - sacrificial anode cathodic protection
        df = df[
            [
                "Data No",
                "Voltage",
                "Latitude",
                "Longitude",
                "Comment",
                "DCP/Feature/DCVG Anomaly",
            ]
        ].copy(deep=True)
        df["protection"] = "SACP"
        return df

    @staticmethod
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

    def transform(
        self,
        df: pd.DataFrame,
        excel_filepath: str,
        sheet_name: str = "Sheet1",
        json_filepath: Optional[str] = None,
    ) -> str:
        """Normalize a file.

        Args:
            df (pd.DataFrame): data frame.
            excel_filepath (str): filename to normalize.
            sheet_name (str): sheet name.
            json_filepath (str): json file path.

        Returns:
            str: normalized file.
        """
        df = self.transform_df(df)

        df["condition"] = df["Voltage"].apply(lambda x: self.condition(x))
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
            df.loc[index, "Real Distance"] = (
                distance + df.loc[index - 1, "Real Distance"]
            )

        df.set_index("Data No", inplace=True)
        df.to_excel(excel_filepath, sheet_name=sheet_name, index=True)

        if json_filepath:
            df.columns = rename_columns(df.columns.tolist())
            df.to_json(json_filepath, orient="records")

        return excel_filepath

    def process_df(
        self,
        df: pd.DataFrame,
        filename: str,
        sheet_name: str = "Sheet1",
        as_json: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Process a file.

        Args:
            df (pd.DataFrame): path to file
            filename (str): filename to normalize.
            sheet_name (str): sheet name.
            as_json (bool): whether to return as json.
            overwrite (bool): overwrite existing file.

        Returns:
            dict[str, Any]: processed file.
        """
        _basename = get_basename(filename, sheet_name, prefix=self.prefix)

        excel_filepath = os.path.join(
            self.excel_dir, f"{slugify(_basename)}.xlsx"
        )
        json_filepath = (
            os.path.join(self.json_dir, f"{slugify(_basename)}.json")
            if as_json
            else None
        )

        if os.path.exists(excel_filepath) and not overwrite:
            return {
                "success": True,
                "message": "File already normalized",
                "excel": excel_filepath,
                "json": json_filepath,
                "sheet": sheet_name,
            }

        try:
            return {
                "success": True,
                "message": "File normalized",
                "excel": self.transform(
                    df,
                    excel_filepath,
                    sheet_name=sheet_name,
                    json_filepath=json_filepath,
                ),
                "json": json_filepath,
                "sheet": sheet_name,
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e),
                "excel": filename,
                "json": json_filepath,
                "sheet": None,
            }

    def create_dir(self) -> Self:
        os.makedirs(self.excel_dir, exist_ok=True)
        os.makedirs(self.json_dir, exist_ok=True)
        return self

    def normalize(self) -> None:
        if len(self.files) > 0:
            self.create_dir()
            for file in self.files:
                if self.verbose:
                    print(f"Processing file: {file}")
                sheets = worksheets(file)

                sheet_name = None
                if self.check_sequential_file:
                    sheet_name = sequential_file(sheets)

                    # Change to Sequential file sheet
                    sheets = [sheet_name]
                    if sheet_name is None:
                        self.results.append(
                            {
                                "success": False,
                                "message": f"Missing Sequential File sheet",
                                "excel": file,
                                "json": None,
                                "sheet": None,
                            }
                        )
                        continue

                dfs = pd.read_excel(file, sheet_name=sheet_name)
                for sheet in sheets:
                    if self.verbose:
                        print(f"|| Processing sheet: {sheet}", end="")
                    df = dfs[sheet] if (sheet_name is None) else dfs
                    columns = df.columns.tolist()
                    column_is_oke, missing_columns = self.validate_column(
                        columns
                    )
                    if column_is_oke:
                        print(" OK!")
                        result = self.process_df(
                            df,
                            filename=file,
                            sheet_name=sheet,
                            as_json=True,
                            overwrite=self.overwrite,
                        )
                        self.results.append(result)
                    else:
                        print(" ‼️NOT OK!")
                        self.results.append(
                            {
                                "success": False,
                                "message": f"Sheet: {sheet}. Missing columns: {missing_columns}",
                                "excel": file,
                                "json": None,
                                "sheet": sheet,
                            }
                        )

        return None
