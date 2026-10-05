import unittest
from koala.citations import render_csl,rich_html,MARKER,locator_issues
from koala.core import validate_sources,cited_ids


def source(i=1,authors=None,title='Collected Arguments',year='2023',**kw):
    return dict(id=f'S{i:03}',authors=['Alex Scholar'] if authors is None else authors,title=title,year=year,**kw)

def passage(locator='42',label='page'):
    return [{'id':'P1','text':'A documented passage','locator':locator,'label':label}]

class CitationGuideTests(unittest.TestCase):
    def render(self,text,sources,style):return render_csl([text],sources,style)[0][0]
    def test_author_page_and_author_date(self):
        s=source(passages=passage())
        self.assertEqual(self.render('A claim [@S001#P1].',[s],'mla'),'A claim (Scholar 42).')
        self.assertEqual(self.render('A claim [@S001#P1].',[s],'chicago-author-date'),'A claim (Scholar 2023, 42).')
    def test_narrative_existing_and_explicit(self):
        s=source(passages=passage())
        for text in ('Scholar argues the point [@S001#P1].','Alex Scholar discusses the point [@S001#P1!].'):
            self.assertIn('(42)',self.render(text,[s],'mla'))
            self.assertIn('(2023, 42)',self.render(text,[s],'chicago-author-date'))
    def test_unpaginated_narrative_no_empty_parentheses(self):
        s=source()
        text,refs=render_csl(['Scholar [@S001!] argues the point.'],[s],'mla')
        self.assertEqual(text[0],'Scholar argues the point.')
        self.assertEqual(len(refs),1)
        self.assertEqual(self.render('Scholar [@S001!] argues the point.',[s],'chicago-author-date'),'Scholar (2023) argues the point.')
    def test_no_suppression_from_previous_sentence_or_secondary_author(self):
        s=source()
        for text in ('Scholar argues something. Another claim [@S001].','Smith describes Scholar’s argument [@S001].'):
            self.assertIn('(Scholar 2023)',self.render(text,[s],'chicago-author-date'))
    def test_multiple_authors_and_clusters(self):
        sources=[source(authors=['Alex Scholar','Bea Writer']),source(2,authors=['Clara Researcher','Dan Reader','Eve Author'])]
        for style in ('mla','chicago-author-date'):
            text=self.render('A claim [@S001] [@S002].',sources,style)
            self.assertIn('Scholar and Writer',text);self.assertIn('Researcher et al.',text);self.assertIn(';',text)
    def test_same_author_titles_and_year_suffixes_narrative(self):
        sources=[source(title='Alpha'),source(2,title='Beta')]
        text=self.render('Scholar argues [@S001!]. Scholar argues [@S002!].',sources,'mla')
        self.assertIn('Alpha',text);self.assertIn('Beta',text);self.assertIn('<i>',rich_html(text))
        text=self.render('Scholar argues [@S001!]. Scholar argues [@S002!].',sources,'chicago-author-date')
        self.assertIn('2023a',text);self.assertIn('2023b',text)
    def test_anonymous_title_and_organization(self):
        s=source(authors=[],type='article-journal',title='Anonymous Argument')
        validate_sources([s]);text=self.render('A claim [@S001].',[s],'mla')
        self.assertIn('“Anonymous Argument”',text)
        s=source(authors=['Research Council'],author_names=[{'literal':'Research Council'}],year='n.d.')
        self.assertIn('(Research Council n.d.)',self.render('A claim [@S001].',[s],'chicago-author-date'))
    def test_nonpage_locator_and_no_publication_pages(self):
        s=source(passages=passage('6','chapter'),pages='1-100')
        self.assertIn('chap. 6',self.render('A claim [@S001#P1].',[s],'chicago-author-date'))
        self.assertNotIn('1–100',self.render('A claim [@S001].',[s],'mla'))
    def test_marker_accounting_and_locator_validation(self):
        text='[@S001!] [@S002#P1!]'
        self.assertEqual(cited_ids(text),['S001','S002'])
        self.assertEqual(MARKER.sub('',text),' ')
        self.assertTrue(locator_issues('[@S001#missing!]',[source()]))

    def test_mla_poetry_line_labels(self):
        s=source(passages=passage('5-6','line'))
        self.assertIn('lines 5–6',self.render('Scholar argues [@S001#P1!].',[s],'mla'))
