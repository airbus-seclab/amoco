# -*- coding: utf-8 -*-

# This code is part of Amoco
# Copyright (C) 2006-2011 Axel Tillequin (bdcht3@gmail.com)
# published under GPLv2 license
"""
cas/expressions.py
==================

The expressions module implements all above :class:`exp` classes.
All symbolic representation of data in amoco rely on these expressions.
"""

from amoco.config import conf
from amoco.logger import Log

logger = Log(__name__)
logger.debug("loading module")
from amoco.ui import render
from amoco.ui.graphics import Engine
import operator


# decorators:
# ------------


def _checkarg1_exp(f):
    def checkarg1_exp(*args):
        if len(args) > 0 and isinstance(args[0], exp):
            return f(*args)
        else:
            logger.error("first arg is not an expression")
            raise TypeError(args)

    return checkarg1_exp


def _checkarg_sizes(f):
    def checkarg_sizes(self, n):
        if self.size != n.size:
            if self.size > 0 and n.size > 0:
                logger.error("size mismatch")
                raise ValueError(n)
        return f(self, n)

    return checkarg_sizes


def _checkarg_numeric(f):
    def checkarg_numeric(self, n):
        if isinstance(n, int):
            n = cst(n, self.size)
        elif isinstance(n, (float)):
            n = cfp(n, self.size)
        return f(self, n)

    return checkarg_numeric


def _checkarg_slice(f):
    def checkarg_slice(self, *args):
        i = args[0]
        if isinstance(i, slice):
            if i.step is not None:
                raise ValueError(i)
            if i.start < 0 or i.stop > self.size:
                logger.error("size mismatch")
                raise ValueError(i)
            if i.stop <= i.start:
                logger.error("invalid slice")
                raise ValueError(i)
        else:
            logger.error("argument should be a slice")
            raise TypeError(i)
        return f(self, *args)

    return checkarg_slice


# expression types:

et_cst = 0x00001
et_reg = 0x00002
# note:  0x00004 \
# note:  0x00008 / these 2 values are used as variants to other types.
et_vra = 0x00004
et_vrb = 0x00008
# note:  0x000#0 is for reg subtypes (STD/PC/FLAG/STACK/OTHER)
et_slc = 0x00100
et_ext = 0x00200
et_lab = 0x00400
et_mem = 0x00800
et_ptr = 0x01000
et_tst = 0x02000
et_eqn = 0x04000
et_vec = 0x08000
et_cmp = 0x10000
et_msk = 0x3FFFF

# ------------------------------------------------------------------------------
# exp is the core class for all expressions.
# It defines mandatory attributes, shared methods like dumps/loads, etc.
# ------------------------------------------------------------------------------


class exp(object):
    """the core class for all expressions.
    It defines mandatory attributes, shared methods like dumps/loads etc.

    Attributes:
        size (int): the bit size of the expression (default is 0.)
        sf (Bool): the sign flag of the expression (default is False: unsigned.)
        length (int): the byte size of the expression.
        mask (int): the bit mask of the expression.

    Note:
        len(exp) returns the byte size, assuming that size is a multiple of 8.
    """

    etype = 0
    __slots__ = ["size", "sf"]

    def __init__(self, size=0, sf=False):
        self.size = size
        self.sf = False

    def __len__(self):
        return self.length

    def signed(self):
        "consider expression as signed"
        self.sf = True
        return self

    def unsigned(self):
        "consider expression as unsigned"
        self.sf = False
        return self

    @property
    def length(self):  # length value is in bytes
        return self.size // 8

    @property
    def mask(self):
        return (1 << self.size) - 1

    def eval(self, env):
        "evalute expression in given :class:`mapper` env"
        if self._is_top:
            return top(self.size)
        if not self._is_def:
            return exp(self.size)
        else:
            raise NotImplementedError("can't eval %s" % self)

    def simplify(self, **kargs):
        "simplify expression based on predefined heuristics"
        return self

    def depth(self):
        "depth size of the expression tree"
        return 1.0

    def addr(self, env):
        raise TypeError("exp has no address")

    def dumps(self):
        "pickle expression"
        from pickle import dumps, HIGHEST_PROTOCOL

        return dumps(self, HIGHEST_PROTOCOL)

    def loads(self, s):
        "unpickle expression"
        from pickle import loads

        self = loads(s)
        return self

    def __unicode__(self):
        if self._is_top:
            return render.icons.top + ("%d" % self.size)
        if not self._is_def:
            return render.icons.bot + ("%d" % self.size)
        raise ValueError("void expression")

    def __format__(self, format_spec):
        return str(self)

    def __str__(self):
        res = self.__unicode__()
        try:
            return str(res)
        except UnicodeEncodeError:
            return res.encode("utf-8")

    def toks(self, **kargs):
        "returns list of pretty printing tokens of the expression"
        return [(render.Token.Literal, "%s" % self)]

    def pp(self, **kargs):
        "pretty-printed string of the expression"
        return Engine.engine.highlight(self.toks(**kargs))

    def bit(self, i):
        "extract i-th bit expression of the expression"
        i = i % self.size
        return self[i : i + 1]

    def bytes(self, sta=0, sto=None, endian=1):
        """
        returns the expression slice located at bytes [sta,sto]
        taking into account given endianess 1 (little)
        or -1 (big). Defaults to little endian.
        """
        s = slice(sta, sto)
        l = self.length
        sta, sto, stp = s.indices(l)
        if endian == -1:
            sta, sto = l - sto, l - sta
        return self[sta * 8 : sto * 8]

    # get item allows to extract the expression of a slice of the exp
    @_checkarg_slice
    def __getitem__(self, i):
        return slicer(self, i.start, i.stop - i.start)

    # set item allows to insert the expression of a slice in the exp
    # note: most child classes can't really inherit from this method
    # since the method makes sense only by returning an comp object
    # while __setitem__ is supposed to modify self...
    @_checkarg_slice
    def __setitem__(self, i, e):
        res = comp(self.size)
        res[0 : res.size] = self
        res[i.start : i.stop] = e
        return res.simplify()

    def extend(self, sign, size):
        "extend expression to given size, taking sign into account"
        xt = size - self.size
        if xt <= 0:
            return self
        sb = self[self.size - 1 : self.size]
        if sign is True:
            xx = tst(sb, cst(-1, xt), cst(0, xt))
            xx.sf = True
        else:
            xx = cst(0, xt)
            xx.sf = False
        return composer([self, xx])

    def signextend(self, size):
        "sign extend expression to given size"
        return self.extend(True, size)

    def zeroextend(self, size):
        "zero extend expression to given size"
        return self.extend(False, size)

    # arithmetic / logic methods : These methods are shared by all nodes.

    # unary operators:
    def __invert__(self):
        return oper(OP_NOT, self)

    def __neg__(self):
        return oper(OP_MIN, self)

    def __pos__(self):
        return self

    # binary operators:
    @_checkarg_numeric
    def __add__(self, n):
        return oper(OP_ADD, self, n)

    @_checkarg_numeric
    def __sub__(self, n):
        return oper(OP_MIN, self, n)

    @_checkarg_numeric
    def __mul__(self, n):
        return oper(OP_MUL, self, n)

    @_checkarg_numeric
    def __pow__(self, n):
        return oper(OP_MUL2, self, n)

    @_checkarg_numeric
    def __truediv__(self, n):
        return oper(OP_DIV, self, n)

    @_checkarg_numeric
    def __div__(self, n):
        return oper(OP_DIV, self, n)

    @_checkarg_numeric
    def __mod__(self, n):
        return oper(OP_MOD, self, n)

    @_checkarg_numeric
    def __floordiv__(self, n):
        return oper(OP_ASR, self, n)

    @_checkarg_numeric
    def __and__(self, n):
        return oper(OP_AND, self, n)

    @_checkarg_numeric
    def __or__(self, n):
        return oper(OP_OR, self, n)

    @_checkarg_numeric
    def __xor__(self, n):
        return oper(OP_XOR, self, n)

    # reflected operand cases:
    @_checkarg_numeric
    def __radd__(self, n):
        return oper(OP_ADD, n, self)

    @_checkarg_numeric
    def __rsub__(self, n):
        return oper(OP_MIN, n, self)

    @_checkarg_numeric
    def __rmul__(self, n):
        return oper(OP_MUL, n, self)

    @_checkarg_numeric
    def __rpow__(self, n):
        return oper(OP_MUL2, n, self)

    @_checkarg_numeric
    def __rand__(self, n):
        return oper(OP_AND, n, self)

    @_checkarg_numeric
    def __ror__(self, n):
        return oper(OP_OR, n, self)

    @_checkarg_numeric
    def __rxor__(self, n):
        return oper(OP_XOR, n, self)

    # shifts:
    @_checkarg_numeric
    def __lshift__(self, n):
        return oper(OP_LSL, self, n)

    @_checkarg_numeric
    def __rshift__(self, n):
        return oper(OP_LSR, self, n)

    # WARNING: comparison operators cmp returns a python bool
    # but any other operators always return an expression !
    def __hash__(self):
        return hash("%s" % self) + self.size

    # An expression defaults to False, and only bit1 will return True.
    def __bool__(self):
        return False

    def __eq__(self, n):
        # we inline checkarg_numeric only here:
        if isinstance(n, int):
            n = cst(n, self.size)
        elif isinstance(n, (float)):
            n = cfp(n, self.size)
        if hash(self) == hash(n):
            return bit1
        return oper(OP_EQ, self, n)

    @_checkarg_numeric
    def __ne__(self, n):
        if hash(self) == hash(n):
            return bit0
        return oper(OP_NEQ, self, n)

    @_checkarg_numeric
    def __lt__(self, n):
        if hash(self) == hash(n):
            return bit0
        return oper(OP_LT, self, n)

    @_checkarg_numeric
    def __le__(self, n):
        if hash(self) == hash(n):
            return bit1
        return oper(OP_LE, self, n)

    @_checkarg_numeric
    def __ge__(self, n):
        if hash(self) == hash(n):
            return bit1
        return oper(OP_GE, self, n)

    @_checkarg_numeric
    def __gt__(self, n):
        if hash(self) == hash(n):
            return bit0
        return oper(OP_GT, self, n)

    def to_smtlib(self, solver=None):
        "translate expression to its smt form"
        logger.warning("no SMT solver defined")
        raise NotImplementedError

    def is_(self, t):
        return t & self.etype

    def set_top(self):
        self.etype = ~(~self.etype & et_msk)

    @property
    def _is_def(self):
        return self.etype > 0

    @property
    def _is_top(self):
        return self.etype < 0

    @property
    def _is_cst(self):
        return et_cst & self.etype

    @property
    def _is_reg(self):
        return et_reg & self.etype

    @property
    def _is_cmp(self):
        return et_cmp & self.etype

    @property
    def _is_slc(self):
        return et_slc & self.etype

    @property
    def _is_mem(self):
        return et_mem & self.etype

    @property
    def _is_ext(self):
        return et_ext & self.etype

    @property
    def _is_lab(self):
        return et_lab & self.etype

    @property
    def _is_ptr(self):
        return et_ptr & self.etype

    @property
    def _is_tst(self):
        return et_tst & self.etype

    @property
    def _is_eqn(self):
        return et_eqn & self.etype

    @property
    def _is_vec(self):
        return et_vec & self.etype


class top(exp):
    """
    top expression represents symbolic values
    that have reached a high complexity threshold.

    Note:
    This expression is an absorbing element of the
    algebra. Any expression that involves a top
    expression results in a top expression.
    """

    etype = -et_msk - 1
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__

    def depth(self):
        return float("inf")


# -----------------------------------
# cst holds numeric immediate values
# -----------------------------------


class cst(exp):
    """
    cst expression represents concrete values (constants).

    Attributes:
        value (int): get the integer of the expression, taking into account
                     the sign flag.
    """

    __slots__ = ["v"]
    etype = et_cst
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__

    def __init__(self, v, size=32):
        if isinstance(v, bool):  # only True/False forces size=1 (not 0/1 !)
            v = 1 if v else 0
            size = 1
        self.sf = False if v >= 0 else True
        self.size = size
        self.v = v & self.mask

    @property
    def value(self):
        if self.sf and (self.v >> (self.size - 1) == 1):
            return -(self.v ^ self.mask) - 1
        else:
            return self.v

    # for slicing purpose:
    def __index__(self):
        return self.value

    # coercion to Python int:
    def __int__(self):
        return self.value

    # defaults to signed hex base
    def __unicode__(self):
        return "{:#x}".format(self.value)

    def toks(self, **kargs):
        return [(render.Token.Constant, "%s" % self)]

    def to_sym(self, ref):
        "cast into a symbol expression associated to name ref"
        return sym(ref, self.v, self.size)

    def to_bytes(self, endian=1):
        s = []
        v = self.v
        for i in range(0, self.size, 8):
            s.append(v & 0xFF)
            v = v >> 8
        return bytes(s[::endian])

    # eval of cst is always itself: (sf flag conserved)
    def eval(self, env):
        return cst(self.value, self.size)

    def zeroextend(self, size):
        return cst(self.v, max(size, self.size))

    def signextend(self, size):
        sf = self.sf
        self.sf = True
        v = self.value
        self.sf = sf
        return cst(v, max(size, self.size))

    # bit-slice (returns cst) :
    @_checkarg_slice
    def __getitem__(self, i):
        start = i.start or 0
        stop = i.stop or self.size
        return cst(self.v >> start, stop - start)

    def __invert__(self):
        # note: masking is needed because python uses unlimited ints
        # so ~0x80 means not(...0000080) = ...fffffef
        return cst((~(self.v)) & self.mask, self.size)

    def __neg__(self):
        return cst(-(self.value), self.size)

    @_checkarg_numeric
    @_checkarg_sizes
    def __add__(self, n):
        if n._is_cst:
            return cst(self.value + n.value, self.size)
        else:
            return exp.__add__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __sub__(self, n):
        if n._is_cst:
            return cst(self.value - n.value, self.size)
        else:
            return exp.__sub__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __mul__(self, n):
        if n._is_cst:
            return cst(self.value * n.value, self.size)
        else:
            return exp.__mul__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __pow__(self, n):
        if n._is_cst:
            return cst(self.value * n.value, 2 * self.size)
        else:
            return exp.__pow__(self, n)

    @_checkarg_numeric
    def __div__(self, n):
        if n._is_cst:
            return cst(self.value // n.value, self.size)
        else:
            return exp.__div__(self, n)

    @_checkarg_numeric
    def __truediv__(self, n):
        if n._is_cst:
            return cst(self.value // n.value, self.size)
        else:
            return exp.__truediv__(self, n)

    @_checkarg_numeric
    def __mod__(self, n):
        if n._is_cst:
            return cst(self.value % n.value, self.size)
        else:
            return exp.__mod__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __and__(self, n):
        if n._is_cst:
            return cst(self.v & n.v, self.size)
        else:
            return exp.__and__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __or__(self, n):
        if n._is_cst:
            return cst(self.v | n.v, self.size)
        else:
            return exp.__or__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __xor__(self, n):
        if n._is_cst:
            return cst(self.v ^ n.v, self.size)
        else:
            return exp.__xor__(self, n)

    @_checkarg_numeric
    def __lshift__(self, n):
        if n._is_cst:
            return cst(self.value << n.value, self.size)
        else:
            return exp.__lshift__(self, n)

    @_checkarg_numeric
    def __rshift__(self, n):
        self.sf = False  # rshift implements logical right shift
        if n._is_cst:
            return cst(self.value >> n.value, self.size)
        else:
            return exp.__rshift__(self, n)

    @_checkarg_numeric
    def __floordiv__(self, n):
        self.sf = True  # floordiv implements arithmetic right shift
        if n._is_cst:
            return cst(self.value >> n.value, self.size)
        else:
            return exp.__floordiv__(self, n)

    @_checkarg_numeric
    def __radd__(self, n):
        return n + self

    @_checkarg_numeric
    def __rsub__(self, n):
        return n - self

    @_checkarg_numeric
    def __rmul__(self, n):
        return n * self

    @_checkarg_numeric
    def __rpow__(self, n):
        return n**self

    @_checkarg_numeric
    def __rdiv__(self, n):
        return n / self

    @_checkarg_numeric
    def __rand__(self, n):
        return n & self

    @_checkarg_numeric
    def __ror__(self, n):
        return n | self

    @_checkarg_numeric
    def __rxor__(self, n):
        return n ^ self

    # the only atom that is considered True is the cst(1,1) (ie bit1 below)
    def __bool__(self):
        if self.size == 1 and self.v == 1:
            return True
        else:
            return False

    @_checkarg_numeric
    @_checkarg_sizes
    def __eq__(self, n):
        if n._is_cst:
            return cst(self.v == n.v)
        else:
            return exp.__eq__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __ne__(self, n):
        if n._is_cst:
            return cst(self.v != n.v)
        else:
            return exp.__ne__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __lt__(self, n):
        if n._is_cst:
            return cst(self.value < n.value)
        else:
            return exp.__lt__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __le__(self, n):
        if n._is_cst:
            return cst(self.value <= n.value)
        else:
            return exp.__le__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __ge__(self, n):
        if n._is_cst:
            return cst(self.value >= n.value)
        else:
            return exp.__ge__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __gt__(self, n):
        if n._is_cst:
            return cst(self.value > n.value)
        else:
            return exp.__gt__(self, n)


bit0 = cst(0, 1)
bit1 = cst(1, 1)
assert bool(bit1)


class sym(cst):
    "symbol expression extends cst with a reference name for pretty printing"

    __slots__ = ["ref"]
    __hash__ = cst.__hash__
    __eq__ = exp.__eq__

    def __init__(self, ref, v, size=32):
        self.ref = ref
        cst.__init__(self, v, size)

    def __unicode__(self):
        return "#%s" % self.ref


class cfp(exp):
    "floating point concrete value expression"

    __slots__ = ["v"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_cst

    def __init__(self, v, size=32):
        self.size = size
        self.v = float(v)

    @property
    def value(self):
        return self.v

    # coercion to integer:
    def __int__(self):
        return NotImplementedError

    def __unicode__(self):
        return "{:f}".format(self.value)

    def toks(self, **kargs):
        return [(render.Token.Constant, "%s" % self)]

    def eval(self, env):
        return cfp(self.value, self.size)

    def __neg__(self):
        return cfp(-(self.value), self.size)

    @_checkarg_numeric
    @_checkarg_sizes
    def __add__(self, n):
        if n._is_cst:
            return cfp(self.v + n.value, self.size)
        else:
            return exp.__add__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __sub__(self, n):
        if n._is_cst:
            return cfp(self.v - n.value, self.size)
        else:
            return exp.__sub__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __mul__(self, n):
        if n._is_cst:
            return cfp(self.v * n.value, self.size)
        else:
            return exp.__mul__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __pow__(self, n):
        if n._is_cst:
            return cfp(self.v * n.value, self.size)
        else:
            return exp.__pow__(self, n)

    @_checkarg_numeric
    def __div__(self, n):
        if n._is_cst:
            return cfp(self.v / n.value, self.size)
        else:
            return exp.__div__(self, n)

    @_checkarg_numeric
    def __truediv__(self, n):
        if n._is_cst:
            return cfp(self.v / n.value, self.size)
        else:
            return exp.__truediv__(self, n)

    @_checkarg_numeric
    def __radd__(self, n):
        return n + self

    @_checkarg_numeric
    def __rsub__(self, n):
        return n - self

    @_checkarg_numeric
    def __rmul__(self, n):
        return n * self

    @_checkarg_numeric
    def __rpow__(self, n):
        return n**self

    @_checkarg_numeric
    def __rdiv__(self, n):
        return n / self

    @_checkarg_numeric
    @_checkarg_sizes
    def __eq__(self, n):
        if n._is_cst:
            return cst(self.value == n.value)
        else:
            return exp.__eq__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __ne__(self, n):
        if n._is_cst:
            return cst(self.value != n.value)
        else:
            return exp.__ne__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __lt__(self, n):
        if n._is_cst:
            return cst(self.value < n.value)
        else:
            return exp.__lt__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __le__(self, n):
        if n._is_cst:
            return cst(self.value <= n.value)
        else:
            return exp.__le__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __ge__(self, n):
        if n._is_cst:
            return cst(self.value >= n.value)
        else:
            return exp.__ge__(self, n)

    @_checkarg_numeric
    @_checkarg_sizes
    def __gt__(self, n):
        if n._is_cst:
            return cst(self.value > n.value)
        else:
            return exp.__gt__(self, n)


# ------------------------------------------------------------------------------
# reg holds 32-bit register reference (refname).
# ------------------------------------------------------------------------------


class reg(exp):
    "symbolic register expression"

    __slots__ = ["ref", "etype", "_subrefs", "__protect"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__

    def __init__(self, refname, size=32):
        self.__protect = False
        self.size = size
        self.__protect = True
        self.sf = False
        self.ref = refname
        self._subrefs = {}
        self.etype = et_reg | (regtype.cur or regtype.STD)

    def __unicode__(self):
        return "%s" % self.ref

    def toks(self, **kargs):
        return [(render.Token.Register, "%s" % self)]

    def eval(self, env):
        r = env[self]
        r.sf = self.sf
        return r

    def addr(self, env):
        return self

    def __setattr__(self, a, v):
        if a == "size" and self.__protect:
            raise AttributeError("protected attribute")
        exp.__setattr__(self, a, v)

    # howto pickle/unpickle reg objects:
    def __setstate__(self, state):
        v = state[1]
        self.__protect = False
        self.size = v["size"]
        self.sf = v["sf"]
        self.ref = v["ref"]
        self.etype = v["etype"]
        self._subrefs = v["_subrefs"]
        self.__protect = v["_reg__protect"]


class regtype(object):
    """
    decorator and context manager (with...) for associating
    a register to a specific category among STD (standard),
    PC (program counter), FLAGS, STACK, OTHER.
    """

    STD = 0x00
    PC = 0x10
    FLAGS = 0x20
    STACK = 0x40
    OTHER = 0x80
    cur = None

    def __init__(self, t):
        self.t = t

    def __call__(self, r):
        if not r._is_reg:
            logger.error("pc decorator ignored (not a register)")
        r.etype |= self.t
        return r

    def __enter__(self):
        regtype.cur = self.t

    def __exit__(self, exc_type, exc_value, traceback):
        regtype.cur = None


is_reg_pc = regtype(regtype.PC)
is_reg_flags = regtype(regtype.FLAGS)
is_reg_stack = regtype(regtype.STACK)
is_reg_other = regtype(regtype.OTHER)

# ------------------------------------------------------------------------------
# ext holds external symbols used by the dynamic linker.
# ------------------------------------------------------------------------------


class ext(reg):
    "external reference to a dynamic (lazy or non-lazy) symbol"

    __hash__ = reg.__hash__
    __eq__ = exp.__eq__

    def __init__(self, refname, **kargs):
        self.ref = refname
        self._subrefs = kargs
        self.size = kargs.get("size", None)
        self.sf = False
        self._reg__protect = False
        self.etype = et_ext | et_reg | regtype.OTHER
        self.stub = None
        # add the instruction interface:
        self.address = None
        self.operands = []
        self.mnemonic = str(self)
        self.misc = {}
        self.type = 2  # type_control_flow

    def __unicode__(self):
        return "@%s" % self.ref

    def toks(self, **kargs):
        tk = render.Token.Tainted if "!" in self.ref else render.Token.Name
        return [(tk, "%s" % self)]

    def __setattr__(self, a, v):
        exp.__setattr__(self, a, v)

    def call(self, env, **kargs):
        "explicit call to the ext's stub"
        logger.info("stub %s explicit call" % self.ref)
        if "size" not in kargs:
            kargs.update(size=self.size)
        try:
            res = self.stub(env, **kargs)
        except TypeError:
            res = None
        if res is None:
            return top(self.size)
        return res[0 : self.size]

    def __call__(self, env):
        "used when the expression is used as a target instruction"
        logger.info("stub %s implicit call" % self.ref)
        f = self.stub
        f(env, **self._subrefs)


# ------------------------------------------------------------------------------
# lab holds labels/symbols, e.g. from relocations
# ------------------------------------------------------------------------------


class lab(ext):
    "label expression used by the assembler"

    __hash__ = ext.__hash__
    __eq__ = exp.__eq__

    def __init__(self, refname, **kargs):
        super().__init__(refname, **kargs)
        self.etype |= et_lab


# ------------------------------------------------------------------------------


def composer(parts):
    """
    composer returns a comp object (see below) constructed with parts from low
    significant bits parts to most significant bits parts.
    The last part sf flag propagates to the resulting comp.
    """
    assert len(parts) > 0
    if len(parts) == 1:
        return parts[0]
    s = sum([x.size for x in parts])
    c = comp(s)
    c.sf = parts[-1].sf
    pos = 0
    for x in parts:
        c[pos : pos + x.size] = x
        pos += x.size
    return c.simplify()


# ------------------------------------------------------------------------------


class comp(exp):
    """
    composite expression, represents an expression made of several parts.

    Attributes:
        parts (dict): expressions parts dictionary.
                      Each key is a tuple (pos,sz) and value is the exp part.
                      pos is the bit position for this part, and sz is its size.
        smask (list): mapping of bit index to the part's key that defines this bit.
    Note:
        Each part can be accessed by 'slicing' the comp to obtain another
        comp or the part if the given slice indices match the part position.
    """

    __slots__ = ["smask", "parts"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_cmp

    def __init__(self, s):
        self.size = s
        self.sf = False
        self.smask = [None] * self.size
        self.parts = {}
        # the symp is only obtained after a restruct !

    def __unicode__(self):
        s = "{ |"
        cur = 0
        for nv in self:
            nk = cur, cur + nv.size
            s += " %s->%s |" % ("[%d:%d]" % nk, nv)
            cur += nv.size
        return s + " }"

    def toks(self, **kargs):
        if "indent" in kargs:
            p = kargs.get("indent", 0)
            pad = "\n".ljust(p + 1)
            kargs["indent"] = p + 4
        else:
            pad = ""
        tl = (render.Token.Literal, ", ")
        s = [(render.Token.Literal, "{")]
        cur = 0
        for nv in self:
            loc = "%s[%2d:%2d] -> " % (pad, cur, cur + nv.size)
            cur += nv.size
            s.append((render.Token.Literal, loc))
            t = nv.toks(**kargs)
            s.extend(t)
            s.append(tl)
        if len(s) > 1:
            s.pop()
        s.append((render.Token.Literal, "}"))
        return s

    def eval(self, env):
        res = comp(self.size)
        res.sf = self.sf
        res.smask = self.smask[:]
        for nk, nv in iter(self.parts.items()):
            res.parts[nk] = nv.eval(env)
        # now there may be raw numeric value in enode dict, so tiddy up:
        res.restruct()
        # once simplified, it may be reduced to 1 part, so:
        if (0, res.size) in res.parts.keys():
            res = res.parts[(0, res.size)]
        return res

    def copy(self):
        res = comp(self.size)
        res.smask = self.smask[:]
        for nk, nv in iter(self.parts.items()):
            res.parts[nk] = nv
        res.sf = self.sf
        return res

    def simplify(self, **kargs):
        for nk, nv in iter(self.parts.items()):
            self.parts[nk] = nv.simplify(**kargs)
        self.restruct()
        if (0, self.size) in self.parts.keys():
            return self.parts[(0, self.size)]
        else:
            return self

    @_checkarg_slice
    def __getitem__(self, i):
        start = i.start or 0
        stop = i.stop or self.size
        # see if the slice is exactly in the compound set:
        if (start, stop) in self.parts.keys():
            return self.parts[(start, stop)]
        if start == 0 and stop == self.size:
            return self.copy()
        l = stop - start
        res = comp(l)
        res.sf = self.sf
        b = 0
        while b < l:
            # select symbol index and object:
            idx = self.smask[start]
            if idx is None:
                b += 1
                start += 1
                continue
            else:  # idx is a slice keyed in enode dict
                s = self.parts[idx]
                # get slice for this symbol:
                deb = start - idx[0]
                fin = min(idx[1], stop) - idx[0]
                d = fin - deb
                res[b : b + d] = s[deb:fin]
                b += d
                start += d
        res.restruct()
        if len(res.parts.keys()) == 0:
            return slicer(self, start, stop - start)
        if len(res.parts.keys()) == 1:
            return list(res.parts.values())[0]
        return res

    @_checkarg_slice
    def __setitem__(self, i, v):
        sta = i.start or 0
        sto = i.stop or self.size
        l = sto - sta
        if v.size != l:
            raise ValueError("size mismatch")
        # make cmp always flat:
        if v._is_cmp:
            for vp, vv in v.parts.items():
                vsta, vsto = vp
                self[sta + vsta : sta + vsto] = vv
        else:
            # see if the slice is exactly in the compound set:
            if (sta, sto) in self.parts.keys():
                self.parts[(sta, sto)] = v
            else:
                self.parts[(sta, sto)] = v
                self.cut(sta, sto)

    def cut(self, start, stop):
        """
        cut will scan the parts dict to find those spanning **over**
        start and/or stop bounds then it will split them and remove their
        inner parts.

        Note:
            cut is in in-place method (affects self).
        """
        # list parts that cover (start,stop) range:
        maskset = []
        for nk in filter(None, self.smask[start:stop]):
            if nk not in maskset:
                maskset.append(nk)
        # for each listed part, remove its covering in this range
        # and update parts and smask dicts accordingly:
        for nk in maskset:
            nv = self.parts.pop(nk)
            if nk[0] < start:
                self.parts[(nk[0], start)] = nv[0 : start - nk[0]]
                self.smask[nk[0] : start] = [(nk[0], start)] * (start - nk[0])
            if nk[1] > stop:
                self.parts[(stop, nk[1])] = nv[stop - nk[0] : nk[1] - nk[0]]
                self.smask[stop : nk[1]] = [(stop, nk[1])] * (nk[1] - stop)
        self.smask[start:stop] = [(start, stop)] * (stop - start)

    def __iter__(self):
        # gather cst as possible:
        part = list(self.parts.keys())
        part.sort(key=operator.itemgetter(0))
        cur = 0
        for p in part:
            assert p[0] == cur
            yield self.parts[p]
            cur = p[1]

    def restruct(self):
        """
        restruct will aggregate consecutive cst expressions in order
        to minimize the number of parts.
        """
        # gather cst as possible:
        part = list(self.parts.keys())
        part.sort(key=operator.itemgetter(0))
        for i in range(len(part) - 1):
            ra = part[i]
            rb = part[i + 1]
            if ra[1] == rb[0]:
                na = self.parts[ra]
                nb = self.parts[rb]
                if na._is_cst and nb._is_cst:
                    v = (nb.v << na.size) | (na.v)
                    self.parts[(ra[0], rb[1])] = cst(v, na.size + nb.size)
                    self.parts.pop(ra)
                    self.parts.pop(rb)
                    self.smask[ra[0] : rb[1]] = [(ra[0], rb[1])] * (rb[1] - ra[0])
                    self.restruct()
                    break
                elif not (na._is_def or nb._is_def):
                    self.parts[(ra[0], rb[1])] = top(rb[1] - ra[0])
                    self.parts.pop(ra)
                    self.parts.pop(rb)
                    self.smask[ra[0] : rb[1]] = [(ra[0], rb[1])] * (rb[1] - ra[0])
                    self.restruct()
                    break

    def depth(self):
        return sum((p.depth() for p in self))


# ------------------------------------------------------------------------------


class mem(exp):
    """
    memory expression represents a symbolic value of length size, in segment seg,
    at given address expression.

    Attributes:
        a (ptr): a pointer expression that represents the address.
        endian (int): 1 means little, -1 means big.
        mods (list): list of possibly aliasing operations affecting this exp.

    Note:
        The mods list allows to handle aliasing issues detected at fetching time
        and adjust the eval result accordingly.
    """

    __slots__ = ["a", "mods", "endian"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_mem

    def __init__(self, a, size=32, seg=None, disp=0, mods=None, endian=1):
        self.size = size
        self.sf = False
        self.a = ptr(a, seg, disp)
        self.mods = mods or []
        self.endian = endian

    def __unicode__(self):
        n = len(self.mods)
        n = "$%d" % n if n > 0 else ""
        return "M%d%s%s" % (self.size, n, self.a)

    def toks(self, **kargs):
        return [(render.Token.Memory, "%s" % self)]

    def eval(self, env):
        a = self.a.eval(env)
        if self.mods:
            m = env.use()
            for loc, v in self.mods:
                if loc._is_ptr:
                    loc = env(loc)
                m[loc] = env(v)
        else:
            m = env
        res = m[mem(a, self.size, endian=self.endian)]
        res.sf = self.sf
        return res

    def simplify(self, **kargs):
        self.a.simplify(**kargs)
        if self.a.base._is_vec:
            seg, disp = self.a.seg, self.a.disp
            l = []
            for a in self.a.base.l:
                x = mem(a, self.size, seg, disp, mods=self.mods, endian=self.endian)
                l.append(x)
            v = vec(l)
            return v if self.a.base._is_def else vecw(v)
        return self

    def addr(self, env):
        return self.a.eval(env).unsigned()

    def bytes(self, sta=0, sto=None, endian=1):
        s = slice(sta, sto)
        l = self.length
        sta, sto, stp = s.indices(l)
        size = (sto - sta) * 8
        a = self.a
        return mem(a, size, disp=sta, mods=self.mods, endian=self.endian)

    @_checkarg_slice
    def __getitem__(self, i):
        sta, sto, stp = i.indices(self.size)
        b1, r1 = divmod(sta, 8)
        b2, r2 = divmod(sto, 8)
        if r2 > 0:
            b2 += 1
        l = self.length
        if self.endian == -1:
            b1, b2 = l - b2, l - b1
        a = self.a
        size = (b2 - b1) * 8
        x = mem(a, size, disp=b1, mods=self.mods, endian=self.endian)
        x.sf = self.sf
        if r1 > 0 or r2 > 0:
            x = slc(x, r1, (sto - sta))
        return x


# ------------------------------------------------------------------------------


class ptr(exp):
    """
    ptr holds memory addresses with segment, base expressions and
    displacement integer (offset relative to base).

    Attributes:
        base (exp): symbolic expression for the base of pointer address.
        disp (int): offset relative to base for the pointer address.
        seg  (reg): segment register (or None if unused.)
    """

    __slots__ = ["base", "disp", "seg"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_ptr

    def __init__(self, base, seg=None, disp=0):
        if base._is_ptr:
            if seg is None:
                seg = base.seg
            disp = base.disp + disp
            base = base.base
        self.base, offset = extract_offset(base)
        self.disp = disp + offset
        self.seg = seg
        self.size = base.size
        self.sf = False

    def __unicode__(self):
        d = self.disp_tostring()
        seg = "" if self.seg is None else self.seg
        return "%s(%s%s)" % (seg, self.base, d)

    def disp_tostring(self, base10=True):
        if hasattr(self.disp, "_is_cst"):
            # When allowing label in expressions, e.g. when parsing
            # relocatable objects and relocations, 'disp' (displacement
            # from a base address in memory) can not only be a number as
            # in standard amoco, but also a label, a difference of labels
            # or even a difference of labels added with an integer
            return "+%s" % self.disp
        if self.disp == 0:
            return ""
        if base10:
            return "%+d" % self.disp
        c = cst(self.disp, self.size)
        c.sf = False
        return "+%s" % c

    def toks(self, **kargs):
        return [(render.Token.Address, "%s" % self)]

    def simplify(self, **kargs):
        self.base, offset = extract_offset(self.base)
        self.disp += offset
        if isinstance(self.seg, exp):
            self.seg = self.seg.simplify(**kargs)
        if not self.base._is_def:
            self.disp = 0
        return self

    # default segment handler just forwards the ptr object
    # see arch/x86/env.py for example of segment_handler override.
    @classmethod
    def segment_handler(cls, env, s, bd):
        base, disp = bd
        return ptr(base, s, disp)

    def eval(self, env):
        a = self.base.eval(env)
        if a._is_ext:
            return a
        return self.segment_handler(env, self.seg, (a, self.disp))


# ------------------------------------------------------------------------------


def slicer(x, pos, size):
    """
    wrapper of slc class that returns a simplified version of x[pos:pos+size].
    """
    if not isinstance(x, exp):
        raise TypeError(x)
    if not x._is_def:
        return top(size)
    if pos == 0 and size == x.size:
        return x
    else:
        if x._is_mem or x._is_cmp:
            res = x[pos : pos + size]
            res.sf = x.sf
            return res
        return slc(x, pos, size)


# ------------------------------------------------------------------------------


class slc(exp):
    """
    slice expression, represents an expression part.

    Attributes:
        x (exp): reference to the symbolic expression
        pos (int): start bit for the part.
        ref (str): an alternative symbolic name for this part.
    """

    __slots__ = ["x", "pos", "ref", "__protect", "etype"]
    __eq__ = exp.__eq__

    def __init__(self, x, pos, size, ref=None):
        if not isinstance(pos, int):
            raise TypeError(pos)
        self.__protect = False
        self.size = size
        self.sf = x.sf
        if isinstance(x, slc):
            res = x[pos : pos + size]
            x, pos = res.x, res.pos
        self.x = x
        self.pos = pos
        self.etype = et_slc
        self.setref(ref)

    def setref(self, ref):
        if self.x._is_reg:
            self.etype |= self.x.etype
            if ref is None:
                ref = self.x._subrefs.get((self.pos, self.size), None)
            else:
                self.x._subrefs[(self.pos, self.size)] = ref
            self.__protect = True
        self.ref = ref

    def raw(self):
        "returns the raw symbolic name (ignore the ref attribute.)"
        return "%s[%d:%d]" % (self.x, self.pos, self.pos + self.size)

    def __setattr__(self, a, v):
        if a == "size" and self.__protect:
            raise AttributeError("protected attribute")
        exp.__setattr__(self, a, v)

    def __unicode__(self):
        return self.ref or self.raw()

    def toks(self, **kargs):
        if self._is_reg:
            return [(render.Token.Register, "%s" % self)]
        subpart = [(render.Token.Literal, "[%d:%d]" % (self.pos, self.pos + self.size))]
        return self.x.toks(**kargs) + subpart

    def __hash__(self):
        return hash(self.raw())  # lgtm [py/equals-hash-mismatch]

    def depth(self):
        return 2 * self.x.depth()

    def eval(self, env):
        n = self.x.eval(env)
        res = n[self.pos : self.pos + self.size]
        res.sf = self.sf
        return res

    # slc of mem objects are simplified by adjusting the disp offset of
    # the sliced mem object.
    def simplify(self, **kargs):
        self.x = self.x.simplify(**kargs)
        if not self.x._is_def:
            return top(self.size)
        if self.x._is_cmp or self.x._is_cst:
            res = self.x[self.pos : self.pos + self.size]
            res.sf = self.sf
            return res
        if self.x._is_mem and self.size % 8 == 0:
            off, rst = divmod(self.pos, 8)
            if rst == 0:
                a = ptr(self.x.a.base, self.x.a.seg, self.x.a.disp + off)
                res = mem(a, self.size)
                res.sf = self.sf
                return res
        if self.x._is_eqn and (
            self.x.op.type == 2
            or (self.x.op.symbol in (OP_ADD, OP_MIN) and self.pos == 0)
        ):
            r = self.x.r[self.pos : self.pos + self.size]
            if self.x.op.unary:
                return self.x.op(r)
            l = self.x.l[self.pos : self.pos + self.size]
            return self.x.op(l, r)
        if self.x._is_vec:
            return vec([x[self.pos : self.pos + self.size] for x in self.x.l])
        else:
            return self

    # slice of a slice:
    @_checkarg_slice
    def __getitem__(self, i):
        if i.start == 0 and i.stop == self.size:
            return self
        else:
            start = self.pos + i.start
            return slicer(self.x, start, i.stop - i.start)

    ##
    # simplify: the only simplification would apply on slc'ed expression x
    # but x can't be of type slc...
    def addr(self, env):
        if self.x._is_mem:
            a = self.x.addr(env).unsigned()
            a.disp = self.pos
            return a
        elif self.x._is_reg:
            return self.x
        else:
            raise TypeError("this expression is not a location")

    def __setstate__(self, state):
        v = state[1]
        self.__protect = False
        self.size = v["size"]
        self.sf = v["sf"]
        self.x = v["x"]
        self.pos = v["pos"]
        self.ref = v["ref"]
        self.etype = v["etype"]
        self.__protect = v["_slc__protect"]


# ------------------------------------------------------------------------------


class tst(exp):
    """
    Conditional expression.

    Attributes:
        tst (exp): the boolean expression that represents the condition.
        l   (exp): the resulting expression if test == bit1.
        r   (exp): the resulting expression if test == bit0.
    """

    __slots__ = ["tst", "l", "r"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_tst

    def __new__(cls, t, l, r):
        if t is True or t is False:
            t = cst(t, 1)
        if t._is_cst and t.size == 1:
            if t.value == 1:
                return l
            if t.value == 0:
                return r
        return super().__new__(cls)

    def __getnewargs__(self):
        return (self.tst, self.l, self.r)

    def __init__(self, t, l, r):
        if t is True or t is False:
            t = cst(t, 1)
        self.tst = t  # the expression to test, probably a 'op' expressions.
        if l.size != r.size:
            raise ValueError((l, r))
        self.l = l  # true (tst evals to val)
        self.r = r  # false
        self.size = self.l.size
        self.sf = False

    ##
    def __unicode__(self):
        return "(%s ? %s : %s)" % (self.tst, self.l, self.r)

    def toks(self, **kargs):
        ttest = self.tst.toks(**kargs)
        ttest.append((render.Token.Literal, " ? "))
        ttrue = self.l.toks(**kargs)
        ttrue.append((render.Token.Literal, " : "))
        tfalse = self.r.toks(**kargs)
        return ttest + ttrue + tfalse

    # default verify method if smt module is not loaded.
    # here we check if tst or its negation exist in env.conds but we can
    # only rely on "syntaxic" features unless we have a solver.
    # see smt.py: tst_verify() for a SMT-based implementation.
    def verify(self, env):
        flag = self.tst.eval(env)
        for c in env.conds:
            if c == flag:
                flag = bit1
                break
            if c == (~flag):
                flag = bit0
                break
        return flag

    def eval(self, env):
        cond = self.verify(env)
        l = self.l.eval(env)
        r = self.r.eval(env)
        if not cond._is_cst:
            return tst(cond, l, r)
        if cond.v == 1:
            return l
        else:
            return r

    def simplify(self, **kargs):
        self.tst = self.tst.simplify(**kargs)
        widening = kargs.get("widening", False)
        if widening or not self.tst._is_def:
            return vec([self.l, self.r]).simplify()
        self.l = self.l.simplify(**kargs)
        if self.tst == bit1:
            return self.l
        self.r = self.r.simplify(**kargs)
        if self.tst == bit0:
            return self.r
        if self.l == self.r:
            return self.l
        return self

    def depth(self):
        return (self.tst.depth() + self.l.depth() + self.r.depth()) / 3.0


# ------------------------------------------------------------------------------


def oper(opsym, l, r=None):
    "wrapper of the operator expression that detects unary operations"
    if r is None:
        return uop(opsym, l).simplify()
    return op(opsym, l, r).simplify()


# ------------------------------------------------------------------------------


class op(exp):
    """
    op holds binary integer arithmetic and bitwise logic expressions

    Attributes:
        op (_operator): binary operator
        prop (int): type of operator (ARITH, LOGIC, CONDT, SHIFT)
        l (exp): left-hand expression of the operator
        r (exp): right-hand expression of the operator
    """

    __slots__ = ["op", "l", "r", "prop"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_eqn

    def __init__(self, op, l, r):
        self.op = _operator(op)
        self.prop = self.op.type
        if self.prop < 4:
            if l.size != r.size:
                raise ValueError("Size mismatch %d != %d" % (l.size, r.size))
        self.l = l
        self.r = r
        self.size = self.l.size
        if self.prop == 4:
            self.size = 1
        elif self.op.symbol in [OP_MUL2]:
            self.size *= 2
        self.sf = l.sf
        if self.prop == 1:
            self.sf |= r.sf
        if self.l._is_eqn:
            self.prop |= self.l.prop
        if self.r._is_eqn:
            self.prop |= self.r.prop

    def eval(self, env):
        # single-operand :
        l = self.l.eval(env)
        r = self.r.eval(env)
        res = self.op(l, r)
        res.sf = self.sf
        return res

    ##

    def __unicode__(self):
        return "(%s%s%s)" % (self.l, render.icons.op(self.op.symbol), self.r)

    def toks(self, **kargs):
        l = self.l.toks(**kargs)
        l.insert(0, (render.Token.Literal, "("))
        r = self.r.toks(**kargs)
        r.append((render.Token.Literal, ")"))
        return l + [(render.Token.Literal, self.op.symbol)] + r

    def simplify(self, **kargs):
        l = self.l.simplify(**kargs)
        r = self.r.simplify(**kargs)
        if self.prop < 4 and self.op.symbol not in (OP_DIV, OP_MOD):
            if l._is_top:
                return l
            if r._is_top:
                return r
            minus = self.op.symbol == OP_MIN
            # arithm/logic normalisation:
            # push cst to the right
            if l._is_cst:
                if r._is_cst:
                    return self.op(l, r)
                if minus:
                    l, r = (-r), l
                    self.op = _operator(OP_ADD)
                else:
                    l, r = r, l
            # lexical ordering of symbols:
            elif not r._is_cst:
                lh = "".join(["%s" % x for x in symbols_of(l)])
                rh = "".join(["%s" % x for x in symbols_of(r)])
                if lh > rh:
                    if minus:
                        l, r = (-r), l
                        self.op = _operator(OP_ADD)
                    else:
                        l, r = r, l
        self.l = l
        self.r = r
        return eqn2_helpers(self, **kargs)

    def depth(self):
        return self.l.depth() + self.r.depth()


# ------------------------------------------------------------------------------


class uop(exp):
    """
    uop holds unary integer arithmetic and bitwise logic expressions

    Attributes:
        op (_operator): unary operator
        prop (int): type of operator (ARITH, LOGIC, CONDT, SHIFT)
        l (None): returns None in case uop is treated as an op instance.
        r (exp): right-hand expression of the operator
    """

    __slots__ = ["op", "r", "prop"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_eqn

    def __init__(self, op, r):
        self.op = _operator(op, unary=1)
        self.prop = self.op.type
        self.r = r
        self.size = r.size
        self.sf = r.sf
        if self.r._is_eqn:
            self.prop |= self.r.prop

    def eval(self, env):
        # single-operand :
        r = self.r.eval(env)
        res = self.op(r)
        res.sf = self.sf
        return res

    @property
    def l(self):
        return None

    def __unicode__(self):
        return "(%s%s)" % (render.icons.op(self.op.symbol), self.r)

    def toks(self, **kargs):
        r = self.r.toks(**kargs)
        r.append((render.Token.Literal, ")"))
        return [(render.Token.Literal, "(%s" % self.op.symbol)] + r

    def simplify(self, **kargs):
        r = self.r.simplify(**kargs)
        if r._is_top:
            return r
        self.r = r
        return eqn1_helpers(self, **kargs)

    def depth(self):
        return self.r.depth()


# operators:
# -----------

OP_ADD = "+"
OP_MIN = "-"
OP_MUL = "*"
OP_MUL2 = "**"
OP_DIV = "/"
OP_MOD = "%"
OP_AND = "&"
OP_OR = "|"
OP_XOR = "^"
OP_NOT = "~"
OP_EQ = "=="
OP_NEQ = "!="
OP_LE = "<="
OP_GE = ">="
OP_GEU = ">=."
OP_LT = "<"
OP_LTU = "<."
OP_GT = ">"
OP_LSL = "<<"
OP_LSR = ">>"
OP_ASR = ".>>"
OP_ROR = ">>>"
OP_ROL = "<<<"


def ror(x, n):
    "high-level rotate right n bits"
    return (x >> n | x << (x.size - n)) if x._is_cst else op(OP_ROR, x, n)


def rol(x, n):
    "high-level rotate left n bits"
    return (x << n | x >> (x.size - n)) if x._is_cst else op(OP_ROL, x, n)


def ltu(x, y):
    "high-level less-than-unsigned operation"
    try:
        if not (x._is_cst and y._is_cst):
            return op(OP_LTU, x, y)
    except AttributeError:
        logger.warning("bad ltu operation")
    x.sf = y.sf = True
    return x < y


def geu(x, y):
    "high level greater-or-equal-unsigned operation"
    try:
        if not (x._is_cst and y._is_cst):
            return op(OP_GEU, x, y)
    except AttributeError:
        logger.warning("bad geu operation")
    x.sf = y.sf = True
    return x >= y


OP_ARITH = {
    OP_ADD: operator.add,
    OP_MIN: operator.sub,
    OP_MUL: operator.mul,
    OP_MUL2: operator.pow,
    OP_DIV: operator.truediv,
    OP_MOD: operator.mod,
}
OP_LOGIC = {
    OP_AND: operator.and_,
    OP_OR: operator.or_,
    OP_XOR: operator.xor,
    OP_NOT: operator.invert,
}
OP_CONDT = {
    OP_EQ: operator.eq,
    OP_NEQ: operator.ne,
    OP_LE: operator.le,
    OP_GE: operator.ge,
    OP_GEU: geu,
    OP_LT: operator.lt,
    OP_LTU: ltu,
    OP_GT: operator.gt,
}
OP_SHIFT = {
    OP_LSR: operator.rshift,  # logical shift right (see cst.value)
    OP_LSL: operator.lshift,
    OP_ASR: operator.floordiv,  # this is arithmetic shift right
    OP_ROR: ror,
    OP_ROL: rol,
}


class _operator(object):
    def __init__(self, op, unary=0):
        self.symbol = op
        self.unary = unary
        self.unsigned = False
        if op in OP_ARITH:
            self.type = 1
            if self.unary:
                self.impl = {OP_ADD: operator.pos, OP_MIN: operator.neg}[op]
            else:
                self.impl = OP_ARITH[op]
        elif op in OP_LOGIC:
            self.type = 2
            self.unsigned = True
            if self.unary:
                assert op == OP_NOT
            self.impl = OP_LOGIC[op]
        elif op in OP_CONDT:
            self.type = 4
            self.impl = OP_CONDT[op]
            if op in (OP_GEU, OP_LTU):
                self.unsigned = True
        elif op in OP_SHIFT:
            self.type = 8
            self.impl = OP_SHIFT[op]
        else:
            raise NotImplementedError

    def __call__(self, l, r=None):
        if r is None:
            assert self.unary
            return self.impl(l)
        if self.unsigned:
            l.sf = r.sf = False
        return self.impl(l, r)

    def __mul__(self, op):
        ss = self.symbol + op.symbol
        if ss in ("++", "--"):
            return OP_ADD
        if ss in ("+-", "-+"):
            return OP_MIN
        return None


# basic simplifier:
# ------------------


def symbols_of(e):
    "returns all symbols contained in expression e"
    if e is None:
        return []
    if e._is_cst:
        return []
    if e._is_reg:
        return [e]
    if e._is_mem:
        return symbols_of(e.a.base)
    if e._is_ptr:
        return symbols_of(e.base)
    if e._is_eqn:
        return symbols_of(e.l) + symbols_of(e.r)
    if e._is_tst:
        return sum([symbols_of(x) for x in (e.tst, e.l, e.r)], [])
    if e._is_slc:
        return symbols_of(e.x)
    if e._is_cmp:
        return sum([symbols_of(x) for x in e.parts.values()], [])
    if e._is_vec:
        return sum([symbols_of(x) for x in e.l], [])
    if not e._is_def:
        return []
    raise ValueError(e)


def locations_of(e):
    "returns all locations contained in expression e"
    if e is None:
        return []
    if e._is_cst:
        return []
    if e._is_reg:
        return [e]
    if e._is_mem:
        return [e]
    if e._is_ptr:
        return [e]
    if e._is_eqn:
        return locations_of(e.l) + locations_of(e.r)
    if e._is_tst:
        return sum([locations_of(x) for x in (e.tst, e.l, e.r)], [])
    if e._is_slc:
        return locations_of(e.x)
    if e._is_cmp:
        return sum([locations_of(x) for x in e.parts.values()], [])
    if e._is_vec:
        return sum([locations_of(x) for x in e.l], [])
    if not e._is_def:
        return []
    raise ValueError(e)


def complexity(e):
    "evaluate the complexity of expression e"
    factor = e.prop if e._is_eqn else 1
    return (e.depth() + len(symbols_of(e))) * factor


def eqn1_helpers(e, **kargs):
    "helpers for simplifying unary expressions"
    assert e.op.unary
    if e.r._is_cst:
        return e.op(e.r)
    if e.r._is_vec:
        return vec([e.op(x) for x in e.r.l])
    if e.r._is_eqn:
        if e.r.op.unary:
            ss = e.op * e.r.op
            if ss == OP_ADD:
                return e.r.r
            elif ss == OP_MIN:
                return -e.r.r
        elif e.op.symbol == OP_MIN:
            if e.r.op.symbol in (OP_MIN, OP_ADD):
                l = -e.r.l
                r = e.r.r
                return OP_ARITH[e.op * e.r.op](l, r)
        elif e.op.symbol == OP_NOT and e.r.op.type == 4:
            notop = {
                OP_EQ: OP_NEQ,
                OP_NEQ: OP_EQ,
                OP_LT: OP_GE,
                OP_GT: OP_LE,
                OP_LTU: OP_GEU,
                OP_GEU: OP_LTU,
                OP_LE: OP_GT,
                OP_GE: OP_LT,
            }[e.r.op.symbol]
            return OP_CONDT[notop](e.r.l, e.r.r)
    return e


def get_lsb_msb(v):
    msb = v.bit_length() - 1
    lsb = (v & -v).bit_length() - 1
    return (lsb, msb)


def ismask(v):
    i1, i2 = get_lsb_msb(v)
    return ((1 << (i2 + 1)) - 1) ^ ((1 << i1) - 1) == v


# reminder: be careful not to modify the internal structure of
# e.l or e.r because these objects might be used also in other
# expressions. See tests/test_cas_exp.py for details.


def eqn2_helpers(e, bitslice=False, widening=False):
    "helpers for simplifying binary expressions"
    threshold = conf.Cas.complexity
    if threshold > 0:
        if complexity(e.r) > threshold:
            e.r = top(e.r.size)
        if complexity(e.l) > threshold:
            e.l = top(e.l.size)
    if e.r._is_top or e.l._is_top:
        return top(e.size)
    # if e := ((a l.op cst) e.op r)
    if e.l._is_eqn and e.l.r._is_cst and e.l.op.unary == 0:
        xop = e.op * e.l.op
        # if ++ -- +- -+,
        if xop:
            # move cst to the right:
            # e := (a e.op r) l.op cst
            e.op, lop = e.l.op, e.op
            lr, e.r = e.r, e.l.r
            e.l = lop(e.l.l, lr)
    # if e:= (l + (- r)
    # change into e:= l - r
    if e.r._is_eqn and e.r.op.unary:
        if e.op.symbol == OP_ADD and e.r.op.symbol == OP_MIN:
            e.op = _operator(OP_MIN)
            e.r = e.r.r
    # if e:= (l [+-] (a [+-] cst))
    # move cst to the right:
    # e:= (l [+-] a) xop cst
    if e.r._is_eqn and e.r.r._is_cst:
        xop = e.op * e.r.op
        if xop:
            e.l = e.op(e.l, e.r.l)
            e.r = e.r.r
            e.op = _operator(xop)
    # now if e:= (l op cst)
    if e.r._is_cst:
        if e.r.value == 0:
            # if e:= (l [|^+-...] 0) then e:= l
            if e.op.symbol in (
                OP_OR,
                OP_XOR,
                OP_ADD,
                OP_MIN,
                OP_LSR,
                OP_LSL,
                OP_ROR,
                OP_ROL,
            ):
                return e.l
            # if e:= (l [|&*] 0) then e:= 0
            if e.op.symbol in (OP_AND, OP_MUL, OP_MUL2):
                return cst(0, e.size)
            # external == 0 ? => false, we assume ext is defined
            if e.op.symbol == OP_EQ and e.l._is_ext:
                return bit0
            # external != 0 ? => true, we assume ext is defined
            if e.op.symbol == OP_NEQ and e.l._is_ext:
                return bit1
        # if e:= (l [|*/] 1) then e:= l
        elif e.r.value == 1 and e.op.symbol in (OP_MUL, OP_MUL2, OP_DIV):
            return e.l
        # if e:= (l & mask) then e:= l[i1:i2]
        elif e.op.symbol == OP_AND and ismask(e.r.value):
            i1, i2 = get_lsb_msb(e.r.value)
            c = comp(e.size)
            c[0 : e.size] = cst(0, e.size)
            c[i1 : i2 + 1] = e.l[i1 : i2 + 1]
            return c.simplify()
        elif bitslice and e.op.symbol in (OP_AND, OP_OR, OP_XOR):
            return composer(
                [e.op(e.l[i : i + 1], e.r[i : i + 1]) for i in range(e.size)]
            )
        elif bitslice and e.op.symbol in (OP_LSL):
            return composer(
                [bit0] * e.r.value
                + [e.l[i : i + 1] for i in range(0, e.size - e.r.value)]
            )
        elif bitslice and e.op.symbol in (OP_LSR):
            return composer(
                [e.l[i : i + 1] for i in range(e.r.value, e.size)] + [bit0] * e.r.value
            )
        # if e:= (l [>> <<] r) then e:= l[i1:i2]
        elif e.op.symbol in (OP_LSL, OP_LSR):
            c = comp(e.l.size)
            c[0 : e.l.size] = cst(0, e.l.size)
            if e.l.size > e.r.value:
                if e.op.symbol == OP_LSL:
                    l = e.l[0 : e.l.size - e.r.value]
                    c[e.r.value : e.l.size] = l
                elif e.op.symbol == OP_LSR:
                    l = e.l[e.r.value : e.l.size]
                    c[0 : e.l.size - e.r.value] = l
            return c.simplify()
        # if e:= ((a op b) e.op cst)
        if e.l._is_eqn:
            xop = e.op * e.l.op
            if xop:
                # if e:= ((a [+-] cst) [+-] cst)
                # merge constants:
                # change into e := a [+-] cst
                if e.l.r._is_cst:
                    cc = OP_ARITH[xop](e.l.r, e.r)
                    e.op = e.l.op
                    if not e.l.op.unary:
                        e.l = e.l.l
                    e.r = cc
                return e
            elif e.r.size == 1:
                # if e:= ((a op b) == bit1) change in e := (a op b)
                # if e:= ((a op b) == bit0) change in e := ~(a op b)
                if e.op.symbol == OP_EQ:
                    return e.l if e.r.value == 1 else ~(e.l)
                if e.op.symbol == OP_NEQ:
                    return ~(e.l) if e.r.value == 1 else ~(e.l)
        elif e.l._is_ptr:
            if e.op.symbol in (OP_MIN, OP_ADD):
                return ptr(e.l, disp=e.op(0, e.r.value))
        elif e.l._is_cmp:
            if e.op.symbol in (OP_AND, OP_OR, OP_XOR):
                cc = comp(e.l.size)
                for ij, p in e.l.parts.items():
                    i, j = ij
                    cc[i:j] = e.op(p, e.r[i:j])
                return cc.simplify(bitslice=bitslice)
        elif e.l._is_cst:
            return e.op(e.l, e.r)
    if e.l._is_vec:
        return vec([e.op(x, e.r) for x in e.l.l]).simplify(widening=widening)
    if e.r._is_vec:
        return vec([e.op(e.l, x) for x in e.r.l]).simplify(widening=widening)
    if "%s" % (e.l) == "%s" % (e.r):
        if e.op.symbol in (OP_NEQ, OP_LT, OP_GT):
            return bit0
        if e.op.symbol in (OP_EQ, OP_LE, OP_GE):
            return bit1
        if e.op.symbol == OP_MIN:
            return cst(0, e.size)
        if e.op.symbol == OP_XOR:
            return cst(0, e.size)
        if e.op.symbol == OP_AND:
            return e.l
        if e.op.symbol == OP_OR:
            return e.l
    return e


def extract_offset(e):
    "separate expression e into (e' + C) with C cst offset."
    x = e.simplify().unsigned()
    if x._is_eqn and x.r._is_cst:
        if e.op.symbol == OP_ADD:
            return (x.l, x.r.value)
        elif e.op.symbol == OP_MIN:
            return (x.l, -x.r.value)
    return (x, 0)


# -----------------------------------------------------


class vec(exp):
    """
    vec holds a list of expressions each being a possible
    representation of the current expression. A vec object
    is obtained by merging several execution paths using
    the merge function in the mapper module.
    The simplify method uses the complexity measure to
    eventually "reduce" the expression to top with a hard-limit
    currently set to op.threshold.
    """

    __slots__ = ["l"]
    __hash__ = exp.__hash__
    __eq__ = exp.__eq__
    etype = et_vec

    def __init__(self, l=None):
        if l is None:
            l = []
        self.l = l
        size = 0
        for e in self.l:
            if e.size > size:
                size = e.size
        if any([e.size != size for e in self.l]):
            raise ValueError("size mismatch")
        self.size = size
        self.sf = any([e.sf for e in self.l])

    def __unicode__(self):
        s = ",".join(["%s" % x for x in self.l])
        return "[%s]" % (s)

    def toks(self, **kargs):
        t = []
        for x in self.l:
            t.extend(x.toks(**kargs))
            t.append((render.Token.Literal, ", "))
        if len(t) > 0:
            t.pop()
        t.insert(0, (render.Token.Literal, "["))
        t.append((render.Token.Literal, "]"))
        return t

    def simplify(self, **kargs):
        widening = kargs.get("widening", False)
        l = []
        for e in self.l:
            ee = e.simplify()
            if not ee._is_def:
                return ee
            if ee._is_vec:
                l.extend(ee.l)
                if isinstance(ee, vecw):
                    widening = True
            else:
                l.append(ee)
        self.l = []
        for e in l:
            if e in self.l:
                continue
            self.l.append(e)
        if len(self.l) == 1:
            return self.l[0]
        if widening:
            return vecw(self)
        cl = [complexity(x) for x in self.l]
        if sum(cl, 0.0) > conf.Cas.complexity > 0:
            return top(self.size)
        return self

    def eval(self, env):
        l = [e.eval(env) for e in self.l]
        return vec(l)

    def depth(self):
        if self.size == 0:
            return 0.0
        return max([e.depth() for e in self.l]) * len(self.l)

    @_checkarg_slice
    def __getitem__(self, i):
        sta, sto, stp = i.indices(self.size)
        l = [e[sta:sto] for e in self.l]
        return vec(l)

    def __contains__(self, x):
        return x in self.l

    def __bool__(self):
        return all([e.__bool__() for e in self.l])


class vecw(top):
    """
    vecw is a *widened* vec expression: it allows to limit
    the list of possible values to a fixed range and acts
    as a top (absorbing) expression.
    """

    __slots__ = ["l"]
    __hash__ = top.__hash__
    __eq__ = exp.__eq__
    etype = ~(~et_vec & et_msk)

    def __init__(self, v):
        self.l = v.l
        self.size = v.size
        self.sf = False

    def __unicode__(self):
        s = ",".join(["%s" % x for x in self.l])
        return "[%s, %s]" % (s, render.icons.dots)

    def toks(self, **kargs):
        t = []
        for x in self.l:
            t.extend(x.toks(**kargs))
            t.append((render.Token.Literal, ", "))
        if len(t) > 0:
            t.pop()
        t.insert(0, (render.Token.Literal, "["))
        t.append((render.Token.Literal, ", %s]" % render.icons.dots))
        return t

    def eval(self, env):
        v = vec([x.eval(env) for x in self.l])
        return vecw(v)

    @_checkarg_slice
    def __getitem__(self, i):
        sta, sto, stp = i.indices(self.size)
        l = [e[sta:sto] for e in self.l]
        return vecw(vec(l))
