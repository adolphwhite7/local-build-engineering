"""One optional text clarification after accessible personal fields are inspected."""
import copy

def next_question(item, next_action='work_item'):
    if next_action!='personal_note':return None
    recipients=item.get('recipients',[])
    supplied={c.get('recipient_id') for c in item.get('clarifications',[]) if c.get('field')=='personal_context' and c.get('text')}
    missing=[r for r in recipients if r.get('card_credit') and not r.get('personal_note') and not r.get('recipient_note')
             and (r.get('person_id') or r.get('household_id')) not in supplied]
    if not missing:return None
    # Multiple recipients need a separately selected note subject; do not guess.
    if len(missing)!=1:return {'status':'PERSONAL_NOTE_SUBJECT_UNRESOLVED','question':None,'blocks_work_item':False}
    person=missing[0]
    return {'status':'OPTIONAL_NEXT_STEP','question':'What personal detail about your relationship with '+person['card_credit']+' would you like included in a thank-you note?',
            'field':'personal_context','recipient_id':person.get('person_id') or person.get('household_id'),
            'blocks_work_item':False,'intended_action':'personal_note',
            'known_context':{k:person.get(k) for k in ['card_credit','relationship','attendance','personal_note','recipient_note']},
            'reason':'The useful planning item is complete; original relationship/attendance fields were inspected, but personal wording is not recorded. No approval or sending implied.'}

def apply_reply(item, question, text, provenance):
    if not question or not question.get('question'):raise ValueError('No selected clarification')
    if not isinstance(text,str) or not text.strip():raise ValueError('Empty text reply')
    if not isinstance(provenance,dict) or not provenance.get('source') or not provenance.get('record_status'):raise ValueError('Reply provenance required')
    result=copy.deepcopy(item)
    result.setdefault('clarifications',[]).append({'field':question['field'],'recipient_id':question['recipient_id'],
        'text':text.strip(),'provenance':copy.deepcopy(provenance),'status':'SUPPLIED_TEXT_NOT_SOURCE_VERIFIED_APPROVAL_OR_SEND'})
    # Do not replace original source facts or clear unrelated unknowns.
    return result
