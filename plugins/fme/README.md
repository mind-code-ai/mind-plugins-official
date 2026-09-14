# fme

Makes the agent competent with [FME](https://fme.safe.com) by Safe Software. It
can read, explain, edit and author workspace files (`.fmw`), check them without
FME installed, run jobs on FME Flow, and write PythonCaller scripts that work
across FME versions.

## Install

```
/plugin marketplace add mind-code-ai/mind-plugins-official
/plugin install fme@mind-plugins-official
```

## Skills

The agent picks these up by itself when a request matches. You can also invoke
them directly:

| Skill | Use it for |
| --- | --- |
| `/fme:workspaces` | Reading, explaining, editing, authoring and validating `.fmw` files from FME 2015 to 2026 |
| `/fme:flow` | Running, monitoring and cancelling FME Flow jobs through REST API V3 or V4, or the `fmeflow` CLI |
| `/fme:python` | PythonCaller and PythonCreator scripts, fmeobjects, and embedding scripts in a workspace |

## Workspace validator

`skills/workspaces/validate_fmw.py` needs Python 3.8+ and nothing else, so it
runs on machines without FME.

```
python3 skills/workspaces/validate_fmw.py workspace.fmw
python3 skills/workspaces/validate_fmw.py --summary workspace.fmw
python3 skills/workspaces/validate_fmw.py --encode < script.py
python3 skills/workspaces/validate_fmw.py --decode 'import<space>fme<lf>'
```

A workspace stores its translation twice: as XML that Workbench reads, and as
the mapping file that the `fme` engine runs. The validator checks the XML, the
connections, embedded Python and published parameters. It also checks that the
two copies agree, because a hand edit that updates only one gives a workspace
that looks right in Workbench and runs differently.

It was built against real public workspaces saved by FME 2015.1, 2020.0,
2020.2, 2025.0 and 2026.2, and all of them validate clean. It also catches
breakage introduced into those files: dangling connections, duplicate
identifiers, malformed XML, Python syntax errors, a wrong class name,
misspelled parameter references, and transformers missing from the mapping
file.

What it cannot do is prove a workspace runs. Parameter values and transformer
behaviour are only checked by FME itself, so the skills always end by giving
you an `fme` command, or a Workbench open-and-save, to confirm.

## Tests

```
cd plugins/fme
python3 -m unittest discover -s tests
```
