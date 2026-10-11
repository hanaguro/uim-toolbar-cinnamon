#!/usr/bin/env python3
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

BRIDGE = Path(__file__).parent / 'uim-toolbar@hanaguro-port/uim_bridge.py'
spec = importlib.util.spec_from_file_location('bridge', BRIDGE)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class ParserTests(unittest.TestCase):
    def test_branch_and_leaf(self):
        text = 'prop_list_update\ncharset=UTF-8\nbranch\tmozc\tMozc\ttooltip\nleaf\thiragana\tあ\tひらがな\t説明\tmode_hiragana\t*\n'
        result = b.parse_properties(text)
        self.assertEqual(result[0]['icon'], 'mozc')
        self.assertEqual(result[0]['items'][0]['command'], 'mode_hiragana')
        self.assertTrue(result[0]['items'][0]['selected'])

    def test_empty_fields_preserved(self):
        text = 'prop_list_update\nbranch\tmode\tあ\nleaf\thiragana\t\tひらがな\t説明\tmode_hiragana\t*\n'
        self.assertEqual(b.parse_properties(text)[0]['items'][0]['label'], b._('ひらがな'))

    def test_malformed_and_orphan(self):
        text = 'prop_list_update\nleaf\tfoo\nx\nbranch\tmode\tM\nleaf\tx\ny\n'
        self.assertEqual(len(b.parse_properties(text)), 1)
        self.assertEqual(b.parse_properties(text)[0]['items'], [])

    def test_invalid_leaf_ignored(self):
        text = 'prop_list_update\nbranch\tmode\tM\nleaf\tx\tx\tname\t\tcmd\n'
        self.assertEqual(b.parse_properties(text)[0]['items'], [])

    def test_encodings(self):
        for encoding in ('UTF-8', 'EUC-JP'):
            raw = ('prop_list_update\ncharset='+encoding+'\nbranch\thiragana\tあ\t日本語\n').encode(encoding)
            self.assertIn('日本語', b.decode_message(raw))
        self.assertIn('�', b.decode_message(b'prop_list_update\n\xff'))

    def test_unknown_charset(self):
        with self.assertRaises(ValueError):
            b.decode_message(b'prop_list_update\ncharset=not-a-codec\n')

    def test_tool_programs(self):
        self.assertEqual([t[3] for t in b.TOOLS], ['uim-im-switcher-qt6','uim-pref-qt6','uim-dict-gtk3','uim-chardict-qt6','uim-tomoe-gtk','uim-help'])

    def test_mock_protocol(self):
        data = json.dumps({'type':'activate','command':'mode_direct'})+'\n'+json.dumps({'type':'quit'})+'\n'
        proc = subprocess.run([sys.executable,str(BRIDGE),'--mock'],input=data,text=True,capture_output=True,timeout=5)
        self.assertEqual(proc.returncode,0,proc.stderr)
        messages = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(messages[0]['type'],'config')
        props = [m for m in messages if m['type']=='properties']
        self.assertEqual(props[-1]['branches'][1]['icon'],'direct')
        self.assertIn('mock activate: mode_direct',proc.stderr)

    def test_reject_injected_command(self):
        data = json.dumps({'type':'activate','command':'mode_direct\nextra'})+'\n'+json.dumps({'type':'quit'})+'\n'
        proc = subprocess.run([sys.executable,str(BRIDGE),'--mock'],input=data,text=True,capture_output=True,timeout=5)
        self.assertEqual(proc.returncode,0)
        self.assertIn('invalid property command',proc.stderr)
        self.assertNotIn('mock activate:',proc.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
