"""Frozen backend entry point; no system Python or development folder required."""
import os
import sys
import certifi
os.environ.setdefault('SSL_CERT_FILE',certifi.where())
if '--self-test' in sys.argv:
    import json,tempfile
    from pathlib import Path
    from koala.desktop import dispatch
    from koala.exporters import write_format
    from koala.citations import render_csl
    from pypdf import PdfReader
    from docx import Document
    from striprtf.striprtf import rtf_to_text
    import pypandoc
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);project=root/'Project'
        result=dispatch({'action':'create','folder':str(project),'brief':{}})
        assert result['brief']['citation_style']=='mla'
        src={'id':'S001','title':'Example Work','authors':['Alex Scholar'],'year':'2024'}
        for style in ('mla','chicago-author-date'):
            text,refs=render_csl(['Example [@S001].'],[src],style)
            assert 'Scholar' in text[0] and refs
        content=[('title','KOALA runtime test'),('disclosure','Generated with the assistance of artificial intelligence.'),('paragraph','Žižek and meaning‐making.')]
        for fmt in ('docx','pdf','html','txt','rtf'):write_format(root/('test.'+fmt),content,fmt)
        assert 'meaning' in PdfReader(root/'test.pdf').pages[0].extract_text()
        assert Document(root/'test.docx').paragraphs
        assert 'meaning' in rtf_to_text((root/'test.rtf').read_text())
        print(json.dumps({'status':'ok','python':sys.version.split()[0],'pandoc':str(pypandoc.get_pandoc_version()),'checks':['project creation','MLA','Chicago','DOCX','PDF','HTML','TXT','RTF','TLS certificates']}))
else:
    from koala.desktop import main
    raise SystemExit(main())
