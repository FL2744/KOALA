#!/usr/bin/env python3
"""Build a relocatable native app and ZIP using an isolated build environment.

Install macos/standalone-requirements.txt and KOALA into that environment first.
"""
import argparse
import importlib.metadata
import json
import platform
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


def run(*args,**kw):subprocess.run([str(a) for a in args],check=True,**kw)

def notices(root,dest):
    dest.mkdir(parents=True)
    shutil.copy2(root/'LICENSE',dest/'KOALA-MIT.txt')
    shutil.copy2(root/'src/koala/styles/README.md',dest/'CSL-NOTICES.md')
    manifest=[]
    for dist in importlib.metadata.distributions():
        name=dist.metadata['Name'];version=dist.version
        manifest.append({'name':name,'version':version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''),'project_urls':dist.metadata.get_all('Project-URL') or []})
        for file in dist.files or []:
            if any(part.lower().startswith(('license','copying','notice')) for part in file.parts):
                source=Path(dist.locate_file(file))
                if source.is_file():
                    target=dest/name/str(file);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (dest/'dependencies.json').write_text(json.dumps(manifest,indent=2))
    (dest/'Python-license.txt').write_text(__import__('pydoc').render_doc('license'))
    for path in [Path(sys.base_prefix).resolve()/'LICENSE']+[ancestor/'LICENSE' for ancestor in Path(sys.base_prefix).resolve().parents]:
        if path.exists():shutil.copy2(path,dest/'Python-LICENSE');break
    (dest/'README.txt').write_text('KOALA is MIT licensed. Third-party components retain their own licenses. Pandoc is GPL licensed: https://pandoc.org/ and https://github.com/jgm/pandoc . PyInstaller bootloader uses the GPL with its distribution exception: https://pyinstaller.org/en/stable/license.html . Bundled CSL styles are CC BY-SA 3.0. See the individual notices and dependency manifest. This directory includes build-tool notices as well as runtime dependencies.\n')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('dist/KOALA.app'));parser.add_argument('--engine',type=Path,help='Reuse an already frozen backend directory');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];output=args.output.resolve()
    if output.exists():raise SystemExit('Choose a new output path; existing apps are never overwritten.')
    with tempfile.TemporaryDirectory(prefix='koala-standalone-') as tmp:
        tmp=Path(tmp);app=tmp/'KOALA.app'
        if args.engine:engine=args.engine.resolve()
        else:
            run(sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','koala-engine','--distpath',tmp/'dist','--workpath',tmp/'work','--specpath',tmp,'--paths',root/'src',*[item for package in ('koala','pypandoc','docx','reportlab','certifi') for item in ('--collect-all',package)],root/'macos/engine_entry.py')
            engine=tmp/'dist/koala-engine'
        run(sys.executable,root/'macos/build_app.py','--project-root',root,'--output',app)
        resources=app/'Contents/Resources';shutil.copytree(engine,resources/'engine',symlinks=True)
        notices(root,resources/'ThirdPartyNotices')
        info_path=app/'Contents/Info.plist'
        with info_path.open('rb') as f:info=plistlib.load(f)
        info.pop('KOALAProjectRoot',None);info['KOALAStandalone']=True
        minimum=sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET') or platform.mac_ver()[0]
        version_tuple=lambda value:tuple(int(n) for n in value.split('.')[:2])
        info['LSMinimumSystemVersion']=minimum if version_tuple(minimum)>=(13,0) else '13.0'
        with info_path.open('wb') as f:plistlib.dump(info,f)
        run('codesign','--force','--deep','--sign','-',app)
        run('codesign','--verify','--deep','--strict',app)
        output.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(app,output,symlinks=True)
    archive=output.parent/f'KOALA-macOS-{platform.machine()}.zip'
    run('ditto','-c','-k','--sequesterRsrc','--keepParent',output,archive)
    print(f'Built {output}\nArchive: {archive}\nMinimum macOS: {info["LSMinimumSystemVersion"]}. Ad-hoc signed; not notarized.')

if __name__=='__main__':main()
