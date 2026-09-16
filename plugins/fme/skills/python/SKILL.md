---
name: python
description: Write, fix and embed Python for FME, including PythonCaller and PythonCreator scripts, fmeobjects feature handling, published parameters read from Python, and code that must run on both older and newer FME builds.
---

# Python in FME

## Find the target first

Before writing any code, find out which FME and which Python will run it:

- `LAST_SAVE_BUILD` in the workspace header names the FME build.
- `FME_PYTHON_VERSION` in the mapping file names the interpreter: `37` is
  Python 3.7 (seen in FME 2020 files), `313` is Python 3.13 (FME 2025).
- `python3 "<fme:workspaces skill dir>/validate_fmw.py" --summary workspace.fmw`
  prints both.

Write for the oldest interpreter that must run the script. Python 3.7 has no
`match`, no walrus operator (`:=`, added in 3.8), no `str.removeprefix` (3.9),
and no `X | Y` type unions (3.10).

## The PythonCaller interface

FME creates the class the transformer is set to call and calls it like this.
The class name is stored as `PYTHONSYMBOL` in the Workbench section and passed
as `SYMBOL_NAME` in the mapping file.

- `__init__()`: once, even if no features arrive.
- `input(feature)`: once per feature, with an `fmeobjects.FMEFeature`.
- `process_group()`: after each group, when group processing is on.
- `close()`: once, after the last feature.

Emit features with `self.pyoutput(feature)`.

### Which base class

- `class FeatureProcessor(object):` is the safe default for mixed fleets. It
  is the template in the FME 2022 documentation, and a workspace saved by FME
  2025.0 still uses it.
- `class FeatureProcessor(fme.BaseTransformer):` is the template in current
  documentation. Use it only when every target build has it. Check on the
  user's FME with `import fme; print(hasattr(fme, "BaseTransformer"))`.
- Very old workspaces use a plain function (`PYTHONSYMBOL` set to
  `processFeature`, seen in an FME 2020.0 file). Keep that style when editing one of those, rather
  than converting it as a side effect.

```python
import fme
import fmeobjects


class FeatureProcessor(object):
    def __init__(self):
        self.count = 0

    def input(self, feature):
        self.count += 1
        feature.setAttribute("row_number", self.count)
        self.pyoutput(feature)

    def close(self):
        pass
```

### Bulk mode

Since FME 2023.1, bulk mode is on by default for PythonCaller, and the features
passed to `input()` come from a feature table. A script opts out by
implementing `has_support_for` and returning `False` for
`fmeobjects.FME_SUPPORT_FEATURE_TABLE_SHIM`:

```python
    def has_support_for(self, support_type):
        if support_type == fmeobjects.FME_SUPPORT_FEATURE_TABLE_SHIM:
            return False
        return True
```

Opting out gives up bulk mode's speed. Do it when the script's behaviour on a
real run differs from what it does with bulk mode off. Don't add it by reflex.
Older builds never call `has_support_for`, so including it is harmless there.

### Attributes and parameters

- Read and write attributes with `feature.getAttribute(name)` and
  `feature.setAttribute(name, value)`.
- Attributes the script creates are invisible to downstream transformers until
  they are listed in "Attributes to Expose" (the `NEW_ATTRIBUTES` parameter).
  List attributes go in `LIST_ATTRS`. When a new attribute "does not exist"
  downstream, check these first.
- Read published parameters with `fme.macroValues["ParameterName"]`. The value
  is always a string, so convert it explicitly.

## Embedding a script in a workspace

A PythonCaller's script is stored twice, and both copies must match:

1. The Workbench section:
   `<XFORM_PARM PARM_NAME="PYTHONSOURCE" PARM_VALUE="...">`, holding the
   FME-encoded script, XML-escaped.
2. The mapping file: the `SOURCE_CODE` argument of the `PythonFactory` line
   whose `FACTORY_NAME` is the transformer. FME 2025 writes
   `SOURCE_CODE { ... }` in braces; FME 2020 writes the value bare.

Steps:

1. Write the script to a file and syntax-check it with the target interpreter
   if one is available.
2. Encode it: `python3 "<fme:workspaces skill dir>/validate_fmw.py" --encode < script.py`.
3. Replace `SOURCE_CODE` in the mapping file with that output.
4. XML-escape the same output (`&` to `&amp;`, `<` to `&lt;`, `>` to `&gt;`,
   `"` to `&quot;`) and replace `PYTHONSOURCE` in the Workbench section.
5. If the class or function name changed, update `PYTHONSYMBOL` in the
   Workbench section and `SYMBOL_NAME` in the mapping file.
6. Validate. It reports a script that does not compile, a class name the script
   does not define, and a mismatch between the two copies.

The validator compiles with whatever Python runs it, which may be newer than
FME's. So a clean result does not prove Python 3.7 accepts the script. Keep to
the syntax limits above.

## Workspace startup and shutdown scripts

The `<WORKSPACE>` attributes `BEGIN_PYTHON` and `END_PYTHON` hold scripts that
run before and after the translation. Give the user the script and ask them to
paste it in Workbench's workspace parameters, then save. Hand-editing these
attributes has not been checked against the mapping file.

## Proving it works

Only a run in FME proves the script works. Give the user a small input and the
`fme` command from the `fme:workspaces` skill. Ask for the log: Python
exceptions appear there with the traceback.
