import netCDF4 as ncdf
import os, re
import numpy as np
from pyart.io.common import make_time_unit_str
import datetime
import pyart
from pyart.config import FileMetadata
from pyart.config import get_metadata
from pyart.core.radar import Radar
from ..Config import AppConfiguration
from ..utils.SparseRadialSet import decompress_sparse
import matplotlib.pyplot as plt

_debug_ = False

import os

def debug_path(label, path):
    exists = os.path.exists(path)
    status = "EXISTS" if exists else "MISSING"
    print(f"[DEBUG PATH] [{status}] {label}: {path}", flush=True)
    return path

# Updated helper functions wrapped with debugging:

def __get_radar_time_path__(radar, run_time, rass_input):
    p = os.path.join(rass_input.format(run_time.strftime("%Y%m%d")), radar)
    return debug_path("Radar Time Path", p)

def __get_path_reflectivity__(radar, run_time, rass_input, rass_input_refl):
    p = os.path.join(__get_radar_time_path__(radar, run_time, rass_input), rass_input_refl)
    return debug_path("Reflectivity Path", p)

def __get_path_reflectivity_tilt__(radar, run_time, tilt, rass_input, rass_input_refl):
    p = os.path.join(__get_path_reflectivity__(radar, run_time, rass_input, rass_input_refl), tilt)
    return debug_path("Reflectivity Tilt Path", p)

def __get_path_velocity__(radar, run_time, rass_input, rass_input_vel):
    p = os.path.join(__get_radar_time_path__(radar, run_time, rass_input), rass_input_vel)
    return debug_path("Velocity Path", p)

def __get_path_velocity_tilt__(radar, run_time, tilt, rass_input, rass_input_vel):
    p = os.path.join(__get_path_velocity__(radar, run_time, rass_input, rass_input_vel), tilt)
    return debug_path("Velocity Tilt Path", p)

_include_tilts = [] # empty list will plot all

def __get_radar_time_path__(radar, run_time, rass_input): return os.path.join(rass_input.format(run_time.strftime("%Y%m%d")), radar)

def __get_path_reflectivity__(radar, run_time, rass_input, rass_input_refl): return os.path.join(__get_radar_time_path__(radar, run_time, rass_input), rass_input_refl)

def __get_path_reflectivity_tilt__(radar, run_time, tilt, rass_input, rass_input_refl): return os.path.join(__get_path_reflectivity__(radar, run_time, rass_input, rass_input_refl), tilt)

def __get_path_velocity__(radar, run_time, rass_input, rass_input_vel): return os.path.join(__get_radar_time_path__(radar, run_time, rass_input), rass_input_vel)

def __get_path_velocity_tilt__(radar, run_time, tilt, rass_input, rass_input_vel): return os.path.join(__get_path_velocity__(radar, run_time, rass_input, rass_input_vel), tilt)

def find_nearest_index(array, value):
    array = np.asarray(array)
    idx = (np.abs(array - value)).argmin()
    return idx

def load_mrms_ppi(fdict, input_refl, input_vel, **kwargs):
    """
    Read multiple field sweeps from an MRMS radar file NetCDF file.
    
    Input parameters
    ----------------
    fdict : (list)  --> list of dicts [{file: file1, ncvar: "Reflectivity", pvar: "reflecitity"},
                                       {file: file2, ncvar: "Velocity",     pvar: "corrected_velocity"}]
               
       filename : (str) --> name of netCDF MRMS file to read from
       ncvar :    (str) --> name of variable to read from that file
       pvar :     (str) --> mapped name of ncvar into pyART
    
    Returns
    -------
    radar : Radar  --> pyArt radar object
    
    TODO:  For a given set of tilts, all the tilts will be set to the smallest number of gates in the
           tilts.  The data structure is not quite correct.

    """
    # Loop over files to find the dimensions of the data.
    
    n_gates = [1192]  # choose this to be the maximum number of gates we ever need.
    n_rays  = []
    n_elev  = []
    gates   = []
    
    # print(f"length of {len(fdict)}")
        
    

    # if _debug > 0:
    #     print(n_gates)
    #     print('LOAD_PPI --> Number of files to read: %d' % len(fdict))
    #     print('LOAD_PPI --> _mygate: %d' % _mygate)
    #     print(f'LOAD_PPI --> n_rays: {n_rays}')
        
        
    # if we get this far, go ahead get to creating the radar object


    # this does not do anything yet except uses the object to create other objects
    # the default configuration is cfradial - for later.
    
    filemetadata = FileMetadata('cfradial')  

    # create all the objects needed below
    
    _latitude              = filemetadata('latitude')
    _longitude             = filemetadata('longitude')
    _altitude              = filemetadata('altitude')
    _metadata              = filemetadata('metadata')
    _sweep_start_ray_index = filemetadata('sweep_start_ray_index')
    _sweep_end_ray_index   = filemetadata('sweep_end_ray_index')
    _sweep_number          = filemetadata('sweep_number')
    
    _sweep_mode            = filemetadata('sweep_mode')
    _fixed_angle           = filemetadata('fixed_angle')
    _time                  = filemetadata('time')
    _elevation             = filemetadata('elevation')
    _azimuth               = filemetadata('azimuth')
    _range                 = filemetadata('range')
    
    _scan_type             = 'other'

    _fields                = {}  # dict to hold data



    # loop through files..


    refl = next(filter(lambda z: z['variables'][0]['ncvar'] == input_refl, fdict))
    vel = next(filter(lambda z: z['variables'][0]['ncvar'] == input_vel, fdict))

    refl_file  = ncdf.Dataset(refl['file'])
    vr_file  = ncdf.Dataset(vel['file'])

    # print(refl_file.variables['Azimuth'][:])
    # print(vr_file.variables['Azimuth'][:])
    # exit()

    n_gates.append(len(vr_file.dimensions['Gate']))
    n_gates.append(len(refl_file.dimensions['Gate']))
    n_rays.append(len(vr_file.dimensions['Azimuth']))
    n_elev.append(vr_file.Elevation)

    _mygate = min(n_gates)


    start_time                     = datetime.datetime.utcfromtimestamp(vr_file.Time)
    _time['data']                  = np.array([vr_file.FractionalTime][:])
    _time['units']                 = make_time_unit_str(start_time)
    _instr_params = {}
    #_time['data']                 = np.array(ncfile.variables['RadialTime'][:]) 

    _latitude['data']              = vr_file.Latitude
    _longitude['data']             = vr_file.Longitude
    _altitude['data']              = np.array([vr_file.Height], 'float64')
    #print(_altitude['data'])
    _range['data']                 = vr_file.RangeToFirstGate + vr_file.variables['GateWidth'][0] * (np.arange(_mygate-1) + 0.5)
    #print(_range['data'])
    _sweep_mode['data']            = np.array(['ppi'])
    
    _azimuth['data']               = np.array(vr_file.variables['Azimuth'][:])

    _fixed_angle['data']           = np.array(n_elev)
    _elevation['data']             = np.array(n_rays[0]*[n_elev[0]])

    _sweep_number['data']          = np.arange(len(fdict), dtype='int32')

    # print(_sweep_number['data']  )
    _instr_params = {'nyquist_velocity': {'data': [float(vr_file.getncattr('Nyquist_Vel-value'))] }}

    _sweep_start_ray_index['data'] = np.cumsum(np.append([0], n_rays[:-1]).astype('int32'))
    _sweep_end_ray_index['data']   = np.cumsum(n_rays).astype('int32') - 1
    
    # copy meta data once

    metadata_mapping = {
                        'vcp-value': 'vcp-value',
                        'radarName-value': 'instrument_name',
                        }
    
    #print(ncfile.variables['Azimuth'][:])
    # print(_range)
    # print(_sweep_start_ray_index)
    # print(_sweep_end_ray_index)

    for netcdf_attr, metadata_key in metadata_mapping.items():
        if netcdf_attr in vr_file.ncattrs():
            print(metadata_key, vr_file.getncattr(netcdf_attr))
            _metadata[metadata_key] = vr_file.getncattr(netcdf_attr)



    def load_data(ncfile, vars, _fields, shift = None):
        for varset in vars:
            pvar                       = varset['pvar']
            ncvar                      = varset['ncvar']
            _dict         = get_metadata(pvar)

            if ncfile.DataType[0:6] == 'Sparse':
                print(f"Loading as Sparse")
                decompressed = decompress_sparse(ncfile, method = "f")
                if decompressed is not None: _dict['data'] = np.ma.array(decompressed[:,0:_mygate-1])
                else: continue
            else:
                print(f"Loading as Other")
                if len(ncfile.variables[ncvar].shape) == 2:
                    _dict['data'] = np.ma.array(ncfile.variables[ncvar][:,0:_mygate-1])
                else: 
                    _dict['data'] = np.ma.array(ncfile.variables[ncvar][:])

            if 'MissingData' in ncfile.ncattrs():
                _dict['data'][_dict['data'] == ncfile.MissingData] = np.ma.masked

            if 'RangeFolded' in ncfile.ncattrs():
                _dict['data'][_dict['data'] == ncfile.RangeFolded] = np.ma.masked
                
            _dict['units'] = ncfile.getncattr('Unit-value')

            #print(_dict['data'][:,0])

            if shift != None:
                _dict['data'] = np.roll(_dict['data'], -1 * shift, 0)

            #print(_dict['data'][:,0])

            _fields[pvar] = _dict

            #print(_dict['data'].shape)

    # sometimes the gates do not match, use the min available
    print(f"MIN GATES: {_mygate}")

    target_index = find_nearest_index(vr_file.variables['Azimuth'][:], 0)

    load_data(vr_file, vel['variables'], _fields)

    rotate_index = find_nearest_index(refl_file.variables['Azimuth'][:], 0)

    rotate_by = target_index - rotate_index

    print(f"TARGET INDEX: {target_index}")
    print(f"ROTATE INDEX: {rotate_index}")
    print(f"ROTATE BY (TARGET-ROTATE): {rotate_by}")

    load_data(refl_file, refl['variables'], _fields, rotate_by * -1)

    # With elevation and azimuth in the radar object, lets recalculate
    # gate latitude, longitude and altitude,

    if _debug_:
        print('LOAD_PPI:  Volume mean time:  ',start_time)
        #print('LOAD_PPI: final field dictionary: \n', _fields.shape)
        print('LOAD_PPI: ngates.shape: ', _range['data'].shape)
        print('LOAD_PPI: nrays.shape: ', _azimuth['data'].shape)
        print('LOAD_PPI: sweep_start/stop: ', _sweep_start_ray_index['data'], _sweep_end_ray_index['data'])
        print('LOAD_PPI: sweeps: ', _sweep_number['data'])
    

    r = Radar( _time, _range, _fields, _metadata, _scan_type,                    \
                  _latitude, _longitude, _altitude,                                 \
                  _sweep_number, _sweep_mode, _fixed_angle, _sweep_start_ray_index, \
                  _sweep_end_ray_index,                                              \
                  _azimuth, _elevation, instrument_parameters=_instr_params)
    
    return r

def getProducts(radar, run_time, tilt):
    """
        Returns an array of dictionaries in the form of
        [{'file': '/file/path.netcdf', 'ncvar': 'Velocity', 'pvar': 'corrected_velocity'},
        {'file': '/file/path.netcdf', 'ncvar': 'ReflectivityQC', 'pvar': "reflectivity"}]
    """
    settings = AppConfiguration.get()

    vr_files = list_abs_files(__get_path_velocity_tilt__(radar, run_time, tilt, settings.rass_input, settings.rass_input_vel)) + list_abs_files(__get_path_velocity_tilt__(radar, run_time - datetime.timedelta(days = 1), tilt, settings.rass_input, settings.rass_input_vel))

    refl_files = list_abs_files(__get_path_reflectivity_tilt__(radar, run_time, tilt, settings.rass_input, settings.rass_input_refl)) + list_abs_files(__get_path_reflectivity_tilt__(radar, run_time - datetime.timedelta(days = 1), tilt, settings.rass_input, settings.rass_input_refl))

    def getNearestFile(time, files):
        win = int(settings.rass_window)
        #TODO: clean this up. initial lambda should do the filter check and return None if beyond window for less looping
        files = map(lambda x: (abs((time - datetime.datetime.strptime(os.path.splitext(os.path.basename(x))[0], "%Y%m%d-%H%M%S")).total_seconds()), x), files)
        s = sorted(files, key = lambda x: x[0])
        s = list(filter(lambda x: x[0] <= win, s))
        return s[0] if len(s) > 0 else None

    v = getNearestFile(run_time, vr_files)
    if v is not None:
        yield {'file': v[1], 'variables': [{'ncvar': 'Velocity', 'pvar': 'velocity'}]} #, {'ncvar': 'NyquistVelocity', 'pvar': 'nyquist_velocity'}

    r = getNearestFile(run_time, refl_files)
    if r is not None:
        yield {'file': r[1], 'variables': [{'ncvar': settings.rass_reflectivity_var, 'pvar': "reflectivity"}]}
        

def list_rel_files(path):
    if os.path.exists(path):
        return os.listdir(path)
    else: return []

def list_abs_files(path):
    if os.path.exists(path):
        return [os.path.join(path, a) for a in os.listdir(path)]
    else: return []

import re
import datetime
import os

def getTiltProducts(radar, run_time):
    settings = AppConfiguration.get()

    # Construct the 4 search paths
    vel_path_curr = __get_path_velocity__(radar, run_time, settings.rass_input, settings.rass_input_vel)
    vel_path_prev = __get_path_velocity__(radar, run_time - datetime.timedelta(days=1), settings.rass_input, settings.rass_input_vel)

    refl_path_curr = __get_path_reflectivity__(radar, run_time, settings.rass_input, settings.rass_input_refl)
    refl_path_prev = __get_path_reflectivity__(radar, run_time - datetime.timedelta(days=1), settings.rass_input, settings.rass_input_refl)

    # Diagnostic printing for base directories
    print(f"\n[DEBUG getTiltProducts] Radar: {radar} | Time: {run_time}", flush=True)
    print(f"  -> VEL Dir (Curr) : [{ 'EXISTS' if os.path.exists(vel_path_curr) else 'MISSING' }] {vel_path_curr}", flush=True)
    print(f"  -> VEL Dir (Prev) : [{ 'EXISTS' if os.path.exists(vel_path_prev) else 'MISSING' }] {vel_path_prev}", flush=True)
    print(f"  -> REFL Dir (Curr): [{ 'EXISTS' if os.path.exists(refl_path_curr) else 'MISSING' }] {refl_path_curr}", flush=True)
    print(f"  -> REFL Dir (Prev): [{ 'EXISTS' if os.path.exists(refl_path_prev) else 'MISSING' }] {refl_path_prev}", flush=True)

    # Gather files
    vel_curr_files = list_rel_files(vel_path_curr)
    vel_prev_files = list_rel_files(vel_path_prev)
    vel_tilts = vel_curr_files + vel_prev_files

    refl_curr_files = list_rel_files(refl_path_curr)
    refl_prev_files = list_rel_files(refl_path_prev)
    refl_tilts = refl_curr_files + refl_prev_files

    print(f"  -> Found {len(vel_tilts)} VEL relative items: {vel_tilts[:5]}...", flush=True)
    print(f"  -> Found {len(refl_tilts)} REFL relative items: {refl_tilts[:5]}...", flush=True)

    # Common set intersection
    raw_tilts = set(refl_tilts).intersection(vel_tilts)
    print(f"  -> Intersection count: {len(raw_tilts)} items: {raw_tilts}", flush=True)

    # Filtered tilts matching decimal tilt pattern
    matched_tilts = [x for x in raw_tilts if re.match(r"[0-9]+\.[0-9]+", x)]
    print(f"  -> Matching Tilts (matching r'[0-9]+\.[0-9]+'): {matched_tilts}", flush=True)

    for tilt in matched_tilts:
        products = list(getProducts(radar, run_time, tilt))
        print(f"  --> Yielding Tilt [{tilt}] with {len(products)} products", flush=True)
        yield { "tilt": tilt, "files": products }

def getTiltProducts_1(radar, run_time):
    settings = AppConfiguration.get()

    vel_tilts = list_rel_files(__get_path_velocity__(radar, run_time, settings.rass_input, settings.rass_input_vel)) + list_rel_files(__get_path_velocity__(radar, run_time - datetime.timedelta(days = 1), settings.rass_input, settings.rass_input_vel))

    refl_tilts = list_rel_files(__get_path_reflectivity__(radar, run_time, settings.rass_input, settings.rass_input_refl)) + list_rel_files(__get_path_reflectivity__(radar, run_time - datetime.timedelta(days = 1), settings.rass_input, settings.rass_input_refl))

    # common set of tilts 
    tilts = set(refl_tilts).intersection(vel_tilts)
    for tilt in [x for x in tilts if re.match(r"[0-9]+\.[0-9]+", x)]:
        yield { "tilt": tilt, "files": list(getProducts(radar, run_time, tilt)) }

def getRadarProducts(radar, run_time, debug = False, input_refl = 'ReflectivityDPQCLight', input_vel = 'Velocity'):
    _debug_ = debug

    for fileset in getTiltProducts(radar, run_time):

        if len(_include_tilts) > 0 and fileset['tilt'] not in _include_tilts:
            continue

        # cannot process vr without reflectivity
        if len(fileset['files']) < 2: 
            continue

        myradar = load_mrms_ppi(fileset['files'], input_refl, input_vel)
        myradar.init_gate_altitude()
        myradar.init_gate_longitude_latitude()

        if _debug_ == True:
            try:
                fig = plt.figure(figsize=[8, 16])
                ax = plt.subplot(2, 1, 1)
                display = pyart.graph.RadarMapDisplay(myradar)
                display.plot_ppi_map(
                    "reflectivity",
                    sweep=0,
                    resolution="50m",
                )

                rt = run_time.strftime("%Y%m%d_%H%M")
                tilt = fileset['tilt']

                ax2 = plt.subplot(2, 1, 2)
                display = pyart.graph.RadarMapDisplay(myradar)
                display.plot_ppi_map(
                    "velocity",
                    sweep=0,
                    resolution="50m",
                    cmap="balance",
                )
                plt.savefig(f'{radar}_{tilt}_{rt}.png')
            except:
                print(f"Could not plot {radar}_{tilt}_{rt}.png")

        yield { "tilt": fileset['tilt'], "radar": myradar }
