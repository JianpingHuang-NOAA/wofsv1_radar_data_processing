#!/usr/bin/env python
#############################################################
# grid3d: A program to process new MRMS volumes             #
#         netCDF4 MRMS files are read in and processed to   #
#         to DART format for assimilationp.                 #
#                                                           #
#       Python package requirements:                        #
#       ----------------------------                        #
#       Numpy                                               #
#       Scipy                                               #
#       matplotlib                                          #
#############################################################
#
# created by Lou Wicker Feb 2017
#
#############################################################
from __future__ import print_function
from __future__ import division

from past.utils import old_div
from builtins import zip
from builtins import range
from builtins import object
import os
import sys
import glob
import time as timeit
import re
from operator import itemgetter
import tempfile
import gzip as gz

# Need to set the backend BEFORE loading pyplot
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
plt.ioff()
from mpl_toolkits.basemap import Basemap

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import scipy.ndimage as ndimage
from optparse import OptionParser
from matplotlib.offsetbox import AnchoredText
import netCDF4 as ncdf
import math

from cmweather import cm
from .grib2_reader import read_mrms_gzip_bytes
from datetime import datetime, timedelta
from numpy import ma
from ..utils.dart_tools import mrms_write_DART_ascii
import xarray as xr
import pandas as pd

from pygeodesy.sphericalNvector import LatLon
from pygeodesy.points import isenclosedBy

import s3fs
from bs4 import BeautifulSoup
import requests, urllib

# missing value
_missing = -9999.
_plot_counties = True

_domain_gridpoint_margin = 7

# Colorscale information

_ref_scale  = np.arange(5.,85.,5.0)
_ref_ctable = cm.NWSRef
_ref_min_plot = 20.
_plot_format = 'png'

# Radar information


_temp_netcdf_file = "./tmp.nc"

# Grid stuff

# NX = 300 #292  # changed from 200 to leave a 20 km ring inside domain
# NY = 300 #232

# Width in minutes of time to look for radar files every 15 min

_dt_window = [-3,3]

# Debug

_debug = True

##########################################################################################
# Parameter dict for reflectivity masking
_grid_dict = {
              'zero_dbz_obtype' : True,
              'thin_zeros'      : 1,
              'halo_footprint'  : 5,
              'vert_halo_fp'    : 1,
              'obs_grid_spacing': 5, #WoFS-Retro
              #'obs_grid_spacing': 3, #MPAS-WoFS
              'ns_radius'       : 421.0,
              'ew_radius'       : 411.0,
              'max_height'      : 10000.,
              'zero_levels'     : [3000.,7000.], 
              'min_dbz_analysis': 15.0,
              'min_dbz_zeros'   : 15.0,
              'reflectivity'    : 7.0,
              '0reflectivity'   : 5.0, #WoFS-Retro
              #'0reflectivity'   : 2.0, #MPAS-WoFS
              'levels'          : ['00.50','01.00','01.50','02.00','02.50','03.00', \
                                   '04.00','05.00','06.00','07.00','08.00','09.00','10.00'],
              'QC_info'         : [[15.,5.],[20.,1.]],
             }

_obs_errors = { 'reflectivity'    : 7.0, '0reflectivity'   : 5.0 }

#=========================================================================================
# Class variable used as container

class Gridded_Field(object):
  
  def __init__(self, name, data=None, **kwargs):    
    self.name = name    
    self.data = data    
    
    if kwargs != None:
      for key in kwargs:  setattr(self, key, kwargs[key])
      
  def keys(self):
    return self.__dict__

#===============================================================================
def get_loc(x, xc, radius):

  """
      Finds the array index of locations around a center point
  """
  if xc < 0:
      indices = np.where(x >= xc)
  else:
      indices = np.where(x < xc)

  if np.size(indices[0]) == 0:
    return -1, 0
  else:
    i0 = indices[0][0]
    return i0, i0+1

#=========================================================================================
# Routine to search the radar directories and find tilts that are within a time window
# Thanks to Anthony Reinhart for the original version of this!
# Modified by Lou Wicker April 2018

def Get_Closest_Elevations(path, anal_time, sub_dir=None, window=_dt_window):
   """
   DEPRECATED IN FAVOR OF MRMS DATA FEED ON AWS - BRIAN MATILLA APRIL 2024
   -----------------------------------------------------------------------
      get_closest_elevations:
          path:       Path to the top level directory of radar
          anal_time:  A datetime object which is the time to center
                      the window search on.
          sub_dir:    In case the radar tilts are written one more layer
                      down (MRMS likes to do this), e.g., the tilts are located
                      in a directory like:  .../KAMA/Velocity_Threshold_cut_smoothed_Collection"
          window:     len(window) == 1:  this is the window +/- of the analysis time.
                      len(window) == 2:  the window uses analysis_time + window[0] --> analysis_time + window[1]
                                         Note that window[0] should equal to or less than zero.
                      window units are SECONDS
          
          RETURNS:    either an empty list, or a list with full path names of the 
                      radar's tilts that are within the supplied window.
   """

   ObsFileList = []
   
   if sub_dir:
       full_path = os.path.join(path, sub_dir)
   else:
       full_path = path

   if len(window) == 1:
       lwindow = [-window, window]
   else:
       if window[0] > 0:  # this is when I am stupid...
           window[0] = -window[0]
       lwindow = window

   for elev in os.listdir(full_path):
   
       tilt_time = {}
           
       for fn in os.listdir(os.path.join(full_path,elev)):
       
           tempdate = datetime(int(fn[0:4]),int(fn[4:6]),int(fn[6:8]),int(fn[9:11]),int(fn[11:13]),int(fn[13:15]))

           timediff = anal_time - tempdate
           time0    = anal_time + timedelta(0,minutes=lwindow[0])
           time1    = anal_time + timedelta(0,minutes=lwindow[1])
           
           # Change this if you want +something -window instead of 0-900. if statement is +2-15
           # if timediff >= datetime.timedelta(0,-120) and timediff < datetime.timedelta(0,window):

         # if timediff >= timedelta(0,minutes=lwindow[0]) and timediff < timedelta(0,minutes=lwindow[1]):
           if tempdate >= time0 and tempdate < time1:
               tilt_time["%s/%s" % (elev,fn)] = timediff
    #          print anal_time
    #          print time0
    #          print time1
    #          print tilt_time
           else:
               continue

       # This code finds the latest file that exists in the list - using only a single tilt per volume.
       if bool(tilt_time):
            maxtime = max(list(tilt_time.items()),key=lambda d:(d[1]))
            ObsFileList.append(os.path.join(full_path,maxtime[0]))
       del(tilt_time)

       
   if len(ObsFileList) > 0:
       print("\n ============================================================================\n")
       print("\n Prep_MRMS.Get_Closest_Elevations:  found %i files in %s  \n" % (len(ObsFileList), path))
   else:
       print("\n Prep_MRMS.Get_Closest_Elevations:  No obs found \n")

   # Handy sort command that will give me the the lowest tilts first....       
   ObsFileList.sort()
   print(ObsFileList)

   return ObsFileList
                 
#=========================================================================================

def Get_Closest_Elevations_AWS(anal_time, grid_dict=_grid_dict, window=_dt_window):
    """
    get_closest_elevations_AWS:
        This routine upgrades Get_Closest_Elevations by combining a search window
        and automated file selection from AWS. 

        anal_time: A datetime object which is the time to center
                   the window search on.
        window:     len(window) == 1:  this is the window +/- of the analysis time.
                    len(window) == 2:  the window uses analysis_time + window[0] --> analysis_time + window[1]
                                         Note that window[0] should equal to or less than zero.
                    window units are SECONDS

    RETURNS:    Either an empty list, or a list with full file names of the radar's tilts that are
                withn the supplied window

    Added by Brian Matilla - April 2024
    """

    ObsFileList = []
    target_time = anal_time

    start = target_time + timedelta(minutes = _dt_window[0]) #NEGATIVE dt_window, so operator must be positive here
    end = target_time + timedelta(minutes = _dt_window[1])

    elev_list = _grid_dict['levels']
    for ea in elev_list:
        valid_files = []
        # FIND FILES ON AMAZON SERVER
        print(f'Now pulling in refl data for elevation angle: {ea} from AWS.')
        fs = s3fs.S3FileSystem(anon=True)
        path = f'noaa-mrms-pds/CONUS/MergedReflectivityQC_{ea}/{target_time:%Y%m%d}/'

        files = np.array(fs.ls(path, refresh=True))

        for v in files:
            m = re.match('^MRMS_MergedReflectivityQC_[0,1][0-9].[0,5][0]_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2}).grib2.gz', v.split('/')[-1])

            if m != None:
                d = datetime.strptime(m.group('year') + m.group('month') + m.group('day') + '-' + m.group('hour') + m.group('minute') + m.group('second'), "%Y%m%d-%H%M%S")

                if start <= d and d <= end:
                    valid_files.append((d, abs((target_time - d).total_seconds()), v.split('/')[-1]))

        # sort the files
        sorted_files = sorted(valid_files, key = itemgetter(1))

        # top (most recent within time block) to download
        file_to_download = next(iter(sorted_files))[2]

        ObsFileList.append(path+file_to_download)

    return ObsFileList
import os
import re
import glob
from datetime import datetime, timedelta
from operator import itemgetter


def Get_Closest_Elevations_Local(
#def Get_Closest_Elevations_NCEP(
        anal_time,
        grid_dict=_grid_dict,
        window=_dt_window,
        data_root='/scratch4/NCEPDEV/fv3-cam/Jianping.Huang/WoFS/sorc/frdd-wofs-obs-radar/test_mrms'):
    """
    Get closest local MRMS reflectivity files.

    Local directory structure:

        /test_mrms/YYYYMMDD/
            MRMS_MergedReflectivityQC_ELEV_YYYYMMDD-HHMMSS.grib2.gz

    Example:

        /test_mrms/20260916/
            MRMS_MergedReflectivityQC_00.50_20260916-042642.grib2.gz

    Parameters
    ----------
    anal_time : datetime
        Analysis time.

    grid_dict : dict
        Dictionary containing the requested elevation levels.
        Expected key:
            grid_dict['levels']

    window : tuple/list
        Time window in minutes relative to anal_time.

        len(window) == 1:
            +/- window[0]

        len(window) == 2:
            anal_time + window[0] --> anal_time + window[1]

    data_root : str
        Root directory containing YYYYMMDD directories.

    Returns
    -------
    ObsFileList : list
        List containing the closest local MRMS files for each
        requested elevation.
    """

    ObsFileList = []

    target_time = anal_time

    # --------------------------------------------------------
    # TIME WINDOW
    # --------------------------------------------------------
    if len(window) == 1:

        start = target_time - timedelta(minutes=window[0])
        end = target_time + timedelta(minutes=window[0])

    elif len(window) == 2:

        start = target_time + timedelta(minutes=window[0])
        end = target_time + timedelta(minutes=window[1])

    else:
        raise ValueError(
            "window must contain either 1 or 2 values."
        )

    # --------------------------------------------------------
    # REQUESTED ELEVATION ANGLES
    # --------------------------------------------------------
    elev_list = grid_dict['levels']

    # --------------------------------------------------------
    # SEARCH LOCAL FILES
    # --------------------------------------------------------
    for ea in elev_list:

        print(
            f'Now searching local MRMS refl data '
            f'for elevation angle: {ea}'
        )

        # ----------------------------------------------------
        # Convert elevation to filename format
        #
        # Example:
        #     0.5  -> 00.50
        #     1.0  -> 01.00
        #     2.0  -> 02.00
        # ----------------------------------------------------
        elev_string = f'{float(ea):05.2f}'

        # Directory based on analysis date
        date_dir = os.path.join(
            data_root,
            target_time.strftime('%Y%m%d')
        )

        # Search pattern
        search_pattern = os.path.join(
            date_dir,
            f'MRMS_MergedReflectivityQC_{elev_string}_'
            f'*.grib2.gz'
        )
        print(f"Search pattern: {search_pattern}")
 # /scratch4/NCEPDEV/fv3-cam/Jianping.Huang/WoFS/sorc/frdd-wofs-obs-radar/test_mrms/20260916/MRMS_MergedReflectivityQC_10.00_20260916-044042.grib2.gz

        files = glob.glob(search_pattern)

        if not files:
            print(
                f'   WARNING: No files found for elevation '
                f'{elev_string} in {date_dir}'
            )
            continue

        # ----------------------------------------------------
        # FIND FILES WITHIN TIME WINDOW
        # ----------------------------------------------------
        valid_files = []

        for filename in files:

            basename = os.path.basename(filename)

            # Example filename:
            #
            # MRMS_MergedReflectivityQC_00.50_
            # 20260916-042642.grib2.gz
            #
            pattern = (
                r'^MRMS_MergedReflectivityQC_'
                r'(?P<elev>\d{2}\.\d{2})_'
                r'(?P<date>\d{8})-'
                r'(?P<time>\d{6})\.grib2\.gz$'
            )

            m = re.match(pattern, basename)

            if m is None:
                continue

            # ------------------------------------------------
            # Convert filename timestamp to datetime
            # ------------------------------------------------
            file_time = datetime.strptime(
                m.group('date') + m.group('time'),
                '%Y%m%d%H%M%S'
            )

            # ------------------------------------------------
            # Check whether file is inside time window
            # ------------------------------------------------
            if start <= file_time <= end:

                time_difference = abs(
                    (target_time - file_time).total_seconds()
                )

                valid_files.append(
                    (
                        file_time,
                        time_difference,
                        filename
                    )
                )

        # ----------------------------------------------------
        # NO VALID FILES
        # ----------------------------------------------------
        if not valid_files:

            print(
                f'   WARNING: No valid files found for '
                f'{elev_string} within '
                f'{start} --> {end}'
            )

            continue

        # ----------------------------------------------------
        # SORT BY DISTANCE FROM ANALYSIS TIME
        # ----------------------------------------------------
        sorted_files = sorted(
            valid_files,
            key=itemgetter(1)
        )

        # ----------------------------------------------------
        # CLOSEST FILE
        # ----------------------------------------------------
        closest_file = sorted_files[0][2]

        print(
            f'   Selected: {os.path.basename(closest_file)}'
        )

        ObsFileList.append(closest_file)

    return ObsFileList
#=========================================================================================
def Get_Closest_Elevations_NCEP(anal_time, grid_dict=_grid_dict, window=_dt_window):
    """
    get_closest_elevations_NCEP:
        - Retrieve MRMS reflectivity obs from the NCEP realtime data feed.
        
        anal_time: A datetime object which is the time to center
                   the window search on.
        window:     len(window) == 1:  this is the window +/- of the analysis time.
                    len(window) == 2:  the window uses analysis_time + window[0] --> analysis_time + window[1]
                                         Note that window[0] should equal to or less than zero.
                    window units are SECONDS

    RETURNS:    Either an empty list, or a list with full file names of the radar's tilts that are
                withn the supplied window

    Added by Brian Matilla - July 2024    
    """
    ObsFileList = []
#    target_time = datetime.strptime(anal_time, "%Y%m%d%H%M")
    target_time = anal_time

    start = target_time + timedelta(minutes = _dt_window[0])
    end = target_time + timedelta(minutes = _dt_window[1])

    elev_list = _grid_dict['levels']
    for ea in elev_list:
        valid_files = []
        print(f'Now pulling in refl data for elevation angle: {ea} from NCEP.')
        # FIND FILES ON MRMS NOAA NCEP SERVER
        url = f'https://mrms.ncep.noaa.gov/data/3DRefl/MergedReflectivityQC_{ea}/'
        geturl = requests.get(url)
        soup = BeautifulSoup(geturl.content, 'html.parser')
        result = [grb2['href'] for grb2 in soup.find_all('a', href=True) if 'grib2.gz' in grb2['href']][2::] # Skip header info

        for v in result:
            m = re.match('^MRMS_MergedReflectivityQC_[0,1][0-9].[0,5][0]_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2}).grib2.gz', v.split('/')[-1])

            if m != None:
                d = datetime.strptime(m.group('year') + m.group('month') + m.group('day') + '-' + m.group('hour') + m.group('minute') + m.group('second'), "%Y%m%d-%H%M%S")
            
            if start <= d and d <= end:
                valid_files.append((d, abs((target_time - d).total_seconds()), v.split('/')[-1]))
        # sort the files
        sorted_files = sorted(valid_files, key = itemgetter(1))

        # top (most recent within time block) to download
        file_to_download = next(iter(sorted_files))[2]

        ObsFileList.append(url+file_to_download)

    return ObsFileList
                     
#=========================================================================================
# Decompress zipped MRMS files from AWS

def load_mrms_AWS(infile):
    """
    Read gzip-compressed MRMS GRIB2 data from AWS.

    Returns an Xarray dataset compatible with the legacy
    MRMS reflectivity processing interface.
    """

    fs = s3fs.S3FileSystem(anon=True)

    with fs.open(infile, mode="rb") as aws_obj:
        compressed_file = aws_obj.read()

    return read_mrms_gzip_bytes(compressed_file)




#=========================================================================================
def load_mrms_NCEP(infile):
    """
    Read gzip-compressed MRMS GRIB2 data from NCEP
    or a local file.

    Returns an Xarray dataset compatible with the legacy
    MRMS reflectivity processing interface.
    """

    if infile.startswith(("http://", "https://")):

        with urllib.request.urlopen(infile) as response:
            compressed_file = response.read()

    else:

        with open(infile, "rb") as f:
            compressed_file = f.read()

    return read_mrms_gzip_bytes(compressed_file)




#=========================================================================================
# Extract data from the AWS files

def assemble_3D_grid_AWS(filenames, loc=None, debug=False, dbz_name = "MergedReflectivityQC", NX = 300, NY = 300):
    """
    This routine assembles the various elevation angle data from MRMS files being passed 
    in to prepare it for masking application.

    filenames   : list of filenames to process
    loc         : A center lat/lon point to focus the data preparation on.
    dbz_name    : Defaults to the standard variable name within MRMS files.
    NX/NY       : Default grid points to use.

    RETURNS:    Gridded_Field object with the MRMS data assembled into a 3-D array.    

    Code applied by Brian Matilla - Apr 2024
    """

    levels = _grid_dict['levels']
    nlvls  = len(levels)

    for n, filename in enumerate(filenames):
 
        f = load_mrms_AWS(filename)       
#        try:
#            f = load_mrms_AWS(filename)
#        except:
#            print(f'Could not open file {filename}')
#            continue

        if debug:
            print("\n Processing file:  %s" % (filename))

        if n == 0:
            nlons  = len(f.lon_0)
            nlats  = len(f.lat_0)
 
            f_lats = f.variables['lat_0'][...]
            f_lons = f.variables['lon_0'][...] - 360. #Convert from full 360 deg. to -180-180 hemispheres.

            missingData = -99.
            noCoverage = -999.
            
            time = datetime.strptime(filenames[n][-24:-9], '%Y%m%d-%H%M%S')

            if loc != None:
                ic     = get_loc(f_lons, loc[1], 0.5)[0]
                jc     = get_loc(f_lats, loc[0], 0.5)[0]
            else:
                ic, jc = old_div(nlats,2), old_div(nlons,2)

            i0, i1 = ic-old_div(NX,2), ic+old_div(NX,2)
            j0, j1 = jc-old_div(NY,2), jc+old_div(NY,2)

            # Fixing things when the NEWSe domain goes out of bounds

            if i0 < 0:  
                print("\n West edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                i0       = 0

            if j0 < 0:  
                print("\n South edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                j0       = 0

            if debug:
                print("\n %d  %d" % (i0, i1))
                print("\n %d  %d" % (j0, j1))
                print("\n SW Lon:  %f  NE_Lon:  %f" % (f_lons[i0], f_lons[i1]))
                print("\n SW Lat:  %f  NE_Lat:  %f" % (f_lats[j1], f_lats[j0]))
                      
            g_lats    = f_lats[j0:j1:_grid_dict['obs_grid_spacing']]
            g_lons    = f_lons[i0:i1:_grid_dict['obs_grid_spacing']]
            array     = noCoverage * np.ones((nlvls, g_lats.size, g_lons.size))
            g_heights = np.zeros((nlvls,))

        g_heights[n] = float(filenames[n][-30:-25])*1000.    
        
        # APPLY a maximum 3x3 filter
        #reffilt = np.where(f.variables[dbz_name][0,j0:j1,i0:i1] <= missingData, f.variables[dbz_name][0,j0:j1,i0:i1], ndimage.maximum_filter(f.variables[dbz_name][0,j0:j1,i0:i1], size=3, mode='constant', cval=0.0))

        try:
            array[n,...] = f.variables[dbz_name][0,j0:j1:_grid_dict['obs_grid_spacing'],i0:i1:_grid_dict['obs_grid_spacing']]
            #array[n,...] = reffilt[::_grid_dict['obs_grid_spacing'],::_grid_dict['obs_grid_spacing']]
        except:
            array[n,...] = f.variables[dbz_name][j0:j1:_grid_dict['obs_grid_spacing'],i0:i1:_grid_dict['obs_grid_spacing']]
         
        f.close()
 
    ref = ma.MaskedArray(array, mask = (array < missingData+1.))        
    
    return Gridded_Field(filename, data = ref, field = "REFLECTIVITY", zg = g_heights, \
                         lats = g_lats, lons = g_lons, radar_hgt = 0.0, local_time = time, \
                         missingData = missingData ) 
#=========================================================================================
# Extract data from the NCEP files

def assemble_3D_grid_NCEP(filenames, loc=None, debug=False, dbz_name = "MergedReflectivityQC", NX = 300, NY = 300):
    """
    This routine assembles the various elevation angle data from MRMS files being passed 
    in to prepare it for masking application.

    filenames   : list of filenames to process
    loc         : A center lat/lon point to focus the data preparation on.
    dbz_name    : Defaults to the standard variable name within MRMS files.
    NX/NY       : Default grid points to use.

    RETURNS:    Gridded_Field object with the MRMS data assembled into a 3-D array.    

    Code applied by Brian Matilla - July 2024
    """

    levels = _grid_dict['levels']
    nlvls  = len(levels)

    for n, filename in enumerate(filenames):
        
        f = load_mrms_NCEP(filename)
#        try:
#            f = load_mrms_NCEP(filename)
#        except:
#            print(f'Could not open file {filename}')
#            continue

        if debug:
            print("\n Processing file:  %s" % (filename))

        if n == 0:
            nlons  = len(f.lon_0)
            nlats  = len(f.lat_0)
 
            f_lats = f.variables['lat_0'][...]
            f_lons = f.variables['lon_0'][...] - 360. #Convert from full 360 deg. to -180-180 hemispheres.

            missingData = -99.
            noCoverage = -999.
            
            time = datetime.strptime(filenames[n][-24:-9], '%Y%m%d-%H%M%S')

            if loc != None:
                ic     = get_loc(f_lons, loc[1], 0.5)[0]
                jc     = get_loc(f_lats, loc[0], 0.5)[0]
            else:
                ic, jc = old_div(nlats,2), old_div(nlons,2)

            i0, i1 = ic-old_div(NX,2), ic+old_div(NX,2)
            j0, j1 = jc-old_div(NY,2), jc+old_div(NY,2)

            # Fixing things when the NEWSe domain goes out of bounds

            if i0 < 0:  
                print("\n West edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                i0       = 0

            if j0 < 0:  
                print("\n South edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                j0       = 0

            if debug:
                print("\n %d  %d" % (i0, i1))
                print("\n %d  %d" % (j0, j1))
                print("\n SW Lon:  %f  NE_Lon:  %f" % (f_lons[i0], f_lons[i1]))
                print("\n SW Lat:  %f  NE_Lat:  %f" % (f_lats[j1], f_lats[j0]))
                      
            g_lats    = f_lats[j0:j1:_grid_dict['obs_grid_spacing']]
            g_lons    = f_lons[i0:i1:_grid_dict['obs_grid_spacing']]
            array     = noCoverage * np.ones((nlvls, g_lats.size, g_lons.size))
            g_heights = np.zeros((nlvls,))

        g_heights[n] = float(filenames[n][-30:-25])*1000.    
        
        # APPLY a maximum 3x3 filter
        #reffilt = np.where(f.variables[dbz_name][0,j0:j1,i0:i1] <= missingData, f.variables[dbz_name][0,j0:j1,i0:i1], ndimage.maximum_filter(f.variables[dbz_name][0,j0:j1,i0:i1], size=3, mode='constant', cval=0.0))

        try:
            array[n,...] = f.variables[dbz_name][0,j0:j1:_grid_dict['obs_grid_spacing'],i0:i1:_grid_dict['obs_grid_spacing']]
            #array[n,...] = reffilt[::_grid_dict['obs_grid_spacing'],::_grid_dict['obs_grid_spacing']]
        except:
            array[n,...] = f.variables[dbz_name][j0:j1:_grid_dict['obs_grid_spacing'],i0:i1:_grid_dict['obs_grid_spacing']]
         
        f.close()
 
    ref = ma.MaskedArray(array, mask = (array < missingData+1.))        
    
    return Gridded_Field(filename, data = ref, field = "REFLECTIVITY", zg = g_heights, \
                         lats = g_lats, lons = g_lons, radar_hgt = 0.0, local_time = time, \
                         missingData = missingData ) 
#=========================================================================================
# Get the filenames out of the directory

def assemble_3D_grid(filenames, loc=None, debug=False, dbz_name = "MergedReflectivityQC_smoothed", NX = 300, NY = 300):

    levels = _grid_dict['levels']
    nlvls  = len(levels)

    file_list = []

    for l in levels:
        for f in filenames:
            if f.find(l) > -1:
                file_list.append(f)

    for n, filename in enumerate(file_list):

        if debug:
            print("\n Processing file:  %s" % (filename))
      
        if filename[-2:] == "gz":
            cmd = "gunzip -c %s > %s" % (filename, _temp_netcdf_file)
        else:
            cmd = "ln -fs %s  %s" % (filename, _temp_netcdf_file)

        if debug:
            print("\n Running......%s" % (cmd))

        os.system(cmd)
     
        try:
            f = ncdf.Dataset(_temp_netcdf_file, "r")
        except:
            print('Could not open file %s' % _temp_netcdf_file)
            continue
        
        if n == 0:
            nlons  = len(f.dimensions['Lon'])
            nlats  = len(f.dimensions['Lat'])
 
            try:
                f_lats = f.variables['Lat'][...]
                f_lons = f.variables['Lon'][...]
            except:
                f_lats = float(f.Latitude)  - float(f.LatGridSpacing) * np.arange(nlats)
                f_lons = float(f.Longitude) + float(f.LonGridSpacing) * np.arange(nlons)

            missingData = f.MissingData
            
            try:
                time   = datetime.fromtimestamp(f.variables['time'][0])
            except:
                time   = datetime.fromtimestamp(float(f.Time))

            if loc != None:
                ic     = get_loc(f_lons, loc[1], 0.5)[0]
                jc     = get_loc(f_lats, loc[0], 0.5)[0]
            else:
                ic, jc = old_div(nlats,2), old_div(nlons,2)

            i0, i1 = ic-old_div(NX,2), ic+old_div(NX,2)
            j0, j1 = jc-old_div(NY,2), jc+old_div(NY,2)

            # Fixing things when the NEWSe domain goes out of bounds

            if i0 < 0:  
                print("\n West edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                i0       = 0

            if j0 < 0:  
                print("\n South edge of requested domain outside of MRMS grid:  %d " % (i0))
                print("\n Adjusting indices")
                j0       = 0

            if debug:
                print("\n %d  %d" % (i0, i1))
                print("\n %d  %d" % (j0, j1))
                print("\n SW Lon:  %f  NE_Lon:  %f" % (f_lons[i0], f_lons[i1]))
                print("\n SW Lat:  %f  NE_Lat:  %f" % (f_lats[j0], f_lats[j1]))
                      
            g_lats    = f_lats[j0:j1]
            g_lons    = f_lons[i0:i1]
            array     = missingData * np.ones((nlvls, g_lats.size, g_lons.size))
            g_heights = np.zeros((nlvls,))

        g_heights[n] = f.Height    
        
        try:
            array[n,...] = f.variables[dbz_name][0,j0:j1,i0:i1]
        except:
            array[n,...] = f.variables[dbz_name][j0:j1,i0:i1]
         
        f.close()

    # remove tmp.nc file - this can cause problems with multiple users..

        cmd = "rm -f %s" % (_temp_netcdf_file)
        os.system(cmd)

    
    ref = ma.MaskedArray(array, mask = (array < missingData+1.))        
    
    return Gridded_Field(filename, data = ref, field = "REFLECTIVITY", zg = g_heights, \
                         lats = g_lats, lons = g_lons, radar_hgt = 0.0, local_time = time, \
                         missingData = missingData ) 

#=========================================================================================
# DBZ Mask

def dbz_masking(ref, thin_zeros=2, cloc=None, wlat = None, wlon = None):

    nz, ny, nx = ref.data.shape

    # First create zeros
    zgo = _grid_dict['zero_levels']
    nzo = len(zgo)
    zeros = np.ones((nzo, ny, nx), dtype=float)

    zero_dbz = np.ma.masked_where(zeros == 1.0, zeros)

    print(" Initial number of zeros in the field:  %d\n " % (np.sum(zero_dbz.mask==False)))

    if thin_zeros > 0:
        zero_dbz.data[:,::thin_zeros, ::thin_zeros] = 0.0       # Here is where the thinned number of zeros is created
        zero_dbz.mask[:,::thin_zeros, ::thin_zeros] = False     # because where mask == False, we have a zero...

    print(" Number of zeros in the field after thining:  %d\n " % (np.sum(zero_dbz.mask==False)))

    ref.composite = ref.data.data
    ref.temp = zeros

    for ko in np.arange(nzo):
        for kr in np.arange(nz):
            if zgo[ko] == ref.zg[kr]:
                ref.temp[ko,:,:] = ref.data.data[kr,:,:]

    zero_dbz.mask[ ref.temp > _grid_dict['min_dbz_zeros'] ] = True

    print(" Number of zeros in the field after compositive ref mask:  %d\n " % (np.sum(zero_dbz.mask==False)))

    zero_dbz.mask[ ref.temp <= -999. ] = True

    print(" Number of zeros in the field after no coverage ref mask:  %d\n " % (np.sum(zero_dbz.mask==False)))
  
    raw_field = np.where(ref.composite < _grid_dict['min_dbz_zeros'], 0.0, ref.composite)

    hhalo = _grid_dict['halo_footprint']
    vhalo = _grid_dict['vert_halo_fp']
    max_neighbor = (ndimage.maximum_filter(raw_field, size=(vhalo,hhalo,hhalo)) > 0.1)

    for ko in np.arange(nzo):
        for kr in np.arange(nz):
            if zgo[ko] == ref.zg[kr]:
                zero_dbz.mask[ko][max_neighbor[kr] == True] = True

    print(" Number of zeros in the field after halo:  %d\n " % (np.sum(zero_dbz.mask==False)))

    # Create new object so that we can combine later

    obj_zero_dbz = Gridded_Field("zero_dbz", data=zero_dbz, zg=_grid_dict['zero_levels'], radar_hgt=0.0)

    ref.zero_dbz = obj_zero_dbz

    # Now clip the reflectivity

    ref.data.mask[ ref.data < _grid_dict['min_dbz_analysis'] ] = True
                
    if _grid_dict['max_height'] > 0:
        zg3d          = np.repeat(ref.zg, ny*nx).reshape(nz,ny,nx)
        mask1         = (zg3d > _grid_dict['max_height'])  
        mask2         = ref.data.mask
        ref.data.mask = np.logical_or(mask1, mask2)


#    if cloc != None:
#        eln = get_end_point(cloc[0],cloc[1],_grid_dict['ew_radius'],90.0)
#        wln = get_end_point(cloc[0],cloc[1],_grid_dict['ew_radius'],270.0)
#        nlt = get_end_point(cloc[0],cloc[1],_grid_dict['ns_radius'],0.0)
#        slt = get_end_point(cloc[0],cloc[1],_grid_dict['ns_radius'],180.0)

#        lon_2d, lat_2d = np.meshgrid(ref.lons, ref.lats)

#        emask = lon_2d > eln[1]
#        wmask = lon_2d < wln[1]
#        nmask = lat_2d > nlt[0]
#        smask = lat_2d < slt[0]

#        for level in np.arange(ref.data.shape[0]):
#            ref.data.mask[level] = np.logical_or(emask, ref.data.mask[level])
#            ref.data.mask[level] = np.logical_or(wmask, ref.data.mask[level])
#            ref.data.mask[level] = np.logical_or(smask, ref.data.mask[level])
#            ref.data.mask[level] = np.logical_or(nmask, ref.data.mask[level])

#        for level in np.arange(ref.zero_dbz.data.shape[0]):
#            ref.zero_dbz.data.mask[level] = np.logical_or(emask, ref.zero_dbz.data.mask[level])
#            ref.zero_dbz.data.mask[level] = np.logical_or(wmask, ref.zero_dbz.data.mask[level])
#            ref.zero_dbz.data.mask[level] = np.logical_or(smask, ref.zero_dbz.data.mask[level])
#            ref.zero_dbz.data.mask[level] = np.logical_or(nmask, ref.zero_dbz.data.mask[level])

    lx = len(wlat[0,:,0]) - 1
    ly = len(wlat[0,0,:]) - 1

    outer_domain = LatLon(wlat[0,0,0], wlon[0,0,0]), \
        LatLon(wlat[0,0,ly], wlon[0,0,ly]), \
        LatLon(wlat[0,lx,ly], wlon[0,lx,ly]), \
        LatLon(wlat[0,lx,0], wlon[0,lx,0])

    inner_domain = LatLon(wlat[0,_domain_gridpoint_margin,_domain_gridpoint_margin], wlon[0,_domain_gridpoint_margin,_domain_gridpoint_margin]), \
        LatLon(wlat[0,_domain_gridpoint_margin,-_domain_gridpoint_margin], wlon[0,_domain_gridpoint_margin,-_domain_gridpoint_margin]), \
        LatLon(wlat[0,-_domain_gridpoint_margin,-_domain_gridpoint_margin], wlon[0,-_domain_gridpoint_margin,-_domain_gridpoint_margin]), \
        LatLon(wlat[0,-_domain_gridpoint_margin,_domain_gridpoint_margin], wlon[0,-_domain_gridpoint_margin,_domain_gridpoint_margin])

    #print(f"Grid point border margin: {_domain_gridpoint_margin}")
    print(f"Bottom left outer domain: {outer_domain[0]}")
    print(f"Bottom right outer domain: {outer_domain[1]}")
    print(f"Top right outer domain: {outer_domain[2]}")
    print(f"Top left outer domain: {outer_domain[3]}")

    print(f"Bottom left inner domain: {inner_domain[0]}")
    print(f"Bottom right inner domain: {inner_domain[1]}")
    print(f"Top right inner domain: {inner_domain[2]}")
    print(f"Top left inner domain: {inner_domain[3]}")

    # Remove everything outside of the domain; remove anything in the border that is != 0
    for j in np.arange(ny):
        for i in np.arange(nx):
            point = LatLon(ref.lats[j], ref.lons[i])
            if not isenclosedBy(point, outer_domain) :
                ref.data.mask[:,j,i] = True
                ref.zero_dbz.data.mask[:,j,i] = True
            elif not isenclosedBy(point, inner_domain) :
                ref.data.mask[:,j,i] = np.logical_or(ref.data[:,j,i] != 0, ref.data.mask[:,j,i])
                ref.zero_dbz.data.mask[:,j,i] = np.logical_or(ref.zero_dbz.data[:,j,i] != 0, ref.zero_dbz.data.mask[:,j,i])

    print(" Size of REF mask after domain edge buffer mask: %d" % np.sum(ref.data.mask == False))
            
    return ref

#=========================================================================================
# Calculate lat-lon given distance and center lat-lon
def get_end_point(latitude, longitude, distance, bearing):
    # Earth's radius in kilometers
    radius = 6371.0

    # Convert the latitude and longitude to radians
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)

    # Convert the bearing to radians
    rad_bearing = math.radians(bearing)

    # Calculate the angular distance
    angular_distance = distance / radius

    # Calculate the latitude of the destination point
    lat2 = math.asin(math.sin(lat1) * math.cos(angular_distance) +
                     math.cos(lat1) * math.sin(angular_distance) * math.cos(rad_bearing))

    # Calculate the longitude of the destination point
    lon2 = lon1 + math.atan2(math.sin(rad_bearing) * math.sin(angular_distance) * math.cos(lat1),
                             math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2))

    # Convert the latitude and longitude back to degrees
    lat2 = math.degrees(lat2)
    lon2 = math.degrees(lon2)

    return lat2, lon2

###########################################################################################
#
# Read environment variables for plotting a shapefile

def plot_shapefiles(map, shapefiles=None, color='k', linewidth=0.5, ax=None, \
                    states=True,                                             \
                    counties=False,                                          \
                    meridians=False,                                         \
                    parallels=False):

    if shapefiles:
        try:
            shapelist = os.getenv(shapefiles).split(":")

            if len(shapelist) > 0:

                for item in shapelist:
                    items      = item.split(",")
                    shapefile  = items[0]
                    color      = items[1]
                    linewidth  = items[2]

                    s = map.readshapefile(shapefile,'myshapes',drawbounds=False)

                    for shape in map.counties:
                        xx, yy = list(zip(*shape))
                        map.plot(xx, yy, color=color, linewidth=linewidth, ax=ax, zorder=4)

        except OSError:
            print("PLOT_SHAPEFILES:  NO SHAPEFILE ENV VARIABLE FOUND ")
            
    if counties:
        map.drawcounties(ax=ax, linewidth=0.25, color='0.5', zorder=5)

    if states:
        map.drawstates(ax=ax, linewidth=0.75, color='k', zorder=5)
   
    if parallels:
        map.drawparallels(list(range(10,80,1)),    labels=[1,0,0,0], linewidth=0.5, ax=ax)
    else:
        map.drawparallels(list(range(10,80,1)),    labels=[1,0,0,0], linewidth=0.001, ax=ax)

    if meridians:
        map.drawmeridians(list(range(-170,-10,1)), labels=[0,0,0,1], linewidth=0.5, ax=ax)
    else:
        map.drawmeridians(list(range(-170,-10,1)), labels=[0,0,0,1], linewidth=0.001, ax=ax)
            
########################################################################
#
# Create processed reflectivity data  

def plot_grid(ref, sweep, plot_filename=None, shapefiles=None, interactive=False, cntrpoint=[0,0], width = 0, height = 0):
  
# Set up colormaps 

  from matplotlib.colors import BoundaryNorm
   
  cmapr = _ref_ctable
  cmapr.set_bad('white',1.0)
  cmapr.set_under('white',1.0)

  normr = BoundaryNorm(_ref_scale, cmapr.N)
  
# Create png file label

  if plot_filename == None:
      print("\n Prep_MRMS.plot_grid:  No output file name is given, writing to %s" % "RF_...png")
      filename = "RF_%2.2d_plot.%s" % (sweep, _plot_format)
  else:
       filename = "%s.%s" % (plot_filename, _plot_format)

  fig, axes = plt.subplots(2, 1, sharey=True, figsize=(10,18))

# Set up coordinates for the plots

  ref_data = ref.data[sweep]

  bgmap = Basemap(projection='lcc', width=width, height=height, \
                  lat_0=cntrpoint[0], lon_0=cntrpoint[1], resolution='i', area_thresh=10., ax=axes[0])
                  
# lon_2d, lat_2d = bgmap.makegrid(nx, ny)
  lon_2d, lat_2d = np.meshgrid(ref.lons, ref.lats)
  xg, yg = bgmap(lon_2d, lat_2d)

# CAPPI REFLECTVITY PLOT

  if shapefiles:
      plot_shapefiles(bgmap, shapefiles=shapefiles, counties=_plot_counties, ax=axes[0])
  else:
      plot_shapefiles(bgmap, counties=_plot_counties, ax=axes[0])

  ref_data = ref.data[sweep]

  im1 = bgmap.contourf(xg, yg, ref_data, levels= _ref_scale, cmap=cmapr, norm=normr, \
                       vmin = _ref_min_plot, vmax = _ref_scale.max(), ax=axes[0])

  cbar = bgmap.colorbar(im1,location='right')
  cbar.set_label('Reflectivity (dBZ)')
  axes[0].set_title('Reflectivity at Height:  %4.1f km' % (0.001*ref.zg[sweep]))
  at = AnchoredText("Max dBZ: %4.1f" % (ref_data.max()), loc=4, prop=dict(size=10), frameon=True,)
  at.patch.set_boxstyle("round,pad=0.,rounding_size=0.2")
  axes[0].add_artist(at)

# COMPOSITE PLOT
  ref_mask = (ref.data.mask == False)
  ref_mask=np.bitwise_or.reduce(ref.data.mask, axis=0)  

  masked_y = np.ma.masked_where(ref_mask == False, ref.data.max(axis=0))

  zero_dbz = ref.zero_dbz.data

  bgmap = Basemap(projection='lcc', width=width, height=height, \
                  lat_0=cntrpoint[0], lon_0=cntrpoint[1], resolution='i', area_thresh=10.0, ax=axes[1])

  if shapefiles:
      plot_shapefiles(bgmap, shapefiles=shapefiles, counties=_plot_counties, ax=axes[1])
  else:
      plot_shapefiles(bgmap, counties=_plot_counties, ax=axes[1])
 

  im1 = bgmap.contourf(xg, yg, masked_y, levels= _ref_scale, cmap=cmapr, norm=normr, \
                       vmin = _ref_min_plot, vmax = _ref_scale.max(), ax=axes[1])

  cbar = bgmap.colorbar(im1,location='right')
  cbar.set_label('Reflectivity (dBZ)')
  axes[1].set_title('Composite Reflectivity') 
  at = AnchoredText("Max dBZ: %4.1f" % (ref_data.max()), loc=4, prop=dict(size=10), frameon=True,)
  at.patch.set_boxstyle("round,pad=0.,rounding_size=0.2")
  axes[1].add_artist(at)

# Plot zeros as "o"

  if zero_dbz.mask.any() == True:
      r_mask = (zero_dbz.mask == False)
      # zero's are diff at various levels... plot where it's 0 through the column
      r_mask=np.bitwise_and.reduce(r_mask, axis=0)  
      bgmap.scatter(xg[r_mask], yg[r_mask], s=15, facecolors='none', \
                    edgecolors='k', alpha=0.3, ax=axes[1]) 
      print("\n Prep_MRMS.plot_grid:  Number of zero reflectivity obs found:  %d" % np.sum(r_mask) )
           
# Get other metadata....for labeling

  time_text = ref.time.strftime('%Y-%m-%d %H:%M')

  title = '\nDate:  %s   Time:  %s' % (time_text[0:10], time_text[10:19])

  plt.suptitle(title, fontsize=14)

  plt.savefig(filename)

  if interactive:  plt.show()
  
#=========================================================================================
# Defines the data frame for each observation type
#
def obs_seq_xarray(len):
        
    return (np.recarray(len, 
                    dtype = [
                             ('value',               'f8'),
                             ('lat',                 'f8'),
                             ('lon',                 'f8'),
                             ('height',              'f8'),
                             ('error_var',           'f4'),
                             ('utime',               'f8'),          
                             ('date',                'S128'),
                             ('day',                 'i8'),
                             ('second',              'i8'),
                             ('platform_lat',        'f8'),
                             ('platform_lon',        'f8'),
                             ('platform_hgt',        'f8'),
                             ('platform_dir1',       'f8'),
                             ('platform_dir2',       'f8'),
                             ('platform_dir3',       'f8'),
                             ('platform_nyquist',    'f8')
                            ]), \
                         {
                           'lat':   ["degrees", "latitude of observation"],
                           'lon':   ["degrees", "longitude of observation (deg. west)"],
                           'height':["meters",  "height above sea level"],
                           'utime': ["seconds since 1970-01-01 00:00:00", "time of observation"],
                           'date':  ["", "date and time of obsevation"]
                          })
                                 
#=========================================================================================
def write_obs_seq_xarray(field, filename=None, obs_error=None, 
                         zero_dbz_obtype=True,
                         levels = [], QC_info=[], zero_levels=[], volume_name=None):

    
   _time_units    = 'seconds since 1970-01-01 00:00:00'
   _calendar      = 'standard'

   if filename == None:
       print("\n WRITE_DATA_XARRAY:  No output file name is given, writing to %s" % "obs_seq.nc")
       filename = "obs_seq.nc"
   else:
       dirname = os.path.dirname(filename)
       basename = "%s.nc" % (filename)
       filename =  basename
             
   if obs_error == None:
       obs_errors = { 'reflectivity': 5.0, '0reflectivity': 5.0 } 

   _stringlen     = 8
   _datelen       = 19
     
# Extract data.city data
  
   data          = field.data
   lats          = field.lats
   lons          = field.lons
   hgts          = field.zg[:]

   try:
       nz, ny, nx     = data.shape
       if len(levels) == 0:
           nz2        = nz + len(zero_levels)
       else:
           nz2        = len(levels) + len(zero_levels)
           
       new_data       = np.ma.zeros((nz2, ny, nx), dtype=float)
       new_hgts       = np.ma.zeros((nz2), dtype=float)
       
       for n, k in enumerate(levels):
           new_data[n,...] = data[n]
           new_hgts[n]     = hgts[n]
       
       for n, lvl in enumerate(zero_levels):
           new_data[nz+n,...] = field.zero_dbz.data[n]
           new_hgts[nz+n] = lvl
           
       data = new_data
       hgts = new_hgts
       print("\n write_DART_ascii:  0-DBZ separate type added to reflectivity output\n")
       
   except AttributeError:
       print("\n write_DART_ascii:  No 0-DBZ separate type found\n")
       
# Use the time of the volume

   secs    = ncdf.date2num(field.local_time, units = _time_units)   
   
# Retain DART time stamps

   days    = ncdf.date2num(field.local_time, units = "days since 1601-01-01 00:00:00")
   seconds = int(86400.*(days - np.floor(days)))  
  
   print("\n -->  Writing %s as the radar file..." % (filename))
    
   nobs = np.sum(data.mask[:]==False)
   print("\n --> Number of good observations for xarray:  %d" % nobs)
   
   # Create numpy rec array that can be converted to a pandas table.

   out, attributes = obs_seq_xarray(nobs)

   nobs = 0
   nobs_clearair = 0
   
   # There is a far better way to do this but this is fast enough for now...

   for k in np.arange(nz2): 
       for j in np.arange(ny):
           for i in np.arange(nx):
         
               if data.mask[k,j,i] == True:   # bad values
                    pass     
               else:          
                   out.value[nobs]              = data[k,j,i]
                   
                   if out.value[nobs] < _grid_dict['min_dbz_zeros']:                   
                       out.error_var[nobs]      = obs_error[1]**2
                       nobs_clearair += 1                
                   else:
                       out.error_var[nobs]      = obs_error[0]**2
                       
                   out.lon[nobs]                = lons[i]
                   out.lat[nobs]                = lats[j]
                   out.height[nobs]             = hgts[k]
                   out.date[nobs]               = field.local_time
                   out.utime[nobs]              = secs
                   out.day[nobs]                = days
                   out.second[nobs]             = seconds
         
                   nobs = nobs + 1
                   
                   
   print("\n -----> Total non-zero Obs: %d  0DBZ Obs: %d" % (nobs-nobs_clearair, nobs_clearair))           
      
   # Create an xarray dataset for file I/O
   xa = xr.Dataset(pd.DataFrame.from_records(out))
   
   # reset index to be a master index across all obs
   xa = xa.rename({'dim_0': 'index'})
   
   # Write the xarray file out (this is all there is, very nice guys!)
   xa.to_netcdf(filename, mode='w')
   xa.close()
   
   # Add attributes to the files
    
   fnc = ncdf.Dataset(filename, mode = 'a')
   fnc.history = "Created " + datetime.today().strftime("%Y%m%d_%H%M")
   fnc.version = "Version 1.0a by Lou Wicker and Thomas Jones (NSSL)"
   if volume_name != None:
       fnc.version = "Created from the MRMS radar volume:  %s" % volume_name
    
   for key in list(attributes.keys()):
       fnc.variables[key].units = attributes[key][0]
       fnc.variables[key].description = attributes[key][1]

   fnc.sync()  
   fnc.close()

def run(options):
   tMAIN = timeit.time()
   
   if options.thin > 1:
       _grid_dict['thin_grid'] = options.thin

   if options.realtime != None:
       year   = int(options.realtime[0:4])
       mon    = int(options.realtime[4:6])
       day    = int(options.realtime[6:8])
       hour   = int(options.realtime[8:10])
       minute = int(options.realtime[10:12])
       a_time = datetime(year, mon, day, hour, minute, 0)

#-------------------------------------------------------------------------------
# Print all current options to a file
   with open("options.txt", "w") as f:
       for name, value in vars(options).items():
           f.write(f"{name} = {value}\n")
   import configparser
   config = configparser.ConfigParser()

   config["OPTIONS"] = {}

   for name, value in vars(options).items():
       config["OPTIONS"][name] = str(value)

   with open("options.cfg", "w") as f:
       config.write(f)

# if realtime, now find the file created within _dt_window of analysis time

   if options.realtime != None:

       try:
           #in_filenames = Get_Closest_Elevations_Local(a_time, _grid_dict, _dt_window)
           in_filenames = Get_Closest_Elevations_NCEP(a_time, _grid_dict, _dt_window)
       except:
           print("\n Prep_MRMS: NCEP data unavailable. Attempting with AWS")
           in_filenames = Get_Closest_Elevations_AWS(a_time, _grid_dict, _dt_window)

       try:
           print("\n Prep_MRMS:  number of levels found:  %s\n" % (len(in_filenames)))
           print("\n Prep_MRMS:  processing first file:  %s\n" % (in_filenames[0]))
           print(" Prep_MRMS:  processing last file:  %s\n" % (in_filenames[-1]))
           rlt_filename = "%s_%s" % ("obs_seq_RF", a_time.strftime("%Y%m%d_%H%M"))
       except:
           print("\n============================================================================")
           print("\n Prep_MRMS cannot find a RF file between [%2.2d,%2.2d] min of %s, exiting" % 
                (_dt_window[0], _dt_window[1], a_time.strftime("%Y%m%d%H%M")))
           print("\n============================================================================")
           return 1

   else:
       in_filenames = Get_Closest_Elevations_Local(a_time, _grid_dict, _dt_window)
       #in_filenames = Get_Closest_Elevations_AWS(a_time, _grid_dict, _dt_window)
       out_filenames = []
       print("\n Prep_MRMS:  Processing %d files in the directory:  %s\n" % (len(in_filenames), options.dir))
       print("\n Prep_MRMS:  First file is %s\n" % (in_filenames[0]))
       print("\n Prep_MRMS:  Last  file is %s\n" % (in_filenames[-1]))
   
 # Make sure there is a directory to write files into....


   if not os.path.exists(options.out_dir):
       try:
           os.makedirs(options.out_dir)
       except:
           print("\n**********************   FATAL ERROR!!  ************************************")
           print("\n PREP_GRID3D:  Cannot create output dir:  %s\n" % options.out_dir)
           print("\n**********************   FATAL ERROR!!  ************************************")      
           return 1

   if options.realtime != None:
       out_filename = rlt_filename
       time         = a_time
       print(" Out filename:  %s\n" % out_filename)
   else:
       file = in_filenames[0]
       str_time     = "%s_%s" % (os.path.basename(file)[-27:-17], os.path.basename(file)[-16:-10])
       prefix       = "RF_%s" % str_time
       out_filename = prefix
       time         = datetime.strptime(file[-24:-9], "%Y%m%d-%H%M%S")
       print(" Out filename:  %s\n" % out_filename)


   out_path = os.path.join(options.out_dir, time.strftime("%Y%m%d"))
   if not os.path.exists(out_path):
       os.makedirs(out_path)  
   out_filename = os.path.join(out_path, out_filename)

   wrfin = ncdf.Dataset(options.domain_path, mode = 'r')
   wlat = wrfin.variables['XLAT' if 'XLAT' in wrfin.variables else 'XLAT_M'][:]
   wlon = wrfin.variables['XLONG' if 'XLONG' in wrfin.variables else 'XLONG_M'][:]
   NX = int(len(wlat[0,:,0])*(wrfin.getncattr('DX')/1000.)*1.4)     # Factor of 1.4 applied to account for northern U.S. clipping
   NY = int(len(wlat[0,0,:])*(wrfin.getncattr('DY')/1000.)*1.4)     # Factor of 1.4 applied to account for northern U.S. clipping

   try:
       ref_obj = assemble_3D_grid_NCEP(in_filenames, loc=options.loc, debug=_debug, dbz_name=options.refl_var_name, NX = NX, NY = NY)
   except:
       ref_obj = assemble_3D_grid_AWS(in_filenames, loc=options.loc, debug=_debug, dbz_name=options.refl_var_name, NX = NX, NY = NY)

   ref_obj.time = a_time
   ref_obj = dbz_masking(ref_obj, thin_zeros=_grid_dict['thin_zeros'], wlat=wlat, wlon=wlon) #cloc=options.loc

   if options.write == True:  
   
       tNCDF = timeit.time()
       ret = write_obs_seq_xarray(ref_obj, filename=out_filename, levels=np.arange(len(_grid_dict['levels'])),
                               obs_error=[_grid_dict['reflectivity'], _grid_dict['0reflectivity']], 
                               QC_info=_grid_dict['QC_info'], zero_levels=_grid_dict['zero_levels'], 
                               volume_name=rlt_filename)
       print("\n --> Time for netCDF write: {} seconds".format(timeit.time() - tNCDF))
       
       tDART = timeit.time()
       ret = mrms_write_DART_ascii(ref_obj, filename=out_filename, levels=np.arange(len(_grid_dict['levels'])),
                              obs_error=[_grid_dict['reflectivity'], _grid_dict['0reflectivity']], 
                              QC_info=_grid_dict['QC_info'], zero_levels=_grid_dict['zero_levels'])
       print("\n --> Time for DART write: {} seconds".format(timeit.time() - tDART))
   
   if options.plot != '':
       tPLOT = timeit.time()
       fsuffix = "OpMRMS_%s" % (ref_obj.time.strftime('%Y%m%d_%H%M'))
       plot_filename = os.path.join(out_path, fsuffix)
       plot_grid(ref_obj, int(options.plot), plot_filename = plot_filename, cntrpoint=options.loc, width = 20000 + (len(wlat[0,:,0])*wrfin.getncattr('DX')), height = 20000 + (len(wlat[0,0,:])*wrfin.getncattr('DY')))
       print("\n --> Time to plot image: {} seconds".format(timeit.time() - tPLOT))
   
   print("\n ----> Time for MRMS operations: {} seconds".format(timeit.time() - tMAIN))
   print("\n PROGRAM MRMS COMPLETED\n")    
   return 0

#-------------------------------------------------------------------------------
# Main function defined to return correct sys.exit() calls

def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = OptionParser()
    parser.add_option("-d", "--dir",   dest="dir",    default=None,  type="string", help = "Directory where MRMS files are")

    parser.add_option(      "--realtime",  dest="realtime",   default=None,  \
                help = "Boolean flag to uses this YYYYMMDDHHMM time stamp for the realtime processing")

    parser.add_option("-g", "--grep",  dest="grep",   default="*.netcdf.gz", type="string", help = "Pattern grep, [*.nc, *VR.h5]")

    parser.add_option("-w", "--write", dest="write",   default=False, \
                            help = "Boolean flag to write DART ascii file", action="store_true")
                            
    parser.add_option("-o", "--out",      dest="out_dir",  default="ref_files",  type="string", \
                            help = "Directory to place output files in")
                            
    parser.add_option("-p", "--plot",      dest="plot",      default=-1,  type="int",      \
                        help = "Specify a number between 0 and 20 to plot reflectivity")

    parser.add_option(     "--loc",      dest="loc",  type="float", default=None, nargs = 2,      \
                        help = "Specify location of NEWSe grid center (lat,lon)")
                    
                    
    parser.add_option(      "--thin",      dest="thin",      default=1,  type="int",      \
                        help = "Specify a number between 2 and 5 thin reflectivity")
                    
    (options, args) = parser.parse_args()

    return run(options)

#-------------------------------------------------------------------------------

#-------------------------------------------------------------------------------
# Main program for testing...
#
if __name__ == "__main__":
    sys.exit(main())
