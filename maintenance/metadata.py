"""Decode complete runtime metadata; preserve defaults and portable type context."""
import hashlib


def decode_metadata(raw):
    if not isinstance(raw, str) or not raw.startswith('0x6d657461'):
        raise ValueError('invalid metadata magic')
    from scalecodec.base import RuntimeConfigurationObject, ScaleBytes
    from scalecodec.type_registry import load_type_registry_preset
    try:
        registry = RuntimeConfigurationObject()
        registry.update_type_registry(load_type_registry_preset('core'))
        obj = registry.create_scale_object('MetadataVersioned', data=ScaleBytes(raw))
        decoded = obj.decode()
        versioned = decoded[1]
        if len(versioned) != 1:
            raise ValueError('ambiguous metadata version')
        version, body = next(iter(versioned.items()))
        if version not in ('V14', 'V15') or not isinstance(body.get('pallets'), list):
            raise ValueError('unsupported metadata schema')
        return {'version': version, **body}
    except Exception as exc:
        raise ValueError('metadata decode failed (' + type(exc).__name__ + ')') from None


def compact_comparison(old, new):
    """Lossless changed-node projection; equal nodes are not repeated.

    Compare name/id keyed collections by identity, not list position. Retain
    changed documentation. Full decoded files are separately checksum-bound.
    """
    import json
    def normal(value):
        if isinstance(value, dict): return {k:normal(v) for k,v in value.items()}
        if isinstance(value, list):
            for key in ('name', 'id'):
                if value and all(isinstance(v,dict) and key in v for v in value):
                    keys=[str(v[key]) for v in value]
                    if len(keys)==len(set(keys)):
                        return {'@by-'+key:{str(v[key]):normal(v) for v in value}}
            return [normal(v) for v in value]
        return value
    changes=[]
    def visit(a,b,path):
        if a==b: return
        if isinstance(a,dict) and isinstance(b,dict):
            for k in sorted(set(a)|set(b)):
                if k not in a: changes.append({'path':path+[k],'before_present':False,'after':b[k]})
                elif k not in b: changes.append({'path':path+[k],'before':a[k],'after_present':False})
                else: visit(a[k],b[k],path+[k])
        else: changes.append({'path':path,'before':a,'after':b})
    visit(normal(old),normal(new),[])
    names=lambda obj:{p['name']:p for p in obj.get('pallets',[])}
    a,b=names(old),names(new)
    digest=lambda obj:hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'complete':True,'comparison_kind':'lossless changed-node projection',
            'old_decoded_sha256':digest(old),'new_decoded_sha256':digest(new),
            'changed_pallets':sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k)),
            'changes':changes,'storage_absence_is_not_removal_proof':True}


def compare_decoded(before, after):
    old = {p['name']: p for p in before['pallets']}
    new = {p['name']: p for p in after['pallets']}
    changed = {name: {'before': old.get(name), 'after': new.get(name)}
               for name in sorted(old.keys() | new.keys()) if old.get(name) != new.get(name)}
    other_old = {k:v for k,v in before.items() if k != 'pallets'}
    other_new = {k:v for k,v in after.items() if k != 'pallets'}
    return {'complete': True, 'changed_pallets': changed,
            'other_before': other_old, 'other_after': other_new,
            'interpretation': 'Type IDs are local to each metadata snapshot. Compare referenced definitions, not numeric IDs. Null raw storage can use a metadata default; source presence is not governance activation.'}
