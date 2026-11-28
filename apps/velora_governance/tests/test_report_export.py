import unittest
from velora_governance.governance.services.report_export import render_pdf, render_docx, compare_revisions, html_blocks

SAMPLE = '''<html><body><h1>Annual Report</h1><p>Performance improved.</p><h2>Highlights</h2><ul><li>Reduced waste</li><li>Improved governance</li></ul><table><tr><th>Metric</th><th>Value</th></tr><tr><td>Energy</td><td>120</td></tr></table></body></html>'''

class ReportExportTests(unittest.TestCase):
    def test_html_parser_extracts_blocks(self):
        blocks=html_blocks(SAMPLE)
        self.assertTrue(any(k=='h1' for k,_ in blocks))
        self.assertTrue(any(k=='table' for k,_ in blocks))
        self.assertTrue(any(k=='li' for k,_ in blocks))
    def test_pdf_export_valid_header_and_nonempty(self):
        data=render_pdf(SAMPLE, {'title':'Annual Report','cover_page':True})
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertGreater(len(data),1000)
    def test_docx_export_valid_zip(self):
        data=render_docx(SAMPLE, {'title':'Annual Report','cover_page':True})
        self.assertTrue(data.startswith(b'PK'))
        self.assertGreater(len(data),1000)
    def test_compare_summary(self):
        result=compare_revisions('<p>alpha beta</p>','<p>alpha gamma delta</p>')
        self.assertTrue(result['changed'])
        self.assertEqual(result['old_word_count'],2)
        self.assertEqual(result['new_word_count'],3)

if __name__=='__main__': unittest.main()

class ExportConfigTests(unittest.TestCase):
    def test_template_config_normalization(self):
        from velora_governance.governance.services.report_export import normalize_export_config
        cfg=normalize_export_config({'template_name':'Board Pack','page_size':'Letter','orientation':'Landscape','cover_page':False,'header_text':'Confidential'})
        self.assertEqual(cfg['title'],'Board Pack')
        self.assertEqual(cfg['page_size'],'Letter')
        self.assertFalse(cfg['cover_page'])
        self.assertEqual(cfg['header'],'Confidential')
    def test_invalid_page_config_rejected(self):
        from velora_governance.governance.services.report_export import normalize_export_config
        with self.assertRaises(ValueError): normalize_export_config({'page_size':'A3'})
