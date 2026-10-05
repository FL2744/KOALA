#!/usr/bin/env python3
"""Build a local native SwiftUI app with Xcode command-line tools."""
import argparse
import platform
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path


def run(*args):
    subprocess.run([str(x) for x in args],check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,default=Path.home()/'Applications/KOALA.app')
    args=parser.parse_args();root=args.project_root.expanduser().resolve();output=args.output.expanduser().resolve()
    if output.exists():raise SystemExit(f'{output} already exists. Build to a new path, then replace it after quitting KOALA.')
    with tempfile.TemporaryDirectory(prefix='koala-app-') as tmp:
        tmp=Path(tmp);app=tmp/'KOALA.app';contents=app/'Contents'
        (contents/'MacOS').mkdir(parents=True);(contents/'Resources').mkdir()
        source=Path(__file__).parent/'KOALA.swift'
        arch='arm64' if platform.machine()=='arm64' else 'x86_64'
        run('xcrun','swiftc','-parse-as-library','-swift-version','5','-target',f'{arch}-apple-macosx13.0',
            '-module-cache-path',tmp/'ModuleCache',source,'-o',contents/'MacOS/KOALA','-framework','SwiftUI','-framework','AppKit')
        info={'CFBundleExecutable':'KOALA','CFBundleIdentifier':'org.koala.scholar.desktop',
              'CFBundleName':'KOALA','CFBundleDisplayName':'KOALA','CFBundlePackageType':'APPL',
              'CFBundleShortVersionString':'0.22.0','CFBundleVersion':'220','LSMinimumSystemVersion':'13.0',
              'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','KOALAProjectRoot':str(root),
              'NSHumanReadableCopyright':'Copyright © 2026 KOALA contributors. MIT License.'}
        logo=root/'koala-logo.png'
        if logo.exists():
            icons=tmp/'KOALA.iconset';icons.mkdir()
            for size in (16,32,128,256,512):
                for scale in (1,2):
                    name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
                    subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(logo),'--out',str(icons/name)],check=True,stdout=subprocess.DEVNULL)
            run('iconutil','-c','icns',icons,'-o',contents/'Resources/KOALA.icns')
            info['CFBundleIconFile']='KOALA.icns'
            shutil.copy2(logo,contents/'Resources/koala-logo.png')
        with (contents/'Info.plist').open('wb') as stream:plistlib.dump(info,stream)
        run('codesign','--force','--sign','-',app)
        output.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(app,output)
    print(f'Built {output}')

if __name__=='__main__':main()
