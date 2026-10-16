"""Verifier failures must fail closed; no credentials, network or real ledger."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('verifier', Path(__file__).resolve().parents[1]/'tools/verify_frozen_source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zip = Path(self.tmp.name)/'candidate.zip'
        self.files = {'VERSION': b'0.2.3\n', 'AIX_SKILL_V0_1_RELEASE_MANIFEST.json': json.dumps({'build_id':'skill-0.2.3-example','source_commit':'b'*40}).encode()}
        with zipfile.ZipFile(self.zip, 'w') as z:
            for name, raw in self.files.items(): z.writestr('pkg/'+name, raw)
        self.record = {'package_sha256':hashlib.sha256(self.zip.read_bytes()).hexdigest(),'public_source_commit':'a'*40,'zip_prefix':'pkg/','public_source_path':'skills/aix','file_count':2,'file_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in self.files.items()},'skill_version':'0.2.3','build_id':'skill-0.2.3-example','protocol_build_input_commit':'b'*40}

    def run_verify(self):
        with patch.object(module.subprocess, 'check_output', side_effect=lambda args,**kw:self.files[args[-1].split('skills/aix/',1)[1]]):
            return module.verify(self.tmp.name,self.zip,self.record)

    def test_exact(self):
        self.assertEqual(self.run_verify()['files_matched'],2)

    def test_changed_zip(self):
        self.zip.write_bytes(self.zip.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'ZIP SHA256'):self.run_verify()

    def test_changed_git_blob(self):
        self.files['VERSION']=b'0.2.2\n'
        with self.assertRaisesRegex(ValueError,'Byte mismatch'):self.run_verify()

    def test_branch_instead_of_commit(self):
        self.record['public_source_commit']='main'
        with self.assertRaisesRegex(ValueError,'immutable'):self.run_verify()

    def test_missing_entry(self):
        self.record['file_sha256'].pop('VERSION');self.record['file_count']=1
        with self.assertRaisesRegex(ValueError,'allowlist'):self.run_verify()

    def test_claimed_version_mismatch(self):
        self.record['skill_version']='0.2.2'
        with self.assertRaisesRegex(ValueError,'Version mismatch'):self.run_verify()


if __name__ == '__main__':unittest.main()
