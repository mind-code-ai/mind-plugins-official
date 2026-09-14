#!/usr/bin/env python3
"""Static checks for FME workspace (.fmw) files. No FME installation needed.

A workspace file carries two copies of the same translation:

  * the Workbench section: XML on lines that start with "#!"
  * the mapping file: plain directives (MACRO, DEFAULT_MACRO, GUI,
    FACTORY_DEF, ...) that the fme engine executes

Workbench shows the first; `fme workspace.fmw` runs the second. An edit that
changes one and not the other gives a workspace that looks right in Workbench
and behaves differently from the command line, or the reverse. This script
catches broken XML, dangling connections, transformers missing from the
mapping file, Python that does not compile, and drift between the two copies.

Passing is necessary, not sufficient: only FME proves a workspace runs.

Usage:
  validate_fmw.py WORKSPACE.fmw [WORKSPACE.fmw ...]
  validate_fmw.py --summary WORKSPACE.fmw
  validate_fmw.py --decode 'import<space>fme<lf>'
  validate_fmw.py --encode < script.py

Exit status: 0 no errors (warnings allowed), 1 errors found, 2 a file could
not be read or the arguments were wrong.

Python 3.8+ and the standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

# How FME writes special characters inside encoded parameter values and
# SOURCE_CODE blocks, as observed in workspaces saved by FME 2015 through
# 2026. Characters not listed are written as themselves.
ENCODED_CHARS = {
    " ": "<space>",
    "\n": "<lf>",
    "(": "<openparen>",
    ")": "<closeparen>",
    "'": "<apos>",
    '"': "<quote>",
    ",": "<comma>",
    "@": "<at>",
    "{": "<opencurly>",
    "}": "<closecurly>",
    "[": "<openbracket>",
    "]": "<closebracket>",
    "/": "<solidus>",
    "<": "<lt>",
    ">": "<gt>",
}
DECODED_TOKENS = {token[1:-1]: char for char, token in ENCODED_CHARS.items()}
TOKEN_RE = re.compile(r"<([a-z]+)>")
MACRO_REF_RE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")
MACRO_DEF_RE = re.compile(r"(?<![A-Za-z0-9_])(?:DEFAULT_)?MACRO\s+([A-Za-z_][A-Za-z0-9_]*)")
PORT_RE = re.compile(r"^(fo|fi) (-?\d+) ?(.*)$")

PYTHON_TRANSFORMERS = {"PythonCaller", "PythonCreator"}
LINK_TAGS = {"FEAT_LINK", "ATTR_LINK"}

# Macros FME defines itself. Names starting FME_ are also treated as built in,
# because the engine and FME Flow add more of them in every release.
BUILTIN_MACROS = {"WORKSPACE_NAME", "WB_CURRENT_CONTEXT"}


def encode(text: str) -> str:
    """Encode text the way FME stores it in PARM_VALUE and SOURCE_CODE."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ENCODED_CHARS.get(ch, ch) for ch in text)


def decode(text: str) -> str:
    """Decode an FME-encoded value. Unknown tokens are left as they are."""
    return TOKEN_RE.sub(lambda m: DECODED_TOKENS.get(m.group(1), m.group(0)), text)


def decode_fully(text: str) -> str:
    """Decode until nothing changes.

    Port names in connections are stored one encoding level deeper than the
    transformer's own output names, so comparisons need both fully decoded.
    """
    for _ in range(5):
        decoded = decode(text)
        if decoded == text:
            break
        text = decoded
    return text


class Report:
    def __init__(self, path: str):
        self.path = path
        self.errors = []
        self.warnings = []
        self.build = None
        self.unreadable = False

    def error(self, line, message):
        self.errors.append((line, message))

    def warn(self, line, message):
        self.warnings.append((line, message))


class Document:
    """The parsed Workbench section, with the file line each element starts on."""

    def __init__(self, root, lines):
        self.root = root
        self._lines = lines

    def line(self, element):
        return self._lines.get(id(element))


def read_text(path: str, report: Report):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        report.unreadable = True
        report.error(None, "cannot read file: %s" % exc.strerror)
        return None
    if raw.startswith(b"PK"):
        report.unreadable = True
        report.error(
            None,
            "this is a zip archive, not a workspace. FME templates (.fmwt) are "
            "packaged this way; extract the .fmw inside and check that",
        )
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        report.warn(
            None,
            "file is not valid UTF-8 (first bad byte at offset %d), read as "
            "Windows-1252 instead. Workspaces saved before FME 2021 can be in the "
            "system code page, and re-saving them in a newer FME can change how "
            "non-ASCII names are read" % exc.start,
        )
        return raw.decode("cp1252", errors="replace")


def split_sections(text: str):
    """Return (header, mapping) as lists of (file line number, text).

    The Workbench document is the "#!" lines from the first one that opens an
    XML tag up to and including "#! </WORKSPACE>". The mapping file reuses the
    "#!" prefix for its own markers (START_HEADER, START_WB_HEADER, ...),
    which are not XML.
    """
    header, mapping = [], []
    state = "before"  # before the XML, inside it, or past </WORKSPACE>
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("#!"):
            content = line[2:]
            if state == "before" and content.lstrip().startswith("<"):
                state = "inside"
            if state == "inside":
                header.append((number, content))
                if content.strip() == "</WORKSPACE>":
                    state = "after"
        elif line.strip() and not line.lstrip().startswith("#"):
            mapping.append((number, line))
    return header, mapping


def parse_header(header):
    """Parse the "#!" lines as XML. Returns (Document, None) or (None, (line, message))."""
    text = "\n".join(t for _, t in header)
    body = text.lstrip()
    skipped = text[: len(text) - len(body)].count("\n")
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()
    lines = {}

    def file_line(xml_line):
        index = xml_line - 1 + skipped
        return header[index][0] if 0 <= index < len(header) else None

    def start(tag, attrs):
        element = builder.start(tag, attrs)
        lines[id(element)] = file_line(parser.CurrentLineNumber)

    parser.StartElementHandler = start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(body, True)
        root = builder.close()
    except expat.ExpatError as exc:
        return None, (
            file_line(exc.lineno),
            "Workbench section is not well-formed XML: %s" % expat.ErrorString(exc.code),
        )
    return Document(root, lines), None


def scopes(root):
    """The main document's elements, then each embedded custom transformer's, separately.

    Identifiers are only unique within one document, so connections are
    resolved per scope.
    """
    main, subdocuments = [], []

    def walk(parent, bucket):
        for child in parent:
            if child.tag == "SUBDOCUMENT":
                inner = []
                name = child.get("DOC_NAME") or child.get("NAME")
                subdocuments.append(("custom transformer %s" % name if name else "custom transformer", inner))
                walk(child, inner)
            else:
                bucket.append(child)
                walk(child, bucket)

    walk(root, main)
    return [("workspace", main)] + subdocuments


def parm(element, name):
    for p in element.findall("XFORM_PARM"):
        if p.get("PARM_NAME") == name:
            return p.get("PARM_VALUE")
    return None


def node_label(element):
    if element.tag == "TRANSFORMER":
        name = parm(element, "XFORMER_NAME") or "#" + element.get("IDENTIFIER", "?")
        return "%s %r" % (element.get("TYPE", "transformer"), name)
    if element.tag == "FEATURE_TYPE":
        role = "reader" if element.get("IS_SOURCE") == "true" else "writer"
        return "%s feature type %r" % (role, element.get("NODE_NAME") or element.get("IDENTIFIER"))
    return "<%s> #%s" % (element.tag, element.get("IDENTIFIER"))


def has_factory(text: str, name: str) -> bool:
    """True when the mapping file defines a factory named for this transformer.

    Workbench writes FACTORY_NAME { Name }, FACTORY_NAME Name, or
    FACTORY_NAME "Name ..." and sometimes a suffix (Creator_XML_Creator). A
    numbered suffix is a different transformer: PythonCaller_2 is not
    PythonCaller.
    """
    for candidate in {name, encode(name)}:
        pattern = r'FACTORY_NAME\s+[{"]?\s*%s(?![A-Za-z0-9])(?!_\d+(?![A-Za-z]))' % re.escape(candidate)
        if re.search(pattern, text):
            return True
    return False


def check_structure(doc: Document, report: Report):
    for label, elements in scopes(doc.root):
        nodes = {}
        for element in elements:
            ident = element.get("IDENTIFIER")
            if ident is None:
                continue
            if ident in nodes:
                report.error(
                    doc.line(element),
                    "%s: IDENTIFIER %s is used by both <%s> and <%s>; every object "
                    "needs its own" % (label, ident, nodes[ident].tag, element.tag),
                )
            else:
                nodes[ident] = element
        for link in (e for e in elements if e.tag == "FEAT_LINK"):
            check_link(doc, report, label, link, nodes)


def check_link(doc, report, label, link, nodes):
    line = doc.line(link)
    ident = link.get("IDENTIFIER", "?")
    ends = {}
    for attr in ("SOURCE_NODE", "TARGET_NODE"):
        ref = link.get(attr)
        node = nodes.get(ref) if ref is not None else None
        if node is None or node.tag in LINK_TAGS:
            report.error(
                line,
                "%s: connection %s has %s=%s, which is not a transformer or feature "
                "type in this document" % (label, ident, attr, ref),
            )
            node = None
        ends[attr] = node

    for attr, prefix, end in (
        ("SOURCE_PORT_DESC", "fo", "SOURCE_NODE"),
        ("TARGET_PORT_DESC", "fi", "TARGET_NODE"),
    ):
        desc = link.get(attr)
        node = ends[end]
        # Workbench writes -1 for the reader or writer end of a connection.
        if desc == "-1" and (node is None or node.tag == "FEATURE_TYPE"):
            continue
        match = PORT_RE.match(desc) if desc is not None else None
        if match is None or match.group(1) != prefix:
            report.warn(
                line,
                "%s: connection %s has %s=%r; Workbench writes %r, a port index and "
                "the port name, or -1 at a reader or writer" % (label, ident, attr, desc, prefix),
            )

    source = ends["SOURCE_NODE"]
    match = PORT_RE.match(link.get("SOURCE_PORT_DESC") or "")
    if source is None or source.tag != "TRANSFORMER" or not match:
        return
    ports = [p.get("NAME") or "" for p in source.findall("OUTPUT_FEAT")]
    if not ports:
        return
    port, index = match.group(3), int(match.group(2))
    if port:
        known = decode_fully(port) in {decode_fully(p) for p in ports}
    else:
        # Older builds write only the index: "fo 0".
        known = 0 <= index < len(ports)
    if not known:
        report.warn(
            line,
            "%s: connection %s leaves %s through port %r, which is not one of its "
            "outputs (%s)"
            % (
                label,
                ident,
                node_label(source),
                decode_fully(port) if port else "#%d" % index,
                ", ".join(decode_fully(p) for p in ports),
            ),
        )


def check_mapping(doc: Document, mapping, report: Report):
    if not mapping:
        report.warn(
            None,
            "no mapping-file section. Workbench can open this, but `fme` has "
            "nothing to run until the workspace is saved from Workbench",
        )
        return
    text = "\n".join(t for _, t in mapping)
    _, main = scopes(doc.root)[0]

    def enabled(element):
        return element.get("ENABLED", "true") != "false"

    def emitted(element):
        name = parm(element, "XFORMER_NAME")
        return bool(name) and has_factory(text, name)

    nodes = {
        e.get("IDENTIFIER"): e
        for e in main
        if e.get("IDENTIFIER") is not None and e.tag not in LINK_TAGS and enabled(e)
    }
    incoming, outgoing = set(), {}
    for link in (e for e in main if e.tag == "FEAT_LINK" and enabled(e)):
        incoming.add(link.get("TARGET_NODE"))
        outgoing.setdefault(link.get("SOURCE_NODE"), []).append(link.get("TARGET_NODE"))

    # Workbench leaves any transformer no feature can reach out of the mapping
    # file, so only transformers downstream of a reader, or of a transformer
    # emitted without inputs (Creator and the like), are expected there.
    queue = [
        ident
        for ident, e in nodes.items()
        if (e.tag == "FEATURE_TYPE" and e.get("IS_SOURCE") == "true")
        or (e.tag == "TRANSFORMER" and ident not in incoming and emitted(e))
    ]
    reached = set(queue)
    while queue:
        for target in outgoing.get(queue.pop(), []):
            if target in nodes and target not in reached:
                reached.add(target)
                queue.append(target)

    for element in main:
        if element.tag != "TRANSFORMER" or element.get("IDENTIFIER") not in reached:
            continue
        if not emitted(element):
            report.warn(
                doc.line(element),
                "%s is in the Workbench section but never named in the mapping file; "
                "the two sections are out of sync" % node_label(element),
            )


def check_python(doc: Document, mapping, report: Report):
    text = "\n".join(t for _, t in mapping)
    for element in doc.root.iter("TRANSFORMER"):
        if element.get("TYPE") not in PYTHON_TRANSFORMERS:
            continue
        encoded = parm(element, "PYTHONSOURCE")
        if not encoded:
            continue
        label, line = node_label(element), doc.line(element)
        source = decode(encoded)
        try:
            compile(source, label, "exec")
        except SyntaxError as exc:
            report.error(
                line,
                "%s: script does not compile under Python %d.%d: %s (script line %s)"
                % (label, sys.version_info[0], sys.version_info[1], exc.msg, exc.lineno),
            )
        # Workbench stores the class (or, in old workspaces, function) to call as
        # PYTHONSYMBOL; the mapping file passes the same value as SYMBOL_NAME.
        symbol = parm(element, "PYTHONSYMBOL") or parm(element, "SYMBOL_NAME")
        if symbol and "." not in symbol and not re.search(
            r"^\s*(class|def)\s+%s\b" % re.escape(symbol), source, re.M
        ):
            report.error(
                line,
                "%s: calls %r (PYTHONSYMBOL) but the script defines no class or "
                "function with that name" % (label, symbol),
            )
        name = parm(element, "XFORMER_NAME")
        if name and has_factory(text, name) and encoded not in text:
            report.warn(
                line,
                "%s: the script in the Workbench section differs from SOURCE_CODE in "
                "the mapping file" % label,
            )


def form_parameters(doc: Document, report: Report):
    """Published parameters from USER_PARAMETERS FORM (base64 JSON, newer FME)."""
    found = []
    for element in doc.root.iter("USER_PARAMETERS"):
        form = element.get("FORM")
        if not form:
            continue
        try:
            data = json.loads(base64.b64decode(form, validate=True).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            report.error(
                doc.line(element),
                "USER_PARAMETERS FORM is not base64-encoded JSON; Workbench cannot load "
                "the published parameters",
            )
            continue

        def walk(params):
            for p in params:
                found.append(p)
                walk(p.get("parameters") or [])

        walk(data.get("parameters") or [])
    return found


def check_macros(doc: Document, mapping, params, report: Report):
    defined = set(BUILTIN_MACROS)
    # Also catches macros an INCLUDE block defines from Tcl, such as
    # INCLUDE [ ... puts {MACRO Name value} ... ].
    for _, line in mapping:
        defined.update(MACRO_DEF_RE.findall(line))
    defined.update(p.get("name") for p in params if p.get("name"))
    defined.update(e.get("NAME") for e in doc.root.iter("INFO") if e.get("NAME"))

    first_use = {}
    for element in doc.root.iter():
        for value in element.attrib.values():
            for name in MACRO_REF_RE.findall(value):
                first_use.setdefault(name, doc.line(element))
    for number, line in mapping:
        for name in MACRO_REF_RE.findall(line):
            first_use.setdefault(name, number)

    for name, line in first_use.items():
        if name not in defined and not name.startswith("FME_"):
            report.warn(
                line,
                "$(%s) is used but never defined by MACRO, DEFAULT_MACRO or a published "
                "parameter" % name,
            )


def load(path: str, report: Report):
    text = read_text(path, report)
    if text is None:
        return None, None
    header, mapping = split_sections(text)
    if not header:
        report.error(
            None,
            "no Workbench section. A workspace starts with '#! <?xml' and '#! <WORKSPACE'; "
            "a file without them is a bare mapping file (.fme), not a workspace",
        )
        return None, mapping
    doc, problem = parse_header(header)
    if problem:
        report.error(*problem)
        return None, mapping
    if doc.root.tag != "WORKSPACE":
        report.error(doc.line(doc.root), "Workbench section's root is <%s>, not <WORKSPACE>" % doc.root.tag)
        return None, mapping
    report.build = doc.root.get("LAST_SAVE_BUILD")
    return doc, mapping


def validate(path: str) -> Report:
    report = Report(path)
    doc, mapping = load(path, report)
    if doc is None:
        return report
    check_structure(doc, report)
    check_mapping(doc, mapping, report)
    check_python(doc, mapping, report)
    check_macros(doc, mapping, form_parameters(doc, report), report)
    return report


def print_report(report: Report, out):
    saved = " (saved by %s)" % report.build if report.build else ""
    verdict = "FAIL" if report.errors else "OK"
    out.write(
        "%s: %s, %d error%s, %d warning%s%s\n"
        % (
            report.path,
            verdict,
            len(report.errors),
            "" if len(report.errors) == 1 else "s",
            len(report.warnings),
            "" if len(report.warnings) == 1 else "s",
            saved,
        )
    )
    for kind, items in (("error", report.errors), ("warning", report.warnings)):
        for line, message in sorted(items, key=lambda item: item[0] or 0):
            where = "line %d" % line if line else "file"
            out.write("  %s %s: %s\n" % (kind, where, message))


def shorten(value, limit=60):
    value = decode(value or "").replace("\n", " ")
    return value if len(value) <= limit else value[: limit - 3] + "..."


def summarize(path: str, out) -> Report:
    report = Report(path)
    doc, mapping = load(path, report)
    if doc is None:
        print_report(report, out)
        return report
    root = doc.root
    out.write("%s\n" % path)
    out.write("  saved by: %s\n" % (report.build or "unknown"))
    python = next((line.split()[1] for _, line in mapping if line.startswith("FME_PYTHON_VERSION ")), None)
    if python:
        out.write("  FME_PYTHON_VERSION: %s\n" % python)

    params = [p for p in form_parameters(doc, report) if p.get("type") != "group"]
    legacy = [e.get("GUI_LINE", "") for e in root.iter("GLOBAL_PARAMETER")]
    out.write("\n  published parameters:\n")
    for p in params:
        out.write("    %s (%s) default=%r\n" % (p.get("name"), p.get("type"), shorten(str(p.get("defaultValue", "")))))
    if not params:
        for gui in legacy:
            out.write("    %s\n" % gui)
    if not params and not legacy:
        out.write("    (none)\n")

    out.write("\n  readers and writers:\n")
    # A DATASET without a FORMAT overrides another dataset; it is not a reader or writer.
    datasets = [d for d in root.iter("DATASET") if d.get("FORMAT")]
    for d in datasets:
        role = "reader" if d.get("IS_SOURCE") == "true" else "writer"
        out.write("    %s %s: %s\n" % (role, d.get("FORMAT"), shorten(d.get("DATASET"))))
    if not datasets:
        out.write("    (none)\n")

    label, main = scopes(root)[0]
    nodes = {e.get("IDENTIFIER"): e for e in main if e.get("IDENTIFIER") is not None}
    out.write("\n  transformers:\n")
    transformers = [e for e in main if e.tag == "TRANSFORMER"]
    for t in transformers:
        disabled = "" if t.get("ENABLED", "true") != "false" else " [disabled]"
        out.write("    #%s %s v%s%s\n" % (t.get("IDENTIFIER"), node_label(t), t.get("VERSION"), disabled))
    if not transformers:
        out.write("    (none)\n")

    out.write("\n  connections:\n")
    links = [e for e in main if e.tag == "FEAT_LINK"]
    for link in links:
        source, target = nodes.get(link.get("SOURCE_NODE")), nodes.get(link.get("TARGET_NODE"))
        src_port = (PORT_RE.match(link.get("SOURCE_PORT_DESC") or "") or [None] * 4)[3]
        tgt_port = (PORT_RE.match(link.get("TARGET_PORT_DESC") or "") or [None] * 4)[3]
        out.write(
            "    %s [%s] -> %s%s\n"
            % (
                node_label(source) if source is not None else "?" + str(link.get("SOURCE_NODE")),
                src_port or "",
                node_label(target) if target is not None else "?" + str(link.get("TARGET_NODE")),
                " [%s]" % tgt_port if tgt_port else "",
            )
        )
    if not links:
        out.write("    (none)\n")

    custom = len(scopes(root)) - 1
    if custom:
        out.write("\n  embedded custom transformers: %d\n" % custom)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Static checks for FME workspace (.fmw) files. No FME needed.",
        epilog="Exit status: 0 no errors, 1 errors found, 2 unreadable file or bad usage.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", help="list parameters, readers, writers, transformers and connections")
    mode.add_argument("--decode", metavar="TEXT", help="decode an FME-encoded value and print it")
    mode.add_argument("--encode", action="store_true", help="encode stdin for use in PARM_VALUE or SOURCE_CODE")
    parser.add_argument("workspaces", nargs="*", metavar="WORKSPACE.fmw")
    args = parser.parse_args(argv)

    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(errors="replace")

    if args.decode is not None:
        out.write(decode(args.decode) + "\n")
        return 0
    if args.encode:
        out.write(encode(sys.stdin.read()) + "\n")
        return 0
    if not args.workspaces:
        parser.print_usage(sys.stderr)
        return 2

    status = 0
    for index, path in enumerate(args.workspaces):
        if index:
            out.write("\n")
        report = summarize(path, out) if args.summary else validate(path)
        if not args.summary:
            print_report(report, out)
        if report.unreadable:
            status = 2
        elif report.errors and status == 0:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
