"""Peregrine front end: lexer, parser and AST.

Peregrine v0.2 -- a small compiled language whose data layout is chosen by
the compiler from proven value ranges: fields are stored at the smallest
width their values provably occupy, enum stores are segregated per variant,
strings are built in place, maps key inline bytes, and sort() lowers to a
radix sort. Loops the compiler proves safe are emitted under `omp simd`.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

KEYWORDS = {
    "const", "enum", "fn", "var", "let", "for", "in", "repeat", "if",
    "elif", "else", "match", "print", "store", "u8", "u16", "u32", "u64",
    "str", "buf", "map",
}
PUNCT = ["<<", ">>", "<=", ">=", "&", "^", "|", "+=", "..", "=>", "==", "!=",
         "{", "}", "(", ")", "[", "]", "<", ">", ";", ",", ".", ":", "=",
         "+", "-", "*", "/", "%"]


@dataclass
class Tok:
    kind: str  # 'ident', 'int', 'str', 'kw', 'punct', 'eof'
    val: Any
    line: int


def lex(src: str) -> List[Tok]:
    toks, i, line = [], 0, 1
    while i < len(src):
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if src.startswith("//", i):
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c.isdigit():
            j = i
            while j < len(src) and (src[j].isdigit() or src[j] == "_"):
                j += 1
            toks.append(Tok("int", int(src[i:j].replace("_", "")), line)); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(Tok("kw" if w in KEYWORDS else "ident", w, line)); i = j; continue
        if c == '"':
            j = i + 1
            while j < len(src) and src[j] != '"':
                j += 1
            if j >= len(src):
                raise SyntaxError(f"line {line}: unterminated string")
            toks.append(Tok("str", src[i + 1:j], line)); i = j + 1; continue
        for p in PUNCT:
            if src.startswith(p, i):
                toks.append(Tok("punct", p, line)); i += len(p); break
        else:
            raise SyntaxError(f"line {line}: unexpected character {c!r}")
    toks.append(Tok("eof", None, line))
    return toks


# --- AST ---------------------------------------------------------------------

@dataclass
class Num:
    v: int
    line: int

@dataclass
class StrLit:
    s: str
    line: int

@dataclass
class StrOf:
    e: Any
    line: int

@dataclass
class Concat:
    lit: str
    rest: Any
    line: int

@dataclass
class Bin:
    op: str
    l: Any
    r: Any
    line: int

@dataclass
class Name:
    x: str
    line: int

@dataclass
class Field:
    base: str
    name: str
    line: int

@dataclass
class Ctor:
    enum: str
    variant: str
    inits: List[Tuple[str, Any]]
    line: int

@dataclass
class Index:
    base: str
    idx: Any
    line: int

@dataclass
class Call:
    name: str
    args: List[Any]
    line: int

@dataclass
class MethodCall:
    base: str
    meth: str
    args: List[Any]
    line: int


@dataclass
class ConstDecl:
    name: str
    type: str
    expr: Any
    line: int

@dataclass
class Variant:
    name: str
    fields: List[Tuple[str, str]]
    line: int

@dataclass
class EnumDecl:
    name: str
    variants: List[Variant]
    line: int

@dataclass
class VarDecl:
    name: str
    type: Any  # 'u32' | 'u64' | ('store', enum) | ('buf', elem, cap) | ('map', 'str', 'u64', slots)
    expr: Any
    line: int

@dataclass
class LetDecl:
    name: str
    type: Optional[str]
    expr: Any
    line: int

@dataclass
class Assign:
    target: str
    op: str  # '=' | '+='
    expr: Any
    line: int

@dataclass
class IndexAssign:
    base: str
    idx: Any
    op: str
    expr: Any
    line: int

@dataclass
class ForRange:
    var: str
    lo: Any
    hi: Any
    body: list
    line: int

@dataclass
class ForIn:
    var: str
    iter: str
    body: list
    line: int

@dataclass
class Repeat:
    count: Any
    body: list
    line: int

@dataclass
class If:
    cond: Any
    then: list
    elifs: List[Tuple[Any, list]]
    els: Optional[list]
    line: int

@dataclass
class MatchOn:
    value: str
    arms: List[Tuple[str, Optional[str], list]]
    line: int

@dataclass
class PushStmt:
    store: str
    ctor: Ctor
    line: int

@dataclass
class Print:
    args: List[Any]
    line: int

@dataclass
class FnDecl:
    name: str
    body: list
    line: int

@dataclass
class Program:
    decls: list


class Parser:
    def __init__(self, toks: List[Tok]):
        self.toks = toks
        self.i = 0

    def peek(self, k: int = 0) -> Tok:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def next(self) -> Tok:
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def at(self, val: str) -> bool:
        return self.peek().val == val

    def expect(self, val: str) -> Tok:
        t = self.next()
        if t.val != val:
            raise SyntaxError(f"line {t.line}: expected {val!r}, got {t.val!r}")
        return t

    # ---- declarations -------------------------------------------------------

    def parse_program(self) -> Program:
        decls = []
        while self.peek().kind != "eof":
            t = self.peek()
            if t.val == "const":
                decls.append(self.const_decl())
            elif t.val == "enum":
                decls.append(self.enum_decl())
            elif t.val == "fn":
                decls.append(self.fn_decl())
            else:
                raise SyntaxError(f"line {t.line}: expected const/enum/fn, got {t.val!r}")
        return Program(decls)

    def const_decl(self) -> ConstDecl:
        t = self.expect("const")
        name = self.next().val
        self.expect(":")
        ty = self.next().val
        if ty not in ("u32", "u64"):
            raise SyntaxError(f"line {t.line}: const type must be u32 or u64")
        self.expect("=")
        e = self.expr()
        self.expect(";")
        return ConstDecl(name, ty, e, t.line)

    def enum_decl(self) -> EnumDecl:
        t = self.expect("enum")
        name = self.next().val
        self.expect("{")
        variants = []
        while not self.at("}"):
            vt = self.next()
            if vt.kind != "ident":
                raise SyntaxError(f"line {vt.line}: expected variant name")
            self.expect("{")
            fields = []
            while not self.at("}"):
                fn_ = self.next().val
                self.expect(":")
                ft = self.next().val
                if ft not in ("u8", "u16", "u32", "u64", "str"):
                    raise SyntaxError(f"line {vt.line}: bad field type {ft!r}")
                fields.append((fn_, ft))
                if self.at(","):
                    self.next()
            self.expect("}")
            if self.at(","):
                self.next()
            variants.append(Variant(vt.val, fields, vt.line))
        self.expect("}")
        return EnumDecl(name, variants, t.line)

    def fn_decl(self) -> FnDecl:
        t = self.expect("fn")
        name = self.next().val
        self.expect("(")
        self.expect(")")
        body = self.block()
        return FnDecl(name, body, t.line)

    def block(self) -> list:
        self.expect("{")
        stmts = []
        while not self.at("}"):
            if self.peek().kind == "eof":
                raise SyntaxError("unexpected end of file in block")
            stmts.append(self.stmt())
        self.expect("}")
        return stmts

    # ---- statements ---------------------------------------------------------

    def stmt(self) -> Any:
        t = self.peek()
        if t.val == "var":
            return self.var_stmt()
        if t.val == "let":
            return self.let_stmt()
        if t.val == "for":
            return self.for_stmt()
        if t.val == "repeat":
            self.next()
            cnt = self.expr()
            body = self.block()
            return Repeat(cnt, body, t.line)
        if t.val == "if":
            return self.if_stmt()
        if t.val == "match":
            return self.match_stmt()
        if t.val == "print":
            self.next()
            self.expect("(")
            args = []
            if not self.at(")"):
                args.append(self.expr())
                while self.at(","):
                    self.next()
                    args.append(self.expr())
            self.expect(")")
            self.expect(";")
            return Print(args, t.line)
        if t.kind != "ident":
            raise SyntaxError(f"line {t.line}: unexpected {t.val!r}")

        # assignments, indexing, push, method calls and plain calls
        name = self.next().val
        if self.at(".") and self.peek(1).val == "push":
            self.expect(".")
            self.expect("push")
            self.expect("(")
            ctor = self.expr()
            if not isinstance(ctor, Ctor):
                raise SyntaxError(f"line {t.line}: push expects an enum constructor")
            self.expect(")")
            self.expect(";")
            return PushStmt(name, ctor, t.line)
        if self.at(".") and self.peek(1).kind == "ident" and self.peek(2).val == "(":
            self.expect(".")
            meth = self.next().val
            self.expect("(")
            args = []
            if not self.at(")"):
                args.append(self.expr())
                while self.at(","):
                    self.next()
                    args.append(self.expr())
            self.expect(")")
            self.expect(";")
            return MethodCall(name, meth, args, t.line)
        if self.at("("):
            self.next()
            args = []
            if not self.at(")"):
                args.append(self.expr())
                while self.at(","):
                    self.next()
                    args.append(self.expr())
            self.expect(")")
            self.expect(";")
            return Call(name, args, t.line)
        if self.at("["):
            self.next()
            idx = self.expr()
            self.expect("]")
            op = self.next().val
            if op not in ("=", "+="):
                raise SyntaxError(f"line {t.line}: expected '=' or '+=' in index assign")
            e = self.expr()
            self.expect(";")
            return IndexAssign(name, idx, op, e, t.line)
        op = self.next().val
        if op not in ("=", "+="):
            raise SyntaxError(f"line {t.line}: expected assignment, got {op!r}")
        e = self.expr()
        self.expect(";")
        return Assign(name, op, e, t.line)

    def var_stmt(self) -> VarDecl:
        t = self.expect("var")
        name = self.next().val
        self.expect(":")
        ty = self.type_name()
        e = None
        if self.at("="):
            self.next()
            e = self.expr()
        self.expect(";")
        if e is None and not (isinstance(ty, tuple) and ty[0] in ("store", "buf", "map")):
            raise SyntaxError(f"line {t.line}: var needs an initializer")
        return VarDecl(name, ty, e, t.line)

    def let_stmt(self) -> LetDecl:
        t = self.expect("let")
        name = self.next().val
        ty = None
        if self.at(":"):
            self.next()
            ty = self.next().val
            if ty not in ("u32", "u64", "str"):
                raise SyntaxError(f"line {t.line}: bad let type {ty!r}")
        self.expect("=")
        e = self.expr()
        self.expect(";")
        return LetDecl(name, ty, e, t.line)

    def for_stmt(self) -> Any:
        t = self.expect("for")
        var = self.next().val
        self.expect("in")
        first = self.expr()
        if self.at(".."):
            self.next()
            hi = self.expr()
            body = self.block()
            return ForRange(var, first, hi, body, t.line)
        if first.__class__.__name__ != "Name":
            raise SyntaxError(f"line {t.line}: for-in needs a store or map name")
        body = self.block()
        return ForIn(var, first.x, body, t.line)

    def if_stmt(self) -> If:
        t = self.expect("if")
        cond = self.expr()
        then = self.block()
        elifs = []
        els = None
        while self.at("elif"):
            self.next()
            c2 = self.expr()
            b2 = self.block()
            elifs.append((c2, b2))
        if self.at("else"):
            self.next()
            els = self.block()
        return If(cond, then, elifs, els, t.line)

    def match_stmt(self) -> MatchOn:
        t = self.expect("match")
        v = self.next().val
        self.expect("{")
        arms = []
        while not self.at("}"):
            vt = self.next()
            if vt.kind != "ident":
                raise SyntaxError(f"line {vt.line}: expected variant name in match")
            binder = None
            if self.at("("):
                self.next()
                binder = self.next().val
                self.expect(")")
            self.expect("=>")
            body = self.block()
            arms.append((vt.val, binder, body))
        self.expect("}")
        return MatchOn(v, arms, t.line)

    # ---- types and expressions ----------------------------------------------

    def type_name(self) -> Any:
        t = self.next()
        if t.val == "store":
            self.expect("<")
            en = self.next().val
            self.expect(">")
            self.expect("(")
            cap = self.expr()
            self.expect(")")
            return ("store", en, cap)
        if t.val == "buf":
            self.expect("<")
            el = self.next().val
            if el not in ("u32", "u64"):
                raise SyntaxError(f"line {t.line}: buf element must be u32 or u64")
            self.expect(">")
            self.expect("(")
            cap = self.expr()
            self.expect(")")
            return ("buf", el, cap)
        if t.val == "map":
            self.expect("<")
            kt = self.next().val
            if kt != "str":
                raise SyntaxError(f"line {t.line}: map key type must be str in v0.2")
            self.expect(",")
            vt = self.next().val
            if vt != "u64":
                raise SyntaxError(f"line {t.line}: map value type must be u64 in v0.2")
            self.expect(">")
            self.expect("(")
            slots = self.expr()
            self.expect(")")
            return ("map", "str", "u64", slots)
        if t.val in ("u32", "u64"):
            return t.val
        raise SyntaxError(f"line {t.line}: bad type {t.val!r}")

    def expr(self) -> Any:
        return self.equality()

    def equality(self):
        l = self.relational()
        while self.peek().val in ("==", "!="):
            t = self.next()
            r = self.relational()
            l = Bin(t.val, l, r, t.line)
        return l

    def relational(self):
        l = self.additive()
        while self.peek().val in ("<", ">", "<=", ">="):
            t = self.next()
            r = self.additive()
            l = Bin(t.val, l, r, t.line)
        return l

    def additive(self):
        l = self.shift()
        while self.peek().val in ("+", "-"):
            t = self.next()
            r = self.shift()
            l = Bin(t.val, l, r, t.line)
        return l

    def shift(self):
        l = self.bits()
        while self.peek().val in ("<<", ">>"):
            t = self.next()
            r = self.bits()
            l = Bin(t.val, l, r, t.line)
        return l

    def bits(self):
        l = self.multiplicative()
        while self.peek().val in ("&", "^", "|"):
            t = self.next()
            r = self.multiplicative()
            l = Bin(t.val, l, r, t.line)
        return l

    def multiplicative(self):
        l = self.unary()
        while self.peek().val in ("*", "/", "%"):
            t = self.next()
            r = self.unary()
            l = Bin(t.val, l, r, t.line)
        return l

    def unary(self):
        if self.at("-"):
            t = self.next()
            e = self.unary()
            if isinstance(e, Num):
                raise SyntaxError(f"line {t.line}: negative literals are not supported on unsigned types")
            raise SyntaxError(f"line {t.line}: unary '-' is not supported in v0.2")
        return self.primary()

    def primary(self) -> Any:
        t = self.next()
        if t.kind == "int":
            return Num(t.val, t.line)
        if t.kind == "str":
            return StrLit(t.val, t.line)
        if t.kind == "kw" and t.val == "str":
            self.expect("(")
            e = self.expr()
            self.expect(")")
            return StrOf(e, t.line)
        if t.val == "(":
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "ident":
            if self.at("("):
                self.next()
                args = []
                if not self.at(")"):
                    args.append(self.expr())
                    while self.at(","):
                        self.next()
                        args.append(self.expr())
                self.expect(")")
                return Call(t.val, args, t.line)
            if self.at(".") and self.peek(1).kind == "ident" and self.peek(2).val == "{":
                self.next()
                vname = self.next().val
                self.expect("{")
                inits = []
                while not self.at("}"):
                    fn_ = self.next().val
                    self.expect(":")
                    e = self.expr()
                    inits.append((fn_, e))
                    if self.at(","):
                        self.next()
                self.expect("}")
                return Ctor(t.val, vname, inits, t.line)
            if self.at(".") and self.peek(1).kind == "ident" and self.peek(2).val != "{":
                path = t.val
                while self.at(".") and self.peek(1).kind == "ident" and self.peek(2).val != "{":
                    self.next()
                    fname = self.next().val
                    path = path + "." + fname
                return Field(path.rsplit(".", 1)[0], path.rsplit(".", 1)[1], t.line)
            if self.at("["):
                self.next()
                idx = self.expr()
                self.expect("]")
                return Index(t.val, idx, t.line)
            return Name(t.val, t.line)
        raise SyntaxError(f"line {t.line}: unexpected token {t.val!r}")


def parse(src: str) -> Program:
    return Parser(lex(src)).parse_program()
