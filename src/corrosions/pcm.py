from typing import Optional
import pandas as pd
import numpy as np
from glob import glob
from .cips import CIPS
from .const import *
from .utils import *


class PCM(CIPS):
    def __init__(
        self,
        file_or_dir: str,
        overwrite: bool = False,
        fix_depth: bool = True,
        calculate_dbma: bool = True,
        calculate_current_loss_rate: bool = True,
        keep_original_filename: bool = False,
        verbose: bool = False,
    ):
        super().__init__(file_or_dir, overwrite, verbose)

        self.prefix = "pcm"
        self.keep_original_filename = keep_original_filename
        self.fix_depth = fix_depth
        self.calculate_dbma = calculate_dbma
        self.calculate_current_loss_rate = calculate_current_loss_rate
        self.COLUMNS_VALIDATED = [
            "Index",
            "4Hz Current (A)",
            "Int GPS Latitude",
            "Int GPS Longitude",
            "Survey name (0-100)",
            "Gain (dB)",
        ]

        self.UNIQUE_COLUMNS = ["Int GPS Latitude", "Int GPS Longitude"]
        self.NUMERIC_COLUMNS = [
            "Index",
            "4Hz Current (A)",
            "Int GPS Latitude",
            "Int GPS Longitude",
            "Ext GPS Latitude",
            "Ext GPS Longitude",
            "Gain (dB)",
        ]

        self.check_sequential_file = True
        self.excel_dir = PCM_EXCEL_DIR
        self.json_dir = PCM_JSON_DIR

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

        if len(missing_columns) > 0:
            return False, missing_columns

        return True, missing_columns

    @staticmethod
    def direction(df, survey_name) -> str:
        df = df[["4Hz Current (A)", "Survey name (0-100)"]]
        y = np.array(
            df[df["Survey name (0-100)"] == survey_name][
                "4Hz Current (A)"
            ].tolist()
        )
        x = range(len(y))

        try:
            m, c = np.polyfit(x, y, 1)
            first_y = m * 0 + c
            last_y = m * (len(y) - 1) + c

            if first_y > last_y:
                return "DECREASING"

            return "INCREASING"
        except Exception as e:
            return "UNKNOWN"

    @staticmethod
    def dbma(df) -> pd.DataFrame:
        df["dbma"] = 20 * np.log10(df["4Hz Current (A)"] * 1000)
        df["dbma"] = df["dbma"].apply(lambda x: round(x, 2))

        return df

    @staticmethod
    def calculate_condition(file_or_dir: str, filter_value: float = 200):
        files = []
        if os.path.isfile(file_or_dir):
            files.append(file_or_dir)

        if os.path.isdir(file_or_dir):
            files = glob(os.path.join(file_or_dir, "*.xlsx"))

        for file in files:
            df = pd.read_excel(file)
            df["Condition"] = df.apply(
                lambda row: (
                    "Medium to High"
                    if row["Current Loss Rate"] <= 50
                    else "Medium to Poor"
                ),
                axis=1,
            )
            save_df(df, file, save_index=False)
            print(f"Updated: {file}")

    def drop_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Drop empty row and duplicated columns.

        Args:
            df: pd.DataFrame

        Returns:
            pd.DataFrame
        """
        if "Distance" in df.columns:
            df.drop(columns=["Distance"], inplace=True)

        if "Index" in df.columns:
            df.dropna(subset=["Index"], ignore_index=True, inplace=True)

        df.dropna(how="all", ignore_index=True, inplace=True)
        df = df.drop_duplicates(
            subset=self.UNIQUE_COLUMNS, keep="last"
        ).reset_index(drop=True)

        return df

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

        df1 = df[
            [
                "Start Symbol",
                "Format",
                "Version",
                "Index",
                "PCMx Operating mode",
                "Locator Frequency",
                "Alpha display",
                "Depth (m)",
                "Depth (ft)",
                "Depth to pipe center (m)",
                "Depth to pipe center (ft)",
                "dBuV",
                "Locate current A",
                "4 Hz Voltage phase",
                "Signal strength",
                "Gain (dB)",
                "MF Foot attached",
                "4Hz C-V Phase",
                "4Hz Current (A)",
                "Current 4-8Hz Phase",
                "RTC day",
                "RTC month",
                "RTC year",
                "UTC",
                "RTC Updated flag",
                "Int GPS mode",
                "Int GPS Latitude",
                "Int GPS Longitude",
                "Int GPS Fix",
                "Int GPS no. of satellites",
                "Int GPS dilution",
                "Int GPS altitude",
                "Ext GPS Latitude",
                "Ext GPS Longitude",
                "Ext GPS Fix",
                "Ext GPS no. of satellites",
                "Ext GPS dilution",
                "Ext GPS altitude",
                "Pipe Diameter",
                "Survey name (0-100)",
                "Comment (0-100)",
            ]
        ]
        df1 = df1[
            (df["Int GPS Latitude"] != 0)
            & (df["Int GPS Longitude"] != 0)
            & (df["4Hz Current (A)"] > 0.00)
        ]
        df1.dropna(
            subset=[
                "Int GPS Latitude",
                "Int GPS Longitude",
                "4Hz Current (A)",
            ],
            inplace=True,
        )

        for numeric_column in self.NUMERIC_COLUMNS:
            df1.loc[:, numeric_column] = df[numeric_column].apply(
                validate_numeric
            )

        if "Unnamed: 41" in df1.columns:
            df1.drop(columns=["Unnamed: 41"], inplace=True)

        # Calculate dBmA
        if self.calculate_dbma:
            df1 = self.dbma(df1)

        # Fix depth
        if self.fix_depth and df1.loc[0, "Depth (m)"] > 0:
            df1["Depth (m)"] = df1["Depth (m)"] * -1
            df1["Depth (ft)"] = df1["Depth (ft)"] * -1
            df1["Depth to pipe center (m)"] = (
                df1["Depth to pipe center (m)"] * -1
            )
            df1["Depth to pipe center (ft)"] = (
                df1["Depth to pipe center (ft)"] * -1
            )

        df1.reset_index(drop=True, inplace=True)

        # Calculate Distance and Current Loss Rate
        for index in df1.index:
            if index == 0:
                df1["Distance"] = 0.0
                df1["Real Distance"] = 0.0
                df1["Current Loss Rate"] = 0.0
                continue

            lat_1 = df1.loc[index - 1, "Int GPS Latitude"]
            lon_1 = df1.loc[index - 1, "Int GPS Longitude"]
            lat_2 = df1.loc[index, "Int GPS Latitude"]
            lon_2 = df1.loc[index, "Int GPS Longitude"]

            # Calculate Distance
            distance = calculate_distance(lat_1, lon_1, lat_2, lon_2)
            df1.loc[index, "Distance"] = distance
            df1.loc[index, "Real Distance"] = (
                distance + df1.loc[index - 1, "Real Distance"]
            )

            # Current Loss Rate (CLR) as milliBels/meter (mB/m)
            if self.calculate_current_loss_rate:
                delta_dbma = (
                    df1.loc[index, "dbma"] - df1.loc[index - 1, "dbma"]
                )
                df1.loc[index, "Current Loss Rate"] = round(
                    abs(delta_dbma / distance) * 1000, 2
                )

        df2 = pd.DataFrame(
            {"Survey Name": df1["Survey name (0-100)"].unique().tolist()}
        )

        # Set the direction
        df2["Direction"] = df2["Survey Name"].apply(
            lambda name: self.direction(df1, name)
        )
        df1["Direction"] = df1["Survey name (0-100)"].apply(
            lambda name: df2[df2["Survey Name"] == name]["Direction"].tolist()[
                0
            ]
        )

        try:
            writer = pd.ExcelWriter(excel_filepath, engine="xlsxwriter")

            df1.to_excel(writer, sheet_name="Sequential File", index=False)
            df1.columns = rename_columns(df1.columns.tolist())
            df1.to_json(json_filepath, orient="records")
            df2.to_excel(writer, sheet_name="Survey Name", index=False)

            writer.close()

            return excel_filepath
        except Exception as e:
            raise e
