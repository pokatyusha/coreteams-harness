import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validator", ROOT / "scripts/validate.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((ROOT / "templates/request.json").read_text(encoding="utf-8"))
        self.ack = json.loads((ROOT / "templates/ack.json").read_text(encoding="utf-8"))
        self.result = json.loads((ROOT / "templates/result.json").read_text(encoding="utf-8"))

    def product_request(self):
        m = copy.deepcopy(self.request)
        m.update(operation="code_change", source={"repository": v.REGISTRY["source_repository"], "base_sha": "a" * 40, "allowed_paths": ["web-demo/server.js"]}, permissions=["read_repo", "edit_scoped_files"])
        return m

    def test_connection_round_trip(self):
        v.validate_pair(self.request, self.ack)
        v.validate_pair(self.request, self.result)

    def test_unknown_recipient_rejected(self):
        self.request["to"] = "arina-infra"
        with self.assertRaises(ValueError): v.validate_message(self.request)

    def test_response_from_other_role_rejected(self):
        self.ack["from"] = "filipp-infra"
        with self.assertRaises(ValueError): v.validate_pair(self.request, self.ack)

    def test_harness_sha_substitution_rejected(self):
        self.ack["harness_sha"] = "f" * 40
        with self.assertRaises(ValueError): v.validate_pair(self.request, self.ack)

    def test_other_request_id_rejected(self):
        self.ack["request_id"] = "CTH-OTHER"
        with self.assertRaises(ValueError): v.validate_pair(self.request, self.ack)

    def test_connection_cannot_run_product_tests(self):
        self.request["permissions"].append("run_local_tests")
        with self.assertRaises(ValueError): v.validate_message(self.request)

    def test_merge_deploy_and_background_permissions_rejected(self):
        for permission in ["merge", "deploy", "background_checks"]:
            with self.subTest(permission=permission):
                m = copy.deepcopy(self.request)
                m["permissions"].append(permission)
                with self.assertRaises(ValueError): v.validate_message(m)

    def test_parent_absolute_and_glob_scope_rejected(self):
        for path in ["../other", "web-demo/../../secret", "/etc", "C:/project", "web-demo\\server.js", "**"]:
            with self.subTest(path=path):
                m = self.product_request()
                m["source"]["allowed_paths"] = [path]
                with self.assertRaises(ValueError): v.validate_message(m)

    def test_source_sha_and_repository_required(self):
        for field, value in [("base_sha", "abc123"), ("base_sha", "0" * 40), ("repository", "other/repo")]:
            m = self.product_request()
            m["source"][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError): v.validate_message(m)

    def test_code_change_needs_edit_permission(self):
        m = self.product_request()
        m["permissions"] = ["read_repo"]
        with self.assertRaises(ValueError): v.validate_message(m)

    def test_review_cannot_edit(self):
        m = self.product_request()
        m["operation"] = "contract_review"
        with self.assertRaises(ValueError): v.validate_message(m)

    def test_accepted_input_sha_cannot_change(self):
        m = self.product_request()
        self.ack["source_sha"] = "b" * 40
        with self.assertRaises(ValueError): v.validate_pair(m, self.ack)

    def test_blocked_requires_explanation(self):
        self.ack["status"] = "blocked"
        with self.assertRaises(ValueError): v.validate_message(self.ack)

    def test_result_requires_limits_and_test_evidence(self):
        self.result["checks"][0]["outcome"] = "PASS"
        with self.assertRaises(ValueError): v.validate_message(self.result)
        self.result["checks"][0]["outcome"] = "NOT_RUN"
        self.result["limitations"] = []
        with self.assertRaises(ValueError): v.validate_message(self.result)

    def test_placeholder_binding_rejected(self):
        b = json.loads((ROOT / "templates/local-binding.example.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError): v.validate_binding(b)

    def test_product_result_carries_tested_sha_and_artifact(self):
        m = self.product_request()
        self.result.update(source_sha="b" * 40, artifacts=["https://github.com/AcryCxde/PP-Sber-Autumn-2026/pull/1"])
        v.validate_pair(m, self.result)
        self.result["artifacts"] = []
        with self.assertRaises(ValueError): v.validate_pair(m, self.result)

    def test_package(self):
        v.validate_package()


if __name__ == "__main__":
    unittest.main()
