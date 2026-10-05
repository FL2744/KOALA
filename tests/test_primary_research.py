import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from koala.primary import PrimaryDiscovery, excerpt_text, identity
from koala.research import Crossref, discover
from koala.research_refresh import expand_research
from koala.core import normalize_brief,save
from koala.coverage import has_evidence

class PrimaryResearchTests(unittest.TestCase):
    def test_author_query_rejects_secondary_title_and_other_given_name(self):
        def item(author,title):return {'title':[title],'author':[{'given':author,'family':'Harris'}],'published':{'date-parts':[[2020]]},'DOI':'10.1234/'+author}
        with patch('koala.research.request_json',return_value={'message':{'items':[item('Sam','A work'),item('Tristan','Sam Harris in context')]}}) as request:
            records=Crossref().primary('Sam Harris')
        self.assertEqual(len(records),1)
        self.assertIn('query.author=Sam+Harris',request.call_args.args[0])
        self.assertFalse(has_evidence(records[0]))

    def test_editions_are_not_merged_on_title_alone(self):
        a={'title':'Ethics','authors':['Aristotle'],'year':'1998','edition_key':'/books/OL1M'}
        self.assertNotEqual(identity(a),identity(dict(a,edition_key='/books/OL2M')))
        self.assertNotEqual(identity({'title':'Ethics','authors':['Spinoza'],'year':'1998'}),identity({'title':'Ethics','authors':['Aristotle'],'year':'1998'}))

    def test_public_text_is_bounded_and_has_no_fabricated_citation_locator(self):
        prose='Technology changes human practices. '*70
        text='License boilerplate\n*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n\n'+prose+'\n\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\nLicense'
        passages=excerpt_text(text,'technology')
        self.assertEqual(len(passages),1);self.assertLessEqual(len(passages[0]['text']),1200)
        self.assertNotIn('locator',passages[0]);self.assertNotIn('License',passages[0]['text'])
        self.assertFalse(excerpt_text('Unexpected HTML or malformed response','technology'))

    def test_library_authority_alias_and_edition_authorship(self):
        responses=[{'docs':[{'name':'Gabriel Turville-Petre','key':'OL1A','alternate_names':['E. O. G. Turville-Petre']}]},
          {'docs':[{'title':'Myth and Religion','author_name':['Gabriel Turville-Petre'],'author_key':['OL1A'],'editions':{'docs':[{'key':'/books/OL1M','ebook_access':'borrowable'}]}}]},
          {'title':'Myth and Religion','authors':[{'key':'/authors/OL1A'}],'publish_date':'1964','publishers':['Publisher']}]
        with patch('koala.primary.time.sleep'),patch('koala.primary.request_json',side_effect=responses):
            records,aliases=PrimaryDiscovery().library('E. O. G. Turville-Petre','religion')
        self.assertEqual(records[0]['year'],'1964');self.assertIn('Gabriel Turville-Petre',aliases)
        self.assertFalse(has_evidence(records[0]));self.assertIn('Borrowing',records[0]['access_status'])
        responses[-1]['authors']=[{'key':'/authors/OL2A'}]
        with patch('koala.primary.time.sleep'),patch('koala.primary.request_json',side_effect=responses):
            records,_=PrimaryDiscovery().library('E. O. G. Turville-Petre','religion')
        self.assertFalse(records)

    def test_primary_expansion_runs_even_with_complete_secondary_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            brief=normalize_brief({'important_authors':['Hannah Arendt'],'citation_target':1})
            secondary={'id':'S001','title':'Arendt study','authors':['Jane Scholar'],'year':'2020','abstract':'Hannah Arendt on political life.'}
            a={'brief':brief,'sources':[secondary],'sections':[],'abstract':'Keep me','stage':'abstract','plan':{'sections':[{}]}}
            save(Path(d)/'article.json',a)
            primary=Mock();primary.warnings=[];primary.author.return_value=[{'title':'The Human Condition','authors':['Hannah Arendt'],'year':'1958','abstract':'','notes':'','access_status':'Catalog record; text not retrieved'}]
            result=expand_research(a,d,lambda _:None,client=Mock(),primary=primary)
            primary.author.assert_called_once();self.assertEqual(result['abstract'],'Keep me')
            self.assertEqual(result['research_expansion']['primary_catalog_authors'],1)
            self.assertEqual(result['research_expansion']['primary_supported_authors'],0)
            self.assertEqual(result['sources'][0]['id'],'S001')

    def test_successful_queries_are_cached_not_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            p=PrimaryDiscovery(d);call=Mock(return_value=[])
            p.cached('test','author',call);p.cached('test','author',call)
            call.assert_called_once()
            failure=Mock(side_effect=RuntimeError('offline'))
            with self.assertRaises(RuntimeError):p.cached('fail','author',failure)
            with self.assertRaises(RuntimeError):p.cached('fail','author',failure)
            self.assertEqual(failure.call_count,2)

    def test_gutenberg_checks_creator_rights_and_preserves_translation(self):
        p=PrimaryDiscovery();p.catalog=[{'Text#':'123','Type':'Text','Language':'en','Authors':'Nietzsche, Friedrich, 1844-1900','Title':'Ethics','Subjects':'morality'}]
        xml='''<root xmlns:d="http://purl.org/dc/terms/" xmlns:p="http://www.gutenberg.org/2009/pgterms/" xmlns:m="http://id.loc.gov/vocabulary/relators/"><d:rights>Public domain in the USA.</d:rights><d:issued>2003-08-01</d:issued><d:creator><p:agent><p:name>Nietzsche, Friedrich Wilhelm</p:name></p:agent></d:creator><m:trl><p:agent><p:name>Helen Zimmern</p:name></p:agent></m:trl></root>'''
        text='*** START OF THE PROJECT GUTENBERG EBOOK ETHICS ***\n\n'+('A discussion of morality. '*40)+'\n\n*** END OF THE PROJECT GUTENBERG EBOOK ETHICS ***'
        with patch.object(p,'mirror_bytes',side_effect=[xml.encode(),text.encode()]):
            records=p.gutenberg('Friedrich Nietzsche',['Friedrich Nietzsche'],'morality')
        self.assertEqual(records[0]['year'],'2003');self.assertEqual(records[0]['translators'],['Helen Zimmern']);self.assertTrue(has_evidence(records[0]))
        from koala.citations import csl_record
        self.assertEqual(csl_record(dict(records[0],id='S001'))['translator'][0]['family'],'Zimmern')
        with patch.object(p,'mirror_bytes',return_value=xml.replace('Public domain in the USA.','Copyright protected.').encode()) as download:
            self.assertFalse(p.gutenberg('Friedrich Nietzsche',['Friedrich Nietzsche'],'morality'));self.assertEqual(download.call_count,1)
        with patch.object(p,'mirror_bytes',return_value=xml.replace('Nietzsche, Friedrich Wilhelm','Another, Writer').encode()) as download:
            self.assertFalse(p.gutenberg('Friedrich Nietzsche',['Friedrich Nietzsche'],'morality'));self.assertEqual(download.call_count,1)

    def test_repeated_outage_stops_requests_for_run(self):
        p=PrimaryDiscovery()
        with patch.object(p,'library',side_effect=RuntimeError('unavailable')) as lib,patch('koala.primary.Crossref') as crossref,patch.object(p,'gutenberg',return_value=[]):
            crossref.return_value.primary.return_value=[]
            for _ in range(5):p.author('Example Author')
        self.assertEqual(lib.call_count,3)
        self.assertTrue(any('skipping this service' in w for w in p.warnings))

    def test_primary_evidence_survives_secondary_only_relevance_selection(self):
        from koala.coverage import preserve_authors
        brief=normalize_brief({'important_authors':['Hannah Arendt']})
        secondary={'id':'S001','title':'A study','authors':['Jane Scholar'],'year':'2020','abstract':'Hannah Arendt and politics.'}
        primary={'id':'S002','title':'Political writing','authors':['Hannah Arendt'],'year':'1958','abstract':'A discussion of political action.'}
        result=preserve_authors(brief,[secondary,primary],[secondary])
        self.assertEqual({s['id'] for s in result},{'S001','S002'})

    def test_concurrent_cache_does_not_duplicate_or_corrupt_downloads(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        with tempfile.TemporaryDirectory() as d:
            primary=PrimaryDiscovery(d)
            def slow():
                time.sleep(.01)
                return {'text':'cached text'}
            call=Mock(side_effect=slow)
            with ThreadPoolExecutor(max_workers=3) as workers:
                results=list(workers.map(lambda _:primary.cached('same','book',call),range(6)))
            call.assert_called_once();self.assertTrue(all(r=={'text':'cached text'} for r in results))

    def test_public_text_skipped_for_unresolved_same_name_people(self):
        p=PrimaryDiscovery();p.ambiguous.add('John Gray')
        with patch.object(p,'catalog_books') as catalog:
            self.assertFalse(p.gutenberg('John Gray',['John Gray'],'nihilism'))
        catalog.assert_not_called()

    def test_unresolved_public_text_identity_is_not_evidence(self):
        self.assertFalse(has_evidence({'identity_review_required':True,'passages':[{'id':'p1','text':'Available text by a same-name writer.'}]}))

    def test_initials_fallback_resolves_full_authority_name(self):
        responses=[{'docs':[]},
          {'docs':[{'name':'Edward Oswald Gabriel Turville-Petre','key':'OL1A'}]},
          {'name':'Edward Oswald Gabriel Turville-Petre','key':'/authors/OL1A'},
          {'docs':[{'title':'Myth and Religion','author_name':['Edward Oswald Gabriel Turville-Petre'],'author_key':['OL1A'],'editions':{'docs':[{'key':'/books/OL1M'}]}}]},
          {'title':'Myth and Religion','authors':[{'key':'/authors/OL1A'}],'publish_date':'1964'}]
        with patch('koala.primary.time.sleep'),patch('koala.primary.request_json',side_effect=responses) as request:
            records,aliases=PrimaryDiscovery().library('E. O. G. Turville-Petre','religion')
        self.assertEqual(len(records),1);self.assertIn('Edward Oswald Gabriel Turville-Petre',aliases)
        self.assertIn('q=Turville-Petre',request.call_args_list[1].args[0])
