import json
from pathlib import Path
import tempfile
import unittest
from issuer_keys import IssuerIdentity
from pos_desktop.key_store import WindowsDpapiProtector


class IssuerKeyTests(unittest.TestCase):
    def test_explicit_dpapi_creation_pin_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'issuer.json'
            original = IssuerIdentity.create_external(path, 'issuer-test', WindowsDpapiProtector())
            loaded = IssuerIdentity.load_external(path, original.fingerprint)
            self.assertEqual(loaded.public_record(), original.public_record())
            self.assertNotIn('private_key', loaded.public_record())
            with self.assertRaises(FileExistsError):
                IssuerIdentity.create_external(path, 'issuer-test')
            with self.assertRaises(ValueError):
                IssuerIdentity.load_external(path, '0' * 64)
            record = json.loads(path.read_text())
            record['public_key_b64'] = 'invalid'
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                IssuerIdentity.load_external(path, original.fingerprint)

    def test_private_identity_cannot_be_created_inside_repository(self):
        repo = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            IssuerIdentity.create_external(repo / 'forbidden-issuer.json', 'issuer-test')
        self.assertFalse((repo / 'forbidden-issuer.json').exists())
