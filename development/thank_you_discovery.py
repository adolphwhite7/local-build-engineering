"""Exact entity discovery and explicit record joins over approved local sources."""
import hashlib
import json
import re
from pathlib import Path
import thank_you

def normalized(text):
    return ' '.join(re.findall(r'\w+',str(text).casefold()))

def entity_candidates(request, entities):
    """Exact complete declared labels or explicit typed IDs; no ranking/first hit."""
    query=normalized(request)
    ids=set(re.findall(r'\bF\d+\b',request))
    matched=[e for e in entities if e['id'] in ids or
             (' '+normalized(e['label'])+' ') in (' '+query+' ')]
    return sorted({(e['id'],e['label']) for e in matched})

def source_discovery(request, inventory_path, source_root):
    inventory=json.loads(Path(inventory_path).read_text())
    root=Path(source_root).resolve();declarations=[];entities=[];coverage=[]
    for d in inventory['documents']:
        rel=Path(d['relative_path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Inventory path escapes source root')
        path=root/rel
        if path.is_symlink():raise ValueError('Source symlink not admitted')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=d['sha256']:raise ValueError('Inventory hash mismatch: '+str(rel))
        text=raw.decode('utf-8');coverage.append({'path':str(rel),'document_id':d['document_id'],'sha256':d['sha256'],'bytes_read':len(raw)})
        for m in re.finditer(r'^(?:## )?(F\d+)(?:: | — )([^\n.]+)',text,re.M):
            entities.append({'id':m[1],'label':m[2]})
        # Only explicitly declared record grammar can supply the structural binder.
        starts=list(re.finditer(r'^(F\d+|H\d+|TY\d+):',text,re.M))
        for i,m in enumerate(starts):
            end=starts[i+1].start() if i+1<len(starts) else len(text)
            tail=text[m.start():end]
            footer=re.search(r'\n(?:Native fields:|Full records:)',tail)
            if footer:tail=tail[:footer.start()]
            tail=tail.rstrip()
            if m[1].startswith('TY'):tail=tail.split('\n\n')[0]
            start=len(text[:m.start()].encode());stop=start+len(tail.encode())
            declarations.append({'record':m[1],'text':tail,'file_name':str(rel),'file_sha256':d['sha256'],'document_id':d['document_id'],'original_file_span':[start,stop]})
    candidates=entity_candidates(request,entities)
    result={'request':request,'candidates':[{'id':i,'label':label} for i,label in candidates],'coverage':coverage,
            'selection_method':'Complete declared entity label or explicit typed ID, case/punctuation normalized; no keyword ranking or ordinal choice',
            'limits':'Exact labels/IDs only; synonyms and implied intent unresolved. Inventory coverage is source-only, not protected evaluator coverage.'}
    if len(candidates)!=1:result.update(status='ENTITY_MISSING_OR_AMBIGUOUS',packet=None);return result
    fid,label=candidates[0]
    def record(key):
        rows=[r for r in declarations if r['record']==key]
        if len(rows)!=1:raise ValueError(key+' missing or conflicting declared record')
        return rows[0]
    try:
        gift=record(fid)
        hid=thank_you.field(gift['text'],r'Household (H\d+);')
        group=thank_you.field(gift['text'],r'Group (GG\d+)\.')
        if not hid or not group:raise ValueError('Gift giver relationship missing or ambiguous')
        household=record(hid)
        notes=[r for r in declarations if re.search(r'^TY\d+: gift '+re.escape(fid)+r', group '+re.escape(group)+r',',r['text'])]
        if len(notes)!=1:raise ValueError('Correspondence missing or conflicting')
        blocks=[dict(r,id='S'+str(i+1)) for i,r in enumerate([gift,household,notes[0]])]
        packet={'question':request,'blocks':blocks,'coverage':{'all_read_source_files':coverage,'scope':'All delivered inventory files verified and scanned; chosen declared records retain exact UTF8 spans.'}}
        thank_you.verify(packet,root);thank_you.binder.bind(blocks)
    except ValueError as error:
        result.update(status='PARTIAL_RELATIONSHIP_UNRESOLVED',packet=None,error=str(error));return result
    result.update(status='EXACT_ENTITY_STRUCTURAL_BUNDLE_DISCOVERED',packet=packet)
    return result
