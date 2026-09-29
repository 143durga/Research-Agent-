"""Minimal pytest-compatible runner used ONLY when pytest cannot be installed
(e.g. offline sandbox). Supports the fixtures/raises this suite uses.
Prefer `pytest` when available."""
import sys, os, inspect, importlib, tempfile, pathlib, traceback, contextlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import types

# --- tiny pytest stand-in so test modules can `import pytest` ---
pt = types.ModuleType("pytest")
@contextlib.contextmanager
def raises(exc):
    try:
        yield
    except exc:
        return
    raise AssertionError(f"did not raise {exc}")
def fixture(*a, **k):
    if a and callable(a[0]): return a[0]
    return lambda f: f
pt.raises, pt.fixture = raises, fixture
sys.modules["pytest"] = pt
import conftest  # sets env + defines fixtures

class MonkeyPatch:
    def __init__(self): self._undo = []
    def setattr(self, target, *rest):
        if isinstance(target, str):
            value = rest[0]
            # like pytest: import the longest importable module prefix, then walk attributes
            # (so "requests.Session.get" patches the `get` attribute of the Session class)
            parts = target.split(".")
            obj = None
            for i in range(len(parts) - 1, 0, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:i]))
                    rest_path = parts[i:-1]
                    break
                except ImportError:
                    continue
            if obj is None:
                raise ImportError(target)
            for name in rest_path:
                obj = getattr(obj, name)
            attr = parts[-1]
        else:
            obj, attr, value = target, rest[0], rest[1]
        self._undo.append((obj, attr, getattr(obj, attr))); setattr(obj, attr, value)
    def setenv(self, k, v):
        if k in os.environ: self._undo.append((os.environ, k, os.environ[k], "env"))
        else: self._undo.append((os.environ, k, None, "envdel"))
        os.environ[k] = str(v)
    def delenv(self, k, raising=True):
        if k in os.environ: self._undo.append((os.environ, k, os.environ[k], "env")); del os.environ[k]
    def undo(self):
        for u in reversed(self._undo):
            if len(u) == 4 and u[3] == "envdel": u[0].pop(u[1], None)
            elif len(u) == 4: u[0][u[1]] = u[2]
            else: setattr(u[0], u[1], u[2])

def make(name, mp, tmp):
    if name == "monkeypatch": return mp
    if name == "tmp_path": return tmp
    if name == "fake_llm": return conftest.fake_llm.__wrapped__(mp) if hasattr(conftest.fake_llm, "__wrapped__") else conftest.fake_llm(mp)
    if name == "sample_pdf": return conftest.sample_pdf(tmp)
    if name == "client": return conftest.client()
    raise KeyError(name)

conftest._db()
passed = failed = 0
for f in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
    mod = importlib.import_module(f.stem)
    for n, fn in inspect.getmembers(mod, inspect.isfunction):
        if not n.startswith("test_"): continue
        mp, tmp = MonkeyPatch(), pathlib.Path(tempfile.mkdtemp())
        try:
            fn(**{p: make(p, mp, tmp) for p in inspect.signature(fn).parameters})
            passed += 1; print("PASS", f.stem, n)
        except Exception:
            failed += 1; print("FAIL", f.stem, n); traceback.print_exc()
        finally: mp.undo()
print(f"\n{passed} passed, {failed} failed"); sys.exit(1 if failed else 0)
