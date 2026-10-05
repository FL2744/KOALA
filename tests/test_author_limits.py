import tempfile
import unittest
from pathlib import Path
from koala.core import normalize_brief, save, read_json
from koala.books import brief_context
from koala.menu import Menu
from test_menu import scripted


class AuthorLimitTests(unittest.TestCase):
    def test_999_names_roundtrip_for_article_and_book(self):
        names=[f'Author {i}' for i in range(999)]
        with tempfile.TemporaryDirectory() as d:
            for kind in ('article','book'):
                brief=normalize_brief({'project_type':kind,'important_authors':names})
                path=Path(d)/'brief.json';save(path,brief)
                self.assertEqual(normalize_brief(read_json(path))['important_authors'],names)

    def test_1000_rejected_with_clear_message(self):
        with self.assertRaisesRegex(ValueError,'at most 999'):
            normalize_brief({'important_authors':['Name']*1000})

    def test_book_prompts_retain_all_authors(self):
        names=[f'Author {i}' for i in range(999)]
        brief=normalize_brief({'project_type':'book','important_authors':names,'possible_citations':['Work']*40})
        result=brief_context(brief)
        self.assertEqual(result['important_authors'],names)
        self.assertEqual(len(result['possible_citations']),30)

    def test_menu_file_import_and_count(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d).resolve();path=folder/'authors.txt'
            names=[f'Author {i}' for i in range(999)]
            path.write_text('\n'.join(names),encoding='utf-8')
            save(folder/'brief.json',normalize_brief({}))
            output=[]
            menu=Menu(read=scripted(['6','@'+str(path),'0']),write=output.append)
            menu.open_project(folder);menu.edit_brief()
            self.assertEqual(read_json(folder/'brief.json')['important_authors'],names)
            self.assertTrue(any('999/999 authors' in s for s in output))

    def test_menu_rejects_excess_without_losing_saved_names(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d).resolve();path=folder/'authors.txt'
            path.write_text(';'.join(['Name']*1000))
            save(folder/'brief.json',normalize_brief({'important_authors':['Original']}))
            output=[]
            menu=Menu(read=scripted(['6','@'+str(path),'0']),write=output.append)
            menu.open_project(folder);menu.edit_brief()
            self.assertEqual(read_json(folder/'brief.json')['important_authors'],['Original'])
            self.assertTrue(any('at most 999' in s for s in output))
