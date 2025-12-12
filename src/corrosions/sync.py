import os
from functools import lru_cache
import pandas as pd
from .utils import calculate_distance, save_df
from .acvg_dcvg import AcvgDcvg
from typing import Self, Optional


class Sync:
    def __init__(
        self,
        area: str,
        year: int,
        segment_code: str,
        pipe_diameter: float,
        length: float,
        normalized_cips_file: str,
        normalized_pcm_file: str,
        normalized_acvg_dcvg_file: Optional[str] = None,
        is_synced: bool = False,
        output_dir: Optional[str] = None,
        verbose: bool = False,
    ):
        self.area = area
        self.segment_code = segment_code
        self.year = year
        self.pipe_diameter = pipe_diameter  # inch
        self.pipe_length = length  # km
        self.normalized_acvg_dcvg_file = normalized_acvg_dcvg_file
        self.normalized_cips_file = normalized_cips_file
        self.normalized_pcm_file = normalized_pcm_file
        self.verbose = verbose

        self._df_acvg_dcvg = pd.DataFrame()
        self._df_cips = pd.DataFrame()
        self._df_pcm = pd.DataFrame()
        self.is_synced = is_synced

        self.output_dir = output_dir

        self.validate()

    def __repr__(self):
        return (
            f"<Sync {self.year}: {self.area}. Segment: {self.segment_code}. "
            f"Diameter: {self.pipe_diameter}. Length: {self.pipe_length} km>. "
            f"ACVG/DCVG File: {self.normalized_acvg_dcvg_file}, "
            f"CIPS File: {self.normalized_cips_file}, "
            f"PCM File: {self.normalized_pcm_file}>"
        )

    def validate(self) -> None:
        """Validate parameter"""
        if self.normalized_acvg_dcvg_file is not None:
            assert os.path.isfile(self.normalized_acvg_dcvg_file), OSError(
                f"{self.normalized_acvg_dcvg_file} not found."
            )

        assert os.path.isfile(self.normalized_cips_file), OSError(
            f"{self.normalized_cips_file} not found."
        )
        assert os.path.isfile(self.normalized_pcm_file), OSError(
            f"{self.normalized_pcm_file} not found."
        )

    @property
    def dict(self):
        return {
            "area_code": self.area,
            "year": self.year,
            "pipe_diameter": self.pipe_diameter,
            "pipe_length": self.pipe_length,
            "segment_code": self.segment_code,
            "cips_protection": self.cips_protection,
            "acvg_dcvg_file": (
                os.path.basename(self.normalized_acvg_dcvg_file).replace(
                    ".xlsx", ".json"
                )
                if self.normalized_acvg_dcvg_file is not None
                else None
            ),
            "pcm_file": os.path.basename(self.normalized_pcm_file).replace(
                ".xlsx", ".json"
            ),
            "cips_file": os.path.basename(self.normalized_cips_file).replace(
                ".xlsx", ".json"
            ),
            "acvg_dcvg_excel": (
                os.path.basename(self.normalized_acvg_dcvg_file)
                if self.normalized_acvg_dcvg_file is not None
                else None
            ),
            "pcm_excel": os.path.basename(self.normalized_pcm_file),
            "cips_excel": os.path.basename(self.normalized_cips_file),
        }

    # DataFrame
    @property
    def df_acvg_dcvg(self) -> pd.DataFrame:

        if self.normalized_acvg_dcvg_file is None:
            return pd.DataFrame()

        @lru_cache
        def cache_df_acvg_dcvg():
            df = pd.read_excel(self.normalized_acvg_dcvg_file)
            df.dropna(how="all", inplace=True)
            return df

        if self._df_acvg_dcvg.empty:
            self._df_acvg_dcvg = cache_df_acvg_dcvg()
            return self._df_acvg_dcvg

        return self._df_acvg_dcvg

    @df_acvg_dcvg.setter
    def df_acvg_dcvg(self, df: pd.DataFrame):
        self._df_acvg_dcvg = df

    @property
    def df_cips(self) -> pd.DataFrame:

        @lru_cache
        def cache_df_cips():
            return pd.read_excel(self.normalized_cips_file, index_col=0)

        if self._df_cips.empty:
            self._df_cips = cache_df_cips()
            return self._df_cips

        return self._df_cips

    @df_cips.setter
    def df_cips(self, df: pd.DataFrame):
        self._df_cips = df

    @property
    def df_pcm(self) -> pd.DataFrame:

        @lru_cache
        def cache_df_pcm():
            df = pd.read_excel(self.normalized_pcm_file)
            df.set_index("Index", inplace=True)
            return df

        if self._df_pcm.empty:
            self._df_pcm = cache_df_pcm()
            return self._df_pcm

        return self._df_pcm

    @df_pcm.setter
    def df_pcm(self, df: pd.DataFrame):
        self._df_pcm = df

    # ACVG - DCVG
    @property
    def first_acvg_dcvg_latitude(self) -> float:
        return self.df_acvg_dcvg.iloc[0]["latitude"]

    @property
    def first_acvg_dcvg_longitude(self) -> float:
        return self.df_acvg_dcvg.iloc[0]["longitude"]

    @property
    def last_acvg_dcvg_latitude(self) -> float:
        return self.df_acvg_dcvg.iloc[-1]["latitude"]

    @property
    def last_acvg_dcvg_longitude(self) -> float:
        return self.df_acvg_dcvg.iloc[-1]["longitude"]

    @property
    def first_acvg_dcvg_coordinates(self) -> tuple[float, float]:
        return self.first_acvg_dcvg_latitude, self.first_acvg_dcvg_longitude

    @property
    def last_acvg_dcvg_coordinates(self) -> tuple[float, float]:
        return self.last_acvg_dcvg_latitude, self.last_acvg_dcvg_longitude

    # CIPS
    @property
    def first_cips_latitude(self) -> float:
        return self.df_cips.iloc[0]["Latitude"]

    @property
    def first_cips_longitude(self) -> float:
        return self.df_cips.iloc[0]["Longitude"]

    @property
    def last_cips_latitude(self) -> float:
        return self.df_cips.iloc[-1]["Latitude"]

    @property
    def last_cips_longitude(self) -> float:
        return self.df_cips.iloc[-1]["Longitude"]

    @property
    def first_cips_coordinates(self) -> tuple[float, float]:
        return self.first_cips_latitude, self.first_cips_longitude

    @property
    def last_cips_coordinates(self) -> tuple[float, float]:
        return self.last_cips_latitude, self.last_cips_longitude

    @property
    def cips_protection(self) -> str:
        return self.df_cips.iloc[0]["protection"]

    # PCM
    @property
    def first_pcm_latitude(self) -> float:
        if "Int GPS Latitude" not in self.df_pcm.columns:
            raise IndexError(
                f"Int GPS Latitude not found in {self.normalized_pcm_file}\n"
                f"columns: {self.df_pcm.columns}"
            )

        return self.df_pcm.iloc[0]["Int GPS Latitude"]

    @property
    def first_pcm_longitude(self) -> float:
        return self.df_pcm.iloc[0]["Int GPS Longitude"]

    @property
    def last_pcm_latitude(self) -> float:
        return self.df_pcm.iloc[-1]["Int GPS Latitude"]

    @property
    def last_pcm_longitude(self) -> float:
        return self.df_pcm.iloc[-1]["Int GPS Longitude"]

    @property
    def first_pcm_coordinates(self) -> tuple[float, float]:
        return self.first_pcm_latitude, self.first_pcm_longitude

    @property
    def last_pcm_coordinates(self) -> tuple[float, float]:
        return self.last_pcm_latitude, self.last_pcm_longitude

    # Coordinates and Distance
    @property
    def first_distance_cips(self) -> float:
        """FIRST Distance between PCM and CIPS in meter."""
        lat1, lon1 = self.first_pcm_coordinates
        lat2, lon2 = self.first_cips_coordinates
        return calculate_distance(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)

    @property
    def last_distance_cips(self) -> float:
        """LAST Distance between PCM and CIPS in meter."""
        lat1, lon1 = self.last_pcm_coordinates
        lat2, lon2 = self.last_cips_coordinates
        return calculate_distance(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)

    @property
    def first_distance_acvg_dcvg(self) -> float:
        """FIRST Distance between PCM and ACVG - DCVG in meter."""
        lat1, lon1 = self.first_pcm_coordinates
        lat2, lon2 = self.first_acvg_dcvg_coordinates
        return calculate_distance(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)

    @property
    def last_distance_acvg_dcvg(self) -> float:
        """LAST Distance between PCM and CIPS in meter."""
        lat1, lon1 = self.last_pcm_coordinates
        lat2, lon2 = self.last_acvg_dcvg_coordinates
        return calculate_distance(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)

    @property
    def matrix_distance_cips(self):
        lat1_pcm_first = self.first_pcm_latitude
        lat1_pcm_last = self.last_pcm_latitude
        lon1_pcm_first = self.first_pcm_longitude
        lon1_pcm_last = self.last_pcm_longitude

        lat2_cips_first = self.first_cips_latitude
        lat2_cips_last = self.last_cips_latitude
        lon2_cips_first = self.first_cips_longitude
        lon2_cips_last = self.last_cips_longitude

        return {
            "first_first": self.first_distance_cips,
            "first_last": calculate_distance(
                lat1=lat1_pcm_first,
                lon1=lon1_pcm_first,
                lat2=lat2_cips_last,
                lon2=lon2_cips_last,
            ),
            "last_first": calculate_distance(
                lat1=lat1_pcm_last,
                lon1=lon1_pcm_last,
                lat2=lat2_cips_first,
                lon2=lon2_cips_first,
            ),
            "last_last": self.last_distance_cips,
        }

    @property
    def matrix_distance_acvg_dcvg(self):
        lat1_pcm_first = self.first_pcm_latitude
        lat1_pcm_last = self.last_pcm_latitude
        lon1_pcm_first = self.first_pcm_longitude
        lon1_pcm_last = self.last_pcm_longitude

        lat2_acvg_dcvg_first = self.first_acvg_dcvg_latitude
        lat2_acvg_dcvg_last = self.last_acvg_dcvg_latitude
        lon2_acvg_dcvg_first = self.first_acvg_dcvg_longitude
        lon2_acvg_dcvg_last = self.last_acvg_dcvg_longitude

        return {
            "first_first": self.first_distance_acvg_dcvg,
            "first_last": calculate_distance(
                lat1=lat1_pcm_first,
                lon1=lon1_pcm_first,
                lat2=lat2_acvg_dcvg_last,
                lon2=lon2_acvg_dcvg_last,
            ),
            "last_first": calculate_distance(
                lat1=lat1_pcm_last,
                lon1=lon1_pcm_last,
                lat2=lat2_acvg_dcvg_first,
                lon2=lon2_acvg_dcvg_first,
            ),
            "last_last": self.last_distance_acvg_dcvg,
        }

    # Check if df should be inverted
    @property
    def pcm_is_sync(self) -> bool:
        distance_matrix = self.matrix_distance_cips
        if (
            distance_matrix["first_first"] > distance_matrix["first_last"]
        ) and (distance_matrix["first_first"] > 0):
            return False
        return True

    @property
    def cips_is_sync(self) -> bool:
        distance_matrix = self.matrix_distance_cips
        if (
            distance_matrix["first_first"] < distance_matrix["first_last"]
        ) and (distance_matrix["first_first"] < 0):
            return False
        return True

    def fix(self, save: bool = True) -> Self:
        if self.pcm_is_sync and self.cips_is_sync:
            if self.verbose:
                print(
                    f"<{self.area} - {self.segment_code}>PCM and CIPS are sync"
                )
            self.is_synced = True
            return self

        if not self.cips_is_sync:
            if self.verbose:
                print("Flipping CIPS")
            self.df_cips = self.invert(self.df_cips)
            if save:
                save_df(df=self.df_cips, filepath=self.normalized_cips_file)
                if self.verbose:
                    print(
                        f"<{self.area} - {self.segment_code}>CIPS Normalized file updated: {self.normalized_cips_file}"
                    )

        if not self.pcm_is_sync:
            if self.verbose:
                print("Flipping PCM")
            self.df_pcm = self.invert(self.df_pcm)
            if save:

                if self.output_dir is not None:
                    print(self.output_dir)

                save_df(df=self.df_pcm, filepath=self.normalized_pcm_file)
                if self.verbose:
                    print(
                        f"<{self.area} - {self.segment_code}>PCM Normalized file updated: {self.normalized_pcm_file}"
                    )

        return self

    def invert(self, df: pd.DataFrame) -> pd.DataFrame:
        """Correction zero point.

        Args:
            df: pd.DataFrame

        Returns:
            pd.DataFrame
        """
        max_distance = df["Real Distance"].max()
        df["Real Distance"] = max_distance - df["Real Distance"]
        df.sort_values("Real Distance", ascending=True, inplace=True)
        if self.verbose:
            print(f"<{self.area} - {self.segment_code}>Inverted Real Distance")
        return df

    def recalculate_distance_cips(self) -> Self:
        """Recalculate distance between CIPS and PCM.

        Returns:
            self
        """
        reference_distance = self.matrix_distance_cips["first_first"]

        df = self.df_cips
        df.reset_index(inplace=True)
        for index in df.index:
            if index == 0:
                df["Distance"] = 0.0
                df["Real Distance"] = reference_distance
                continue

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
        save_df(df=df, filepath=self.normalized_cips_file)
        self.df_cips = df
        return self

    def recalculate_distance_acvg_dcvg(self) -> Self:
        """Recalculate distance between ACVG/DCVG and PCM and CIPS.

        Returns:
            self
        """
        if self.normalized_acvg_dcvg_file is None:
            return self

        df_acvg_dcvg = self.df_acvg_dcvg
        df_pcm = self.df_pcm
        df_cips = self.df_cips

        df_acvg_dcvg = AcvgDcvg.closest_distance_pcm(df_acvg_dcvg, df_pcm)
        df = AcvgDcvg.closest_distance_cips(df_acvg_dcvg, df_cips)

        save_df(
            df=df, filepath=self.normalized_acvg_dcvg_file, save_index=False
        )
        self.df_acvg_dcvg = df
        return self

    def recalculate_distance(self) -> Self:
        """Recalculate distance between ACVG/DCVG, CIPS and PCM.

        Returns:
            self
        """
        if self.cips_is_sync and self.pcm_is_sync:
            if self.verbose:
                print(
                    f"<{self.area} - {self.segment_code}>Recalculating distance.."
                )
            self.recalculate_distance_acvg_dcvg().recalculate_distance_cips()
            if self.verbose:
                print(f"<{self.area} - {self.segment_code}>Sync is done.\n")
            return self
        if self.verbose:
            print(
                f"<{self.area} - {self.segment_code}>CIPS and PCM need to be synced."
            )
        return self
