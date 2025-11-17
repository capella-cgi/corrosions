import pandas as pd
import numpy as np
from typing import Optional

from .pcm import PCM
from .const import *
from .utils import *


class AcvgDcvg(PCM):
    def __init__(
        self,
        file_or_dir: str,
        overwrite: bool = False,
        verbose: bool = False,
    ):
        super().__init__(file_or_dir, overwrite, verbose)

        self.prefix = "acvg_dcvg"

        self.COLUMNS_VALIDATED = [
            "segment_code",
            "diameter",
            "anomaly_location",
            "surface_condition",
            "drop_pcm",
            "on_potential",
            "off_potential",
            "survey_dcvg",
            "survey_acvg",
            "latitude",
            "longitude",
            "ir_drop",
            "pipe_depth",
            "result_acvg",
            "protection",
        ]

        self.UNIQUE_COLUMNS = ["latitude", "longitude"]

        self.check_sequential_file = False
        self.excel_dir = ACVG_DCVG_EXCEL_DIR
        self.json_dir = ACVG_DCVG_JSON_DIR

    @staticmethod
    def closest_distance(
        df_acvg_dcvg: pd.DataFrame, df_pcm: pd.DataFrame
    ) -> pd.DataFrame:
        acvg_dvcg_distance = []
        closest_pcm_distance = []
        closest_pcm_index = []
        closest_pcm_latitude = []
        closest_pcm_longitude = []
        closest_pcm_real_distance = []

        pcm_coordinates = df_pcm[
            ["Int GPS Latitude", "Int GPS Longitude", "Real Distance"]
        ]

        for index, row_acvg_dcvg in df_acvg_dcvg.iterrows():
            distances = []
            lat2 = row_acvg_dcvg["latitude"]
            lon2 = row_acvg_dcvg["longitude"]

            for _, pcm in pcm_coordinates.iterrows():
                lat1 = pcm["Int GPS Latitude"]
                lon1 = pcm["Int GPS Longitude"]
                distance = calculate_distance(lat1, lon1, lat2, lon2)
                distances.append(distance)

            np_distances = np.array(distances)
            distance_min = np.min(np_distances)

            acvg_dvcg_distance.append(
                pcm_coordinates.iloc[np_distances.argmin()]["Real Distance"]
                + distance_min
            )
            closest_pcm_distance.append(0 - distance_min)
            closest_pcm_index.append(np_distances.argmin())
            closest_pcm_latitude.append(
                pcm_coordinates.iloc[np_distances.argmin()]["Int GPS Latitude"]
            )
            closest_pcm_longitude.append(
                pcm_coordinates.iloc[np_distances.argmin()][
                    "Int GPS Longitude"
                ]
            )
            closest_pcm_real_distance.append(
                pcm_coordinates.iloc[np_distances.argmin()]["Real Distance"]
            )

        df_acvg_dcvg["real_distance"] = acvg_dvcg_distance
        df_acvg_dcvg["closest_pcm_distance"] = closest_pcm_distance
        df_acvg_dcvg["closest_pcm_real_distance"] = closest_pcm_real_distance
        df_acvg_dcvg["closest_pcm_index"] = closest_pcm_index
        df_acvg_dcvg["closest_pcm_latitude"] = closest_pcm_latitude
        df_acvg_dcvg["closest_pcm_longitude"] = closest_pcm_longitude

        df_acvg_dcvg.sort_values("real_distance", ascending=True, inplace=True)

        return df_acvg_dcvg

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
        df_acvg_dcvg = df.drop_duplicates(
            subset=self.UNIQUE_COLUMNS, keep="last"
        ).reset_index(drop=True)

        try:
            writer = pd.ExcelWriter(excel_filepath, engine="xlsxwriter")

            df_acvg_dcvg.to_excel(writer, sheet_name="Sheet1", index=False)
            df_acvg_dcvg.columns = rename_columns(
                df_acvg_dcvg.columns.tolist()
            )
            df_acvg_dcvg.to_json(json_filepath, orient="records")

            writer.close()

            # print(excel_filepath)

            return excel_filepath
        except Exception as e:
            raise e
