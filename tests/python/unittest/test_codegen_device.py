import tvm
from tvm.addon import testing
import numpy as np

def test_add_pipeline():
    n = tvm.Var('n')
    A = tvm.placeholder((n,), name='A')
    B = tvm.placeholder((n,), name='B')
    C = tvm.compute(A.shape, lambda *i: A(*i) + B(*i), name='C')
    s = tvm.Schedule(C.op)

    # GPU schedule have to split by gridIdx and threadIdx
    num_thread = 256
    xo, xi = s[C].split(C.op.axis[0], factor=num_thread)
    s[C].bind(xo, tvm.thread_axis("threadIdx.x"))
    s[C].bind(xi, tvm.thread_axis("blockIdx.x"))

    # compile to IR
    bounds = tvm.schedule.InferBound(s)
    stmt = tvm.schedule.ScheduleOps(s, bounds)
    Ab = tvm.Buffer(A.shape, A.dtype, name='A')
    Bb = tvm.Buffer(B.shape, B.dtype, name='B')
    Cb = tvm.Buffer(C.shape, C.dtype, name='C')
    stmt = tvm.ir_pass.StorageFlatten(stmt, {A: Ab, B:Bb, C:Cb})
    stmt = tvm.ir_pass.Simplify(stmt)
    fapi = tvm.ir_pass.MakeAPI(stmt, "myadd", [Ab, Bb, Cb], 0)
    fsplits = tvm.ir_pass.SplitHostDevice(fapi)

    def check_target(device, host="stackvm"):
        if not tvm.codegen.enabled(host):
            return
        if not tvm.codegen.enabled(device):
            return
        ctx = tvm.gpu(0) if device == "cuda" else tvm.cl(0)
        mhost = tvm.codegen.build(fsplits[0], host)
        mdev = tvm.codegen.build(fsplits[1:], device)
        mhost.import_module(mdev)
        code = mdev.get_source()
        f = mhost.entry_func

        # launch the kernel.
        n = 1027
        a = tvm.nd.array(np.random.uniform(size=n).astype(Ab.dtype), ctx)
        b = tvm.nd.array(np.random.uniform(size=n).astype(Bb.dtype), ctx)
        c = tvm.nd.array(np.zeros(n, dtype=Cb.dtype), ctx)
        f(a, b, c)
        np.testing.assert_allclose(
            c.asnumpy(), a.asnumpy() + b.asnumpy())

    def check_module_save(device, host="stackvm"):
        if not tvm.codegen.enabled(host):
            return
        if not tvm.codegen.enabled(device):
            return
        ctx = tvm.gpu(0) if device == "cuda" else tvm.cl(0)
        fmt = "ptx" if device == "cuda" else "cl"
        mhost = tvm.codegen.build(fsplits[0], host)
        mdev = tvm.codegen.build(fsplits[1:], device)
        temp = testing.tempdir()
        mpath = temp.relpath("test.%s" % fmt)
        mdev.save(mpath)
        mdev2 = tvm.module.load(mpath)
        mhost.import_module(mdev2)
        f = mhost.entry_func
        # launch the kernel.
        n = 1027
        a = tvm.nd.array(np.random.uniform(size=n).astype(Ab.dtype), ctx)
        b = tvm.nd.array(np.random.uniform(size=n).astype(Bb.dtype), ctx)
        c = tvm.nd.array(np.zeros(n, dtype=Cb.dtype), ctx)
        f(a, b, c)
        np.testing.assert_allclose(
            c.asnumpy(), a.asnumpy() + b.asnumpy())

    check_target("cuda", host="stackvm")
    check_target("cuda", host="llvm")
    check_module_save("cuda", host="stackvm")


if __name__ == "__main__":
    test_add_pipeline()