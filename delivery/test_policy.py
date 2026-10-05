import json
from pathlib import Path
import tempfile
import unittest
from policy import sanitize, safe_path, verify_package, digest

class ContractTests(unittest.TestCase):
    def test_nested_encoded_credentials_removed(self):
        value={'config':json.dumps({'headers':{'Authorization':'Bearer abcdefghijklmnop'},'apiKey':'private-value','model':'embedding-001'})}
        result=json.loads(sanitize(value,{},[])['config'])
        self.assertEqual(result,{'headers':{'Authorization':''},'apiKey':'','model':'embedding-001'})

    def test_secret_in_prompt_blocks(self):
        with self.assertRaises(ValueError):sanitize({'prompt':'use customer-secret-value here'},{},['customer-secret-value'])

    def test_source_identity_rebound(self):
        self.assertEqual(sanitize({'created_by':'old-owner','tenant_id':'workspace'}, {'old-owner':'admin','workspace':'new'},[]),{'created_by':'admin','tenant_id':'new'})

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):safe_path(Path('/package'),'../secret')

    def test_package_rejects_extra_files_and_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'database.json';data.write_text(json.dumps({'user':[]}))
            (root/'manifest.json').write_text(json.dumps({'format':2,'status':'verified-export','tables':{'user':0},'files':{'database.json':digest(data)}}))
            with self.assertRaisesRegex(ValueError,'Forbidden table'):verify_package(root)
            (root/'password.txt').write_text('hidden')
            with self.assertRaisesRegex(ValueError,'Unexpected'):verify_package(root)

    def test_package_rejects_old_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').write_text('{"format":1}')
            with self.assertRaisesRegex(ValueError,'incomplete'):verify_package(root)

if __name__=='__main__':unittest.main()
