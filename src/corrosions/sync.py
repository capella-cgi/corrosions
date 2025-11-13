from functools import cached_property, lru_cache
import pandas as pd
from .utils import calculate_distance


class Sync:
    def __init__(
        self,
        area: str,
        year: int,
        segment: str,
        pipe_diameter: float,
        length: float,
        acvg_dcvg_file: str,
        normalized_cips_file: str,
        normalized_pcm_file: str,
        verbose: bool = False,
    ):
        self.area = area
        self.segment = segment
        self.year = year
        self.pipe_diameter = pipe_diameter  # inch
        self.length = length  # km
        self.acvg_dcvg_file = acvg_dcvg_file
        self.normalized_cips_file = normalized_cips_file
        self.normalized_pcm_file = normalized_pcm_file
        self.verbose = verbose

        self._df_acvg_dcvg = pd.DataFrame()
        self._df_cips = pd.DataFrame()
        self._df_pcm = pd.DataFrame()

    def __repr__(self):
        return (
            f"<Sync {self.year}: {self.area}. Segment: {self.segment}. "
            f"Diameter: {self.pipe_diameter} - {self.length} km>"
        )

    @property
    def dict(self):
        return {
            "year": self.year,
            "area": self.area,
            "segment": self.segment,
            "pipe_diameter": self.pipe_diameter,
            "length": self.length,
            "files": {
                "acvg_dcvg": self.acvg_dcvg_file,
                "pcm": self.normalized_pcm_file,
                "cips": self.normalized_cips_file,
            },
        }

    # DataFrame
    @property
    def df_acvg_dcvg(self) -> pd.DataFrame:

        @lru_cache
        def cache_df_acvg_dcvg():
            df = pd.read_excel(self.acvg_dcvg_file)
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
        return self.df_cips.iloc[0]["latitude"]

    @property
    def first_cips_longitude(self) -> float:
        return self.df_cips.iloc[0]["longitude"]

    @property
    def last_cips_latitude(self) -> float:
        return self.df_cips.iloc[-1]["latitude"]

    @property
    def last_cips_longitude(self) -> float:
        return self.df_cips.iloc[-1]["longitude"]

    @property
    def first_cips_coordinates(self) -> tuple[float, float]:
        return self.first_cips_latitude, self.first_cips_longitude

    @property
    def last_cips_coordinates(self) -> tuple[float, float]:
        return self.last_cips_latitude, self.last_cips_longitude

    # PCM
    @property
    def first_pcm_latitude(self) -> float:
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

    def fix(self, save: bool = True) -> None:
        if self.pcm_is_sync and self.cips_is_sync:
            if self.verbose:
                print(f"PCM and CIPS are sync")
            return None

        if not self.cips_is_sync:
            if self.verbose:
                print("Flipping CIPS")
            self.df_cips = self.invert(self.df_cips)
            if save:
                self.df_cips.to_excel(self.normalized_cips_file)
                if self.verbose:
                    print(
                        f"CIPS Normalized file updated: {self.normalized_cips_file}"
                    )

        if not self.pcm_is_sync:
            if self.verbose:
                print("Flipping PCM")
            self.df_pcm = self.invert(self.df_pcm)
            if save:
                self.df_pcm.to_excel(self.normalized_pcm_file)
                if self.verbose:
                    print(
                        f"PCM Normalized file updated: {self.normalized_pcm_file}"
                    )

        return None

    def invert(self, df: pd.DataFrame) -> pd.DataFrame:
        max_distance = df["Real Distance"].max()
        df["Real Distance"] = max_distance - df["Real Distance"]
        df.sort_values("Real Distance", ascending=True, inplace=True)
        if self.verbose:
            print("Inverted Real Distance")
        return df

    def recalculate_distance_cips(self) -> None:
        reference_distance = self.matrix_distance_cips["first_first"]

        df = self.df_cips
        df.reset_index(inplace=True)
        for index in df.index:
            if index == 0:
                df["distance"] = 0.0
                df["real_distance"] = reference_distance
                continue

            lat_1 = df.loc[index - 1, "latitude"]
            lon_1 = df.loc[index - 1, "longitude"]
            lat_2 = df.loc[index, "latitude"]
            lon_2 = df.loc[index, "longitude"]

            distance = calculate_distance(lat_1, lon_1, lat_2, lon_2)
            df.loc[index, "distance"] = distance
            df.loc[index, "real_distance"] = (
                distance + df.loc[index - 1, "real_distance"]
            )
        df.set_index("data_no", inplace=True)
        self.df_cips = df

    def recalculate_distance(self) -> None:
        if self.cips_is_sync and self.pcm_is_sync:
            return self.recalculate_distance_cips()
        if self.verbose:
            print("CIPS and PCM need to be synced.")
        return None
