"""
The module contains the main class ``ExtTestCase`` which adds
specific functionalities to this project.
"""

import copy
import glob
import itertools
import logging
import os
import re
import sys
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from timeit import Timer
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import numpy
from numpy.testing import assert_allclose

BOOLEAN_VALUES = (1, "1", True, "True", "true", "TRUE")


def is_azure() -> bool:
    """Tells if the job is running on Azure DevOps."""
    return os.environ.get("AZURE_HTTP_USER_AGENT", "undefined") != "undefined"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_apple() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform == "linux"


def skipif_ci_windows(msg) -> Callable:
    """Skips a unit test if it runs on :epkg:`azure pipeline` on :epkg:`Windows`."""
    if is_windows() and is_azure():
        msg = f"Test does not work on azure pipeline (Windows). {msg}"
        return unittest.skip(msg)
    return lambda x: x


def skipif_ci_linux(msg) -> Callable:
    """Skips a unit test if it runs on :epkg:`azure pipeline` on :epkg:`Linux`."""
    if is_linux() and is_azure():
        msg = f"Takes too long (Linux). {msg}"
        return unittest.skip(msg)
    return lambda x: x


def skipif_ci_apple(msg) -> Callable:
    """Skips a unit test if it runs on :epkg:`azure pipeline` on :epkg:`Windows`."""
    if is_apple() and is_azure():
        msg = f"Test does not work on azure pipeline (Apple). {msg}"
        return unittest.skip(msg)
    return lambda x: x


def unit_test_going():
    """
    Enables a flag telling the script is running while testing it.
    Avois unit tests to be very long.
    """
    going = int(os.environ.get("UNITTEST_GOING", 0))
    return going == 1


def ignore_warnings(warns: List[Warning]) -> Callable:
    """
    Catches warnings.

    :param warns:   warnings to ignore
    """
    if not isinstance(warns, (tuple, list)):
        warns = (warns,)
    new_list = []
    for w in warns:
        if w == "TracerWarning":
            from torch.jit import TracerWarning

            new_list.append(TracerWarning)
        else:
            new_list.append(w)
    warns = tuple(new_list)

    def wrapper(fct):
        if warns is None:
            raise AssertionError(f"warns cannot be None for '{fct}'.")

        def call_f(self):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", warns)
                return fct(self)

        try:  # noqa: SIM105
            call_f.__name__ = fct.__name__
        except AttributeError:
            pass
        return call_f

    return wrapper


def ignore_errors(errors: Union[Exception, Tuple[Exception]]) -> Callable:
    """
    Catches exception, skip the test if the error is expected sometimes.

    :param errors: errors to ignore
    """

    def wrapper(fct):
        if errors is None:
            raise AssertionError(f"errors cannot be None for '{fct}'.")

        def call_f(self):
            try:
                return fct(self)
            except errors as e:
                raise unittest.SkipTest(  # noqa: B904
                    f"expecting error {e.__class__.__name__}: {e}"
                )

        try:  # noqa: SIM105
            call_f.__name__ = fct.__name__
        except AttributeError:
            pass
        return call_f

    return wrapper


def hide_stdout(f: Optional[Callable] = None) -> Callable:
    """
    Catches warnings, hides standard output.
    The function may be disabled by setting ``UNHIDE=1``
    before running the unit test.

    :param f: the function is called with the stdout as an argument
    """

    def wrapper(fct):
        def call_f(self):
            if os.environ.get("UNHIDE", ""):
                fct(self)
                return
            st = StringIO()
            with redirect_stdout(st), warnings.catch_warnings():
                warnings.simplefilter("ignore", (UserWarning, DeprecationWarning))
                try:
                    fct(self)
                except AssertionError as e:
                    if "torch is not recent enough, file" in str(e):
                        raise unittest.SkipTest(str(e))  # noqa: B904
                    raise
            if f is not None:
                f(st.getvalue())
            return None

        try:  # noqa: SIM105
            call_f.__name__ = fct.__name__
        except AttributeError:
            pass
        return call_f

    return wrapper


def long_test(msg: str = "") -> Callable:
    """Skips a unit test if it runs on :epkg:`azure pipeline` on :epkg:`Windows`."""
    if os.environ.get("LONGTEST", "0") in ("0", 0, False, "False", "false"):
        msg = f"Skipped (set LONGTEST=1 to run it. {msg}"
        return unittest.skip(msg)
    return lambda x: x


def never_test(msg: str = "") -> Callable:
    """Skips a unit test."""
    if os.environ.get("NEVERTEST", "0") in ("0", 0, False, "False", "false"):
        msg = f"Skipped (set NEVERTEST=1 to run it. {msg}"
        return unittest.skip(msg)
    return lambda x: x


def measure_time(
    stmt: Union[str, Callable],
    context: Optional[Dict[str, Any]] = None,
    repeat: int = 10,
    number: int = 50,
    warmup: int = 1,
    div_by_number: bool = True,
    max_time: Optional[float] = None,
) -> Dict[str, Union[str, int, float]]:
    """
    Measures a statement and returns the results as a dictionary.

    :param stmt: string or callable
    :param context: variable to know in a dictionary
    :param repeat: average over *repeat* experiment
    :param number: number of executions in one row
    :param warmup: number of iteration to do before starting the
        real measurement
    :param div_by_number: divide by the number of executions
    :param max_time: execute the statement until the total goes
        beyond this time (approximately), *repeat* is ignored,
        *div_by_number* must be set to True
    :return: dictionary

    .. runpython::
        :showcode:

        from pprint import pprint
        from math import cos
        from onnx_diagnostic.ext_test_case import measure_time

        res = measure_time(lambda: cos(0.5))
        pprint(res)

    See `Timer.repeat <https://docs.python.org/3/library/
    timeit.html?timeit.Timer.repeat>`_
    for a better understanding of parameter *repeat* and *number*.
    The function returns a duration corresponding to
    *number* times the execution of the main statement.
    """
    if not callable(stmt) and not isinstance(stmt, str):
        raise TypeError(f"stmt is not callable or a string but is of type {type(stmt)!r}.")
    if context is None:
        context = {}

    if isinstance(stmt, str):
        tim = Timer(stmt, globals=context)
    else:
        tim = Timer(stmt)

    if warmup > 0:
        warmup_time = tim.timeit(warmup)
    else:
        warmup_time = 0

    if max_time is not None:
        if not div_by_number:
            raise ValueError("div_by_number must be set to True of max_time is defined.")
        i = 1
        total_time = 0.0
        results = []
        while True:
            for j in (1, 2):
                number = i * j
                time_taken = tim.timeit(number)
                results.append((number, time_taken))
                total_time += time_taken
                if total_time >= max_time:
                    break
            if total_time >= max_time:
                break
            ratio = (max_time - total_time) / total_time
            ratio = max(ratio, 1)
            i = int(i * ratio)

        res = numpy.array(results)
        tw = res[:, 0].sum()
        ttime = res[:, 1].sum()
        mean = ttime / tw
        ave = res[:, 1] / res[:, 0]
        dev = (((ave - mean) ** 2 * res[:, 0]).sum() / tw) ** 0.5
        mes = dict(
            average=mean,
            deviation=dev,
            min_exec=numpy.min(ave),
            max_exec=numpy.max(ave),
            repeat=1,
            number=tw,
            ttime=ttime,
        )
    else:
        res = numpy.array(tim.repeat(repeat=repeat, number=number))
        if div_by_number:
            res /= number

        mean = numpy.mean(res)
        dev = numpy.mean(res**2)
        dev = (dev - mean**2) ** 0.5
        mes = dict(
            average=mean,
            deviation=dev,
            min_exec=numpy.min(res),
            max_exec=numpy.max(res),
            repeat=repeat,
            number=number,
            ttime=res.sum(),
        )

    if "values" in context:
        if hasattr(context["values"], "shape"):
            mes["size"] = context["values"].shape[0]
        else:
            mes["size"] = len(context["values"])
    else:
        mes["context_size"] = sys.getsizeof(context)
    mes["warmup_time"] = warmup_time
    return mes


def statistics_on_folder(
    folder: Union[str, List[str]],
    pattern: str = ".*[.]((py|rst))$",
    aggregation: int = 0,
) -> List[Dict[str, Union[int, float, str]]]:
    """
    Computes statistics on files in a folder.

    :param folder: folder or folders to investigate
    :param pattern: file pattern
    :param aggregation: show the first subfolders
    :return: list of dictionaries

    .. runpython::
        :showcode:
        :toggle:

        import os
        import pprint
        from onnx_diagnostic.ext_test_case import statistics_on_folder, __file__

        pprint.pprint(statistics_on_folder(os.path.dirname(__file__)))

    Aggregated:

    .. runpython::
        :showcode:
        :toggle:

        import os
        import pprint
        from onnx_diagnostic.ext_test_case import statistics_on_folder, __file__

        pprint.pprint(statistics_on_folder(os.path.dirname(__file__), aggregation=1))
    """
    if isinstance(folder, list):
        rows = []
        for fold in folder:
            last = fold.replace("\\", "/").split("/")[-1]
            r = statistics_on_folder(
                fold, pattern=pattern, aggregation=max(aggregation - 1, 0)
            )
            if aggregation == 0:
                rows.extend(r)
                continue
            for line in r:
                line["dir"] = os.path.join(last, line["dir"])
            rows.extend(r)
        return rows

    rows = []
    reg = re.compile(pattern)
    for name in glob.glob("**/*", root_dir=folder, recursive=True):
        if not reg.match(name):
            continue
        if os.path.isdir(os.path.join(folder, name)):
            continue
        n = name.replace("\\", "/")
        spl = n.split("/")
        level = len(spl)
        stat = statistics_on_file(os.path.join(folder, name))
        stat["name"] = name
        if aggregation <= 0:
            rows.append(stat)
            continue
        spl = os.path.dirname(name).replace("\\", "/").split("/")
        level = "/".join(spl[:aggregation])
        stat["dir"] = level
        rows.append(stat)
    return rows


def get_figure(ax):
    """Returns the figure of a matplotlib figure."""
    if hasattr(ax, "get_figure"):
        return ax.get_figure()
    if len(ax.shape) == 0:
        return ax.get_figure()
    if len(ax.shape) == 1:
        return ax[0].get_figure()
    if len(ax.shape) == 2:
        return ax[0, 0].get_figure()
    raise RuntimeError(f"Unexpected shape {ax.shape} for axis.")


def has_cuda() -> bool:
    """Returns ``torch.cuda.device_count() > 0``."""
    import torch

    return torch.cuda.device_count() > 0


def requires_python(version: Tuple[int, ...], msg: str = ""):
    """
    Skips a test if python is too old.

    :param msg: to overwrite the message
    :param version: minimum version
    """
    if sys.version_info[: len(version)] < version:
        return unittest.skip(msg or f"python not recent enough {sys.version_info} < {version}")
    return lambda x: x


def requires_cuda(msg: str = "", version: str = "", memory: int = 0):
    """
    Skips a test if cuda is not available.

    :param msg: to overwrite the message
    :param version: minimum version
    :param memory: minimum number of Gb to run the test
    """
    import torch

    if torch.cuda.device_count() == 0:
        msg = msg or "only runs on CUDA but torch does not have it"
        return unittest.skip(msg or "cuda not installed")
    if version:
        import packaging.versions as pv

        if pv.Version(torch.version.cuda) < pv.Version(version):
            msg = msg or f"CUDA older than {version}"
        return unittest.skip(msg or f"cuda not recent enough {torch.version.cuda} < {version}")

    if memory:
        m = torch.cuda.get_device_properties(0).total_memory / 2**30
        if m < memory:
            msg = msg or f"available memory is not enough {m} < {memory} (Gb)"
            return unittest.skip(msg)

    return lambda x: x


def requires_zoo(msg: str = "") -> Callable:
    """Skips a unit test if environment variable ZOO is not equal to 1."""
    var = os.environ.get("ZOO", "0") in BOOLEAN_VALUES

    if not var:
        msg = f"ZOO not set up or != 1. {msg}"
        return unittest.skip(msg or "zoo not installed")
    return lambda x: x


def requires_sklearn(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`scikit-learn` is not recent enough."""
    import packaging.version as pv
    import sklearn

    if pv.Version(sklearn.__version__) < pv.Version(version):
        msg = f"scikit-learn version {sklearn.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def requires_experimental(version: str = "0.0.0", msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`experimental-experiment` is not recent enough."""
    import packaging.version as pv

    try:
        import experimental_experiment
    except ImportError:
        msg = f"experimental-experiment not installed: {msg}"
        return unittest.skip(msg)

    if pv.Version(experimental_experiment.__version__) < pv.Version(version):
        msg = (
            f"experimental-experiment version "
            f"{experimental_experiment.__version__} < {version}: {msg}"
        )
        return unittest.skip(msg)
    return lambda x: x


def has_torch(version: str) -> bool:
    "Returns True if torch transformers is higher."
    import packaging.version as pv
    import torch

    return pv.Version(torch.__version__) >= pv.Version(version)


def has_transformers(version: str) -> bool:
    "Returns True if transformers version is higher."
    import packaging.version as pv
    import transformers

    return pv.Version(transformers.__version__) >= pv.Version(version)


def requires_torch(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`pytorch` is not recent enough."""
    import packaging.version as pv
    import torch

    if pv.Version(torch.__version__) < pv.Version(version):
        msg = f"torch version {torch.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def requires_numpy(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`numpy` is not recent enough."""
    import packaging.version as pv
    import numpy

    if pv.Version(numpy.__version__) < pv.Version(version):
        msg = f"numpy version {numpy.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def requires_transformers(
    version: str, msg: str = "", or_older_than: Optional[str] = None
) -> Callable:
    """Skips a unit test if :epkg:`transformers` is not recent enough."""
    import packaging.version as pv

    try:
        import transformers
    except ImportError:
        msg = f"diffusers not installed {msg}"
        return unittest.skip(msg)

    v = pv.Version(transformers.__version__)
    if v < pv.Version(version):
        msg = f"transformers version {transformers.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    if or_older_than and v > pv.Version(or_older_than):
        msg = (
            f"transformers version {or_older_than} < "
            f"{transformers.__version__} < {version}: {msg}"
        )
        return unittest.skip(msg)
    return lambda x: x


def requires_diffusers(
    version: str, msg: str = "", or_older_than: Optional[str] = None
) -> Callable:
    """Skips a unit test if :epkg:`transformers` is not recent enough."""
    import packaging.version as pv

    try:
        import diffusers
    except ImportError:
        msg = f"diffusers not installed {msg}"
        return unittest.skip(msg)

    v = pv.Version(diffusers.__version__)
    if v < pv.Version(version):
        msg = f"diffusers version {diffusers.__version__} < {version} {msg}"
        return unittest.skip(msg)
    if or_older_than and v > pv.Version(or_older_than):
        msg = (
            f"diffusers version {or_older_than} < "
            f"{diffusers.__version__} < {version} {msg}"
        )
        return unittest.skip(msg)
    return lambda x: x


def requires_onnxscript(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`onnxscript` is not recent enough."""
    import packaging.version as pv
    import onnxscript

    if not hasattr(onnxscript, "__version__"):
        # development version
        return lambda x: x

    if pv.Version(onnxscript.__version__) < pv.Version(version):
        msg = f"onnxscript version {onnxscript.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def has_onnxscript(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`onnxscript` is not recent enough."""
    import packaging.version as pv
    import onnxscript

    if not hasattr(onnxscript, "__version__"):
        # development version
        return True

    if pv.Version(onnxscript.__version__) < pv.Version(version):
        msg = f"onnxscript version {onnxscript.__version__} < {version}: {msg}"
        return False
    return True


def requires_onnxruntime(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`onnxruntime` is not recent enough."""
    import packaging.version as pv
    import onnxruntime

    if pv.Version(onnxruntime.__version__) < pv.Version(version):
        msg = f"onnxruntime version {onnxruntime.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def has_onnxruntime_training(push_back_batch: bool = False):
    """Tells if onnxruntime_training is installed."""
    try:
        from onnxruntime import training
    except ImportError:
        # onnxruntime not training
        training = None
    if training is None:
        return False

    if push_back_batch:
        try:
            from onnxruntime.capi.onnxruntime_pybind11_state import OrtValueVector
        except ImportError:
            return False

        if not hasattr(OrtValueVector, "push_back_batch"):
            return False
    return True


def requires_onnxruntime_training(
    push_back_batch: bool = False, ortmodule: bool = False, msg: str = ""
) -> Callable:
    """Skips a unit test if :epkg:`onnxruntime` is not onnxruntime_training."""
    try:
        from onnxruntime import training
    except ImportError:
        # onnxruntime not training
        training = None
    if training is None:
        msg = msg or "onnxruntime_training is not installed"
        return unittest.skip(msg)

    if push_back_batch:
        try:
            from onnxruntime.capi.onnxruntime_pybind11_state import OrtValueVector
        except ImportError:
            msg = msg or "OrtValue has no method push_back_batch"
            return unittest.skip(msg)

        if not hasattr(OrtValueVector, "push_back_batch"):
            msg = msg or "OrtValue has no method push_back_batch"
            return unittest.skip(msg)
    if ortmodule:
        try:
            import onnxruntime.training.ortmodule  # noqa: F401
        except (AttributeError, ImportError):
            msg = msg or "ortmodule is missing in onnxruntime-training"
            return unittest.skip(msg)
    return lambda x: x


def requires_onnx(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`onnx` is not recent enough."""
    import packaging.version as pv
    import onnx

    if pv.Version(onnx.__version__) < pv.Version(version):
        msg = f"onnx version {onnx.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def requires_onnx_array_api(version: str, msg: str = "") -> Callable:
    """Skips a unit test if :epkg:`onnx-array-api` is not recent enough."""
    import packaging.version as pv
    import onnx_array_api

    if pv.Version(onnx_array_api.__version__) < pv.Version(version):
        msg = f"onnx-array-api version {onnx_array_api.__version__} < {version}: {msg}"
        return unittest.skip(msg)
    return lambda x: x


def statistics_on_file(filename: str) -> Dict[str, Union[int, float, str]]:
    """
    Computes statistics on a file.

    .. runpython::
        :showcode:

        import pprint
        from onnx_diagnostic.ext_test_case import statistics_on_file, __file__

        pprint.pprint(statistics_on_file(__file__))
    """
    assert os.path.exists(filename), f"File {filename!r} does not exists."

    ext = os.path.splitext(filename)[-1]
    if ext not in {".py", ".rst", ".md", ".txt"}:
        size = os.stat(filename).st_size
        return {"size": size}
    alpha = set("abcdefghijklmnopqrstuvwxyz0123456789")
    with open(filename, "r", encoding="utf-8") as f:
        n_line = 0
        n_ch = 0
        for line in f.readlines():
            s = line.strip("\n\r\t ")
            if s:
                n_ch += len(s.replace(" ", ""))
                ch = set(s.lower()) & alpha
                if ch:
                    # It avoid counting line with only a bracket, a comma.
                    n_line += 1

    stat = dict(lines=n_line, chars=n_ch, ext=ext)
    if ext != ".py":
        return stat
    # add statistics on python syntax?
    return stat


class ExtTestCase(unittest.TestCase):
    """
    Inherits from :class:`unittest.TestCase` and adds specific comprison
    functions and other helper.
    """

    _warns: List[Tuple[str, int, Warning]] = []
    _todos: List[Tuple[Callable, str]] = []

    @property
    def verbose(self):
        "Returns the the value of environment variable ``VERBOSE``."
        return int(os.environ.get("VERBOSE", "0"))

    @classmethod
    def setUpClass(cls):
        logger = logging.getLogger("onnxscript.optimizer.constant_folding")
        logger.setLevel(logging.ERROR)
        unittest.TestCase.setUpClass()

    @classmethod
    def tearDownClass(cls):
        for name, line, w in cls._warns:
            warnings.warn(f"\n{name}:{line}: {type(w)}\n  {w!s}", stacklevel=2)
        if not cls._todos:
            return
        for f, msg in cls._todos:
            sys.stderr.write(f"TODO {cls.__name__}::{f.__name__}: {msg}\n")

    @classmethod
    def todo(cls, f: Callable, msg: str):
        "Adds a todo printed when all test are run."
        cls._todos.append((f, msg))

    @classmethod
    def ort(cls):
        import onnxruntime

        return onnxruntime

    @classmethod
    def to_onnx(self, *args, **kwargs):
        from experimental_experiment.torch_interpreter import to_onnx

        return to_onnx(*args, **kwargs)

    def print_model(self, model: "ModelProto"):  # noqa: F821
        "Prints a ModelProto"
        from onnx_diagnostic.helpers.onnx_helper import pretty_onnx

        print(pretty_onnx(model))

    def print_onnx(self, model: "ModelProto"):  # noqa: F821
        "Prints a ModelProto"
        from onnx_diagnostic.helpers.onnx_helper import pretty_onnx

        print(pretty_onnx(model))

    def get_dump_file(self, name: str, folder: Optional[str] = None) -> str:
        """Returns a filename to dump a model."""
        if folder is None:
            folder = "dump_test"
        if folder and not os.path.exists(folder):
            os.mkdir(folder)
        return os.path.join(folder, name)

    def get_dump_folder(self, folder: str) -> str:
        """Returns a folder."""
        folder = os.path.join("dump_test", folder)
        if not os.path.exists(folder):
            os.makedirs(folder)
        return folder

    def dump_onnx(
        self,
        name: str,
        proto: Any,
        folder: Optional[str] = None,
    ) -> str:
        """Dumps an onnx file."""
        fullname = self.get_dump_file(name, folder=folder)
        with open(fullname, "wb") as f:
            f.write(proto.SerializeToString())
        return fullname

    def assertExists(self, name):
        """Checks the existing of a file."""
        if not os.path.exists(name):
            raise AssertionError(f"File or folder {name!r} does not exists.")

    def assertGreaterOrEqual(self, a, b, msg=None):
        """In the name"""
        if a < b:
            return AssertionError(f"{a} < {b}, a not greater or equal than b\n{msg or ''}")

    def assertInOr(self, tofind: Tuple[str, ...], text: str, msg: str = ""):
        for tof in tofind:
            if tof in text:
                return
        raise AssertionError(
            msg or f"Unable to find one string in the list {tofind!r} in\n--\n{text}"
        )

    def assertIn(self, tofind: str, text: str, msg: str = ""):
        if tofind in text:
            return
        raise AssertionError(
            msg or f"Unable to find the list of strings {tofind!r} in\n--\n{text}"
        )

    def assertHasAttr(self, obj: Any, name: str):
        assert hasattr(
            obj, name
        ), f"Unable to find attribute {name!r} in object type {type(obj)}"

    def assertSetContained(self, set1, set2):
        "Checks that ``set1`` is contained in ``set2``."
        set1 = set(set1)
        set2 = set(set2)
        if set1 & set2 != set1:
            raise AssertionError(f"Set {set2} does not contain set {set1}.")

    def assertEqualArrays(
        self,
        expected: Sequence[numpy.ndarray],
        value: Sequence[numpy.ndarray],
        atol: float = 0,
        rtol: float = 0,
        msg: Optional[str] = None,
    ):
        """In the name"""
        self.assertEqual(len(expected), len(value))
        for a, b in zip(expected, value):
            self.assertEqualArray(a, b, atol=atol, rtol=rtol)

    def assertEqualArray(
        self,
        expected: Any,
        value: Any,
        atol: float = 0,
        rtol: float = 0,
        msg: Optional[str] = None,
    ):
        """In the name"""
        if hasattr(expected, "detach") and hasattr(value, "detach"):
            if msg:
                try:
                    self.assertEqual(expected.dtype, value.dtype)
                except AssertionError as e:
                    raise AssertionError(msg) from e
                try:
                    self.assertEqual(expected.shape, value.shape)
                except AssertionError as e:
                    raise AssertionError(msg) from e
            else:
                self.assertEqual(expected.dtype, value.dtype)
                self.assertEqual(expected.shape, value.shape)

            import torch

            try:
                torch.testing.assert_close(value, expected, atol=atol, rtol=rtol)
            except AssertionError as e:
                expected_max = torch.abs(expected).max()
                expected_value = torch.abs(value).max()
                rows = [
                    f"{msg}\n{e}" if msg else str(e),
                    f"expected max value={expected_max}",
                    f"expected computed value={expected_value}",
                ]
                raise AssertionError("\n".join(rows))  # noqa: B904
            return

        from .helpers.torch_helper import to_numpy

        if hasattr(expected, "detach"):
            expected = to_numpy(expected.detach().cpu())
        if hasattr(value, "detach"):
            value = to_numpy(value.detach().cpu())
        if msg:
            try:
                self.assertEqual(expected.dtype, value.dtype)
            except AssertionError as e:
                raise AssertionError(msg) from e
            try:
                self.assertEqual(expected.shape, value.shape)
            except AssertionError as e:
                raise AssertionError(msg) from e
        else:
            self.assertEqual(expected.dtype, value.dtype)
            self.assertEqual(expected.shape, value.shape)

        try:
            assert_allclose(desired=expected, actual=value, atol=atol, rtol=rtol)
        except AssertionError as e:
            expected_max = numpy.abs(expected).max()
            expected_value = numpy.abs(value).max()
            te = expected.astype(int) if expected.dtype == numpy.bool_ else expected
            tv = value.astype(int) if value.dtype == numpy.bool_ else value
            rows = [
                f"{msg}\n{e}" if msg else str(e),
                f"expected max value={expected_max}",
                f"expected computed value={expected_value}\n",
                f"ratio={te / tv}\ndiff={te - tv}",
            ]
            raise AssertionError("\n".join(rows))  # noqa: B904

    def assertEqualDataFrame(self, d1, d2, **kwargs):
        """
        Checks that two dataframes are equal.
        Calls :func:`pandas.testing.assert_frame_equal`.
        """
        from pandas.testing import assert_frame_equal

        assert_frame_equal(d1, d2, **kwargs)

    def assertEqualTrue(self, value: Any, msg: str = ""):
        if value is True:
            return
        raise AssertionError(msg or f"value is not True: {value!r}")

    def assertEqual(self, expected: Any, value: Any, msg: str = ""):
        """Overwrites the error message to get a more explicit message about what is what."""
        if msg:
            super().assertEqual(expected, value, msg)
        else:
            try:
                super().assertEqual(expected, value)
            except AssertionError as e:
                raise AssertionError(  # noqa: B904
                    f"expected is {expected!r}, value is {value!r}\n{e}"
                )

    def assertEqualAny(
        self, expected: Any, value: Any, atol: float = 0, rtol: float = 0, msg: str = ""
    ):
        if expected.__class__.__name__ == "BaseModelOutput":
            self.assertEqual(type(expected), type(value), msg=msg)
            self.assertEqual(len(expected), len(value), msg=msg)
            self.assertEqual(list(expected), list(value), msg=msg)  # checks the order
            self.assertEqualAny(
                {k: v for k, v in expected.items()},  # noqa: C416
                {k: v for k, v in value.items()},  # noqa: C416
                atol=atol,
                rtol=rtol,
                msg=msg,
            )
        elif isinstance(expected, (tuple, list, dict)):
            self.assertIsInstance(value, type(expected), msg=msg)
            self.assertEqual(len(expected), len(value), msg=msg)
            if isinstance(expected, dict):
                for k in expected:
                    self.assertIn(k, value, msg=msg)
                    self.assertEqualAny(expected[k], value[k], msg=msg, atol=atol, rtol=rtol)
            else:
                for e, g in zip(expected, value):
                    self.assertEqualAny(e, g, msg=msg, atol=atol, rtol=rtol)
        elif expected.__class__.__name__ in ("DynamicCache", "SlidingWindowCache"):
            self.assertEqual(type(expected), type(value), msg=msg)
            atts = ["key_cache", "value_cache"]
            self.assertEqualAny(
                {k: expected.__dict__.get(k, None) for k in atts},
                {k: value.__dict__.get(k, None) for k in atts},
                atol=atol,
                rtol=rtol,
            )
        elif expected.__class__.__name__ == "StaticCache":
            self.assertEqual(type(expected), type(value), msg=msg)
            self.assertEqual(expected.max_cache_len, value.max_cache_len)
            atts = ["key_cache", "value_cache"]
            self.assertEqualAny(
                {k: expected.__dict__.get(k, None) for k in atts},
                {k: value.__dict__.get(k, None) for k in atts},
                atol=atol,
                rtol=rtol,
            )
        elif expected.__class__.__name__ == "EncoderDecoderCache":
            self.assertEqual(type(expected), type(value), msg=msg)
            atts = ["self_attention_cache", "cross_attention_cache"]
            self.assertEqualAny(
                {k: expected.__dict__.get(k, None) for k in atts},
                {k: value.__dict__.get(k, None) for k in atts},
                atol=atol,
                rtol=rtol,
            )
        elif isinstance(expected, (int, float, str)):
            self.assertEqual(expected, value, msg=msg)
        elif hasattr(expected, "shape"):
            self.assertEqual(type(expected), type(value), msg=msg)
            self.assertEqualArray(expected, value, msg=msg, atol=atol, rtol=rtol)
        elif expected.__class__.__name__ in ("Dim", "_Dim", "_DimHintType"):
            self.assertEqual(type(expected), type(value), msg=msg)
            self.assertEqual(expected.__name__, value.__name__, msg=msg)
        elif expected is None:
            self.assertEqual(expected, value, msg=msg)
        else:
            raise AssertionError(
                f"Comparison not implemented for types {type(expected)} and {type(value)}"
            )

    def assertEqualArrayAny(
        self, expected: Any, value: Any, atol: float = 0, rtol: float = 0, msg: str = ""
    ):
        if isinstance(expected, (tuple, list, dict)):
            self.assertIsInstance(value, type(expected), msg=msg)
            self.assertEqual(len(expected), len(value), msg=msg)
            if isinstance(expected, dict):
                for k in expected:
                    self.assertIn(k, value, msg=msg)
                    self.assertEqualArrayAny(
                        expected[k], value[k], msg=msg, atol=atol, rtol=rtol
                    )
            else:
                excs = []
                for i, (e, g) in enumerate(zip(expected, value)):
                    try:
                        self.assertEqualArrayAny(e, g, msg=msg, atol=atol, rtol=rtol)
                    except AssertionError as e:
                        excs.append(f"Error at position {i} due to {e}")
                if excs:
                    msg_ = "\n".join(excs)
                    msg = f"{msg}\n{msg_}" if msg else msg_
                    raise AssertionError(f"Found {len(excs)} discrepancies\n{msg}")
        elif expected.__class__.__name__ in ("DynamicCache", "StaticCache"):
            atts = {"key_cache", "value_cache"}
            self.assertEqualArrayAny(
                {k: expected.__dict__.get(k, None) for k in atts},
                {k: value.__dict__.get(k, None) for k in atts},
                atol=atol,
                rtol=rtol,
            )
        elif isinstance(expected, (int, float, str)):
            self.assertEqual(expected, value, msg=msg)
        elif hasattr(expected, "shape"):
            self.assertEqual(type(expected), type(value), msg=msg)
            self.assertEqualArray(expected, value, msg=msg, atol=atol, rtol=rtol)
        elif expected is None:
            assert value is None, f"Expected is None but value is of type {type(value)}"
        else:
            raise AssertionError(
                f"Comparison not implemented for types {type(expected)} and {type(value)}"
            )

    def assertAlmostEqual(
        self,
        expected: numpy.ndarray,
        value: numpy.ndarray,
        atol: float = 0,
        rtol: float = 0,
    ):
        """In the name"""
        if not isinstance(expected, numpy.ndarray):
            expected = numpy.array(expected)
        if not isinstance(value, numpy.ndarray):
            value = numpy.array(value).astype(expected.dtype)
        self.assertEqualArray(expected, value, atol=atol, rtol=rtol)

    def check_ort(self, onx: "onnx.ModelProto") -> bool:  # noqa: F821
        from onnxruntime import InferenceSession

        return InferenceSession(onx.SerializeToString(), providers=["CPUExecutionProvider"])

    def assertRaise(self, fct: Callable, exc_type: type[Exception], msg: Optional[str] = None):
        """In the name"""
        try:
            fct()
        except exc_type as e:
            if not isinstance(e, exc_type):
                raise AssertionError(f"Unexpected exception {type(e)!r}.")  # noqa: B904
            if msg is not None and msg not in str(e):
                raise AssertionError(f"Unexpected exception message {e!r}.")  # noqa: B904
            return
        raise AssertionError("No exception was raised.")  # noqa: B904

    def assertEmpty(self, value: Any):
        """In the name"""
        if value is None:
            return
        if not value:
            return
        raise AssertionError(f"value is not empty: {value!r}.")

    def assertNotEmpty(self, value: Any):
        """In the name"""
        if value is None:
            raise AssertionError(f"value is empty: {value!r}.")
        if isinstance(value, (list, dict, tuple, set)):
            if not value:
                raise AssertionError(f"value is empty: {value!r}.")

    def assertStartsWith(self, prefix: str, full: str):
        """In the name"""
        if not full.startswith(prefix):
            raise AssertionError(f"prefix={prefix!r} does not start string  {full!r}.")

    def assertEndsWith(self, suffix: str, full: str):
        """In the name"""
        if not full.endswith(suffix):
            raise AssertionError(f"suffix={suffix!r} does not end string  {full!r}.")

    def capture(self, fct: Callable):
        """
        Runs a function and capture standard output and error.

        :param fct: function to run
        :return: result of *fct*, output, error
        """
        sout = StringIO()
        serr = StringIO()
        with redirect_stdout(sout), redirect_stderr(serr):
            try:
                res = fct()
            except Exception as e:
                raise AssertionError(
                    f"function {fct} failed, stdout="
                    f"\n{sout.getvalue()}\n---\nstderr=\n{serr.getvalue()}"
                ) from e
        return res, sout.getvalue(), serr.getvalue()

    def tryCall(
        self, fct: Callable, msg: Optional[str] = None, none_if: Optional[str] = None
    ) -> Optional[Any]:
        """
        Calls the function, catch any error.

        :param fct: function to call
        :param msg: error message to display if failing
        :param none_if: returns None if this substring is found in the error message
        :return: output of *fct*
        """
        try:
            return fct()
        except Exception as e:
            if none_if is not None and none_if in str(e):
                return None
            if msg is None:
                raise
            raise AssertionError(msg) from e

    def assert_onnx_disc(
        self,
        test_name: str,
        proto: "onnx.ModelProto",  # noqa: F821
        model: "torch.nn.Module",  # noqa: F821
        inputs: Union[Tuple[Any], Dict[str, Any]],
        verbose: int = 0,
        atol: float = 1e-5,
        rtol: float = 1e-3,
        copy_inputs: bool = True,
        expected: Optional[Any] = None,
        use_ort: bool = False,
        **kwargs,
    ):
        """
        Checks for discrepancies.
        Runs the onnx models, computes expected outputs, in that order.
        The inputs may be modified by this functions if the torch model
        modifies them inplace.

        :param test_name: test name, dumps the model if not empty
        :param proto: onnx model
        :param model: torch model
        :param inputs: inputs
        :param verbose: verbosity
        :param atol: absolute tolerance
        :param rtol: relative tolerance
        :param expected: expected values
        :param copy_inputs: to copy the inputs
        :param use_ort: use :class:`onnxruntime.InferenceSession`
        :param kwargs: arguments sent to
            :class:`onnx_diagnostic.helpers.ort_session.InferenceSessionForTorch`
        """
        from .helpers import string_type, string_diff, max_diff
        from .helpers.rt_helper import make_feeds
        from .helpers.ort_session import InferenceSessionForTorch

        kws = dict(with_shape=True, with_min_max=verbose > 1)
        if verbose:
            vname = test_name or "assert_onnx_disc"
        if test_name:
            name = f"{test_name}.onnx"
            print(f"[{vname}] save the onnx model into {name!r}")
            name = self.dump_onnx(name, proto)
            print(f"[{vname}] file size {os.stat(name).st_size // 2**10:1.3f} kb")
        if verbose:
            print(f"[{vname}] make feeds {string_type(inputs, **kws)}")
        if use_ort:
            feeds = make_feeds(proto, inputs, use_numpy=True, copy=True)
            if verbose:
                print(f"[{vname}] feeds {string_type(feeds, **kws)}")
            import onnxruntime

            sess = onnxruntime.InferenceSession(
                proto.SerializeToString(), providers=["CPUExecutionProvider"]
            )
            got = sess.run(None, feeds)
        else:
            feeds = make_feeds(proto, inputs, copy=True)
            if verbose:
                print(f"[{vname}] feeds {string_type(feeds, **kws)}")
            sess = InferenceSessionForTorch(proto, **kwargs)
            got = sess.run(None, feeds)
        if verbose:
            print(f"[{vname}] compute expected values")
        if expected is None:
            if copy_inputs:
                expected = (
                    model(*copy.deepcopy(inputs))
                    if isinstance(inputs, tuple)
                    else model(**copy.deepcopy(inputs))
                )
            else:
                expected = model(*inputs) if isinstance(inputs, tuple) else model(**inputs)
        if verbose:
            print(f"[{vname}] expected {string_type(expected, **kws)}")
            print(f"[{vname}] obtained {string_type(got, **kws)}")
        diff = max_diff(expected, got, flatten=True)
        if verbose:
            print(f"[{vname}] diff {string_diff(diff)}")
        assert (
            isinstance(diff["abs"], float)
            and isinstance(diff["rel"], float)
            and not numpy.isnan(diff["abs"])
            and diff["abs"] <= atol
            and not numpy.isnan(diff["rel"])
            and diff["rel"] <= rtol
        ), f"discrepancies in {test_name!r}, diff={string_diff(diff)}"

    def _debug(self):
        "Tells if DEBUG=1 is set up."
        return os.environ.get("DEBUG") in BOOLEAN_VALUES

    def string_type(self, *args, **kwargs):
        from .helpers import string_type

        return string_type(*args, **kwargs)

    def subloop(self, *args, verbose: int = 0):
        "Loops over elements and calls :meth:`unittests.TestCase.subTest`."
        if len(args) == 1:
            for it in args[0]:
                with self.subTest(case=it):
                    if verbose:
                        print(f"[subloop] it={it!r}")
                    yield it
        else:
            for it in itertools.product(*args):
                with self.subTest(case=it):
                    if verbose:
                        print(f"[subloop] it={it!r}")
                    yield it
