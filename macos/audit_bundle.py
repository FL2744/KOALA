#!/usr/bin/env python3
"""Reject binaries requiring a newer macOS or external non-system libraries."""
import argparse
import json
import re
import subprocess
from pathlib import Path

MAGICS={bytes.fromhex(x) for x in ('feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca')}

def version(value):
    parts=tuple(int(n) for n in value.split('.'))
    return parts+(0,)*(3-len(parts))

def audit(app,minimum):
    binaries=[];errors=[];seen=set()
    for path in sorted(app.rglob('*')):
        if not path.is_file() or path.resolve() in seen:continue
        seen.add(path.resolve())
        with path.open('rb') as stream:magic=stream.read(4)
        if magic not in MAGICS:continue
        relative=str(path.relative_to(app))
        details=subprocess.check_output(['otool','-l',str(path)],text=True)
        versions=re.findall(r'\bminos\s+(\d+(?:\.\d+)*)',details)
        versions+=re.findall(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+(?:\.\d+)*)',details)
        if not versions:errors.append(f'{relative}: no macOS deployment target found')
        for value in versions:
            if version(value)>version(minimum):errors.append(f'{relative}: requires macOS {value}, exceeds {minimum}')
        dependencies=subprocess.check_output(['otool','-L',str(path)],text=True)
        for line in dependencies.splitlines():
            if not line.startswith(('\t',' ')):continue
            dep=line.strip().split(' (')[0]
            if dep.startswith('/') and not dep.startswith(('/System/Library/','/usr/lib/')):
                errors.append(f'{relative}: external dependency {dep}')
        binaries.append({'path':relative,'minimum_versions':versions})
    if not binaries:errors.append('No Mach-O binaries found')
    return {'target_macos':minimum,'binary_count':len(binaries),'errors':errors,'binaries':binaries}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('app',type=Path);parser.add_argument('--minimum-macos',required=True);args=parser.parse_args()
    result=audit(args.app,args.minimum_macos)
    print(json.dumps(result,indent=2))
    raise SystemExit(bool(result['errors']))

if __name__=='__main__':main()
