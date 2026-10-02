from corrosions.data.base_data import BaseData


class PCM(BaseData):
    """Pipeline Current Mapping (PCM) survey reader.

    PCM surveys are performed to determine the coating integrity of underground
    gas pipelines. This class loads a single PCM Excel export, coerces its
    numeric columns, and inherits the fluent ``check`` / ``clean`` / ``save``
    pipeline from ``BaseData``.

    Attributes:
        REQUIRED_COLUMNS (list[str]): Required columns expected in the source Excel.
        NUMERIC_COLUMNS (list[str]): Columns coerced to numeric via
            ``pd.to_numeric(..., errors="coerce")`` at load time.
        CLEAN_REQUIRED_COLUMNS (list[str]): Columns whose presence and
            non-NaN value is required for a row to survive ``clean``. Excludes
            ``Ext GPS Latitude`` / ``Ext GPS Longitude`` because they are
            frequently blank in real PCM exports.
        UNIQUE_COLUMNS (tuple[str, str]): Columns whose combination must be
            unique across rows (used by ``check`` to flag duplicates).

    Example:
        >>> pcm = PCM("data/2024/PCM/segment-01.xlsx", year=2024)
        >>> pcm.check().clean().save()
        >>> pcm.report["is_valid"]
        True
    """

    KIND = "pcm"

    REQUIRED_COLUMNS: list[str] = [
        "Index",
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Ext GPS Latitude",
        "Ext GPS Longitude",
        "Survey name (0-100)",
        "Gain (dB)",
    ]

    NUMERIC_COLUMNS: list[str] = [
        "Index",
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
    ]

    CLEAN_REQUIRED_COLUMNS: list[str] = [
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
    ]

    UNIQUE_COLUMNS: tuple[str, str] = ("Int GPS Latitude", "Int GPS Longitude")
