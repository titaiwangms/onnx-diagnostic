import subprocess
from argparse import ArgumentParser, Namespace
from typing import Dict, List, Optional, Tuple, Union


def check_cuda_availability():
    """
    Checks if CUDA is available without pytorch or onnxruntime.
    Calls `nvidia-smi`.
    """
    try:
        import torch

        return torch.cuda.device_count() > 0
    except ImportError:
        pass
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_parsed_args(
    name: str,
    scenarios: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    epilog: Optional[str] = None,
    number: int = 10,
    repeat: int = 10,
    warmup: int = 5,
    sleep: float = 0.1,
    tries: int = 2,
    expose: Optional[str] = None,
    new_args: Optional[List[str]] = None,
    **kwargs: Dict[str, Tuple[Union[int, str, float], str]],
) -> Namespace:
    """
    Returns parsed arguments for examples in this package.

    :param name: script name
    :param scenarios: list of available scenarios
    :param description: parser description
    :param epilog: text at the end of the parser
    :param number: default value for number parameter
    :param repeat: default value for repeat parameter
    :param warmup: default value for warmup parameter
    :param sleep: default value for sleep parameter
    :param expose: if empty, keeps all the parameters,
        if not None, only publish kwargs contains, otherwise the list
        of parameters to publish separated by a comma
    :param new_args: args to consider or None to take `sys.args`
    :param kwargs: additional parameters,
        example: `n_trees=(10, "number of trees to train")`
    :return: parser
    """
    if description is None:
        description = f"Available options for {name}.py."
    if epilog is None:
        epilog = ""
    parser = ArgumentParser(prog=name, description=description, epilog=epilog)
    if expose is not None:
        to_publish = set(expose.split(",")) if expose else set()
        if scenarios is not None:
            rows = ", ".join(f"{k}: {v}" for k, v in scenarios.items())
            parser.add_argument("-s", "--scenario", help=f"Available scenarios: {rows}.")
        if not to_publish or "number" in to_publish:
            parser.add_argument(
                "-n",
                "--number",
                help=f"number of executions to measure, default is {number}",
                type=int,
                default=number,
            )
        if not to_publish or "repeat" in to_publish:
            parser.add_argument(
                "-r",
                "--repeat",
                help=f"number of times to repeat the measure, default is {repeat}",
                type=int,
                default=repeat,
            )
        if not to_publish or "warmup" in to_publish:
            parser.add_argument(
                "-w",
                "--warmup",
                help=f"number of times to repeat the measure, default is {warmup}",
                type=int,
                default=warmup,
            )
        if not to_publish or "sleep" in to_publish:
            parser.add_argument(
                "-S",
                "--sleep",
                help=f"sleeping time between two configurations, default is {sleep}",
                type=float,
                default=sleep,
            )
        if not to_publish or "tries" in to_publish:
            parser.add_argument(
                "-t",
                "--tries",
                help=f"number of tries for each configurations, default is {tries}",
                type=int,
                default=tries,
            )
    for k, v in kwargs.items():
        parser.add_argument(
            f"--{k}",
            help=f"{v[1]}, default is {v[0]}",
            type=type(v[0]),
            default=v[0],
        )

    res = parser.parse_args(args=new_args)
    update: Dict[str, Union[int, float]] = {}
    for k, v in res.__dict__.items():
        try:
            vi = int(v)
            update[k] = vi
            continue
        except (ValueError, TypeError):
            pass
        try:
            vf = float(v)
            update[k] = vf
            continue
        except (ValueError, TypeError):
            pass
    if update:
        res.__dict__.update(update)
    return res
