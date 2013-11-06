import os
import numpy as np

from .db import surfs
from . import dataset

def unmask(mask, data):
    """unmask(mask, data)

    `Unmasks` the data, assuming it's been masked.

    Parameters
    ----------
    mask : array_like
        The data mask
    data : array_like
        Actual MRI data to unmask
    """
    nvox = mask.sum()
    if data.shape[0] == nvox:
        data = data[np.newaxis]
    elif nvox not in data.shape:
        raise ValueError('Invalid mask for the data')

    if data.shape[-1] in (3, 4):
        if data.dtype != np.uint8:
            raise TypeError('Invalid dtype for raw dataset')
        #raw dataset, unmask with an alpha channel
        output = np.zeros((len(data),)+mask.shape+(4,), dtype=np.uint8)
        output[:, mask > 0, :data.shape[-1]] = data
        if data.shape[-1] == 3:
            output[:, mask > 0, 3] = 255
    else:
        output = (np.nan*np.ones((len(data),)+mask.shape)).astype(data.dtype)
        output[:, mask > 0] = data

    return output.squeeze()

def detrend_median(data, kernel=15):
    from scipy.signal import medfilt
    lowfreq = medfilt(data, [1, kernel, kernel])
    return data - lowfreq

def detrend_gradient(data, diff=3):
    return (np.array(np.gradient(data, 1, diff, diff))**2).sum(0)

def detrend_poly(data, polyorder = 10, mask=None):
    from scipy.special import legendre
    polys = [legendre(i) for i in range(polyorder)]
    s = data.shape
    b = data.ravel()[:,np.newaxis]
    lins = np.mgrid[-1:1:s[0]*1j, -1:1:s[1]*1j, -1:1:s[2]*1j].reshape(3,-1)

    if mask is not None:
        lins = lins[:,mask.ravel() > 0]
        b = b[mask.ravel() > 0]
    
    A = np.vstack([[p(i) for i in lins] for p in polys]).T
    x, res, rank, sing = np.linalg.lstsq(A, b)

    detrended = b.ravel() - np.dot(A, x).ravel()
    if mask is not None:
        filled = np.zeros_like(mask)
        filled[mask > 0] = detrended
        return filled
    else:
        return detrended.reshape(*s)

def mosaic(data, dim=0, show=True, **kwargs):
    """mosaic(data, dim=0, show=True)

    Turns volume data into a mosaic, useful for quickly viewing volumetric data
    IN RADIOLOGICAL COORDINATES (LEFT SIDE OF FIGURE IS RIGHT SIDE OF SUBJECT)

    Parameters
    ----------
    data : array_like
        3D volumetric data to mosaic
    dim : int
        Dimension across which to mosaic. Default 0.
    show : bool
        Display mosaic with matplotlib? Default True.
    """
    if data.ndim not in (3, 4):
        raise ValueError("Invalid data shape")
    plane = list(data.shape)
    slices = plane.pop(dim)
    height, width = plane[:2]
    aspect = width / float(height)
    square = np.sqrt(slices / aspect)
    nwide = int(np.ceil(square))
    ntall = int(np.ceil(slices*aspect / nwide))

    shape = (ntall * (height+1) + 1, nwide * (width+1) + 1)
    if data.dtype == np.uint8:
        output = np.zeros(shape+(4,), dtype=np.uint8)
    else:
        output = (np.nan*np.ones(shape)).astype(data.dtype)

    sl = [slice(None), slice(None), slice(None)]
    for h in range(ntall):
        for w in range(nwide):
            sl[dim] = h*nwide+w
            if sl[dim] < slices:
                hsl = slice(h*(height+1)+1, (h+1)*(height+1))
                wsl = slice(w*(width+1)+1, (w+1)*(width+1))
                if data.dtype == np.uint8:
                    output[hsl, wsl, :data.shape[3]] = data[sl]
                    if data.shape[3] == 3:
                        output[hsl, wsl, 3] = 255
                else:    
                    output[hsl, wsl] = data[sl]
    
    if show:
        from matplotlib import pyplot as plt
        plt.imshow(output, **kwargs)
        plt.axis('off')

    return output, (nwide, ntall)

def show_slice(dataview, **kwargs):
    import nibabel
    from matplotlib import cm
    import matplotlib.pyplot as plt

    dataview = dataset.normalize(dataview)
    if not isinstance(dataview.data, dataset.BrainData):
        raise TypeError('Only simple views supported by matplotlib')
    if not isinstance(dataview.data, dataset.VolumeData):
        raise TypeError('Only volumetric data may be visualized in show_slice')

    subject = dataview.data.subject
    xfmname = dataview.data.xfmname
    imshow_kw = dict(vmin=dataview.vmin, vmax=dataview.vmax, cmap=dataview.cmap)
    imshow_kw.update(kwargs)

    anat = surfs.getAnat(subject, 'raw').get_data().T
    data, _ = epi2anatspace(dataview.data)

    data[data < dataview.vmin] = np.nan

    state = dict(slice=data.shape[0]*.66, dim=0, pad=())

    fig = plt.figure()
    ax = fig.add_subplot(111)
    anatomical = ax.imshow(anat[state['pad'] + (state['slice'],)], cmap=cm.gray, aspect='equal')
    functional = ax.imshow(data[state['pad'] + (state['slice'],)], aspect='equal', **imshow_kw)

    def update():
        print("showing dim %d, slice %d"%(state['dim'] % 3, state['slice']))
        functional.set_data(data[state['pad'] + (state['slice'],)])
        anatomical.set_data(anat[state['pad'] + (state['slice'],)])
        fig.canvas.draw()

    def switchslice(event):
        state['dim'] += 1
        state['pad'] = (slice(None),)*(state['dim'] % 3)
        update()

    def scrollslice(event):
        if event.button == 'up':
            state['slice'] += 1
        elif event.button == 'down':
            state['slice'] -= 1
        update()

    fig.canvas.mpl_connect('scroll_event', scrollslice)
    fig.canvas.mpl_connect('button_press_event', switchslice)
    return fig

def show_mip(data, **kwargs):
    '''Display a maximum intensity projection for the data, using three subplots'''
    import matplotlib.pyplot as plt
    fig = plt.figure()
    fig.add_subplot(221).imshow(data.max(0), **kwargs)
    fig.add_subplot(222).imshow(data.max(1), **kwargs)
    fig.add_subplot(223).imshow(data.max(2), **kwargs)
    return fig

def show_glass(dataview, pad=10):
    '''Create a classic "glass brain" view of the data, with the outline'''
    import nibabel
    nib = surfs.getAnat(subject, 'fiducial')
    mask = nib.get_data()

    left, right = np.nonzero(np.diff(mask.max(0).max(0)))[0][[0,-1]]
    front, back = np.nonzero(np.diff(mask.max(0).max(1)))[0][[0,-1]]
    top, bottom = np.nonzero(np.diff(mask.max(1).max(1)))[0][[0,-1]]

    glass = np.zeros((mask.shape[1], mask.shape[2]*2), dtype=bool)
    glass[:, :mask.shape[2]] = mask.max(0)
    #this requires a lot of logic to put the image into a canonical orientation
    #too much work for something we'll never use
    raise NotImplementedError

def epi2anatspace(volumedata):
    """Resamples epi-space [data] into the anatomical space for the given [subject]
    using the given transformation [xfm].

    Returns the data and a temporary filename.
    """
    import tempfile
    import subprocess
    import nibabel

    volumedata = dataset.normalize(volumedata).data
    subject = volumedata.subject
    xfmname = volumedata.xfmname
    data = volumedata.volume

    ## Get transform (remember cortex estimates anat-to-epi!)
    xfm = surfs.getXfm(subject, xfmname)
    fslxfm = xfm.to_fsl(surfs.getAnat(subject, 'raw').get_filename())
    ## Invert to epi-to-anat
    #print('orig transform')
    #print(fslxfm)
    fslxfm = np.linalg.inv(fslxfm)
    #print('inverted transform')
    #print(fslxfm)
    ## Save out into ascii file
    xfmfilename = tempfile.mktemp(".mat")
    with open(xfmfilename, "w") as xfmh:
        for ll in fslxfm.tolist():      
            xfmh.write(" ".join(["%0.5f"%f for f in ll])+"\n")

    ## Save out data into nifti file
    datafile = nibabel.Nifti1Image(data.T, xfm.reference.get_affine(), xfm.reference.get_header())
    datafilename = tempfile.mktemp(".nii")
    nibabel.save(datafile, datafilename)

    ## Reslice epi-space image
    raw = surfs.getAnat(subject, type='raw').get_filename()
    outfilename = tempfile.mktemp(".nii")
    subprocess.call(["fsl5.0-flirt",
                     "-ref", raw,
                     "-in", datafilename,
                     "-applyxfm",
                     "-init", xfmfilename,
                     #"-interp", "sinc",
                     "-out", outfilename])

    ## Load resliced image
    outdata = nibabel.load(outfilename+".gz").get_data().T

    return outdata, outfilename
def anat2epispace(data,subject,xfmname):
    """Resamples anat-space volumedata into the epi space for the given [subject]
    and transformation [xfm] incorporated into the volumedata object.

    Returns the data and a temporary filename.
    """
    import tempfile
    import subprocess
    import nibabel

    #volumedata = dataset.normalize(volumedata).data
    #subject = volumedata.subject
    #xfmname = volumedata.xfmname
    #data = volumedata.volume

    ## Get transform (pycortex estimates anat-to-epi)
    xfm = surfs.getXfm(subject, xfmname)
    anatNII = surfs.getAnat(subject, type='raw')
    fslxfm = xfm.to_fsl(anatNII.get_filename())
    ## Save out into ascii file
    xfmfilename = tempfile.mktemp(".mat")
    print('xfm file: %s'%xfmfilename)
    with open(xfmfilename, "w") as xfmh:
        for ll in fslxfm.tolist():
            xfmh.write(" ".join(["%0.5f"%f for f in ll])+"\n")

    ## Save out data into nifti file
    datafile = nibabel.Nifti1Image(data.T, anatNII.get_affine(), anatNII.get_header())
    datafilename = tempfile.mktemp(".nii")
    nibabel.save(datafile, datafilename)

    ## Reslice epi-space image
    epiNIIf = xfm.reference.get_filename()
    outfilename = tempfile.mktemp(".nii")
    subprocess.call(["fsl5.0-flirt",
                     "-in", datafilename,
                     "-ref", epiNIIf,
                     "-out", outfilename,
                     "-init", xfmfilename,
                     #"-interp", "sinc",
                     "-applyxfm"])

    ## Load resliced image
    outdata = nibabel.load(outfilename+".gz").get_data().T

    return outdata, outfilename

def fslview(*ims):
    import tempfile
    import subprocess

    fnames = []
    tempfiles = []
    for im in ims:
        if not (isinstance(im, str) and os.path.exists(im)):
            import nibabel
            tf = tempfile.NamedTemporaryFile(suffix=".nii.gz")
            tempfiles.append(tf)
            nib = nibabel.Nifti1Image(im.T, np.eye(4))
            nib.to_filename(tf.name)
            fnames.append(tf.name)
        else:
            fnames.append(im)

    subprocess.call(["fslview"] + fnames)
