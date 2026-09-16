---
name: workspaces
description: Read, explain, edit, author and validate FME workspace files (.fmw) from FME 2015 to 2026. Use for any task that opens, changes or creates an .fmw, or asks why a workspace will not open or run.
---

# FME workspaces

An `.fmw` is plain text, so it can be read, diffed and edited. But it holds the
same translation twice, and FME trusts each copy for a different job. Most
broken hand edits change one copy and not the other.

## The validator

`validate_fmw.py` sits in this skill's directory (the `skill` tool prints the
path). It needs Python 3.8 or newer and no FME. Run it with the `shell` tool:

```
python3 "<skill dir>/validate_fmw.py" workspace.fmw              # check
python3 "<skill dir>/validate_fmw.py" --summary workspace.fmw    # parameters, readers, writers, transformers, connections
python3 "<skill dir>/validate_fmw.py" --encode < script.py       # text to FME encoding
python3 "<skill dir>/validate_fmw.py" --decode 'a<space>b'       # FME encoding to text
```

On Windows use `py` in place of `python3`. Exit status 0 means no errors, 1
means errors, 2 means the file could not be read.

It checks that the Workbench XML is well formed, identifiers are unique,
every connection joins real nodes through real ports, every reachable
transformer has a factory in the mapping file, embedded Python compiles and
matches in both sections, published parameter forms decode, and every
`$(MACRO)` is defined. A clean result means the file is consistent. It does
not mean FME will run it: see [Verify with FME](#verify-with-fme).

## Anatomy

### 1. Workbench section

The `#!` lines from `#! <?xml ...?>` to `#! </WORKSPACE>`, read as XML with the
`#!` stripped. Workbench draws the canvas from this.

- `<WORKSPACE ...>` attributes: `LAST_SAVE_BUILD` says which FME saved the
  file, e.g. `FME(R) 2020.2.1.0 (20201130 - Build 20806 - WIN64)`. Also
  `FME_BUILD_NUM`, `FME_DOCUMENT_GUID`, and `A0_PREVIEW_IMAGE` (a base64
  thumbnail). Plain `#` lines inside the start tag record the command line.
- `<DATASET>`: a reader or writer. `IS_SOURCE`, `FORMAT`, `KEYWORD`, and
  `DATASET`, usually a parameter reference such as `$(SourceDataset_SHAPE)`.
- `<FEATURE_TYPE>`: a reader or writer node on the canvas. `IDENTIFIER`,
  `NODE_NAME`, `IS_SOURCE`, `KEYWORD`.
- `<TRANSFORMER>`: `IDENTIFIER`, `TYPE` (e.g. `AttributeCreator`), `VERSION`,
  `ENABLED`, `POSITION`. Children: `<OUTPUT_FEAT NAME>` for each output port,
  `<XFORM_ATTR>` for attributes it exposes, and `<XFORM_PARM PARM_NAME
  PARM_VALUE>` for its settings. The `XFORMER_NAME` parameter is the name shown
  on the canvas.
- `<FEAT_LINK>`: a connection. `SOURCE_NODE` and `TARGET_NODE` are identifiers.
  `SOURCE_PORT_DESC` is `fo <index> <port name>` and `TARGET_PORT_DESC` is
  `fi <index> <port name>`. A reader or writer end is written `-1`, and older
  builds write only the index (`fo 0`).
- Published parameters come in two forms, and one file can carry both.
  `<GLOBAL_PARAMETERS>` with a `GUI_LINE` per parameter appears in 2015, 2020
  and 2025 files. `<USER_PARAMETERS FORM="...">`, where the FORM is base64
  JSON, plus `<PARAMETER_INFO>`, appears in 2025 and 2026 files.
- `<SUBDOCUMENTS>`: embedded custom transformers, each with its own identifiers.

### 2. Mapping file

Every other line that is not a `#` comment. This is what `fme workspace.fmw`
executes.

- Settings: `FME_PYTHON_VERSION 37` (Python 3.7; 2020 files) or `313` (2025),
  `READER_TYPE MULTI_READER`, `LOG_FILENAME "$(FME_MF_DIR)name.log"`.
- Parameters: `DEFAULT_MACRO Name value`, `GUI <TYPE> Name <prompt>`, and
  `INCLUDE [ ...Tcl... ]` blocks that validate or derive values.
- One or more `FACTORY_DEF` lines per transformer. Their `FACTORY_NAME` is the
  transformer's name, and they are wired by feature type names:
  `OUTPUT { FEATURE_TYPE Creator_CREATED }` in one factory feeds
  `INPUT FEATURE_TYPE Creator_CREATED` in the next.
- `#! START_HEADER`, `#! START_WB_HEADER` and similar markers. These are not XML.
- A transformer that no feature can reach has no factory at all.

### Encoded values

Parameter values, `SOURCE_CODE` blocks and published parameter defaults use
FME's encoding: `<space>`, `<lf>`, `<openparen>`, `<closeparen>`, `<apos>`,
`<quote>`, `<comma>`, `<at>`, `<opencurly>`, `<closecurly>`, `<openbracket>`,
`<closebracket>`, `<solidus>`, `<lt>`, `<gt>`. Inside a `#!` attribute the
result is XML-escaped again, so `<space>` is written `&lt;space&gt;`. Port
names in connections are encoded one level deeper still. Do not encode by hand:
use `--encode` and `--decode`.

## Explaining a workspace

Run `--summary`, then read the transformer blocks it names. Describe the flow in
the order features travel, from reader through each transformer to writer, and
decode parameter values before quoting them. Call out disabled transformers,
unconnected ones, and anything the validator warns about.

## Editing a workspace

1. Validate and summarize first. Note `LAST_SAVE_BUILD`. If the file already has
   errors or warnings, tell the user before changing anything, so they are not
   mistaken for yours.
2. Make each change in both sections:

   | Change | Workbench section | Mapping file |
   | --- | --- | --- |
   | A transformer setting | its `XFORM_PARM` | the matching argument in the `FACTORY_DEF` lines whose `FACTORY_NAME` is that transformer |
   | A published parameter default | `GLOBAL_PARAMETER DEFAULT_VALUE`, and the `PARAMETER_INFO` entry and `FORM` JSON where present | the `DEFAULT_MACRO` line |
   | An embedded Python script | `PYTHONSOURCE` | `SOURCE_CODE` (use the `fme:python` skill) |

3. Leave alone anything the change does not need: identifiers, `VERSION`,
   positions, GUIDs, the preview image, line endings and file encoding.
4. Validate again, and compare `--summary` before and after so the only
   differences are the ones you meant.

Renaming a transformer, adding or removing one, rewiring connections, or
changing a reader or writer format means rewriting generated factory lines
whose exact shape depends on the FME build. Do that in Workbench. You can give
the user precise steps, or copy a block from a workspace saved by the same
build (see below). Don't write new `FACTORY_DEF` lines from memory.

## Authoring a workspace

Transformer versions and parameter names are defined by the FME build that
saves the file, and they change between releases. So:

1. Ask for, or look in the project for, a workspace saved by the user's target
   FME version. Ideally it already uses the same reader, writer and
   transformers.
2. With a template, assemble the new workspace by copying whole transformer
   blocks together with their `FACTORY_DEF` lines. Give each copy a new
   `IDENTIFIER` (one more than the highest in that document) and a unique
   `XFORMER_NAME`. Rename its feature types consistently in the mapping file,
   add `FEAT_LINK` entries that match the factory wiring, then validate.
3. Without a template, don't produce a plausible-looking `.fmw`. Deliver a build
   sheet the user can follow in Workbench: readers and writers with formats,
   transformers in order with their settings, connections port by port, and
   published parameters. Offer to turn it into a file once they save a starter
   workspace from their FME.

When several FME versions must run the workspace, build and save it in the
oldest one. A workspace saved by a newer FME may not open in an older one, so
never copy blocks from a newer build's file into an older build's file.

## Verify with FME

The validator runs anywhere. Behaviour can only be proven on a machine with FME
Form installed. Give the user the command:

```
fme workspace.fmw --SourceDataset_SHAPE "C:\data\in.shp" --DestDataset "C:\out" LOG_FILENAME "C:\out\run.log"
```

- Published parameters are passed as `--Name value`.
- `LOG_FILENAME` is a mapping-file directive, so it takes no dashes. It is also
  the reliable way to set the log path: passing `--LOG_FILE` failed in FME 2024.
- On Windows the engine is usually `"C:\Program Files\FME\fme.exe"`.

Then ask for the log. Look for `ERROR` lines and the closing translation
summary. For a structural edit, also ask them to open the workspace in Workbench
for the target version, save it, and send it back. Validate that saved copy:
it is the file FME itself produced.

## Reporting

Say which checks actually ran: the static validator, an `fme` run, and a
Workbench open and save. Never describe a workspace as working on the strength
of the validator alone.
