import numpy as np

from mpi4py import MPI
from pyoperators.core import Operator
from pyoperators.decorators import (real, linear, square, inplace)
from pyoperators.utils import tointtuple

__all__ = ['DistributionGlobalOperator',
           'DistributionIdentityOperator']


@real
@linear
class DistributionGlobalOperator(Operator):
    """
    Distribute sections of a global map to different MPI processes.

    It is a block column operator, whose blocks are distributed across the MPI
    processes.

                   |I   O|
    MPI rank 1 --> |  O  |
                   |O   O|
                   +-----+
                   |O   O|
    MPI rank 2 --> |  I  |
                   |O   O|
                   +-----+
                   |O   O|
    MPI rank 3 --> |  O  |
                   |O   I|

    Example
    -------
    Given the file 'example_dgo.py':

    import numpy as np
    from tamasis import *
    from mpi4py import MPI
    x_global = np.array([1,2,3])
    d = DistributionGlobalOperator(x_global.shape)
    x_local = d(x_global)
    print MPI.COMM_WORLD.rank, ':', x_local, np.all(d.T(x_local) == x_global)

    the following command:
    $ mpirun -n 3 python example_dgo.py

    will output (in random rank order):
    0 : [1] True
    1 : [2] True
    2 : [3] True
    
    """

    def __init__(self, shapein, commout=None, **keywords):

        if shapein is None:
            raise ValueError('The input shape is None.')
        commout = commout or MPI.COMM_WORLD

        shapeout = distribute_shape(shapein, comm=commout)
        slice_ = distribute_slice(shapein[0], comm=commout)

        counts = []
        offsets = [0]
        for rank in range(commout.size):
            s = distribute_slice(shapein[0], rank=rank, comm=commout)
            n = (s.stop - s.start) * np.product(shapein[1:])
            counts.append(n)
            offsets.append(offsets[-1] + n)
        offsets.pop()
        Operator.__init__(self, commin=MPI.COMM_SELF, commout=commout,
                          shapein=shapein, shapeout=shapeout, **keywords)
        self.slice = slice_
        self.counts = counts
        self.offsets = offsets

    def direct(self, input, output):
        output[:] = input[self.slice.start:self.slice.stop]

    def transpose(self, input, output):
        if input.itemsize != output.itemsize:
            input = input.astype(output.dtype)
        nbytes = output.itemsize
        self.commout.Allgatherv(input.view(np.byte), [output.view(np.byte),
            ([c * nbytes for c in self.counts], [o * nbytes for o in \
            self.offsets])])


@real
@linear
@square
@inplace
class DistributionIdentityOperator(Operator):
    """
    Distribute a global map, of which each MPI process has a copy, to the
    MPI processes.

    It is a block column operator whose blocks are identities distributed
    across the MPI processes.

                   |1   O|
    MPI rank 0 --> |  .  |
                   |O   1|
                   +-----+
                   |1   O|
    MPI rank 1 --> |  .  |
                   |O   1|
                   +-----+
                   |1   O|
    MPI rank 2 --> |  .  |
                   |O   1|

    For an MPI process, the direct method is the Identity and the transpose
    method is a reduction.

    Example
    -------
    Given the file 'example_dio.py':

    import numpy as np
    from tamasis import *
    from mpi4py import MPI
    x_global = np.array([1,1,1])
    d = DistributionIdentityOperator()
    x_local = x_global * (MPI.COMM_WORLD.rank + 1)
    print MPI.COMM_WORLD.rank, ':', np.all(d(x_global)==x_global), d.T(x_local)

    the following command:
    $ mpirun -n 3 python example_dio.py

    will output (in random rank order):
    0 : True [6 6 6]
    1 : True [6 6 6]
    2 : True [6 6 6]
    
    """

    def __init__(self, commout=None, **keywords):
        Operator.__init__(self, commin=MPI.COMM_SELF,
                          commout=commout or MPI.COMM_WORLD, **keywords)

    def direct(self, input, output):
        if self.same_data(input, output):
            return
        output[...] = input

    def transpose(self, input, output):
        if not self.same_data(input, output):
            output[...] = input
        self.commout.Allreduce(MPI.IN_PLACE, output, op=MPI.SUM)


def distribute_shape(shape, rank=None, size=None, comm=None):
    """
    Return the shape of a local array given the shape of a global array,
    according to the rank of the MPI job, The load is distributed along
    the first dimension.
    """
    if rank is None or size is None:
        comm = comm or MPI.COMM_WORLD
    if size is None:
        size = comm.size
    if rank is None:
        rank = comm.rank

    shape = tointtuple(shape)
    if len(shape) == 0:
        if size > 1:
            raise ValueError('It is ambiguous to split a scalar across processe'
                             's.')
        return ()
    nglobal = shape[0]
    nlocal = nglobal // size + ((nglobal % size) > rank)
    return (nlocal,) + tuple(shape[1:])


def distribute_slice(nglobal, rank=None, size=None, comm=None):
    """
    Given a number of ordered global work items, return the slice that brackets
    the items distributed to a local MPI job.
    """
    if rank is None or size is None:
        comm = comm or MPI.COMM_WORLD
    if size is None:
        size = comm.size
    if rank is None:
        rank = comm.rank
    nlocal = nglobal // size + ((nglobal % size) > rank)
    start = nglobal // size * rank + min(rank, nglobal % size)
    stop = start + nlocal
    return slice(start, stop)