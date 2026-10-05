"""Named reusable writing prompts; projects retain their own text snapshots."""
import fcntl
import uuid
from pathlib import Path
from .core import read_json, save
from .writing_style import DEFAULT_WRITING_STYLE

LIBRARY_PATH = Path.home()/'Library/Application Support/KOALA/writing-prompts.json'


def library_view():
    records=read_json(LIBRARY_PATH).get('templates',[]) if LIBRARY_PATH.exists() else []
    return {'templates':[{'id':'default','name':'KOALA default','text':DEFAULT_WRITING_STYLE}]+records}


def save_template(name, text, template_id=None):
    if not isinstance(name,str) or not name.strip() or len(name)>120:
        raise ValueError('Enter a prompt name of 1–120 characters.')
    if not isinstance(text,str) or not text.strip() or len(text)>30000:
        raise ValueError('Enter a writing prompt of 1–30,000 characters.')
    if template_id=='default': raise ValueError('Save changes to the built-in prompt as a new template.')
    LIBRARY_PATH.parent.mkdir(parents=True,exist_ok=True)
    with LIBRARY_PATH.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        records=library_view()['templates'][1:]
        if template_id:
            record=next((r for r in records if r['id']==template_id),None)
            if record is None: raise ValueError('This template no longer exists. Save it as a new template.')
        else:
            record={'id':uuid.uuid4().hex};records.append(record)
        record.update(name=name.strip(),text=text.strip())
        save(LIBRARY_PATH,{'templates':records})
        return {**library_view(),'saved_id':record['id']}
