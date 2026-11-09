"""Site-bound plugin packages: actual ZIP and CLI, no production env/network."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stometric.web
from stometric import extension_package as package, api_plugin, config
from fastapi import HTTPException


class PackageTests(unittest.TestCase):
    def unpack(self,site):
        with zipfile.ZipFile(io.BytesIO(package.archive(ROOT/'extension',site))) as z:
            self.assertEqual(set(z.namelist()),{'seller-analytics-plugin/'+p for p in package.FILES})
            return {name:z.read('seller-analytics-plugin/'+name).decode() for name in package.FILES}
    def test_archive_targets_site_in_all_active_components(self):
        before={name:(ROOT/'extension'/name).read_bytes() for name in package.FILES}
        for site in ('https://shop.test','https://other.test:8443'):
            files=self.unpack(site);manifest=json.loads(files['manifest.json'])
            self.assertEqual(manifest['version'],'0.2.9')
            self.assertEqual(manifest['host_permissions'],[site+'/*','https://*.wildberries.ru/*'])
            self.assertIn('const API = '+json.dumps(site)+';',files['bg.js'])
            self.assertIn('<span id="platform-host">'+site+'</span>',files['popup.html'])
            self.assertIn(site.split('://')[1]+' → вкладка «Полки»',files['wb.js'])
            self.assertIn('AI-100metric by Max Popov',manifest['name'])
        self.assertEqual(before,{name:(ROOT/'extension'/name).read_bytes() for name in package.FILES})
    def test_invalid_or_example_site_is_rejected(self):
        for value in ('','http://shop.test','https://platform.example.org','https://analytics.example.org',
                      'https://localhost','https://127.0.0.1','https://[::1]','https://shop.test/path',
                      'https://shop.test?x=1','https://shop.test#x','https://user:pass@shop.test',
                      ' https://shop.test','https://shop.test\\x','https://shop.test:99999',
                      'https://shop.test:0','https://-bad.test','https://shop.test.','https://shop.test/\n'):
            with self.subTest(value=value),self.assertRaises(package.ExtensionConfigError):package.origin(value)
    def test_https_origin_normalization(self):
        self.assertEqual(package.origin('https://SHOP.test:443/'),'https://shop.test')
        self.assertEqual(package.origin('https://тест.рф'),'https://xn--e1aybc.xn--p1ai')
    def test_download_uses_site_config_without_request_host(self):
        with patch.object(config,'site_url',return_value='https://own.test'),patch.object(api_plugin,'EXT_DIR',ROOT/'extension'):
            response=api_plugin.download()
        self.assertEqual(response.media_type,'application/zip')
        self.assertEqual(response.headers['cache-control'],'no-store')
        with zipfile.ZipFile(io.BytesIO(response.body)) as z:
            self.assertIn('https://own.test/*',json.loads(z.read('seller-analytics-plugin/manifest.json'))['host_permissions'])
        with patch.object(config,'site_url',return_value='https://platform.example.org'):
            with self.assertRaises(HTTPException) as err:api_plugin.download()
        self.assertEqual(err.exception.status_code,409)
        self.assertIn('SITE_URL',err.exception.detail)
    def test_cli_reconfiguration_updates_every_target_and_invalid_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shutil.copytree(ROOT/'extension',root/'extension')
            (root/'scripts').mkdir();(root/'stometric').mkdir();(root/'stometric/__init__.py').write_text('')
            shutil.copyfile(ROOT/'scripts/configure_extension.py',root/'scripts/configure_extension.py')
            shutil.copyfile(ROOT/'stometric/extension_package.py',root/'stometric/extension_package.py')
            for site in ('https://first.test','https://second.test'):
                subprocess.run([sys.executable,str(root/'scripts/configure_extension.py'),site],check=True,capture_output=True)
                files=package.configured_files(root/'extension',site)
                for name in ('manifest.json','bg.js','popup.html','wb.js'):
                    self.assertEqual((root/'extension'/name).read_bytes(),files[name])
            before={name:(root/'extension'/name).read_bytes() for name in package.FILES}
            result=subprocess.run([sys.executable,str(root/'scripts/configure_extension.py'),'http://bad.test'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(before,{name:(root/'extension'/name).read_bytes() for name in package.FILES})
    def test_missing_links_and_unlisted_files_are_not_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'extension';shutil.copytree(ROOT/'extension',folder)
            (folder/'private-note.txt').write_text('synthetic-not-for-release')
            with zipfile.ZipFile(io.BytesIO(package.archive(folder,'https://shop.test'))) as z:
                self.assertFalse(any('private-note' in x for x in z.namelist()))
            (folder/'brand.svg').unlink();(folder/'brand.svg').symlink_to(folder/'panel.css')
            with self.assertRaises(package.ExtensionConfigError):package.archive(folder,'https://shop.test')

if __name__=='__main__':unittest.main()
