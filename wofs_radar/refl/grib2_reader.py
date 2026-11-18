"""
MRMS MergedReflectivityQC GRIB2 reader for WoFS.

Replaces the legacy Xarray/PyNIO GRIB2 backend with pygrib.

Preserves:
    - North-to-south latitude orientation
    - West-to-east longitude orientation
    - 0-360 degree longitude convention
    - Original reflectivity values
    - Missing-data value (-99)
    - No-coverage value (-999)
    - Legacy PyNIO variable names
"""

import gzip
import tempfile

import numpy as np
import pygrib
import xarray as xr


REFLECTIVITY_NAME = "CONUSMergedReflectivityQC_P0_L102_GLL0"


def read_mrms_grib2(filename):
    """Decode one MRMS MergedReflectivityQC GRIB2 file."""

    grbs = pygrib.open(str(filename))

    try:

        if grbs.messages != 1:
            raise ValueError(
                f"Expected one MRMS GRIB2 message, "
                f"found {grbs.messages}: {filename}"
            )

        grb = grbs.message(1)

        # Validate the MRMS reflectivity product.

        parameter = (
            int(grb["discipline"]),
            int(grb["parameterCategory"]),
            int(grb["parameterNumber"]),
        )

        if parameter != (209, 9, 0):
            raise ValueError(
                f"Unexpected MRMS parameter: {parameter}"
            )

        if grb["gridType"] != "regular_ll":
            raise ValueError(
                f"Unsupported MRMS grid: {grb['gridType']}"
            )

        if grb["typeOfLevel"] != "heightAboveSea":
            raise ValueError(
                f"Unexpected level type: {grb['typeOfLevel']}"
            )

        # Decode reflectivity and preserve MRMS missing-data codes.

        raw = np.ma.asarray(grb.values)

        if np.ma.count_masked(raw) != 0:
            raise ValueError(
                "Unexpected masked GRIB2 values; "
                "missing-data representation requires review"
            )

        values = np.asarray(raw.data)

        if not np.isfinite(values).all():
            raise ValueError("Non-finite MRMS reflectivity values")

        ni = int(grb["Ni"])
        nj = int(grb["Nj"])

        if values.shape != (nj, ni):
            raise ValueError(
                f"Unexpected MRMS data shape: {values.shape}"
            )

        # Obtain the coordinates associated with decoded data.

        lats, lons = grb.latlons()

        if lats.shape != values.shape or lons.shape != values.shape:
            raise ValueError("MRMS coordinate shape mismatch")

        if not np.allclose(
            lats, lats[:, :1], rtol=0, atol=1.e-6
        ):
            raise ValueError("MRMS latitude is not rectilinear")

        if not np.allclose(
            lons, lons[:1, :], rtol=0, atol=1.e-6
        ):
            raise ValueError("MRMS longitude is not rectilinear")

        lat = lats[:, 0].copy()
        lon = np.mod(lons[0, :], 360.0)

        # Normalize orientation if required.

        if lat[0] < lat[-1]:
            lat = lat[::-1].copy()
            values = values[::-1, :]

        if lon[0] > lon[-1]:
            lon = lon[::-1].copy()
            values = values[:, ::-1]

        if not np.all(np.diff(lat) < 0):
            raise ValueError("MRMS latitude is not descending")

        if not np.all(np.diff(lon) > 0):
            raise ValueError("MRMS longitude is not ascending")

        # Construct the legacy-compatible Xarray dataset.

        reflectivity = xr.DataArray(
            values,
            dims=("lat_0", "lon_0"),
            coords={
                "lat_0": lat,
                "lon_0": lon,
            },
            attrs={
                "long_name": "MRMS Merged Reflectivity QC",
                "units": "dBZ",
                "height_above_sea_level": float(grb["level"]),
                "mrms_missing_data": -99.0,
                "mrms_no_coverage": -999.0,
            },
        )

        ds = xr.Dataset(
            {
                REFLECTIVITY_NAME: reflectivity,
                "MergedReflectivityQC": reflectivity,
            },
            attrs={
                "source": "NOAA MRMS",
                "reader": "pygrib",
                "grib2_discipline": parameter[0],
                "grib2_parameter_category": parameter[1],
                "grib2_parameter_number": parameter[2],
            },
        )

        ds["lat_0"].attrs["units"] = "degrees_north"
        ds["lon_0"].attrs["units"] = "degrees_east"

        return ds

    finally:
        grbs.close()


def read_mrms_gzip_bytes(compressed_data):
    """Decode gzip-compressed MRMS GRIB2 bytes."""

    with tempfile.NamedTemporaryFile(
        suffix=".grib2"
    ) as tmp:

        tmp.write(gzip.decompress(compressed_data))
        tmp.flush()

        return read_mrms_grib2(tmp.name)
