import inspect
import os
import pprint
from typing import Any, Dict, Optional, Tuple
import torch
import transformers
from ...helpers.config_helper import update_config
from ...tasks import reduce_model_config, random_input_kwargs
from .hub_api import task_from_arch, task_from_id, get_pretrained_config, download_code_modelid


def _code_needing_rewriting(model: Any) -> Any:
    from onnx_diagnostic.torch_export_patches.patch_module_helper import code_needing_rewriting

    return code_needing_rewriting(model)


def get_untrained_model_with_inputs(
    model_id: str,
    config: Optional[Any] = None,
    task: Optional[str] = "",
    inputs_kwargs: Optional[Dict[str, Any]] = None,
    model_kwargs: Optional[Dict[str, Any]] = None,
    verbose: int = 0,
    dynamic_rope: Optional[bool] = None,
    use_pretrained: bool = False,
    same_as_pretrained: bool = False,
    use_preinstalled: bool = True,
    add_second_input: int = 1,
    subfolder: Optional[str] = None,
    use_only_preinstalled: bool = False,
) -> Dict[str, Any]:
    """
    Gets a non initialized model similar to the original model
    based on the model id given to the function.
    The model size is reduced compare to the original model.
    No weight is downloaded, only the configuration file sometimes.

    :param model_id: model id, ex: :epkg:`arnir0/Tiny-LLM`
    :param config: to overwrite the configuration
    :param task: model task, can be overwritten, otherwise, it is automatically determined
    :param input_kwargs: parameters sent to input generation
    :param model_kwargs: to change the model generation
    :param verbose: display found information
    :param dynamic_rope: use dynamic rope (see :class:`transformers.LlamaConfig`)
    :param same_as_pretrained: if True, do not change the default values
        to get a smaller model
    :param use_pretrained: download the pretrained weights as well
    :param use_preinstalled: use preinstalled configurations
    :param add_second_input: provides a second inputs to check a model
        supports different shapes
    :param subfolder: subfolder to use for this model id
    :param use_only_preinstalled: use only preinstalled version
    :return: dictionary with a model, inputs, dynamic shapes, and the configuration,
        some necessary rewriting as well

    Example:

    .. runpython::
        :showcode:

        import pprint
        from onnx_diagnostic.helpers import string_type
        from onnx_diagnostic.torch_models.hghub import get_untrained_model_with_inputs

        data = get_untrained_model_with_inputs("arnir0/Tiny-LLM", verbose=1)

        print("-- model size:", data['size'])
        print("-- number of parameters:", data['n_weights'])
        print("-- inputs:", string_type(data['inputs'], with_shape=True))
        print("-- dynamic shapes:", pprint.pformat(data['dynamic_shapes']))
        print("-- configuration:", pprint.pformat(data['configuration']))
    """
    assert not use_preinstalled or not use_only_preinstalled, (
        f"model_id={model_id!r}, pretinstalled model is only available "
        f"if use_only_preinstalled is False."
    )
    if verbose:
        print(f"[get_untrained_model_with_inputs] model_id={model_id!r}")
        if use_preinstalled:
            print(f"[get_untrained_model_with_inputs] use preinstalled {model_id!r}")
    if config is None:
        config = get_pretrained_config(
            model_id,
            use_preinstalled=use_preinstalled,
            use_only_preinstalled=use_only_preinstalled,
            subfolder=subfolder,
            **(model_kwargs or {}),
        )

    if hasattr(config, "architecture") and config.architecture:
        archs = [config.architecture]
    if type(config) is dict:
        assert "_class_name" in config, f"Unable to get the architecture from config={config}"
        archs = [config["_class_name"]]
    else:
        archs = config.architectures  # type: ignore
    task = None
    if archs is None:
        task = task_from_id(model_id)
    assert task is not None or (archs is not None and len(archs) == 1), (
        f"Unable to determine the architecture for model {model_id!r}, "
        f"architectures={archs!r}, conf={config}"
    )
    if verbose:
        print(f"[get_untrained_model_with_inputs] architectures={archs!r}")
        print(f"[get_untrained_model_with_inputs] cls={config.__class__.__name__!r}")
    if task is None:
        task = task_from_arch(archs[0], model_id=model_id, subfolder=subfolder)
    if verbose:
        print(f"[get_untrained_model_with_inputs] task={task!r}")

    # model kwagrs
    if dynamic_rope is not None:
        assert (
            type(config) is not dict
        ), f"Unable to set dynamic_rope if the configuration is a dictionary\n{config}"
        assert hasattr(config, "rope_scaling"), f"Missing 'rope_scaling' in\n{config}"
        config.rope_scaling = (
            {"rope_type": "dynamic", "factor": 10.0} if dynamic_rope else None
        )

    # updating the configuration
    mkwargs = reduce_model_config(config, task) if not same_as_pretrained else {}
    if model_kwargs:
        for k, v in model_kwargs.items():
            if isinstance(v, dict):
                if k in mkwargs:
                    mkwargs[k].update(v)
                else:
                    mkwargs[k] = v
            else:
                mkwargs[k] = v
    if mkwargs:
        update_config(config, mkwargs)

    # SDPA
    if model_kwargs and "attn_implementation" in model_kwargs:
        if hasattr(config, "_attn_implementation_autoset"):
            config._attn_implementation_autoset = False
        config._attn_implementation = model_kwargs["attn_implementation"]  # type: ignore[union-attr]
        if verbose:
            print(
                f"[get_untrained_model_with_inputs] config._attn_implementation="
                f"{config._attn_implementation!r}"  # type: ignore[union-attr]
            )
    elif verbose:
        print(
            f"[get_untrained_model_with_inputs] default config._attn_implementation="
            f"{getattr(config, '_attn_implementation', '?')!r}"  # type: ignore[union-attr]
        )

    if type(config) is dict and "_diffusers_version" in config:
        import diffusers

        package_source = diffusers
    else:
        package_source = transformers

    if use_pretrained:
        model = transformers.AutoModel.from_pretrained(model_id, **mkwargs)
    else:
        if archs is not None:
            try:
                cls_model = getattr(package_source, archs[0])
            except AttributeError as e:
                # The code of the models is not in transformers but in the
                # repository of the model. We need to download it.
                pyfiles = download_code_modelid(model_id, verbose=verbose)
                if pyfiles:
                    if "." in archs[0]:
                        cls_name = archs[0]
                    else:
                        modeling = [_ for _ in pyfiles if "/modeling_" in _]
                        assert len(modeling) == 1, (
                            f"Unable to guess the main file implemented class {archs[0]!r} "
                            f"from {pyfiles}, found={modeling}."
                        )
                        last_name = os.path.splitext(os.path.split(modeling[0])[-1])[0]
                        cls_name = f"{last_name}.{archs[0]}"
                    if verbose:
                        print(
                            f"[get_untrained_model_with_inputs] custom code for {cls_name!r}"
                        )
                        print(
                            f"[get_untrained_model_with_inputs] from folder "
                            f"{os.path.split(pyfiles[0])[0]!r}"
                        )
                    cls_model = (
                        transformers.dynamic_module_utils.get_class_from_dynamic_module(
                            cls_name,
                            pretrained_model_name_or_path=os.path.split(pyfiles[0])[0],
                        )
                    )
                else:
                    raise AttributeError(
                        f"Unable to find class 'tranformers.{archs[0]}'. "
                        f"The code needs to be downloaded, config="
                        f"\n{pprint.pformat(config)}."
                    ) from e
        else:
            assert same_as_pretrained and use_pretrained, (
                f"Model {model_id!r} cannot be built, the model cannot be built. "
                f"It must be downloaded. Use same_as_pretrained=True "
                f"and use_pretrained=True."
            )

        try:
            if type(config) is dict:
                model = cls_model(**config)
            else:
                model = cls_model(config)
        except RuntimeError as e:
            raise RuntimeError(
                f"Unable to instantiate class {cls_model.__name__} with\n{config}"
            ) from e

    # input kwargs
    kwargs, fct = random_input_kwargs(config, task)
    if verbose:
        print(f"[get_untrained_model_with_inputs] use fct={fct}")
        if os.environ.get("PRINT_CONFIG") in (1, "1"):
            print(f"-- input kwargs for task {task!r}")
            pprint.pprint(kwargs)
    if inputs_kwargs:
        kwargs.update(inputs_kwargs)

    # This line is important. Some models may produce different
    # outputs even with the same inputs in training mode.
    model.eval()
    res = fct(model, config, add_second_input=add_second_input, **kwargs)

    res["input_kwargs"] = kwargs
    res["model_kwargs"] = mkwargs

    sizes = compute_model_size(model)
    res["model"] = model
    res["configuration"] = config
    res["size"] = sizes[0]
    res["n_weights"] = sizes[1]
    res["task"] = task

    update = {}
    for k, v in res.items():
        if k.startswith(("inputs", "dynamic_shapes")) and isinstance(v, dict):
            update[k] = filter_out_unexpected_inputs(model, v, verbose=verbose)
    res.update(update)

    rewrite = _code_needing_rewriting(model.__class__.__name__)
    if rewrite:
        res["rewrite"] = rewrite
    return res


def filter_out_unexpected_inputs(
    model: torch.nn.Module, kwargs: Dict[str, Any], verbose: int = 0
):
    """
    Removes input names in kwargs if no parameter names was found in ``model.forward``.
    """
    sig = inspect.signature(model.forward)
    allowed = set(sig.parameters)
    new_kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    diff = set(kwargs) - set(new_kwargs)
    if diff and verbose:
        print(f"[filter_out_unexpected_inputs] removed {diff}")
    return new_kwargs


def compute_model_size(model: torch.nn.Module) -> Tuple[int, int]:
    """Returns the size of the models (weights only) and the number of the parameters."""
    param_size = 0
    nparams = 0
    for param in model.parameters():
        param_size += param.nelement() * param.element_size()
        nparams += param.nelement()
    return param_size, nparams
