import copy
import sys
import unittest

from support import SCRIPTS, base_manifest

sys.path.insert(0, str(SCRIPTS))
import manifest_contract  # noqa: E402
import review_server  # noqa: E402


class ManifestContractTests(unittest.TestCase):
    def test_pure_contract_matches_server_public_api(self):
        manifest = base_manifest()
        self.assertEqual(
            manifest_contract.validate_manifest_contract(manifest),
            review_server.validate_manifest_contract(manifest),
        )

    def test_future_schema_fails_without_importing_http_state(self):
        manifest = copy.deepcopy(base_manifest())
        manifest["schema_version"] = "1.5"
        with self.assertRaisesRegex(ValueError, "versione massima"):
            manifest_contract.validate_manifest_contract(manifest)

    def test_contract_normalizes_expected_outputs(self):
        manifest = base_manifest()
        manifest["production"]["expected_outputs"] = ["pdf", "contact-sheet"]
        contract = manifest_contract.validate_manifest_contract(manifest)
        self.assertEqual(
            contract["production"]["expected_outputs"],
            ["pdf", "contact_sheet"],
        )


if __name__ == "__main__":
    unittest.main()
