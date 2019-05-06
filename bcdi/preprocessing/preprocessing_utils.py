# -*- coding: utf-8 -*-

# BCDI: tools for pre(post)-processing Bragg coherent X-ray diffraction imaging data
#   (c) 07/2017-06/2019 : CNRS UMR 7344 IM2NP
#       authors:
#         Jerome Carnis, jerome.carnis@esrf.fr

import numpy as np
import bcdi.graph.graph_utils as gu
import matplotlib.pyplot as plt
from matplotlib.path import Path
from scipy.ndimage.measurements import center_of_mass
import xrayutilities as xu
import fabio
import os


def center_fft(data, mask, frames_logical, centering='max', fft_option='crop_asymmetric_ZYX', **kwargs):
    """
    Center and crop/pad the dataset depending on user parameters

    :param data: the 3D data array
    :param mask: the 3D mask array
    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param centering: centering option, 'max' or 'com'. It will be overridden if the kwarg 'fix_bragg' is provided.
    :param fft_option:
     - 'crop_symmetric_ZYX': crop the array for FFT requirements, Bragg peak centered
     - 'crop_asymmetric_ZYX': crop the array for FFT requirements without centering the Brag peak
     - 'pad_symmetric_Z_crop_YX': crop detector images, pad the rocking angle based on 'pad_size', Bragg peak centered
     - 'pad_asymmetric_Z_crop_YX': crop detector images, pad the rocking angle without centering the Brag peak
     - 'pad_symmetric_Z': keep detector size and pad/center the rocking angle based on 'pad_size', Bragg peak centered
     - 'pad_asymmetric_Z': keep detector size and pad the rocking angle without centering the Brag peak
     - 'pad_symmetric_ZYX': pad all dimensions based on 'pad_size', Brag peak centered
     - 'pad_asymmetric_ZYX': pad all dimensions based on 'pad_size' without centering the Brag peak
     - 'do_nothing': keep the full dataset or crop it to the size defined by fix_size
    :param kwargs:
     - 'fix_bragg' = user-defined position in pixels of the Bragg peak [z_bragg, y_bragg, x_bragg]
     - 'fix_size' = user defined output array size [zstart, zstop, ystart, ystop, xstart, xstop]
     - 'pad_size' = user defined output array size [nbz, nby, nbx]
     - 'q_values' = [qx, qz, qy], each component being a 1D array
    :return:
     - updated data, mask (and q_values if provided, [] otherwise)
     - pad_width = [z0, z1, y0, y1, x0, x1] number of pixels added at each end of the original data
     - updated frames_logical
    """
    if data.ndim != 3 or mask.ndim != 3:
        raise ValueError('data and mask should be 3D arrays')

    if data.shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data is ', data.shape, ' while mask is ', mask.shape)

    for k in kwargs.keys():
        if k in ['fix_bragg']:
            fix_bragg = kwargs['fix_bragg']
        elif k in ['fix_size']:
            fix_size = kwargs['fix_size']
        elif k in ['pad_size']:
            pad_size = kwargs['pad_size']
        elif k in ['q_values']:
            q_values = kwargs['q_values']
        else:
            raise Exception("unknown keyword argument given: allowed is"
                            "'fix_bragg', 'fix_size', 'pad_size' and 'q_values'")
    try:
        fix_bragg
    except NameError:  # fix_bragg not declared
        fix_bragg = []
    try:
        fix_size
    except NameError:  # fix_size not declared
        fix_size = []
    try:
        pad_size
    except NameError:  # pad_size not declared
        pad_size = []
    try:
        q_values
        qx = q_values[0]  # axis=0, z downstream, qx in reciprocal space
        qz = q_values[1]  # axis=1, y vertical, qz in reciprocal space
        qy = q_values[2]  # axis=2, x outboard, qy in reciprocal space
    except NameError:  # q_values not declared
        q_values = []
        qx = []
        qy = []
        qz = []
    except IndexError:  # q_values empty
        q_values = []
        qx = []
        qy = []
        qz = []

    if centering == 'max':
        z0, y0, x0 = np.unravel_index(abs(data).argmax(), data.shape)
        print("Max at (qx, qz, qy): ", z0, y0, x0)
    elif centering == 'com':
        z0, y0, x0 = center_of_mass(data)
        print("Center of mass at (qx, qz, qy): ", z0, y0, x0)
    else:
        raise ValueError("Incorrect value for 'centering' parameter")

    if len(fix_bragg) != 0:
        if len(fix_bragg) != 3:
            raise ValueError('fix_bragg should be a list of 3 integers')
        z0, y0, x0 = fix_bragg
        print("Bragg peak position defined by user at (qx, qz, qy): ", z0, y0, x0)

    iz0, iy0, ix0 = int(round(z0)), int(round(y0)), int(round(x0))
    print('data at Bragg peak = ', data[iz0, iy0, ix0])

    # Max symmetrical box around center of mass
    nbz, nby, nbx = np.shape(data)
    max_nz = abs(2 * min(iz0, nbz - iz0))
    max_ny = 2 * min(iy0, nby - iy0)
    max_nx = abs(2 * min(ix0, nbx - ix0))
    print("Max symmetrical box (qx, qz, qy): ", max_nz, max_ny, max_nx)
    if max_nz == 0 or max_ny == 0 or max_nx == 0:
        print('Images with no intensity!')
        fft_option = 'do_nothing'

    # Crop/pad data to fulfill FFT size and user requirements
    if fft_option == 'crop_symmetric_ZYX':
        # crop rocking angle and detector, Bragg peak centered
        nz1, ny1, nx1 = smaller_primes((max_nz, max_ny, max_nx), maxprime=7, required_dividers=(2,))
        pad_width = np.zeros(6, dtype=int)

        data = data[iz0 - nz1 // 2:iz0 + nz1//2, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        mask = mask[iz0 - nz1 // 2:iz0 + nz1//2, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        print("FFT box (qx, qz, qy): ", data.shape)

        if (iz0 - nz1//2) > 0:  # if 0, the first frame is used
            frames_logical[0:iz0 - nz1 // 2] = 0
        if (iz0 + nz1 // 2) < nbz:  # if nbz, the last frame is used
            frames_logical[iz0 + nz1 // 2:] = 0

        if len(q_values) != 0:
            qx = qx[iz0 - nz1//2:iz0 + nz1//2]
            qy = qy[ix0 - nx1//2:ix0 + nx1//2]
            qz = qz[iy0 - ny1//2:iy0 + ny1//2]

    elif fft_option == 'crop_asymmetric_ZYX':
        # crop rocking angle and detector without centering the Bragg peak
        nz1, ny1, nx1 = smaller_primes((nbz, nby, nbx), maxprime=7, required_dividers=(2,))
        pad_width = np.zeros(6, dtype=int)

        data = data[nbz//2 - nz1//2:nbz//2 + nz1//2, nby//2 - ny1//2:nby//2 + ny1//2,
                    nbx//2 - nx1//2:nbx//2 + nx1//2]
        mask = mask[nbz//2 - nz1//2:nbz//2 + nz1//2, nby//2 - ny1//2:nby//2 + ny1//2,
                    nbx//2 - nx1//2:nbx//2 + nx1//2]
        print("FFT box (qx, qz, qy): ", data.shape)

        if (nbz//2 - nz1//2) > 0:  # if 0, the first frame is used
            frames_logical[0:nbz//2 - nz1//2] = 0
        if (nbz//2 + nz1//2) < nbz:  # if nbz, the last frame is used
            frames_logical[nbz//2 + nz1 // 2:] = 0

        if len(q_values) != 0:
            qx = qx[nbz//2 - nz1//2:nbz//2 + nz1//2]
            qy = qy[nbx//2 - nx1//2:nbx//2 + nx1//2]
            qz = qz[nby//2 - ny1//2:nby//2 + ny1//2]

    elif fft_option == 'pad_symmetric_Z_crop_YX':
        # pad rocking angle based on 'pad_size', Bragg peak centered , crop detector
        if len(pad_size) != 3:
            raise ValueError('pad_size should be a list of three elements')
        if pad_size[0] != higher_primes(pad_size[0], maxprime=7, required_dividers=(2,)):
            raise ValueError(pad_size[0], 'does not meet FFT requirements')
        ny1, nx1 = smaller_primes((max_ny, max_nx), maxprime=7, required_dividers=(2,))

        data = data[:, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        mask = mask[:, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        pad_width = np.array([int(min(pad_size[0]/2-iz0, pad_size[0]-nbz)),
                              int(min(pad_size[0]/2-nbz + iz0, pad_size[0]-nbz)),
                              0, 0, 0, 0], dtype=int)
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels
        print("FFT box (qx, qz, qy): ", data.shape)

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qx = qx0 + np.arange(pad_size[0])*dqx
            qy = qy[ix0 - nx1 // 2:ix0 + nx1 // 2]
            qz = qz[iy0 - ny1 // 2:iy0 + ny1 // 2]

    elif fft_option == 'pad_asymmetric_Z_crop_YX':
        # pad rocking angle without centering the Bragg peak, crop detector
        ny1, nx1 = smaller_primes((max_ny, max_nx), maxprime=7, required_dividers=(2,))
        nz1 = higher_primes(nbz, maxprime=7, required_dividers=(2,))

        data = data[:, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        mask = mask[:, iy0 - ny1//2:iy0 + ny1//2, ix0 - nx1//2:ix0 + nx1//2]
        pad_width = np.array([int((nz1 - nbz + ((nz1 - nbz) % 2)) / 2), int((nz1 - nbz + 1) / 2 - ((nz1 - nbz) % 2)),
                              0, 0, 0, 0], dtype=int)
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels
        print("FFT box (qx, qz, qy): ", data.shape)

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qx = qx0 + np.arange(nz1)*dqx
            qy = qy[ix0 - nx1 // 2:ix0 + nx1 // 2]
            qz = qz[iy0 - ny1 // 2:iy0 + ny1 // 2]

    elif fft_option == 'pad_symmetric_Z':
        # pad rocking angle based on 'pad_size', Bragg peak centered, keep detector size
        if len(pad_size) != 3:
            raise ValueError('pad_size should be a list of three elements')
        if pad_size[0] != higher_primes(pad_size[0], maxprime=7, required_dividers=(2,)):
            raise ValueError(pad_size[0], 'does not meet FFT requirements')

        pad_width = np.array([int(min(pad_size[0]/2-iz0, pad_size[0]-nbz)),
                              int(min(pad_size[0]/2-nbz + iz0, pad_size[0]-nbz)),
                              0, 0, 0, 0], dtype=int)
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels
        print("FFT box (qx, qz, qy): ", data.shape)

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qx = qx0 + np.arange(pad_size[0])*dqx

    elif fft_option == 'pad_asymmetric_Z':
        # pad rocking angle without centering the Bragg peak, keep detector size
        nz1 = higher_primes(nbz, maxprime=7, required_dividers=(2,))

        pad_width = np.array([int((nz1-nbz+((nz1-nbz) % 2))/2), int((nz1-nbz+1)/2-((nz1-nbz) % 2)),
                              0, 0, 0, 0], dtype=int)
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels
        print("FFT box (qx, qz, qy): ", data.shape)

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qx = qx0 + np.arange(nz1)*dqx

    elif fft_option == 'pad_symmetric_ZYX':
        # pad both dimensions based on 'pad_size', Bragg peak centered
        if len(pad_size) != 3:
            raise ValueError('pad_size should be a list of 3 integers')
        if pad_size[0] != higher_primes(pad_size[0], maxprime=7, required_dividers=(2,)):
            raise ValueError(pad_size[0], 'does not meet FFT requirements')
        if pad_size[1] != higher_primes(pad_size[1], maxprime=7, required_dividers=(2,)):
            raise ValueError(pad_size[1], 'does not meet FFT requirements')
        if pad_size[2] != higher_primes(pad_size[2], maxprime=7, required_dividers=(2,)):
            raise ValueError(pad_size[2], 'does not meet FFT requirements')

        pad_width = [int(min(pad_size[0]/2-iz0, pad_size[0]-nbz)), int(min(pad_size[0]/2-nbz + iz0, pad_size[0]-nbz)),
                     int(min(pad_size[1]/2-iy0, pad_size[1]-nby)), int(min(pad_size[1]/2-nby + iy0, pad_size[1]-nby)),
                     int(min(pad_size[2]/2-ix0, pad_size[2]-nbx)), int(min(pad_size[2]/2-nbx + ix0, pad_size[2]-nbx))]
        pad_width = np.array(list((map(lambda value: max(value, 0), pad_width))), dtype=int)  # remove negative numbers
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels
        print("FFT box (qx, qz, qy): ", data.shape)

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            dqy = qy[1] - qy[0]
            dqz = qz[1] - qz[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qy0 = qy[0] - pad_width[2] * dqy
            qz0 = qz[0] - pad_width[1] * dqz
            qx = qx0 + np.arange(pad_size[0]) * dqx
            qy = qy0 + np.arange(pad_size[2]) * dqy
            qz = qz0 + np.arange(pad_size[1]) * dqz

    elif fft_option == 'pad_asymmetric_ZYX':
        # pad both dimensions without centering the Bragg peak
        nz1, ny1, nx1 = [higher_primes(nbz, maxprime=7, required_dividers=(2,)),
                         higher_primes(nby, maxprime=7, required_dividers=(2,)),
                         higher_primes(nbx, maxprime=7, required_dividers=(2,))]

        pad_width = np.array(
            [int((nz1-nbz+((nz1-nbz) % 2))/2), int((nz1-nbz+1)/2-((nz1-nbz) % 2)),
             int((ny1-nby+((pad_size[1]-nby) % 2))/2), int((ny1-nby+1)/2-((ny1-nby) % 2)),
             int((nx1-nbx+((nx1-nbx) % 2))/2), int((nx1-nbx+1)/2-((nx1-nbx) % 2))])
        data = zero_pad(data, padding_width=pad_width, mask_flag=False)
        mask = zero_pad(mask, padding_width=pad_width, mask_flag=True)  # mask padded pixels

        temp_frames = -1 * np.ones(data.shape[0])
        temp_frames[pad_width[0]:pad_width[0] + nbz] = frames_logical
        frames_logical = temp_frames

        if len(q_values) != 0:
            dqx = qx[1] - qx[0]
            dqy = qy[1] - qy[0]
            dqz = qz[1] - qz[0]
            qx0 = qx[0] - pad_width[0] * dqx
            qy0 = qy[0] - pad_width[2] * dqy
            qz0 = qz[0] - pad_width[1] * dqz
            qx = qx0 + np.arange(nz1) * dqx
            qy = qy0 + np.arange(nx1) * dqy
            qz = qz0 + np.arange(ny1) * dqz

    elif fft_option == 'do_nothing':
        # keep the full dataset or use 'fix_size' parameter
        pad_width = np.zeros(6, dtype=int)  # do nothing or crop the data, starting_frame should be 0
        if len(fix_size) == 3:
            # size of output array defined
            nbz, nby, nbx = np.shape(data)
            z_pan = fix_size[1] - fix_size[0]
            y_pan = fix_size[3] - fix_size[2]
            x_pan = fix_size[5] - fix_size[4]
            if z_pan > nbz or y_pan > nby or x_pan > nbx or fix_size[1] > nbz or fix_size[3] > nby or fix_size[5] > nbx:
                raise ValueError("Predefined fix_size uncorrect")
            else:
                data = data[fix_size[0]:fix_size[1], fix_size[2]:fix_size[3], fix_size[4]:fix_size[5]]
                mask = mask[fix_size[0]:fix_size[1], fix_size[2]:fix_size[3], fix_size[4]:fix_size[5]]

                if fix_size[0] > 0:  # if 0, the first frame is used
                    frames_logical[0:fix_size[0]] = 0
                if fix_size[1] < nbz:  # if nbz, the last frame is used
                    frames_logical[fix_size[1]:] = 0

                if len(q_values) != 0:
                    qx = qx[fix_size[0]:fix_size[1]]
                    qy = qy[fix_size[4]:fix_size[5]]
                    qz = qz[fix_size[2]:fix_size[3]]
    else:
        raise ValueError("Incorrect value for 'fft_option'")

    if len(q_values) != 0:
        q_values[0] = qx
        q_values[1] = qz
        q_values[2] = qy
    return data, mask, pad_width, q_values, frames_logical


def check_pixels(data, mask, debugging=False):
    """
    Check for hot pixels in the data using the mean value and the variance.

    :param data: 3D diffraction data
    :param mask: 2D or 3D mask. Mask will summed along the first axis if a 3D array.
    :param debugging: set to True to see plots
    :type debugging: bool
    :return: the filtered 3D data and the updated 2D mask.
    """
    if data.ndim != 3:
        raise ValueError('Data should be a 3D array')

    nbz, nby, nbx = data.shape

    if mask.ndim == 3:  # 3D array
        print("Mask is a 3D array, summing it along axis 0")
        mask = mask.sum(axis=0)
        mask[np.nonzero(mask)] = 1

    if data[0, :, :].shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data slice is ',
                         data[0, :, :].shape, ' while mask is ', mask.shape)

    meandata = data.mean(axis=0)  # 2D
    vardata = 1 / data.var(axis=0)  # 2D
    var_mean = vardata[vardata != np.inf].mean()
    vardata[meandata == 0] = var_mean  # pixels were data=0 (hence 1/variance=inf) are set to the mean of 1/var
    if debugging:
        gu.combined_plots(tuple_array=(meandata, vardata), tuple_sum_frames=(False, False), tuple_sum_axis=(0, 0),
                          tuple_width_v=(np.nan, np.nan), tuple_width_h=(np.nan, np.nan), tuple_colorbar=(True, True),
                          tuple_vmin=(0, 0), tuple_vmax=(1, np.nan), tuple_scale=('linear', 'linear'),
                          tuple_title=('mean(data) before masking', '1/var(data) before masking'),
                          reciprocal_space=True)
    # calculate the mean and 1/variance for a single photon event along the rocking curve
    min_count = 1.0  # pixels with only 1 photon count along the rocking curve.

    mean_threshold = min_count / nbz
    var_threshold = ((nbz - 1) * mean_threshold ** 2 + (min_count - mean_threshold) ** 2) * 1 / nbz

    indices_badpixels = np.nonzero(vardata > 1 / var_threshold)
    mask[indices_badpixels] = 1  # mask is 2D
    for index in range(nbz):
        tempdata = data[index, :, :]
        tempdata[indices_badpixels] = 0  # numpy array is mutable hence data will be modified  # TODO: check that

    if debugging:
        meandata = data.mean(axis=0)
        vardata = 1 / data.var(axis=0)
        gu.combined_plots(tuple_array=(meandata, vardata), tuple_sum_frames=(False, False), tuple_sum_axis=(0, 0),
                          tuple_width_v=(np.nan, np.nan), tuple_width_h=(np.nan, np.nan), tuple_colorbar=(True, True),
                          tuple_vmin=(0, 0), tuple_vmax=(1, np.nan), tuple_scale=('linear', 'linear'),
                          tuple_title=('mean(data) after masking', '1/var(data) after masking'), reciprocal_space=True)
    print("check_pixels():", str(indices_badpixels[0].shape[0]), "badpixels were masked on a total of", str(nbx * nby))
    return data, mask


def create_logfile(setup, detector, scan_number, root_folder, filename):
    """
    Create the logfile used in gridmap().

    :param setup: the experimental setup: Class SetupPreproc
    :param detector: the detector object: Class experiment_utils.Detector()
    :param scan_number: the scan number to load
    :param root_folder: the root directory of the experiment, where is the specfile/.fio file
    :param filename: the file name to load, or the path of 'alias_dict.txt' for SIXS
    :return: logfile
    """
    if setup.beamline == 'CRISTAL':  # no specfile, load directly the dataset
        import h5py
        ccdfiletmp = os.path.join(detector.datadir + detector.template_imagefile % scan_number)
        logfile = h5py.File(ccdfiletmp, 'r')

    elif setup.beamline == 'P10':  # load .fio file
        logfile = root_folder + filename + '\\' + filename + '.fio'

    elif setup.beamline == 'SIXS':  # no specfile, load directly the dataset
        import bcdi.preprocessing.nxsReady as nxsReady

        logfile = nxsReady.DataSet(longname=detector.datadir + detector.template_imagefile % scan_number,
                                   shortname=detector.template_imagefile % scan_number, alias_dict=filename,
                                   scan="SBS")

    elif setup.beamline == 'ID01':  # load spec file
        from silx.io.specfile import SpecFile
        logfile = SpecFile(root_folder + filename + '.spec')
    else:
        raise ValueError('Incorrect value for beamline parameter')

    return logfile


def gridmap(logfile, scan_number, detector, setup, flatfield, hotpixels, orthogonalize=False, hxrd=None, **kwargs):
    """
    Load the data, apply filters and concatenate it for phasing.

    :param logfile: file containing the information about the scan and image numbers (specfile, .fio...)
    :param scan_number: the scan number to load
    :param detector: the detector object: Class experiment_utils.Detector()
    :param setup: the experimental setup: Class SetupPreprocessing()
    :param flatfield: the 2D flatfield array
    :param hotpixels: the 2D hotpixels array
    :param orthogonalize: if True will interpolate the data and the mask on an orthogonal grid using xrayutilities
    :param hxrd: an initialized xrayutilities HXRD object used for the orthogonalization of the dataset
    :param kwargs:
     - follow_bragg (bool): True when for energy scans the detector was also scanned to follow the Bragg peak
     - headerline_p10: number of header lines before scanned motor position in .fio file (only for P10 dataset)
     - header_cristal: string, header of data path in CRISTAL .nxs files
    :return:
     - the 3D data array in the detector frame and the 3D mask array
     - frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
       A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
     - the monitor values for normalization
    """
    for k in kwargs.keys():
        if k in ['follow_bragg']:
            follow_bragg = kwargs['follow_bragg']
        elif k in ['headerline_p10']:
            headerline_p10 = kwargs['headerline_p10']
        elif k in ['header_cristal']:
            header_cristal = kwargs['header_cristal']
        else:
            raise Exception("unknown keyword argument given: allowed is 'follow_bragg' and 'headerline_p10'")
    if setup.rocking_angle == 'energy':
        try:
            follow_bragg
        except NameError:
            raise TypeError("Parameter 'follow_bragg' not provided, defaulting to False")

    if setup.beamline == 'P10':
        try:
            headerline_p10
        except NameError:
            raise TypeError("Parameter 'headerline_p10' not provided")

    if setup.beamline == 'CRISTAL':
        try:
            header_cristal
        except NameError:
            raise TypeError("Parameter 'header_cristal' not provided")

    if flatfield is None:
        flatfield = np.ones((detector.nb_pixel_y, detector.nb_pixel_x))
    if hotpixels is None:
        hotpixels = np.zeros((detector.nb_pixel_y, detector.nb_pixel_x))

    if setup.beamline == 'ID01':
        rawdata, rawmask, monitor, frames_logical = \
            load_id01_data(logfile=logfile, scan_number=scan_number, detector=detector, flatfield=flatfield,
                           hotpixels=hotpixels)
    elif setup.beamline == 'CRISTAL':
        rawdata, rawmask, monitor, frames_logical = \
            load_cristal_data(logfile=logfile, header=header_cristal, scan_number=scan_number, detector=detector,
                              flatfield=flatfield, hotpixels=hotpixels)
    elif setup.beamline == 'SIXS':
        rawdata, rawmask, monitor, frames_logical = \
            load_sixs_data(logfile=logfile, detector=detector, flatfield=flatfield, hotpixels=hotpixels)
    elif setup.beamline == 'P10':
        rawdata, rawmask, monitor, frames_logical = \
            load_p10_data(logfile=logfile, detector=detector, flatfield=flatfield,
                          hotpixels=hotpixels, headerlines=headerline_p10)
    else:
        raise ValueError("Incorrect value for parameter 'beamline'")

    if not orthogonalize:
        return [], rawdata, [], rawmask, [], frames_logical, monitor
    else:
        nbz, nby, nbx = rawdata.shape
        if setup.beamline == 'ID01':
            qx, qz, qy, frames_logical = \
                regrid_id01(follow_bragg=follow_bragg, frames_logical=frames_logical, logfile=logfile,
                            scan_number=scan_number, detector=detector, setup=setup, hxrd=hxrd)

            # below is specific to ID01 energy scans where frames are duplicated for undulator gap change
            if setup.rocking_angle == 'energy':  # frames need to be removed
                tempdata = np.zeros(((frames_logical != 0).sum(), nby, nbx))
                offset_frame = 0
                for idx in range(nbz):
                    if frames_logical[idx] != 0:  # use frame
                        tempdata[idx-offset_frame, :, :] = rawdata[idx, :, :]
                    else:  # average with the precedent frame
                        offset_frame = offset_frame + 1
                        tempdata[idx-offset_frame, :, :] = (tempdata[idx-offset_frame, :, :] + rawdata[idx, :, :])/2
                rawdata = tempdata
                rawmask = rawmask[0:rawdata.shape[0], :, :]  # truncate the mask to have the correct size

        elif setup.beamline == 'CRISTAL':
            qx, qz, qy, frames_logical = regrid_cristal(frames_logical=frames_logical, logfile=logfile,
                                                        header=header_cristal, scan_number=scan_number,
                                                        detector=detector, setup=setup, hxrd=hxrd)
        elif setup.beamline == 'SIXS':
            qx, qz, qy, frames_logical = regrid_sixs(frames_logical=frames_logical, logfile=logfile, detector=detector,
                                                     setup=setup, hxrd=hxrd)
        elif setup.beamline == 'P10':
            qx, qz, qy, frames_logical = regrid_p10(frames_logical=frames_logical, logfile=logfile,
                                                    detector=detector, setup=setup, hxrd=hxrd,
                                                    headerlines=headerline_p10)
        else:
            raise ValueError("Incorrect value for parameter 'beamline'")

        nbz, nby, nbx = rawdata.shape
        gridder = xu.Gridder3D(nbz, nby, nbx)
        # convert mask to rectangular grid in reciprocal space
        gridder(qx, qz, qy, rawmask)
        mask = np.copy(gridder.data)
        # convert data to rectangular grid in reciprocal space
        gridder(qx, qz, qy, rawdata)

        q_values = (gridder.xaxis, gridder.yaxis, gridder.zaxis)

        return q_values, rawdata, gridder.data, rawmask, mask, frames_logical, monitor


def higher_primes(number, maxprime=13, required_dividers=(4,)):
    """
    Find the closest integer >=n (or list/array of integers), for which the largest prime divider is <=maxprime,
    and has to include some dividers. The default values for maxprime is the largest integer accepted
    by the clFFT library for OpenCL GPU FFT. Adapted from PyNX.

    :param number: the integer number
    :param maxprime: the largest prime factor acceptable
    :param required_dividers: a list of required dividers for the returned integer.
    :return: the integer (or list/array of integers) fulfilling the requirements
    """
    if (type(number) is list) or (type(number) is tuple) or (type(number) is np.ndarray):
        vn = []
        for i in number:
            limit = i
            assert (i > 1 and maxprime <= i)
            while try_smaller_primes(i, maxprime=maxprime, required_dividers=required_dividers) is False:
                i = i + 1
                if i == limit:
                    return limit
            vn.append(i)
        if type(number) is np.ndarray:
            return np.array(vn)
        return vn
    else:
        limit = number
        assert (number > 1 and maxprime <= number)
        while try_smaller_primes(number, maxprime=maxprime, required_dividers=required_dividers) is False:
            number = number + 1
            if number == limit:
                return limit
        return number


def init_qconversion(setup):
    """
    Initialize the qconv object from xrayutilities depending on the setup parameters

    :param setup: the experimental setup: Class SetupPreprocessing()
    :return: qconv object and offsets for motors
    """
    beamline = setup.beamline
    offset_inplane = setup.offset_inplane
    beam_direction = setup.beam_direction

    if beamline == 'ID01':
        offsets = (0, 0, 0, offset_inplane, 0)  # eta chi phi nu del
        qconv = xu.experiment.QConversion(['y-', 'x+', 'z-'], ['z-', 'y-'], r_i=beam_direction)  # for ID01
        # 2S+2D goniometer (ID01 goniometer, sample: eta, phi      detector: nu,del
        # the vector beam_direction is giving the direction of the primary beam
        # convention for coordinate system: x downstream; z upwards; y to the "outside" (right-handed)
    elif beamline == 'SIXS':
        offsets = (0, 0, 0, offset_inplane, 0)  # beta, mu, beta, gamma del
        qconv = xu.experiment.QConversion(['y-', 'z+'], ['y-', 'z+', 'y-'], r_i=beam_direction)  # for SIXS
        # 2S+3D goniometer (SIXS goniometer, sample: beta, mu     detector: beta, gamma, del
        # beta is below both sample and detector circles
        # the vector is giving the direction of the primary beam
        # convention for coordinate system: x downstream; z upwards; y to the "outside" (right-handed)
    elif beamline == 'CRISTAL':
        offsets = (0, offset_inplane, 0)  # komega, gamma, delta
        qconv = xu.experiment.QConversion(['y-'], ['z+', 'y-'], r_i=beam_direction)  # for CRISTAL
        # 1S+2D goniometer (CRISTAL goniometer, sample: mgomega    detector: gamma, delta
        # the vector is giving the direction of the primary beam
        # convention for coordinate system: x downstream; z upwards; y to the "outside" (right-handed)
    elif beamline == 'P10':
        offsets = (0, 0, 0, 0, offset_inplane, 0)  # mu, omega, chi, phi, gamma del
        qconv = xu.experiment.QConversion(['z+', 'y-', 'x+', 'z-'], ['z+', 'y-'], r_i=beam_direction)  # for CRISTAL
        # 4S+2D goniometer (P10 goniometer, sample: mu, omega, chi,phi   detector: gamma, delta
        # the vector is giving the direction of the primary beam
        # convention for coordinate system: x downstream; z upwards; y to the "outside" (right-handed)
    else:
        raise ValueError("Incorrect value for parameter 'beamline'")

    return qconv, offsets


def load_cristal_data(logfile, header, scan_number, detector, flatfield, hotpixels):
    """
    Load ID01 data, apply filters and concatenate it for phasing.

    :param logfile: h5py File object of CRISTAL .nxs scan file
    :param header: string, header of data path in CRISTAL .nxs files
    :param scan_number: the scan number to load
    :param detector: the detector object: Class experiment_utils.Detector()
    :param flatfield: the 2D flatfield array
    :param hotpixels: the 2D hotpixels array
    :return:
     - the 3D data array in the detector frame and the 3D mask array
     - a logical array of length = initial frames number. A frame used will be set to True, a frame unused to False.
     - the monitor values for normalization
    """
    mask_2d = np.zeros((detector.nb_pixel_y, detector.nb_pixel_x))

    tmp_data = logfile[header + '_' + str('{:04d}'.format(scan_number))]['scan_data']['data_06'][:]

    nb_img = tmp_data.shape[0]
    data = np.zeros((nb_img, detector.roi[1] - detector.roi[0], detector.roi[3] - detector.roi[2]))

    for idx in range(nb_img):
        ccdraw = tmp_data[idx, :, :]
        ccdraw, mask_2d = remove_hotpixels(data=ccdraw, mask=mask_2d, hotpixels=hotpixels)
        if detector.name == "Maxipix":
            ccdraw, mask_2d = mask_maxipix(ccdraw, mask_2d)
        else:
            raise ValueError('Detector ', detector.name, 'not supported for CRISTAL')
        ccdraw = flatfield * ccdraw
        ccdraw = ccdraw[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
        data[idx, :, :] = ccdraw

    mask_2d = mask_2d[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
    data, mask_2d = check_pixels(data=data, mask=mask_2d, debugging=False)
    mask3d = np.repeat(mask_2d[np.newaxis, :, :], nb_img, axis=0)
    mask3d[np.isnan(data)] = 1
    data[np.isnan(data)] = 0

    frames_logical = np.ones(nb_img)

    monitor = logfile[header + '_' + str('{:04d}'.format(scan_number))]['scan_data']['data_04'][:]

    return data, mask3d, monitor, frames_logical


def load_flatfield(flatfield_file):
    """
    Load a flatfield file.

    :param flatfield_file: the path of the flatfield file
    :return: a 2D flatfield
    """
    if flatfield_file != "":
        flatfield = np.load(flatfield_file)
        npz_key = flatfield.files
        flatfield = flatfield[npz_key[0]]
        if flatfield.ndim != 2:
            raise ValueError('flatfield should be a 2D array')
    else:
        flatfield = None
    return flatfield


def load_hotpixels(hotpixels_file):
    """
    Load a hotpixels file.

    :param hotpixels_file: the path of the hotpixels file
    :return: a 2D array of hotpixels (1 for hotpixel, 0 for normal pixel)
    """
    if hotpixels_file != "":
        hotpixels = np.load(hotpixels_file)
        npz_key = hotpixels.files
        hotpixels = hotpixels[npz_key[0]]
        if hotpixels.ndim == 3:
            hotpixels = hotpixels.sum(axis=0)
        if hotpixels.ndim != 2:
            raise ValueError('hotpixels should be a 2D array')
        hotpixels[np.nonzero(hotpixels)] = 1
    else:
        hotpixels = None
    return hotpixels


def load_id01_data(logfile, scan_number, detector, flatfield, hotpixels):
    """
    Load ID01 data, apply filters and concatenate it for phasing.

    :param logfile: Silx SpecFile object containing the information about the scan and image numbers
    :param scan_number: the scan number to load
    :param detector: the detector object: Class experiment_utils.Detector()
    :param flatfield: the 2D flatfield array
    :param hotpixels: the 2D hotpixels array
    :return:
     - the 3D data array in the detector frame and the 3D mask array
     - the monitor values for normalization
     - frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
       A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    """
    mask_2d = np.zeros((detector.nb_pixel_y, detector.nb_pixel_x))

    labels = logfile[str(scan_number) + '.1'].labels  # motor scanned
    labels_data = logfile[str(scan_number) + '.1'].data  # motor scanned

    ccdfiletmp = os.path.join(detector.datadir, detector.template_imagefile)

    try:
        monitor = labels_data[labels.index('exp1'), :]  # mon2 monitor at ID01
    except ValueError:
        monitor = labels_data[labels.index('mon2'), :]  # exp1 for old data at ID01

    try:
        ccdn = labels_data[labels.index(detector.counter), :]
    except ValueError:
        raise ValueError(detector.counter, 'not in the list, the detector name may be wrong')

    nb_img = len(ccdn)
    data = np.zeros((nb_img, detector.roi[1] - detector.roi[0], detector.roi[3] - detector.roi[2]))
    for idx in range(nb_img):
        i = int(ccdn[idx])
        e = fabio.open(ccdfiletmp % i)
        ccdraw = e.data
        ccdraw, mask_2d = remove_hotpixels(data=ccdraw, mask=mask_2d, hotpixels=hotpixels)
        if detector.name == "Eiger2M":
            ccdraw, mask_2d = mask_eiger(data=ccdraw, mask=mask_2d)
        elif detector.name == "Maxipix":
            ccdraw, mask_2d = mask_maxipix(data=ccdraw, mask=mask_2d)
        else:
            raise ValueError('Detector ', detector.name, 'not supported for ID01')
        ccdraw = flatfield * ccdraw
        ccdraw = ccdraw[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
        data[idx, :, :] = ccdraw

    mask_2d = mask_2d[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
    data, mask_2d = check_pixels(data=data, mask=mask_2d, debugging=False)
    mask3d = np.repeat(mask_2d[np.newaxis, :, :], nb_img, axis=0)
    mask3d[np.isnan(data)] = 1
    data[np.isnan(data)] = 0

    frames_logical = np.ones(nb_img)

    return data, mask3d, monitor, frames_logical


def load_p10_data(logfile, detector, flatfield, hotpixels, headerlines):
    """
    Load P10 data, apply filters and concatenate it for phasing.

    :param logfile: path of the . fio file containing the information about the scan
    :param detector: the detector object: Class experiment_utils.Detector()
    :param flatfield: the 2D flatfield array
    :param hotpixels: the 2D hotpixels array
    :param headerlines: number of header lines before scanned motor position in .fio file (only for P10 dataset)
    :return:
     - the 3D data array in the detector frame and the 3D mask array
     - the monitor values for normalization
     - frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
       A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.

    """
    import hdf5plugin  # should be imported before h5py
    import h5py
    mask_2d = np.zeros((detector.nb_pixel_y, detector.nb_pixel_x))

    ccdfiletmp = os.path.join(detector.datadir, detector.template_imagefile % 1)
    h5file = h5py.File(ccdfiletmp, 'r')

    try:
        tmp_data = h5file['entry']['data']['data'][:]
    except OSError:
        raise OSError('hdf5plugin is not installed')
    nb_img = tmp_data.shape[0]
    data = np.zeros((nb_img, detector.roi[1] - detector.roi[0], detector.roi[3] - detector.roi[2]))

    for idx in range(nb_img):

        ccdraw, mask2d = remove_hotpixels(data=tmp_data[idx, :, :], mask=mask_2d, hotpixels=hotpixels)
        if detector.name == "Eiger4M":
            ccdraw, mask_2d = mask_eiger4m(data=ccdraw, mask=mask_2d)
        else:
            raise ValueError('Detector ', detector.name, 'not supported for ID01')
        ccdraw = flatfield * ccdraw
        ccdraw = ccdraw[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
        data[idx, :, :] = ccdraw

    mask_2d = mask_2d[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
    data, mask_2d = check_pixels(data=data, mask=mask_2d, debugging=False)
    mask3d = np.repeat(mask_2d[np.newaxis, :, :], nb_img, axis=0)
    mask3d[np.isnan(data)] = 1
    data[np.isnan(data)] = 0

    frames_logical = np.ones(nb_img)
    fio = open(logfile, 'r')
    monitor = np.zeros(nb_img)
    for ii in range(headerlines):  # header
        fio.readline()

    line_counter = 0
    for ii in range(nb_img):
        line = fio.readline()
        line = line.strip()
        columns = line.split()
        if columns[0] == '!':
            raise ValueError("Wrong value for the parameter 'headerlines'")
        monitor[line_counter] = columns[7]  # ipetra  # TODO detect automatically the index for ipetra
        line_counter += 1
    fio.close()

    return data, mask3d, monitor, frames_logical


def load_sixs_data(logfile, detector, flatfield, hotpixels):
    """
    Load SIXS data, apply filters and concatenate it for phasing.

    :param logfile: nxsReady Dataset object of SIXS .nxs scan file
    :param detector: the detector object: Class experiment_utils.Detector()
    :param flatfield: the 2D flatfield array
    :param hotpixels: the 2D hotpixels array
    :return:
     - the 3D data array in the detector frame and the 3D mask array
     - the monitor values for normalization
     - frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
       A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    """
    mask_2d = np.zeros((detector.nb_pixel_y, detector.nb_pixel_x))

    data = logfile.mfilm[:]
    monitor = logfile.imon1[:]

    data = data[1:, :, :]  # first frame is duplicated
    monitor = monitor[1:]  # first frame is duplicated
    frames_logical = np.ones(data.shape[0])

    nb_img = data.shape[0]
    for idx in range(nb_img):
        ccdraw = data[idx, :, :]
        ccdraw, mask_2d = remove_hotpixels(data=ccdraw, mask=mask_2d, hotpixels=hotpixels)
        if detector.name == "Maxipix":
            ccdraw, mask_2d = mask_maxipix(data=ccdraw, mask=mask_2d)
        else:
            raise ValueError('Detector ', detector.name, 'not supported for SIXS')
        ccdraw = flatfield * ccdraw
        ccdraw = ccdraw[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
        data[idx, :, :] = ccdraw

    mask_2d = mask_2d[detector.roi[0]:detector.roi[1], detector.roi[2]:detector.roi[3]]
    data, mask_2d = check_pixels(data=data, mask=mask_2d, debugging=False)
    mask3d = np.repeat(mask_2d[np.newaxis, :, :], nb_img, axis=0)
    mask3d[np.isnan(data)] = 1
    data[np.isnan(data)] = 0
    return data, mask3d, monitor, frames_logical


def mask_eiger(data, mask):
    """
    Mask data measured with an Eiger2M detector

    :param data: the 2D data to mask
    :param mask: the 2D mask to be updated
    :return: the masked data and the updated mask
    """
    if data.ndim != 2 or mask.ndim != 2:
        raise ValueError('Data and mask should be 2D arrays')

    if data.shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data is ', data.shape, ' while mask is ', mask.shape)

    data[:, 255: 259] = 0
    data[:, 513: 517] = 0
    data[:, 771: 775] = 0
    data[0: 257, 72: 80] = 0
    data[255: 259, :] = 0
    data[511: 552, :0] = 0
    data[804: 809, :] = 0
    data[1061: 1102, :] = 0
    data[1355: 1359, :] = 0
    data[1611: 1652, :] = 0
    data[1905: 1909, :] = 0
    data[1248:1290, 478] = 0
    data[1214:1298, 481] = 0
    data[1649:1910, 620:628] = 0

    mask[:, 255: 259] = 1
    mask[:, 513: 517] = 1
    mask[:, 771: 775] = 1
    mask[0: 257, 72: 80] = 1
    mask[255: 259, :] = 1
    mask[511: 552, :] = 1
    mask[804: 809, :] = 1
    mask[1061: 1102, :] = 1
    mask[1355: 1359, :] = 1
    mask[1611: 1652, :] = 1
    mask[1905: 1909, :] = 1
    mask[1248:1290, 478] = 1
    mask[1214:1298, 481] = 1
    mask[1649:1910, 620:628] = 1
    return data, mask


def mask_eiger4m(data, mask):
    """
    Mask data measured with an Eiger4M detector

    :param data: the 2D data to mask
    :param mask: the 2D mask to be updated
    :return: the masked data and the updated mask
    """
    if data.ndim != 2 or mask.ndim != 2:
        raise ValueError('Data and mask should be 2D arrays')

    if data.shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data is ', data.shape, ' while mask is ', mask.shape)

    data[:, 1029:1041] = 0
    data[513:552, :] = 0
    data[1064:1103, :] = 0
    data[1614:1654, :] = 0

    mask[:, 1029:1041] = 1
    mask[513:552, :] = 1
    mask[1064:1103, :] = 1
    mask[1614:1654, :] = 1
    return data, mask


def mask_maxipix(data, mask):
    """
    Mask data measured with a Maxipix detector

    :param data: the 2D data to mask
    :param mask: the 2D mask to be updated
    :return: the masked data and the updated mask
    """
    if data.ndim != 2 or mask.ndim != 2:
        raise ValueError('Data and mask should be 2D arrays')

    if data.shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data is ', data.shape, ' while mask is ', mask.shape)

    data[:, 255:261] = 0
    data[255:261, :] = 0

    mask[:, 255:261] = 1
    mask[255:261, :] = 1
    return data, mask


def mean_filter(data, nb_neighbours, mask, interpolate=False, debugging=False):
    """
    Apply a mean filter if the empty pixel is surrounded by nb_neighbours or more pixels

    :param data: 2D array to be filtered
    :param nb_neighbours: minimum number of non-zero neighboring pixels for median filtering
    :param mask: 2D mask array
    :param interpolate: if False will mask isolated pixels based on 'nb_neighbours',
      if True will interpolate isolated pixels based on 'nb_neighbours'
    :type interpolate: bool
    :param debugging: set to True to see plots
    :type debugging: bool
    :return: updated data and mask, number of pixels treated
    """

    if data.ndim != 2 or mask.ndim != 2:
        raise ValueError('Data and mask should be 2D arrays')

    if debugging:
        gu.combined_plots(tuple_array=(data, mask), tuple_sum_frames=(False, False), tuple_sum_axis=(0, 0),
                          tuple_width_v=(np.nan, np.nan), tuple_width_h=(np.nan, np.nan), tuple_colorbar=(True, True),
                          tuple_vmin=(-1, 0), tuple_vmax=(np.nan, 1), tuple_scale=('log', 'linear'),
                          tuple_title=('Data before filtering', 'Mask before filtering'), reciprocal_space=True)
    zero_pixels = np.argwhere(data == 0)
    nb_pixels = 0
    for indx in range(zero_pixels.shape[0]):
        pixrow = zero_pixels[indx, 0]
        pixcol = zero_pixels[indx, 1]
        temp = data[pixrow-1:pixrow+2, pixcol-1:pixcol+2]
        if temp.size != 0 and temp.sum() > 24 and sum(sum(temp != 0)) >= nb_neighbours:
            # mask/interpolate if at least 3 photons in each neighboring pixels
            nb_pixels = nb_pixels + 1
            if interpolate:
                value = temp.sum() / sum(sum(temp != 0))
                data[pixrow, pixcol] = value
                mask[pixrow, pixcol] = 0
            else:
                mask[pixrow, pixcol] = 1
    if interpolate:
        print("Nb of filtered pixel: ", nb_pixels)
    else:
        print("Nb of masked pixel: ", nb_pixels)

    if debugging:
        gu.combined_plots(tuple_array=(data, mask), tuple_sum_frames=(False, False), tuple_sum_axis=(0, 0),
                          tuple_width_v=(np.nan, np.nan), tuple_width_h=(np.nan, np.nan), tuple_colorbar=(True, True),
                          tuple_vmin=(-1, 0), tuple_vmax=(np.nan, 1), tuple_scale=('log', 'linear'),
                          tuple_title=('Data after filtering', 'Mask after filtering'), reciprocal_space=True)
    return data, nb_pixels, mask


def normalize_dataset(array, raw_monitor, frames_logical, norm_to_min=True, debugging=False):
    """
    Normalize array using the monitor values.

    :param array: the 3D array to be normalized
    :param raw_monitor: the monitor values
    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param norm_to_min: normalize to min(monitor), which does not multiply the noise
    :type norm_to_min: bool
    :param debugging: set to True to see plots
    :type debugging: bool
    :return:
     - normalized dataset
     - updated monitor
     - a title for plotting
    """
    ndim = array.ndim
    if ndim != 3:
        raise ValueError('Array should be 3D')

    if debugging:
        gu.imshow_plot(array=array, sum_frames=True, sum_axis=1, vmin=0, scale='log', title='Data before normalization')

    # crop/pad monitor depending on frames_logical array
    monitor = np.zeros((frames_logical != 0).sum())
    nb_overlap = 0
    nb_padded = 0
    for idx in range(len(frames_logical)):
        if frames_logical[idx] == -1:  # padded frame, no monitor value for this
            if norm_to_min:
                monitor[idx - nb_overlap] = raw_monitor.min()
            else:  # norm to max
                monitor[idx - nb_overlap] = raw_monitor.max()
            nb_padded = nb_padded + 1
        elif frames_logical[idx] == 1:
            monitor[idx - nb_overlap] = raw_monitor[idx-nb_padded]
        else:
            nb_overlap = nb_overlap + 1

    if nb_padded != 0:
        print('Monitor value set to 1 for ', nb_padded, ' frames padded')

    if norm_to_min:
        monitor = monitor.min() / monitor
        title = 'monitor.min() / monitor'
    else:  # norm to max
        monitor = monitor / monitor.max()
        title = 'monitor / monitor.max()'

    nbz = array.shape[0]
    if len(monitor) != nbz:
        raise ValueError('The frame number and the monitor data length are different:'
                         ' Got ', nbz, 'frames but ', len(monitor), ' monitor values')

    for idx in range(nbz):
        array[idx, :, :] = array[idx, :, :] * monitor[idx]

    return array, monitor, title


def primes(number):
    """
    Returns the prime decomposition of n as a list. Adapted from PyNX.

    :param number: the integer to be decomposed
    :return: the list of prime dividers of number
    """
    if not isinstance(number, int):
        raise TypeError('Number should be an integer')

    list_primes = [1]
    assert (number > 0)
    i = 2
    while i * i <= number:
        while number % i == 0:
            list_primes.append(i)
            number //= i
        i += 1
    if number > 1:
        list_primes.append(number)
    return list_primes


def regrid_cristal(frames_logical, logfile, header, scan_number, detector, setup, hxrd):
    """
    Load CRISTAL motor positions and calculate q positions for orthogonalization.

    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param logfile: Silx SpecFile object containing the information about the scan and image numbers
    :param header: string, header of data path in CRISTAL .nxs files
    :param scan_number: the scan number to load
    :param detector: the detector object: Class experiment_utils.Detector()
    :param setup: the experimental setup: Class SetupPreprocessing()
    :param hxrd: an initialized xrayutilities HXRD object used for the orthogonalization of the dataset
    :return:
     - qx, qz, qy components for the dataset
     - updated frames_logical
    """
    if setup.rocking_angle != 'outofplane':
        raise ValueError('Only out of plane rocking curve implemented for CRISTAL')

    mgomega = logfile[header +
                      '_' + str('{:04d}'.format(scan_number))]['scan_data']['actuator_1_1'][:] / 1e6

    delta = logfile[header +
                    '_' + str('{:04d}'.format(scan_number))]['CRISTAL']['Diffractometer']['I06-C-C07-EX-DIF-DELTA'][
        'position'][:]

    gamma = \
        logfile[header +
                '_' +
                str('{:04d}'.format(scan_number))]['CRISTAL']['Diffractometer']['I06-C-C07-EX-DIF-GAMMA']['position'][:]

    qx, qy, qz = hxrd.Ang2Q.area(mgomega, gamma, delta, en=setup.energy, delta=detector.offsets)

    return qx, qz, qy, frames_logical


def regrid_id01(follow_bragg, frames_logical, logfile, scan_number, detector, setup, hxrd):
    """
    Load ID01 motor positions and calculate q positions for orthogonalization.

    :param follow_bragg: True when for energy scans the detector was also scanned to follow the Bragg peak
    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param logfile: Silx SpecFile object containing the information about the scan and image numbers
    :param scan_number: the scan number to load
    :param detector: the detector object: Class experiment_utils.Detector()
    :param setup: the experimental setup: Class SetupPreprocessing()
    :param hxrd: an initialized xrayutilities HXRD object used for the orthogonalization of the dataset
    :return:
     - qx, qz, qy components for the dataset
     - updated frames_logical
    """
    motor_names = logfile[str(scan_number) + '.1'].motor_names  # positioners
    motor_positions = logfile[str(scan_number) + '.1'].motor_positions  # positioners
    labels = logfile[str(scan_number) + '.1'].labels  # motor scanned
    labels_data = logfile[str(scan_number) + '.1'].data  # motor scanned

    energy = setup.energy  # will be overridden if setup.rocking_angle is 'energy'

    if follow_bragg:
        delta = list(labels_data[labels.index('del'), :])  # scanned
    else:
        delta = motor_positions[motor_names.index('del')]  # positioner
    nu = motor_positions[motor_names.index('nu')]  # positioner
    chi = 0

    if setup.rocking_angle == "outofplane":
        eta = labels_data[labels.index('eta'), :]
        phi = motor_positions[motor_names.index('phi')]
    elif setup.rocking_angle == "inplane":
        phi = labels_data[labels.index('phi'), :]
        eta = motor_positions[motor_names.index('eta')]
    elif setup.rocking_angle == "energy":
        raw_energy = list(labels_data[labels.index('energy'), :])  # in kev, scanned
        phi = motor_positions[motor_names.index('phi')]  # positioner
        eta = motor_positions[motor_names.index('eta')]  # positioner
        if follow_bragg == 1:
            delta = list(labels_data[labels.index('del'), :])  # scanned

        nb_overlap = 0
        energy = raw_energy[:]
        for idx in range(len(raw_energy) - 1):
            if raw_energy[idx + 1] == raw_energy[idx]:  # duplicate energy when undulator gap is changed
                frames_logical[idx + 1] = 0
                energy.pop(idx - nb_overlap)
                if follow_bragg == 1:
                    delta.pop(idx - nb_overlap)
                nb_overlap = nb_overlap + 1
        energy = np.array(energy) * 1000.0 - 6  # switch to eV, 6 eV of difference at ID01

    else:
        raise ValueError('Invalid rocking angle ', setup.rocking_angle, 'for ID01')

    qx, qy, qz = hxrd.Ang2Q.area(eta, chi, phi, nu, delta, en=energy, delta=detector.offsets)

    return qx, qz, qy, frames_logical


def regrid_p10(frames_logical, logfile, detector, setup, hxrd, headerlines):
    """
    Load SIXS motor positions and calculate q positions for orthogonalization.

    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param logfile: Silx SpecFile object containing the information about the scan and image numbers
    :param detector: the detector object: Class experiment_utils.Detector()
    :param setup: the experimental setup: Class SetupPreprocessing()
    :param hxrd: an initialized xrayutilities HXRD object used for the orthogonalization of the dataset
    :param headerlines: number of header lines before scanned motor position in .fio file (only for P10 dataset)
    :return:
     - qx, qz, qy components for the dataset
     - updated frames_logical
    """
    # TODO: find motors in specfile
    om = []
    fio = open(logfile, 'r')
    for index in range(headerlines):  # header
        fio.readline()
    for index, myline in enumerate(fio, 0):
        myline = myline.strip()
        mycolumns = myline.split()
        if mycolumns[0] == '!':
            break
        om.append(mycolumns[0])
    om = np.asarray(om, dtype=float)

    fio.close()

    # qx, qy, qz = hxrd.Ang2Q.area(mu, om, chi, phi, gamma, delta, en=setup.energy, delta=detector.offsets)

    qx = []
    qz = []
    qy = []

    return qx, qz, qy, frames_logical


def regrid_sixs(frames_logical, logfile, detector, setup, hxrd):
    """
    Load SIXS motor positions and calculate q positions for orthogonalization.

    :param frames_logical: array of initial length the number of measured frames. In case of padding the length changes.
     A frame whose index is set to 1 means that it is used, 0 means not used, -1 means padded (added) frame.
    :param logfile: Silx SpecFile object containing the information about the scan and image numbers
    :param detector: the detector object: Class experiment_utils.Detector()
    :param setup: the experimental setup: Class SetupPreprocessing()
    :param hxrd: an initialized xrayutilities HXRD object used for the orthogonalization of the dataset
    :return:
     - qx, qz, qy components for the dataset
     - updated frames_logical
    """
    temp_delta = logfile.delta[:]
    temp_gamma = logfile.gamma[:]
    temp_mu = logfile.mu[:]

    delta = np.zeros((frames_logical != 0).sum())
    gamma = np.zeros((frames_logical != 0).sum())
    mu = np.zeros((frames_logical != 0).sum())

    nb_overlap = 0
    for idx in range(len(frames_logical)):
        if frames_logical[idx]:
            delta[idx - nb_overlap] = temp_delta[idx]
            gamma[idx - nb_overlap] = temp_gamma[idx]
            mu[idx - nb_overlap] = temp_mu[idx]
        else:
            nb_overlap = nb_overlap + 1

    delta = delta.mean()  # not scanned
    gamma = gamma.mean()  # not scanned

    qx, qy, qz = hxrd.Ang2Q.area(setup.grazing_angle, mu, setup.grazing_angle, gamma, delta, en=setup.energy,
                                 delta=detector.offsets)

    return qx, qz, qy, frames_logical


def remove_hotpixels(data, mask, hotpixels):
    """
    Remove hot pixels from CCD frames and update the mask

    :param data: 2D or 3D array
    :param hotpixels: 2D array of hotpixels
    :param mask: array of the same shape as data
    :return: the data without hotpixels and the updated mask
    """
    if hotpixels.ndim == 3:  # 3D array
        print('Hotpixels is a 3D array, summing along the first axis')
        hotpixels = hotpixels.sum(axis=0)

    if data.shape != mask.shape:
        raise ValueError('Data and mask must have the same shape\n data is ', data.shape, ' while mask is ', mask.shape)

    if data.ndim == 3:  # 3D array
        if data[0, :, :].shape != hotpixels.shape:
            raise ValueError('Data and hotpixels must have the same shape\n data is ',
                             data.shape, ' while hotpixels is ', hotpixels.shape)
        for idx in range(data.shape[0]):
            temp_data = data[idx, :, :]
            temp_mask = mask[idx, :, :]
            temp_data[hotpixels == 1] = 0  # numpy array is mutable hence data will be modified  # TODO: check that
            temp_mask[hotpixels == 1] = 1  # numpy array is mutable hence mask will be modified
    elif data.ndim == 2:  # 2D array
        if data.shape != hotpixels.shape:
            raise ValueError('Data and hotpixels must have the same shape\n data is ',
                             data.shape, ' while hotpixels is ', hotpixels.shape)
        data[hotpixels == 1] = 0
        mask[hotpixels == 1] = 1
    else:
        raise ValueError('2D or 3D data array expected, got ', data.ndim, 'D')
    return data, mask


def smaller_primes(number, maxprime=13, required_dividers=(4,)):
    """
    Find the closest integer <=n (or list/array of integers), for which the largest prime divider is <=maxprime,
    and has to include some dividers. The default values for maxprime is the largest integer accepted
    by the clFFT library for OpenCL GPU FFT. Adapted from PyNX.

    :param number: the integer number
    :param maxprime: the largest prime factor acceptable
    :param required_dividers: a list of required dividers for the returned integer.
    :return: the integer (or list/array of integers) fulfilling the requirements
    """
    if (type(number) is list) or (type(number) is tuple) or (type(number) is np.ndarray):
        vn = []
        for i in number:
            assert (i > 1 and maxprime <= i)
            while try_smaller_primes(i, maxprime=maxprime, required_dividers=required_dividers) is False:
                i = i - 1
                if i == 0:
                    return 0
            vn.append(i)
        if type(number) is np.ndarray:
            return np.array(vn)
        return vn
    else:
        assert (number > 1 and maxprime <= number)
        while try_smaller_primes(number, maxprime=maxprime, required_dividers=required_dividers) is False:
            number = number - 1
            if number == 0:
                return 0
        return number


def try_smaller_primes(number, maxprime=13, required_dividers=(4,)):
    """
    Check if the largest prime divider is <=maxprime, and optionally includes some dividers. Adapted from PyNX.

    :param number: the integer number for which the prime decomposition will be checked
    :param maxprime: the maximum acceptable prime number. This defaults to the largest integer accepted by the clFFT
        library for OpenCL GPU FFT.
    :param required_dividers: list of required dividers in the prime decomposition. If None, this check is skipped.
    :return: True if the conditions are met.
    """
    p = primes(number)
    if max(p) > maxprime:
        return False
    if required_dividers is not None:
        for k in required_dividers:
            if number % k != 0:
                return False
    return True


def update_aliens(key, pix, piy, original_data, updated_data, updated_mask, figure, width, dim, idx,
                  vmax, vmin=0):
    """
    Update the plot while removing the parasitic diffraction intensity in 3D dataset

    :param key: the keyboard key which was pressed
    :param pix: the x value of the mouse pointer
    :param piy: the y value of the mouse pointer
    :param original_data: the 3D data array before masking aliens
    :param updated_data: the current 3D data array
    :param updated_mask: the current 3D mask array
    :param figure: the figure instance
    :param width: the half_width of the masking window
    :param dim: the axis currently under review (axis 0, 1 or 2)
    :param idx: the frame index in the current axis
    :param vmax: the higher boundary for the colorbar
    :param vmin: the lower boundary for the colorbar
    :return: updated data, mask and controls
    """
    if original_data.ndim != 3 or updated_data.ndim != 3 or updated_mask.ndim != 3:
        raise ValueError('original_data, updated_data and updated_mask should be 3D arrays')

    nbz, nby, nbx = original_data.shape
    stop_masking = False
    if dim > 2:
        raise ValueError('dim should be 0, 1 or 2')

    if key == 'u':
        idx = idx + 1
        figure.clear()
        if dim == 0:
            if idx > nbz - 1:
                idx = 0
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            if idx > nby - 1:
                idx = 0
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            if idx > nbx - 1:
                idx = 0
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'd':
        idx = idx - 1
        figure.clear()
        if dim == 0:
            if idx < 0:
                idx = nbz - 1
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            if idx < 0:
                idx = nby - 1
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            if idx < 0:
                idx = nbx - 1
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'up':
        width = width + 1
        print('width: ', width)

    elif key == 'down':
        width = width - 1
        if width < 0:
            width = 0
        print('width: ', width)

    elif key == 'right':
        vmax = vmax * 2
        print('vmax: ', vmax)
        figure.clear()
        if dim == 0:
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'left':
        vmax = vmax / 2
        if vmax < 1:
            vmax = 1
        print('vmax: ', vmax)
        figure.clear()
        if dim == 0:
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'm':
        figure.clear()
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        if dim == 0:
            updated_data[idx, starty:piy + width + 1, startx:pix + width + 1] = 0
            updated_mask[idx, starty:piy + width + 1, startx:pix + width + 1] = 1
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            updated_data[starty:piy + width + 1, idx, startx:pix + width + 1] = 0
            updated_mask[starty:piy + width + 1, idx, startx:pix + width + 1] = 1
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            updated_data[starty:piy + width + 1, startx:pix + width + 1, idx] = 0
            updated_mask[starty:piy + width + 1, startx:pix + width + 1, idx] = 1
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'b':
        figure.clear()
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        if dim == 0:
            updated_data[idx, starty:piy + width + 1, startx:pix + width + 1] = \
                original_data[idx, starty:piy + width + 1, startx:pix + width + 1]
            updated_mask[idx, starty:piy + width + 1, startx:pix + width + 1] = 0
            plt.imshow(updated_data[idx, :, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbz) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 1:
            updated_data[starty:piy + width + 1, idx, startx:pix + width + 1] = \
                original_data[starty:piy + width + 1, idx, startx:pix + width + 1]
            updated_mask[starty:piy + width + 1, idx, startx:pix + width + 1] = 0
            plt.imshow(updated_data[:, idx, :], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nby) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        elif dim == 2:
            updated_data[starty:piy + width + 1, startx:pix + width + 1, idx] = \
                original_data[starty:piy + width + 1, startx:pix + width + 1, idx]
            updated_mask[starty:piy + width + 1, startx:pix + width + 1, idx] = 0
            plt.imshow(updated_data[:, :, idx], vmin=vmin, vmax=vmax)
            plt.title("Frame " + str(idx + 1) + "/" + str(nbx) + "\n"
                      "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                      "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'q':
        stop_masking = True

    return updated_data, updated_mask, width, vmax, idx, stop_masking


def update_aliens_2d(key, pix, piy, original_data, updated_data, updated_mask, figure, width,
                     vmax, vmin=0):
    """
    Update the plot while removing the parasitic diffraction intensity in 2D dataset

    :param key: the keyboard key which was pressed
    :param pix: the x value of the mouse pointer
    :param piy: the y value of the mouse pointer
    :param original_data: the 2D data array before masking aliens
    :param updated_data: the current 2D data array
    :param updated_mask: the current 2D mask array
    :param figure: the figure instance
    :param width: the half_width of the masking window
    :param vmax: the higher boundary for the colorbar
    :param vmin: the lower boundary for the colorbar
    :return: updated data, mask and controls
    """
    if original_data.ndim != 2 or updated_data.ndim != 2 or updated_mask.ndim != 2:
        raise ValueError('original_data, updated_data and updated_mask should be 2D arrays')

    stop_masking = False

    if key == 'up':
        width = width + 1
        print('width: ', width)

    elif key == 'down':
        width = width - 1
        if width < 0:
            width = 0
        print('width: ', width)

    elif key == 'right':
        vmax = vmax * 2
        print('vmax: ', vmax)
        figure.clear()

        plt.imshow(updated_data, vmin=vmin, vmax=vmax)
        plt.title("m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'left':
        vmax = vmax / 2
        if vmax < 1:
            vmax = 1
        print('vmax: ', vmax)
        figure.clear()

        plt.imshow(updated_data, vmin=vmin, vmax=vmax)
        plt.title("m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'm':
        figure.clear()
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width

        updated_data[starty:piy + width + 1, startx:pix + width + 1] = 0
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 1
        plt.imshow(updated_data, vmin=vmin, vmax=vmax)
        plt.title("m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'b':
        figure.clear()
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width

        updated_data[starty:piy + width + 1, startx:pix + width + 1] = \
            original_data[starty:piy + width + 1, startx:pix + width + 1]
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 0
        plt.imshow(updated_data, vmin=vmin, vmax=vmax)
        plt.title("m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'q':
        stop_masking = True

    return updated_data, updated_mask, width, vmax, stop_masking


def update_mask(key, pix, piy, original_data, original_mask, updated_data, updated_mask, figure, flag_pause, points,
                xy, width, dim, vmax, vmin=0, masked_color=0.1):
    """
    Update the mask to remove parasitic diffraction intensity and hotpixels in 3D dataset.

    :param key: the keyboard key which was pressed
    :param pix: the x value of the mouse pointer
    :param piy: the y value of the mouse pointer
    :param original_data: the 3D data array before masking
    :param original_mask: the 3D mask array before masking
    :param updated_data: the current 3D data array
    :param updated_mask: the temporary 2D mask array with updated points
    :param figure: the figure instance
    :param flag_pause: set to 1 to stop registering vertices using mouse clicks
    :param points: list of all point coordinates: points=np.stack((x, y), axis=0).T with x=x.flatten() , y = y.flatten()
     given x,y=np.meshgrid(np.arange(nx), np.arange(ny))
    :param xy: the list of vertices which defines a polygon to be masked
    :param width: the half_width of the masking window
    :param dim: the axis currently under review (axis 0, 1 or 2)
    :param vmax: the higher boundary for the colorbar
    :param vmin: the lower boundary for the colorbar
    :param masked_color: the value that detector gaps should have in plots
    :return: updated data, mask and controls
    """
    if original_data.ndim != 3 or updated_data.ndim != 3 or original_mask.ndim != 3:
        raise ValueError('original_data, updated_data and original_mask should be 3D arrays')
    if updated_mask.ndim != 2:
        raise ValueError('updated_mask should be 2D arrays')

    nbz, nby, nbx = original_data.shape
    stop_masking = False
    if dim != 0 and dim != 1 and dim != 2:
        raise ValueError('dim should be 0, 1 or 2')

    if key == 'up':
        width = width + 1
        print('width: ', width)

    elif key == 'down':
        width = width - 1
        if width < 0:
            width = 0
        print('width: ', width)

    elif key == 'right':
        vmax = vmax + 1
        print('vmax: ', vmax)
        array = updated_data.sum(axis=dim)
        array[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(array)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'left':
        vmax = vmax - 1
        if vmax < 1:
            vmax = 1
        print('vmax: ', vmax)
        array = updated_data.sum(axis=dim)
        array[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(array)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'm':
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 1
        array = updated_data.sum(axis=dim)
        array[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(array)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'b':
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 0
        array = updated_data.sum(axis=dim)
        array[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(array)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'a':  # restart mask from beginning
        updated_data = np.copy(original_data)
        xy = []
        print('restart masking')
        if dim == 0:
            updated_data[
                original_mask == 1] = masked_color / nbz  # masked pixels plotted with the value of masked_pixel
            updated_mask = np.zeros((nby, nbx))
        if dim == 1:
            updated_data[
                original_mask == 1] = masked_color / nby  # masked pixels plotted with the value of masked_pixel
            updated_mask = np.zeros((nbz, nbx))
        if dim == 2:
            updated_data[
                original_mask == 1] = masked_color / nbx  # masked pixels plotted with the value of masked_pixel
            updated_mask = np.zeros((nbz, nby))
        figure.clear()
        plt.imshow(np.log10(abs(updated_data.sum(axis=dim))), vmin=0, vmax=vmax)
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'p':  # plot masked image
        if len(xy) != 0:
            xy.append(xy[0])
            print(xy)
            if dim == 0:
                ind = Path(np.array(xy)).contains_points(points).reshape((nby, nbx))
            elif dim == 1:
                ind = Path(np.array(xy)).contains_points(points).reshape((nbz, nbx))
            else:  # dim=2
                ind = Path(np.array(xy)).contains_points(points).reshape((nbz, nby))
            updated_mask[ind] = 1
        array = updated_data.sum(axis=dim)
        array[updated_mask == 1] = masked_color
        xy = []  # allow to mask a different area
        figure.clear()
        plt.imshow(np.log10(abs(array)), vmin=vmin, vmax=vmax)
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()
        thismanager = plt.get_current_fig_manager()
        thismanager.toolbar.pan()  # deactivate the pan
    elif key == 'x':
        if not flag_pause:
            flag_pause = True
            print('pause for pan/zoom')
        else:
            flag_pause = False
            print('resume masking')

    elif key == 'q':
        stop_masking = True

    return updated_data, updated_mask, flag_pause, xy, width, vmax, stop_masking


def update_mask_2d(key, pix, piy, original_data, original_mask, updated_data, updated_mask, figure, flag_pause, points,
                   xy, width, vmax, vmin=0, masked_color=0.1):
    """
    Update the mask to remove parasitic diffraction intensity and hotpixels for 2d dataset.

    :param key: the keyboard key which was pressed
    :param pix: the x value of the mouse pointer
    :param piy: the y value of the mouse pointer
    :param original_data: the 2D data array before masking
    :param original_mask: the 2D mask array before masking
    :param updated_data: the current 2D data array
    :param updated_mask: the temporary 2D mask array with updated points
    :param figure: the figure instance
    :param flag_pause: set to 1 to stop registering vertices using mouse clicks
    :param points: list of all point coordinates: points=np.stack((x, y), axis=0).T with x=x.flatten() , y = y.flatten()
     given x,y=np.meshgrid(np.arange(nx), np.arange(ny))
    :param xy: the list of vertices which defines a polygon to be masked
    :param width: the half_width of the masking window
    :param vmax: the higher boundary for the colorbar
    :param vmin: the lower boundary for the colorbar
    :param masked_color: the value that detector gaps should have in plots
    :return: updated data, mask and controls
    """
    if original_data.ndim != 2 or updated_data.ndim != 2 or original_mask.ndim != 2 or updated_mask.ndim != 2:
        raise ValueError('original_data, updated_data, original_mask and updated_mask should be 2D arrays')

    nby, nbx = original_data.shape
    stop_masking = False

    if key == 'up':
        width = width + 1
        print('width: ', width)

    elif key == 'down':
        width = width - 1
        if width < 0:
            width = 0
        print('width: ', width)

    elif key == 'right':
        vmax = vmax + 1
        print('vmax: ', vmax)
        updated_data[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'left':
        vmax = vmax - 1
        if vmax < 1:
            vmax = 1
        print('vmax: ', vmax)
        updated_data[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'm':
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 1
        updated_data[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'b':
        if (piy - width) < 0:
            starty = 0
        else:
            starty = piy - width
        if (pix - width) < 0:
            startx = 0
        else:
            startx = pix - width
        updated_mask[starty:piy + width + 1, startx:pix + width + 1] = 0
        updated_data[updated_mask == 1] = masked_color
        myfig = plt.gcf()
        myaxs = myfig.gca()
        xmin, xmax = myaxs.get_xlim()
        ymin, ymax = myaxs.get_ylim()
        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=vmin, vmax=vmax)
        myaxs = myfig.gca()
        myaxs.set_xlim([xmin, xmax])
        myaxs.set_ylim([ymin, ymax])
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'a':  # restart mask from beginning
        updated_data = np.copy(original_data)
        xy = []
        print('restart masking')

        updated_data[
            original_mask == 1] = masked_color  # masked pixels plotted with the value of masked_pixel
        updated_mask = np.zeros((nby, nbx))

        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=0, vmax=vmax)
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()

    elif key == 'p':  # plot masked image
        if len(xy) != 0:
            xy.append(xy[0])
            print(xy)
            ind = Path(np.array(xy)).contains_points(points).reshape((nby, nbx))
            updated_mask[ind] = 1

        updated_data[updated_mask == 1] = masked_color
        xy = []  # allow to mask a different area
        figure.clear()
        plt.imshow(np.log10(abs(updated_data)), vmin=vmin, vmax=vmax)
        plt.title('x to pause/resume masking for pan/zoom \n'
                  'p plot mask ; a restart ; click to select vertices\n'
                  "m mask ; b unmask ; q quit ; u next frame ; d previous frame\n"
                  "up larger ; down smaller ; right darker ; left brighter")
        plt.draw()
        thismanager = plt.get_current_fig_manager()
        thismanager.toolbar.pan()  # deactivate the pan
    elif key == 'x':
        if not flag_pause:
            flag_pause = True
            print('pause for pan/zoom')
        else:
            flag_pause = False
            print('resume masking')

    elif key == 'q':
        stop_masking = True

    return updated_data, updated_mask, flag_pause, xy, width, vmax, stop_masking


def zero_pad(array, padding_width=np.array([0, 0, 0, 0, 0, 0]), mask_flag=False, debugging=False):
    """
    Pad obj with zeros.

    :param array: 3D array to be padded
    :param padding_width: number of zero pixels to padd on each side
    :param mask_flag: set to True to pad with 1, False to pad with 0
    :type mask_flag: bool
    :param debugging: set to True to see plots
    :type debugging: bool
    :return: obj padded with zeros
    """
    if array.ndim != 3:
        raise ValueError('3D Array expected, got ', array.ndim, 'D')

    nbz, nby, nbx = array.shape
    padding_z0 = padding_width[0]
    padding_z1 = padding_width[1]
    padding_y0 = padding_width[2]
    padding_y1 = padding_width[3]
    padding_x0 = padding_width[4]
    padding_x1 = padding_width[5]
    if debugging:
        gu.multislices_plot(array=array, sum_frames=False, invert_yaxis=True, plot_colorbar=True, vmin=0, vmax=1,
                            title='Array before padding')

    if mask_flag:
        newobj = np.ones((nbz + padding_z0 + padding_z1, nby + padding_y0 + padding_y1, nbx + padding_x0 + padding_x1))
    else:
        newobj = np.zeros((nbz + padding_z0 + padding_z1, nby + padding_y0 + padding_y1, nbx + padding_x0 + padding_x1))
    newobj[padding_z0:padding_z0 + nbz, padding_y0:padding_y0 + nby, padding_x0:padding_x0 + nbx] = array
    if debugging:
        gu.multislices_plot(array=newobj, sum_frames=False, invert_yaxis=True, plot_colorbar=True, vmin=0, vmax=1,
                            title='Array after padding')
    return newobj