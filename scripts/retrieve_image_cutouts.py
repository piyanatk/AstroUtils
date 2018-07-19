#!python

import os.path
import numpy as NP
import yaml, argparse, warnings, copy
from astroquery.skyview import SkyView
from astropy.coordinates import SkyCoord
from astropy import units as U
from astropy.io import ascii, fits
import astroutils

astroutils_path = astroutils.__path__[0]+'/'

if __name__ == '__main__':
    
    ## Parse input arguments
    
    parser = argparse.ArgumentParser(description='Program to retrieve TGSS image cutouts')
    
    input_group = parser.add_argument_group('Input parameters', 'Input specifications')
    input_group.add_argument('-i', '--infile', dest='infile', default=astroutils_path+'examples/cosmotile/cosmotile_parms.yaml', type=str, required=False, help='File specifying input parameters for retrieving image cutouts')

    args = vars(parser.parse_args())
    
    with open(args['infile'], 'r') as parms_file:
        parms = yaml.safe_load(parms_file)

    projectdir = parms['dirStruct']['projectdir']
    outdir = projectdir + parms['dirStruct']['outdir']

    coordinfo = parms['coordinates']
    catalogfile = coordinfo['infile']
    ra_colname = coordinfo['RA_colname']
    dec_colname = coordinfo['Dec_colname']
    if coordinfo['RA_units'] == 'hms':
        ra_units = U.hourangle
    if (coordinfo['Dec_units'] == 'dms') or (coordinfo['Dec_units'] == 'deg'):
        dec_units = U.deg

    catalog = ascii.read(catalogfile)

    ra = catalog[ra_colname]
    dec = catalog[dec_colname]

    coords = SkyCoord(ra, dec, unit=(ra_units, dec_units), equinox=coordinfo['epoch'], frame='icrs')

    subsetinfo = parms['subset']
    subparnames = subsetinfo['parmnames']
    select = NP.ones(len(catalog), dtype=NP.bool)
    if len(subparnames) > 0:
        parmranges = subsetinfo['parmrange']
        for i,prm in enumerate(subparnames):
            subdat = catalog[prm]
            if (subdat.dtype == NP.float) or (subdat.dtype == NP.int):
                select[NP.logical_or(subdat < parmranges[i][0], subdat > parmranges[i][1])] = False
            else:
                for prmstr in parmranges[i]:
                    if prmstr[0] == '!':
                        pstr = prmstr[1:]
                        select = NP.logical_and(select, NP.logical_not(NP.asarray([pstr in subdat[j] for j in range(len(subdat))])))
                    else:
                        pstr = prmstr
                        select = NP.logical_and(select, NP.asarray([pstr in subdat[j] for j in range(len(subdat))]))

    select_ind = NP.where(select)[0]
    
    imgparms = parms['image']
    survey = imgparms['survey']
    projection = imgparms['projection']
    pixels = imgparms['pixels']
    overwrite = imgparms['overwrite']

    failure_count = 0
    failed_coords = []
    for ind in select_ind:
        radec_hmsdms = coords[ind].to_string('hmsdms')
        outfname = outdir + '{0}_{1[0]:0d}x{1[1]:0d}.fits'.format(radec_hmsdms.replace(' ',''), pixels)
        if (not os.path.isfile(outfname)) or overwrite:
            try:
                paths = SkyView.get_images(radec_hmsdms, survey=survey, pixels=pixels, coordinates=coordinfo['epoch'], projection=projection)
                hdulist = paths[0][0]
                hdulist.writeto(outfname, overwrite=True)
            except Exception as err:
                warnings.warn('Problem with retrieving image at {0}.\nEncountered error: {1}.\nProceeding to the next object...\n'.format(radec_hmsdms, err.message))

                if isinstance(err, AttributeError):
                    # For some reason, timeouts come under Attribute Error.
                    # There will be retries on these failures, but not others
                    # such as pointing outside the survey area, etc.

                    failure_count += 1
                    failed_coords += [radec_hmsdms]

    if failure_count > 0:
        # Process the failures
        failurefile = projectdir + parms['failure']['failurefile']
        n_retry = parms['failure']['retry']
        success_coords = []
        if n_retry > 0:
            # Retry the failed retrievals
            for iretry in range(n_retry):
                if len(success_coords) < len(failed_coords):
                    for indfail, failcoord in enumerate(failed_coords):
                        if failcoord not in success_coords:
                            outfname = outdir + '{0}_{1[0]:0d}x{1[1]:0d}.fits'.format(failcoord.replace(' ',''), pixels)
                            try:
                                paths = SkyView.get_images(failcoord, survey=survey, pixels=pixels, coordinates=coordinfo['epoch'], projection=projection)
                                hdulist = paths[0][0]
                                hdulist.writeto(outfname, overwrite=True)
                            except Exception as err:
                                warnings.warn('Problem with retrieving image at {0}.\nEncountered error: {1}.\nProceeding to the next object...\n'.format(failcoord, err.message))
                            else: # Successful retrieval
                                failure_count -= 1
                                success_coords += [failcoord]
                            
        if len(success_coords) < len(failed_coords):
            # Write information about failed retrievals to a file

            print('Failed to retrieve {0:0d}/{1:0d} images. Failed coordinates listed in {2}'.format(failure_count-len(success_coords), select_ind.size, failurefile))
            final_failed_coords = NP.setdiff1d(failed_coords, success_coords)
            NP.savetxt(failurefile, final_failed_coords, fmt='%s')
        
