"""Source-bound supplied-work-item assembly; no model, subject search or sending."""
import copy
import datetime
import hashlib
import importlib.util
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

binder = load('retained_structural_binder', PROJECT/'outputs/m4-intent-trace-20261011/record_binding.py')

def verify(packet, source_root):
    for block in packet['blocks']:
        path = Path(source_root)/block['file_name']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != block['file_sha256']:
            raise ValueError('Source file changed')
        start, end = block['original_file_span']
        if raw[start:end].decode('utf-8') != block['text']:
            raise ValueError('Source passage differs from original bytes')

def field(text, pattern):
    hits = re.findall(pattern, text, re.M)
    return hits[0] if len(hits) == 1 else None

def assemble(packet):
    result = {'question':packet['question'], 'fields':{}, 'unknown':[],
              'software_record_bindings':{}, 'model_reasoning_credit':False,
              'source_scope':'Already supplied single bundle; subject selection and full-repository recall unproved.'}
    gifts = [b['text'] for b in packet['blocks'] if re.search(r'^F\d+:', b['text'], re.M)]
    if len(gifts) == 1:
        result['fields']['gift'] = field(gifts[0], r'^F\d+: ([^.]+)\.')
    try:
        bound = binder.bind(packet['blocks'])
    except (KeyError, ValueError) as error:
        result['unknown'] = ['Record relationship unresolved: '+str(error)]
        result['status'] = 'PARTIAL_RECORD_RELATIONSHIP_UNRESOLVED'
        return result
    result['software_record_bindings'] = bound
    texts = {b['id']:b['text'] for b in packet['blocks']}
    gift, person, note = [texts[bound[k]] for k in ['gift_and_card_credit','matching_person','matching_correspondence']]
    patterns = {
        'gift':(gift,r'^F\d+: ([^.]+)\.'),
        'gift_id':(gift,r'^(F\d+):'),
        'credited_giver':(gift,r'card credit ([^.]+)\.'),
        'person_id':(gift,r'person (G\d+)\.'),
        'household_id':(gift,r'Household (H\d+);'),
        'group_id':(gift,r'Group (GG\d+)\.'),
        'purchaser_record':(gift,r'Purchaser: ([^.]+)\.'),
        'received':(gift,r'Received (\d{4}-\d\d-\d\d)\.'),
        'correspondence_id':(note,r'^(TY\d+):'),
        'owner_id':(note,r'owner (P\d+)\.'),
        'status_record':(note,r'Status ([^.]+)\.'),
        'recorded_target':(note,r'target (\d{4}-\d\d-\d\d);'),
        'policy_days':(note,r'policy (\d+) days\.'),
        'draft_date':(note,r'Draft date (\d{4}-\d\d-\d\d)\.'),
        'approval_date':(note,r'Approval date (\d{4}-\d\d-\d\d)\.'),
        'sent_date':(note,r'Sent date (\d{4}-\d\d-\d\d)\.'),
        'address_publication_record':(person,r'Address publication: ([^.]+)\.'),
    }
    result['fields'] = {k:field(text, pattern) for k,(text,pattern) in patterns.items()}
    f = result['fields']
    for key in ['gift','credited_giver','status_record','received','policy_days','recorded_target']:
        if f[key] is None: result['unknown'].append(key+' missing or ambiguous')
    result['date_calculation'] = None
    if f['received'] and f['policy_days']:
        try:
            days = int(f['policy_days'])
            if not 0 < days <= 365: raise ValueError('Unsupported duration')
            computed = (datetime.date.fromisoformat(f['received'])+datetime.timedelta(days=days)).isoformat()
            result['date_calculation'] = {'received':f['received'],'days':days,'receipt_plus_days':computed,
                                         'recorded_target':f['recorded_target'],'matches_recorded':computed==f['recorded_target'],
                                         'scope':'Recorded per-item interval only; no independent policy approval or whole-policy classification.'}
            if computed != f['recorded_target']:result['unknown'].append('Calculated and recorded target do not agree; target unresolved')
        except ValueError:result['unknown'].append('Receipt date or interval invalid; target unresolved')
    for key,label in [('approval_date','Approval date'),('sent_date','Sent date')]:
        if not f[key]:result['unknown'].append(label+' not established; absence does not prove an explicit refusal')
    if f['purchaser_record'] in (None,'unknown'):result['unknown'].append('Purchaser unknown; card credit does not establish purchaser')
    result['unknown'] += ['Personal note wording and relationship detail are not established by this selected bundle.',
                          'The workflow owner is a recorded ID; a display-name mapping is not supplied.',
                          'Contact details are fictional, not deliverable; no address publication or sending authorized.']
    result['status'] = 'PARTIAL_USEFUL_WORK_ITEM'
    return result

def presentation(item, blocks):
    f = item['fields'];calc=item.get('date_calculation')
    target = calc['receipt_plus_days'] if calc and calc['matches_recorded'] else 'unresolved'
    answer = ('Work item: '+str(f.get('gift') or 'unresolved gift')+'. Credited giver: '+str(f.get('credited_giver') or 'unresolved')+
              '. Correspondence record: '+str(f.get('correspondence_id') or 'unresolved')+'. Receipt-based target: '+target+
              '. Recorded status: '+str(f.get('status_record') or 'unresolved')+'. Approval and sending remain separate recorded fields; no note is generated or sent.')
    return {'answer':answer,'raw_response':answer,'support':[{'quote':b['text']} for b in blocks],
            'support_status':'EXACT_ATTRIBUTION_ONLY','work_item':copy.deepcopy(item)}
