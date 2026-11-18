import os
import datetime as DT
import logging
from .Config import AppConfiguration
from .vr import run_vr_for_radar_time
from .refl import run_refl_for_radar_time
from multiprocessing import Pool, TimeoutError
from .utils.combine_VR_ncdf import combine_from_pattern
from optparse import OptionParser
from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

logging.basicConfig() 

def __abortable_worker__(func, *args, **kwargs):
    timeout = kwargs.get('timeout', None)
    p = ThreadPool(1)
    res = p.apply_async(func, args=args)
    try:
        out = res.get(timeout)  # Wait timeout seconds for func to complete.
        return out
    except TimeoutError:
        print("Aborting due to timeout")
        raise

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-t", "--time",   dest="time", default = None)
    parser.add_option("-r", "--radars",   dest="radars", default = None)
    #parser.add_option("-i", "--id",   dest="id", default = None)
    parser.add_option("-y", "--latitude",   dest="lat", default = None)
    parser.add_option("-x", "--longitude",   dest="lon", default = None)
    parser.add_option("-f", "--file",   dest="file", default = None)
    parser.add_option("-d", "--domain",   dest="domain", default = None)
    parser.add_option("-p", "--realtime",   dest="realtime", default = None)

    (options, args) = parser.parse_args()

    run_time = DT.datetime.strptime(options.time, "%Y%m%d%H%M")
    radars = options.radars.split(',')

    settings = AppConfiguration.load(options.file)

    if settings.default_parallel:
        print('Running in parallel mode')
        #print('Running in parallel mode', flush=True)
        #logging.info('Running in parallel mode')
        with Pool(processes=len(radars)+1, maxtasksperchild=1) as pool:
            refl_func = partial(__abortable_worker__, run_refl_for_radar_time, timeout=360)
            pool.apply_async(refl_func, args = (run_time, float(options.lon), float(options.lat), options.file, options.domain, options.realtime))

            for name in radars:
                abortable_func = partial(__abortable_worker__, run_vr_for_radar_time, timeout=360)
                pool.apply_async(abortable_func, args = (run_time, name, float(options.lon), float(options.lat), options.file, options.domain))

            pool.close()
            pool.join()   
    else:
        print('Running in serial mode')

        #run_refl_for_radar_time(run_time, float(options.lon), float(options.lat), options.file, options.domain, options.realtime)
        for name in radars:
            run_vr_for_radar_time(run_time, name, float(options.lon), float(options.lat), options.file, options.domain)    

    output_dir = settings.rass_output.format(run_time.strftime("%Y%m%d"))

    __abortable_worker__(combine_from_pattern, '_VR_%s.nc' % run_time.strftime("%Y%m%d_%H%M"), 
        os.path.join(output_dir, run_time.strftime("%Y%m%d")), timeout=360)

    #try:
        #Shrink image size with pngquant.            
        #cmd = f"/home/brian.matilla/micromamba/envs/wofs-func/bin//pngquant --ext .png -f {output_dir}/**/*.png"
        #print(f"Running command: {cmd}")
        #os.system(cmd)
    #except:
    #    raise OSError('Unable to compress the PNG file. Check that pngquant is installed!')

    print("\n Processing VR/REFL for time %s finished at %s" % (run_time, DT.datetime.utcnow().strftime("%H:%M:%S")))    
