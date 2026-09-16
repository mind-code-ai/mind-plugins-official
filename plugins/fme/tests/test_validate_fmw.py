"""Tests for validate_fmw.py. Run from the plugin root:

    python3 -m unittest discover -s tests
"""

import io
import os
import sys
import tempfile
import unittest
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "workspaces"))

import validate_fmw  # noqa: E402

SCRIPT = (
    "import fme\n"
    "import fmeobjects\n"
    "\n"
    "class FeatureProcessor(object):\n"
    "    def input(self, feature):\n"
    "        feature.setAttribute('greeting', \"hello (world)\")\n"
    "        self.pyoutput(feature)\n"
)

HEADER = """#! <?xml version="1.0" encoding="UTF-8" ?>
#! <WORKSPACE
#    Command line to run this workspace:
#        fme test.fmw
#!   FME_BUILD_NUM="25208"
#!   LAST_SAVE_BUILD="FME(R) 2025.0.0.0 (20250228 - Build 25208 - WIN64)"
#! >
#! <USER_PARAMETERS
#!   FORM="@FORM@"
#! >
#! </USER_PARAMETERS>
#! <TRANSFORMERS>
#! <TRANSFORMER
#!   IDENTIFIER="2"
#!   TYPE="Creator"
#!   VERSION="6"
#!   ENABLED="true"
#! >
#!     <OUTPUT_FEAT NAME="CREATED"/>
#!     <XFORM_PARM PARM_NAME="XFORMER_NAME" PARM_VALUE="Creator"/>
#! </TRANSFORMER>
#! <TRANSFORMER
#!   IDENTIFIER="3"
#!   TYPE="PythonCaller"
#!   VERSION="4"
#!   ENABLED="true"
#! >
#!     <OUTPUT_FEAT NAME="Output"/>
#!     <XFORM_PARM PARM_NAME="PYTHONSOURCE" PARM_VALUE=@HEADER_SCRIPT@/>
#!     <XFORM_PARM PARM_NAME="PYTHONSYMBOL" PARM_VALUE="FeatureProcessor"/>
#!     <XFORM_PARM PARM_NAME="XFORMER_NAME" PARM_VALUE="PythonCaller"/>
#! </TRANSFORMER>
#! </TRANSFORMERS>
#! <FEAT_LINKS>
#! <FEAT_LINK
#!   IDENTIFIER="4"
#!   SOURCE_NODE="2"
#!   TARGET_NODE="3"
#!   SOURCE_PORT_DESC="fo 0 CREATED"
#!   TARGET_PORT_DESC="fi 0 "
#! />
#! </FEAT_LINKS>
#! </WORKSPACE>
"""

MAPPING = """
FME_PYTHON_VERSION 311
#! START_HEADER
#! START_WB_HEADER
READER_TYPE MULTI_READER
#! END_WB_HEADER
#! END_HEADER
DEFAULT_MACRO OutputDir C:/out
LOG_FILENAME "$(FME_MF_DIR)test.log"
DEFAULT_MACRO WB_CURRENT_CONTEXT
FACTORY_DEF {*} CreationFactory FACTORY_NAME { Creator } OUTPUT { FEATURE_TYPE Creator_CREATED }
FACTORY_DEF {*} PythonFactory FACTORY_NAME { PythonCaller } INPUT FEATURE_TYPE Creator_CREATED SYMBOL_NAME { FeatureProcessor } SOURCE_CODE { @MAPPING_SCRIPT@ }
"""

# {"parameters":[{"name":"OutputDir","type":"dir","defaultValue":"C:/out"}]}
FORM = "eyJwYXJhbWV0ZXJzIjpbeyJuYW1lIjoiT3V0cHV0RGlyIiwidHlwZSI6ImRpciIsImRlZmF1bHRWYWx1ZSI6IkM6L291dCJ9XX0="


def workspace(script=SCRIPT, mapping_script=None, header=HEADER, mapping=MAPPING, form=FORM):
    encoded = validate_fmw.encode(script)
    mapping_encoded = validate_fmw.encode(mapping_script if mapping_script is not None else script)
    text = header.replace("@HEADER_SCRIPT@", quoteattr(encoded)).replace("@FORM@", form)
    return text + mapping.replace("@MAPPING_SCRIPT@", mapping_encoded)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, text, name="test.fmw", newline="\n"):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
        return path

    def check(self, text, **kwargs):
        return validate_fmw.validate(self.write(text, **kwargs))

    def messages(self, items):
        return "\n".join(message for _, message in items)

    def test_well_formed_workspace_is_clean(self):
        report = self.check(workspace())
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertIn("2025.0.0.0", report.build)

    def test_windows_line_endings_are_accepted(self):
        report = self.check(workspace(), newline="\r\n")
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_connection_to_missing_node_is_an_error(self):
        report = self.check(workspace().replace('TARGET_NODE="3"', 'TARGET_NODE="99"'))
        self.assertIn("TARGET_NODE=99", self.messages(report.errors))

    def test_duplicate_identifier_is_an_error(self):
        report = self.check(workspace().replace('IDENTIFIER="3"', 'IDENTIFIER="2"'))
        self.assertIn("IDENTIFIER 2 is used by both", self.messages(report.errors))

    def test_malformed_xml_reports_the_file_line(self):
        text = workspace().replace("#! </TRANSFORMER>\n#! </TRANSFORMERS>", "#! </TRANSFORMERS>")
        report = self.check(text)
        self.assertEqual(len(report.errors), 1)
        line, message = report.errors[0]
        self.assertIn("not well-formed", message)
        self.assertEqual(text.splitlines()[line - 1], "#! </TRANSFORMERS>")

    def test_unknown_output_port_is_a_warning(self):
        report = self.check(workspace().replace("fo 0 CREATED", "fo 0 OUTPUT"))
        self.assertEqual(report.errors, [])
        self.assertIn("port 'OUTPUT'", self.messages(report.warnings))

    def test_malformed_port_description_is_a_warning(self):
        report = self.check(workspace().replace('TARGET_PORT_DESC="fi 0 "', 'TARGET_PORT_DESC="input"'))
        self.assertIn("TARGET_PORT_DESC='input'", self.messages(report.warnings))

    def test_minus_one_port_at_a_reader_is_accepted(self):
        text = workspace().replace(
            "#! <TRANSFORMERS>",
            '#! <FEATURE_TYPES>\n'
            '#! <FEATURE_TYPE IDENTIFIER="5" IS_SOURCE="true" NODE_NAME="points" ENABLED="true"/>\n'
            "#! </FEATURE_TYPES>\n"
            "#! <TRANSFORMERS>",
        ).replace(
            "#! </FEAT_LINKS>",
            '#! <FEAT_LINK IDENTIFIER="6" SOURCE_NODE="5" TARGET_NODE="3" SOURCE_PORT_DESC="-1" TARGET_PORT_DESC="fi 0 "/>\n'
            "#! </FEAT_LINKS>",
        )
        report = self.check(text)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_minus_one_port_at_a_transformer_is_a_warning(self):
        report = self.check(workspace().replace('SOURCE_PORT_DESC="fo 0 CREATED"', 'SOURCE_PORT_DESC="-1"'))
        self.assertIn("SOURCE_PORT_DESC='-1'", self.messages(report.warnings))

    def test_index_only_port_from_older_builds(self):
        self.assertEqual(self.check(workspace().replace("fo 0 CREATED", "fo 0")).warnings, [])
        report = self.check(workspace().replace("fo 0 CREATED", "fo 3"))
        self.assertIn("port '#3'", self.messages(report.warnings))

    def test_port_names_match_across_encoding_depths(self):
        text = workspace().replace('<OUTPUT_FEAT NAME="CREATED"/>', '<OUTPUT_FEAT NAME="Large&lt;space&gt;Maples"/>')
        text = text.replace("fo 0 CREATED", "fo 0 Large&lt;lt&gt;space&lt;gt&gt;Maples")
        self.assertEqual(self.check(text).warnings, [])

    def test_macro_defined_by_tcl_include_counts_as_defined(self):
        mapping = MAPPING + 'INCLUDE [ if { {A} == {A} } { puts {MACRO Joiner_MODE NO}; } ]\nX "$(Joiner_MODE)"\n'
        report = self.check(workspace(mapping=mapping))
        self.assertNotIn("Joiner_MODE", self.messages(report.warnings))

    def test_numbered_factory_belongs_to_a_different_transformer(self):
        text = workspace().replace("FACTORY_NAME { PythonCaller }", "FACTORY_NAME { PythonCaller_2 }")
        warnings = self.messages(self.check(text).warnings)
        self.assertIn("PythonCaller 'PythonCaller' is in the Workbench section", warnings)
        self.assertNotIn("differs from SOURCE_CODE", warnings)

    def test_python_syntax_error_is_an_error(self):
        broken = SCRIPT.replace("def input(self, feature):", "def input(self, feature)")
        report = self.check(workspace(script=broken))
        self.assertIn("does not compile", self.messages(report.errors))

    def test_symbol_name_must_exist_in_script(self):
        renamed = SCRIPT.replace("class FeatureProcessor", "class Processor")
        report = self.check(workspace(script=renamed, mapping_script=renamed))
        self.assertIn("calls 'FeatureProcessor' (PYTHONSYMBOL)", self.messages(report.errors))

    def test_script_drift_between_sections_is_a_warning(self):
        drifted = SCRIPT.replace("hello", "goodbye")
        report = self.check(workspace(mapping_script=drifted))
        self.assertEqual(report.errors, [])
        self.assertIn("differs from SOURCE_CODE", self.messages(report.warnings))

    def test_reachable_transformer_missing_from_mapping_is_a_warning(self):
        text = workspace().replace("FACTORY_NAME { PythonCaller }", "FACTORY_NAME { Caller }")
        report = self.check(text)
        self.assertIn("PythonCaller 'PythonCaller' is in the Workbench section", self.messages(report.warnings))

    def test_disabled_transformer_is_not_expected_in_mapping(self):
        text = workspace().replace("FACTORY_NAME { PythonCaller }", "FACTORY_NAME { Caller }")
        text = text.replace('TYPE="PythonCaller"\n#!   VERSION="4"\n#!   ENABLED="true"', 'TYPE="PythonCaller"\n#!   VERSION="4"\n#!   ENABLED="false"')
        report = self.check(text)
        self.assertNotIn("never named in the mapping", self.messages(report.warnings))

    def test_unreachable_transformer_is_not_expected_in_mapping(self):
        # Nothing feeds the Creator's factory, so neither transformer can receive
        # features and Workbench leaves both out of the mapping file.
        text = workspace().replace("FACTORY_NAME { Creator }", "FACTORY_NAME { Maker }")
        text = text.replace("FACTORY_NAME { PythonCaller }", "FACTORY_NAME { Caller }")
        report = self.check(text)
        self.assertNotIn("never named in the mapping", self.messages(report.warnings))

    def test_header_only_file_warns_that_fme_cannot_run_it(self):
        report = self.check(workspace(mapping=""))
        self.assertEqual(report.errors, [])
        self.assertIn("no mapping-file section", self.messages(report.warnings))

    def test_undefined_macro_is_a_warning_but_fme_builtins_are_not(self):
        report = self.check(workspace() + 'LOG_FILTER "$(Missing)" "$(FME_SHAREDRESOURCE_LOG)"\n')
        warnings = self.messages(report.warnings)
        self.assertIn("$(Missing)", warnings)
        self.assertNotIn("FME_SHAREDRESOURCE_LOG", warnings)

    def test_published_parameter_from_form_counts_as_defined(self):
        mapping = MAPPING.replace("DEFAULT_MACRO OutputDir C:/out\n", "") + 'X "$(OutputDir)"\n'
        report = self.check(workspace(mapping=mapping))
        self.assertNotIn("$(OutputDir)", self.messages(report.warnings))

    def test_invalid_form_is_an_error(self):
        report = self.check(workspace(form="not base64!"))
        self.assertIn("USER_PARAMETERS FORM", self.messages(report.errors))

    def test_mapping_file_without_workbench_section_is_an_error(self):
        report = self.check(MAPPING)
        self.assertIn("no Workbench section", self.messages(report.errors))

    def test_zip_archive_is_unreadable(self):
        path = os.path.join(self.dir.name, "template.fmwt")
        with open(path, "wb") as fh:
            fh.write(b"PK\x03\x04rest")
        report = validate_fmw.validate(path)
        self.assertTrue(report.unreadable)
        self.assertIn("zip archive", self.messages(report.errors))


class EncodingTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(validate_fmw.decode(validate_fmw.encode(SCRIPT)), SCRIPT)

    def test_matches_what_fme_writes(self):
        self.assertEqual(
            validate_fmw.encode("class FeatureProcessor(object):\n    pass"),
            "class<space>FeatureProcessor<openparen>object<closeparen>:<lf><space><space><space><space>pass",
        )

    def test_crlf_becomes_one_lf(self):
        self.assertEqual(validate_fmw.encode("a\r\nb"), "a<lf>b")

    def test_unknown_tokens_are_left_alone(self):
        self.assertEqual(validate_fmw.decode("a<space><mystery>b"), "a <mystery>b")


class MainTest(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            status = validate_fmw.main(argv)
        finally:
            sys.stdout = real
        return status, out.getvalue()

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.fmw")
            bad = os.path.join(tmp, "bad.fmw")
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(workspace())
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write(workspace().replace('TARGET_NODE="3"', 'TARGET_NODE="99"'))
            self.assertEqual(self.run_main([good])[0], 0)
            self.assertEqual(self.run_main([good, bad])[0], 1)
            self.assertEqual(self.run_main([os.path.join(tmp, "missing.fmw")])[0], 2)

    def test_summary_lists_the_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "good.fmw")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(workspace())
            status, output = self.run_main(["--summary", path])
        self.assertEqual(status, 0)
        self.assertIn("OutputDir (dir)", output)
        self.assertIn("Creator 'Creator' [CREATED] -> PythonCaller 'PythonCaller'", output)
        self.assertIn("FME_PYTHON_VERSION: 311", output)

    def test_decode_flag(self):
        self.assertEqual(self.run_main(["--decode", "a<space>b"]), (0, "a b\n"))


if __name__ == "__main__":
    unittest.main()
