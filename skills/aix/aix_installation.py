"""Read-only diagnostics for the files actually loaded by the current host."""
import hashlib
import json
import pathlib
import sys
import urllib.request


def loaded_source(filename):
    """Capture once at import; on-disk replacement cannot rewrite running code."""
    path=pathlib.Path(filename).resolve()
    version=path.parent/'VERSION'
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'version':version.read_text(encoding='utf-8-sig').strip() if version.exists() else 'UNKNOWN'}


def installation_status(directory, *, check_public=False):
    directory = pathlib.Path(directory).resolve()
    metadata = {}
    try:
        metadata = json.loads((directory/'AIX_SKILL_V0_1_RELEASE_MANIFEST.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        pass
    if not isinstance(metadata,dict):metadata={}
    loaded = {}
    for name in ('aix_skill','aix_client','aix_guidance'):
        module = sys.modules.get(name)
        path = getattr(module,'__file__',None)
        if path:
            path = pathlib.Path(path).resolve()
            loaded[name] = {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            snapshot=getattr(module,'_AIX_LOADED_SOURCE',{})
            loaded[name].update(imported_sha256=snapshot.get('sha256'),
                imported_version=snapshot.get('version'),
                disk_changed_since_import=snapshot.get('sha256') != loaded[name]['sha256'])
    version_file = directory/'VERSION'
    version = version_file.read_text(encoding='utf-8-sig').strip() if version_file.exists() else 'UNKNOWN'
    imported=getattr(sys.modules.get('aix_skill'),'_AIX_LOADED_SOURCE',{})
    result = {'loaded_version':imported.get('version','UNKNOWN'),'disk_version':version,
              'loaded_build_id':metadata.get('build_id'),
              'loaded_modules':loaded,'public_release_status':'NOT_CHECKED',
              'mixed_search_paths':any(pathlib.Path(x['path']).parent != directory for x in loaded.values()),
              'reload_required':False,'credentials_modified':False,
              'next_action':'Use the official installer with checksum verification, then reload the host; preserve existing identity and credential storage. A downloaded ZIP does not replace already loaded modules.'}
    if check_public:
        try:
            req=urllib.request.Request('https://skill.aixprotocol.org/manifest.json',headers={'User-Agent':'AIX-Skill/0.1'})
            with urllib.request.urlopen(req,timeout=15) as response:
                public=json.load(response)
            public['build_id']=public.get('build_id') or public.get('skill_build_id')
            public['download_url']=public.get('download_url') or public.get('package_url')
            result['public_release']={k:public.get(k) for k in ('version','build_id','package_sha256','download_url')}
            mismatch=version != public.get('version') or metadata.get('build_id') != public.get('build_id')
            expected=public.get('file_sha256',{})
            result['loaded_file_checksums']='NOT_AVAILABLE' if not expected else 'CHECKED'
            mismatch = mismatch or bool(expected) and any(expected.get(pathlib.Path(x['path']).name) != x['imported_sha256'] for x in loaded.values())
            result['public_release_status']='MISMATCH' if mismatch else 'MATCH'
            result['reload_required']=bool(mismatch)
        except (OSError,ValueError):
            result['public_release_status']='UNREACHABLE'
    if result['mixed_search_paths'] or any(x['disk_changed_since_import'] for x in loaded.values()):
        result['reload_required']=True
    # Manifest values identify the release; they do not verify original ZIP bytes.
    result['zip_bytes_verified']=False
    return result
