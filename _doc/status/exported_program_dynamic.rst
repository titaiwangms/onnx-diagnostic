=====================================
Exported Programs with Dynamic Shapes
=====================================

The following script shows the exported program for many short cases exported
with different options. This steps happens before converting into ONNX.

.. runpython::
    :showcode:
    :rst:
    :toggle: code
    :warningout: UserWarning

    import inspect
    import textwrap
    import pandas
    from onnx_diagnostic.helpers import string_type
    from onnx_diagnostic.torch_export_patches.eval import discover, run_exporter
    from onnx_diagnostic.ext_test_case import unit_test_going

    cases = discover()
    print()
    print(":ref:`Summary <led-summary-exported-program>`")
    print()
    sorted_cases = sorted(cases.items())
    if unit_test_going():
        sorted_cases = sorted_cases[:3]
    for name, cls_model in sorted_cases:
        print(f"* :ref:`{name} <led-model-case-export-{name}>`")
    print()
    print()

    obs = []
    for name, cls_model in sorted(cases.items()):
        print()
        print(f".. _led-model-case-export-{name}:")
        print()
        print(name)
        print("=" * len(name))
        print()
        print("forward")
        print("+++++++")
        print()
        print(".. code-block:: python")
        print()
        src = inspect.getsource(cls_model.forward)
        if src:
            print(textwrap.indent(textwrap.dedent(src), "    "))
        else:
            print("    # code is missing")
        print()
        print()
        for exporter in (
            "export-strict",
            "export-nostrict",
            "export-nostrict-decall",
            "export-tracing",
        ):
            expname = exporter.replace("export-", "")
            print()
            print(expname)
            print("+" * len(expname))
            print()
            res = run_exporter(exporter, cls_model, True, quiet=True)
            case_ref = f":ref:`{name} <led-model-case-export-{name}>`"
            expo = exporter.split("-", maxsplit=1)[-1]
            if "inputs" in res:
                print(f"* **inputs:** ``{string_type(res['inputs'], with_shape=True)}``")
            if "dynamic_shapes" in res:
                print(f"* **shapes:** ``{string_type(res['dynamic_shapes'])}``")
            print()
            print()
            if "exported" in res:
                print(".. code-block:: text")
                print()
                print(textwrap.indent(str(res["exported"].graph), "    "))
                print()
                print()
                obs.append(dict(case=case_ref, error="", exporter=expo))
            else:
                print("**FAILED**")
                print()
                print(".. code-block:: text")
                print()
                err = str(res["error"])
                if err:
                    print(textwrap.indent(err, "    "))
                else:
                    print("    # no error found for the failure")
                print()
                print()
                obs.append(dict(case=case_ref, error="FAIL", exporter=expo))

    print()
    print(".. _led-summary-exported-program:")
    print()
    print("Summary")
    print("+++++++")
    print()
    df = pandas.DataFrame(obs)
    piv = df.pivot(index="case", columns="exporter", values="error")
    print(piv.to_markdown(tablefmt="rst"))
    print()
