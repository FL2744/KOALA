import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from koala.books import normalize_citation_groups, section_issues
from koala.core import read_json
from koala.pipeline import prepare, draft
from test_books import BookProvider, setup_book


class SectionRecoveryTests(unittest.TestCase):
    def test_grouped_citations_preserve_ids_and_do_not_hide_unknowns(self):
        text=normalize_citation_groups('Claim [@S001; @S002] and [ @S003, S004 ].')
        self.assertEqual(text,'Claim [@S001] [@S002] and [@S003] [@S004].')
        self.assertTrue(any('Unavailable source IDs: S004' in issue for issue in section_issues(text,1,50,{'S001','S002','S003'})))
        self.assertEqual(normalize_citation_groups('Claim [@S001, p. 4].'),'Claim [@S001, p. 4].')
        self.assertTrue(any('Malformed' in issue for issue in section_issues('Claim [@S001, p. 4].',1,50,{'S001'})))

    def test_specific_diagnostics(self):
        self.assertIn('Add at least 8 words',section_issues('Two words',10,20,set())[0])
        self.assertIn('Remove at least 5 words',section_issues('word '*25,10,20,set())[0])

    def test_moderate_length_variation_and_groups_complete_without_rewriting(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);p=BookProvider();brief=setup_book(base)
            a=prepare(p,brief,base/'run',base/'brief.json',True,lambda _:None)
            original=p.generate; changed=False
            def generate(system,prompt):
                nonlocal changed
                text=original(system,prompt)
                if prompt.startswith('Write one section') and not changed:
                    changed=True
                    target=int(re.search(r'Target (\d+) prose',prompt)[1])
                    ids=re.findall(r'\[@(S\d+)\]',text)
                    return 'Memory '*round(target*.8) + ' ['+'; '.join('@'+i for i in ids)+']'
                return text
            with patch.object(p,'generate',side_effect=generate):
                done=draft(p,a,base/'run',lambda _:None)
            records=list((base/'run/draft-attempts').glob('*/*/*.json'))
            self.assertEqual(len(records),len(done['sections']))
            self.assertEqual(done['audit']['issues'],[])
            self.assertTrue(all(read_json(f)['accepted'] for f in records))

    def test_failed_attempts_are_preserved_and_correction_is_specific(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);p=BookProvider();brief=setup_book(base)
            a=prepare(p,brief,base/'run',base/'brief.json',True,lambda _:None)
            prompts=[]
            def short(system,prompt):
                prompts.append(prompt)
                return 'Too short [@S999999].'
            with patch.object(p,'generate',side_effect=short),self.assertRaisesRegex(ValueError,'Draft attempts are saved'):
                draft(p,a,base/'run',lambda _:None)
            records=list((base/'run/draft-attempts').glob('*/*/*.json'))
            self.assertEqual(len(records),3)
            self.assertIn('Too short:',prompts[1])
            self.assertIn('Unavailable source IDs: S999999',prompts[1])
            self.assertIn('Allowed source IDs:',prompts[1])
            self.assertTrue(all(read_json(f)['raw_text']=='Too short [@S999999].' for f in records))
            self.assertEqual(read_json(base/'run/article.json')['sections'],[])
