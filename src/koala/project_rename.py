"""Rename a project folder while relocating its stored internal file references."""
import json
from pathlib import Path
from .core import save

def rename_project(folder,name):
    folder=Path(folder).resolve();destination=folder.with_name(name)
    engine=Path(__file__).resolve().parents[2]
    if folder==engine or folder in engine.parents or folder==Path.home():raise ValueError('The application or home folder cannot be renamed as a project.')
    if destination!=folder and destination.exists():raise ValueError('A folder with that name already exists. Choose another project name.')
    def relocate(value):
        if isinstance(value,str):
            if value.startswith('/') and '\n' not in value:
                try:
                    relative=Path(value).resolve().relative_to(folder)
                    return str(destination/relative)
                except (ValueError,OSError):pass
            return value
        if isinstance(value,list):return [relocate(v) for v in value]
        if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
        return value
    originals={};updated={}
    for path in folder.rglob('*.json'):
        if path.relative_to(folder).parts[0]=='data':continue
        if path.is_symlink() or not path.resolve().is_relative_to(folder):continue
        raw=path.read_bytes()
        try:value=json.loads(raw)
        except (ValueError,UnicodeDecodeError):continue
        new=relocate(value)
        if new!=value:originals[path.relative_to(folder)]=raw;updated[path.relative_to(folder)]=new
    article_path=folder/'article.json'
    if article_path.exists():
        old=json.loads(article_path.read_text());new=updated.get(Path('article.json'),relocate(old))
        from .manuscript_repair import fingerprint
        if old.get('manuscript_repair',{}).get('expected_fingerprint')==fingerprint(old):
            new['manuscript_repair']['expected_fingerprint']=fingerprint(new)
        originals[Path('article.json')]=article_path.read_bytes();updated[Path('article.json')]=new
        state_path=folder/'rewrite.json'
        if state_path.exists():
            from .rewrite import fingerprint as rewrite_fingerprint
            state=json.loads(state_path.read_text())
            if state.get('fingerprint')==rewrite_fingerprint(old):
                new_state=relocate(state);new_state['fingerprint']=rewrite_fingerprint(new)
                originals[Path('rewrite.json')]=state_path.read_bytes();updated[Path('rewrite.json')]=new_state
    metadata=folder/'.koala-project.json'
    originals[Path('.koala-project.json')]=metadata.read_bytes() if metadata.exists() else None
    updated[Path('.koala-project.json')]={'name':name}
    moved=False;writing=False
    try:
        if destination!=folder:folder.rename(destination);moved=True
        writing=True
        for relative,value in updated.items():save(destination/relative,value)
    except Exception:
        if not writing:raise
        for relative,raw in originals.items():
            target=destination/relative
            if raw is None:target.unlink(missing_ok=True)
            else:target.write_bytes(raw)
        if moved:destination.rename(folder)
        raise
    return destination
