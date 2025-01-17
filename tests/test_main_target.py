import amoco.cas.expressions
from amoco.sa import forward as fwd


def test_001():
    c = amoco.cas.expressions.cst(0x804849D, 32)
    t = fwd.target(c, None)
    assert t.dirty is False
    T = t.expand()
    assert len(T) == 1
    tc = T[0]
    assert tc.cst._is_cst
    assert tc.cst == c


def test_002(ploop):
    p = amoco.load_program(ploop)
    z = fwd.fforward(p)
    c = amoco.cas.expressions.cst(0x804849D, 32)
    z.init_spool(c)
    t = z.spool.pop(0)
    assert isinstance(t, fwd.target)
    assert z.check_ext_target(t) is False
    assert t.cst._is_cst
    assert t.econd is None
    b0 = next(z.iterblocks(loc=t.cst))
    n0 = fwd.cfg.node(b0)
    assert t.parent is None
    z.add_root_node(n0)
    assert z.G.C[0].sV[0] is n0
    z.update_spool(n0, t.parent)
    assert len(z.spool) == 1
    t = z.spool.pop(0)
    assert t.cst == 0x80484D0
    b1 = next(z.iterblocks(t.cst))
    n1 = fwd.cfg.node(b1)
    e0 = fwd.cfg.link(n0, n1, data=t.econd)
    e = z.G.add_edge(e0)
    assert e is e0
    z.update_spool(n1, n0)
    assert len(z.spool) == 2
