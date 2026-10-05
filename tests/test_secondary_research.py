import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from koala.core import normalize_brief, save, read_json
from koala.coverage import author_coverage, citation_readiness, section_budget, coverage_issues, preserve_authors
from koala.secondary import annotate, secondary_evidence
from koala.research_refresh import expand_research
from koala.research import discover, normalize


def secondary(sid='S001',text='Hannah Arendt argues for political judgment.'):
    return {'id':sid,'title':'Judgment and public life','authors':['Jane Scholar'],'year':'2020','doi':'10.1234/'+sid,
            'abstract':text,'notes':''}


class SecondaryResearchTests(unittest.TestCase):
    def test_relationship_does_not_change_byline_and_needs_text(self):
        s=secondary();annotate(['Hannah Arendt'],s)
        self.assertEqual(s['authors'],['Jane Scholar'])
        self.assertEqual(s['author_links'][0]['author'],'Hannah Arendt')
        self.assertIsNone(secondary_evidence('Tristan Harris',secondary(text='Sam Harris on morality.')))
        metadata=secondary();metadata.update(title='Hannah Arendt',abstract='')
        self.assertIsNone(secondary_evidence('Hannah Arendt',metadata))
        metadata.update(title='References',references=[{'author':'Hannah Arendt'}])
        self.assertIsNone(secondary_evidence('Hannah Arendt',metadata))

    def test_secondary_requires_name_and_marker_in_same_paragraph(self):
        brief=normalize_brief({'important_authors':['Hannah Arendt']});sources=[secondary()]
        self.assertEqual(author_coverage(brief,sources,['S001'],'General claim [@S001].')[0]['status'],'not_cited')
        row=author_coverage(brief,sources,['S001'],'Scholar discusses Arendt’s judgment [@S001].')[0]
        self.assertEqual(row['status'],'cited');self.assertEqual(row['secondary_ids'],['S001']);self.assertFalse(row['primary_ids'])
        self.assertEqual(author_coverage(brief,sources,['S001'],'Arendt matters.\n\nOther claim [@S001].')[0]['status'],'not_cited')

    def test_shared_surname_is_not_misattributed(self):
        brief=normalize_brief({'important_authors':['Sam Harris','Tristan Harris']})
        s=secondary(text='Sam Harris and Tristan Harris hold contrasting views.')
        rows=author_coverage(brief,[s],['S001'],'Harris is discussed [@S001].')
        self.assertTrue(all(r['status']=='not_cited' for r in rows))
        rows=author_coverage(brief,[s],['S001'],'Sam Harris is discussed [@S001].')
        self.assertEqual([r['status'] for r in rows],['cited','not_cited'])

    def test_shared_survey_does_not_silently_cover_all_authors(self):
        a={'brief':normalize_brief({'citation_target':1,'important_authors':['Hannah Arendt','Judith Butler']}),
           'sources':[secondary(text='Hannah Arendt and Judith Butler address public life.')],
           'plan':{'sections':[{},{}]},'sections':[{'text':'Arendt is discussed [@S001].'}]}
        budget=section_budget(a,1)
        self.assertEqual(budget['required_author_mentions'],[{'author':'Judith Butler','source_id':'S001'}])
        self.assertEqual(budget['minimum_new_works'],0)
        self.assertTrue(coverage_issues('A generic statement [@S001].',budget))
        self.assertFalse(coverage_issues('Scholar discusses Butler’s account [@S001].',budget))

    def test_discovery_keeps_secondary_results(self):
        brief=normalize_brief({'citation_target':1,'important_authors':['Hannah Arendt']})
        client=Mock(spec=['query','doi']);client.query.return_value=[secondary()]
        sources,_=discover(brief,{'search_queries':[]},crossref=client)
        self.assertEqual(sources[0]['authors'],['Jane Scholar'])
        self.assertTrue(sources[0]['author_links'])
        self.assertEqual(preserve_authors(brief,sources,[]),sources)

    def test_expand_preserves_abstract_ids_and_cached_queries(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);brief=normalize_brief({'citation_target':2,'important_authors':['Hannah Arendt','Judith Butler']})
            old=secondary('S123');old['abstract']='Existing evidence.'
            a={'brief':brief,'sources':[old],'sections':[],'plan':{'sections':[{}]},'abstract':'Saved abstract','stage':'abstract','warnings':[]}
            save(folder/'article.json',a);save(folder/'research-cache/old.json',[secondary()])
            client=Mock();client.secondary.return_value=[dict(secondary('S002'),abstract='Judith Butler and politics.')]
            with patch('koala.research_refresh.time.sleep'):
                result=expand_research(a,folder,lambda _:None,client)
            self.assertEqual(result['abstract'],'Saved abstract');self.assertEqual(result['stage'],'abstract')
            self.assertEqual(result['sources'][0]['id'],'S123')
            self.assertEqual(result['research_expansion']['authors_with_supported_sources'],2)
            self.assertTrue(result['research_history'])
            count=client.secondary.call_count
            expand_research(result,folder,lambda _:None,client)
            self.assertEqual(client.secondary.call_count,count)
            self.assertEqual(len({s['id'] for s in result['sources']}),len(result['sources']))

    def test_reference_metadata_retained_without_inventing_evidence(self):
        s=normalize({'title':['A study'],'author':[{'given':'Jane','family':'Scholar'}],
                     'published':{'date-parts':[[2020]]},'reference':[{'author':'Hannah Arendt'}]})
        self.assertEqual(s['references'][0]['author'],'Hannah Arendt')
        self.assertFalse(s['abstract']);self.assertIsNone(secondary_evidence('Hannah Arendt',s))
