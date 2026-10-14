"""Bounded declared meal, coverage and closeout schemas; not arbitrary prose inference.
Paths, scenario amounts and fixed answer IDs never select source documents.
"""
import re
from collections import Counter
import budget_closeout as b
WORDS={w:i for i,w in enumerate(['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'])}
def number(s):
    if s.isdigit():return int(s)
    if s.lower() in WORDS:return WORDS[s.lower()]
    raise ValueError('Unsupported explicitly written integer')
def table_document(docs,headers,metadata):
    found=[]
    for d in docs:
        t=[t for t in b.tables(d) if t['headers']==headers]
        if t:
            m,ref=b.one(d,metadata);found.append((d,t,m,ref))
    if len(found)!=1 or len(found[0][1])!=1:raise ValueError('Missing or competing declared source/table; no timestamp winner')
    d,t,m,ref=found[0];return d,t[0],m,ref

def meals(request,docs,native):
    if not re.search(r'externally ordered meal portions',request):raise ValueError('Unsupported meal intent')
    d,t,meta,ref=table_document(docs,['Food basis','Quantity','Illustrative unit cost','Extension.'],r'Document (\w+)\. ([^\n]+?) Working agreement effective ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
    rows={r['values']['Food basis']:r for r in t['rows']};keys=['Adult package, including cocktail food and dinner','Child package','Vendor box'];counts={k:number(rows[k]['values']['Quantity']) for k in keys}
    staff,sr=b.one(d,r'([A-Z][a-z]+|\d+) caterer staff meals are provided within the staffing package, rather than charged as additional vendor boxes\.')
    couple,cr=b.one(d,r'Morgan and Jordan add ([a-z]+|\d+) adult meals and ([a-z]+|\d+) seats\.')
    overlay,orr=b.one(d,r'Vegan is a subset of vegetarian, and gluten-free and allergy requests are overlays\. They are not additional meals\.')
    approvals=[]
    for a in docs:
        for m,ar in b.matches(a,r'The couple approved plated dinner on ([A-Z][a-z]+ \d{1,2}),[^\n]+\n\n[^\n]+The plated approval supersedes the buffet proposal\.'):
            # Declaration includes named decision owner and explicit supersession, not keyword ranking.
            if 'Fictional working register maintained by' in a['text']:approvals.append(ar)
    if len(approvals)!=1:raise ValueError('Plated approval/supersession declaration missing or competing')
    accepted=[r for r in native['tables']['Guests'] if r['RSVP']['value']=='Accepted']
    for r in accepted:
        if r['Age group']['value'] not in ['Adult','Child'] or not r['Meal']['value']:raise ValueError('Accepted guest meal/age unknown; not zero/no')
    age=Counter(r['Age group']['value'] for r in accepted);variants=Counter(r['Meal']['value'] for r in accepted if r['Age group']['value']=='Adult')
    declared=[x for x in b.tables(d) if x['headers']==['Adult meal code','Plate','Guaranteed quantity','Included dietary variants.']]
    if len(declared)!=1:raise ValueError('Adult meal schema missing or competing')
    native_refs=[{'cell':r[k]['cell'],'value':r[k]['value']} for r in accepted for k in ['Guest ID','RSVP','Age group','Meal']]
    native_refs+=native['couple_meals']
    adults=age['Adult']+number(couple[1]);children=age['Child']
    couple_codes=Counter(x['value'] for x in native['couple_meals']);agreement=adults==counts[keys[0]] and children==counts[keys[1]] and len(native['couple_meals'])==number(couple[1])
    for row in declared[0]['rows']:
        k=row['values']['Adult meal code'];agreement &= variants[k]+couple_codes[k]==number(row['values']['Guaranteed quantity'])
    result={'request':request,'facts':{'adult_order':counts[keys[0]],'child_order':counts[keys[1]],'vendor_boxes':counts[keys[2]],'internally_supplied_staff_meals':number(staff[1]),'native_accepted_adults':age['Adult'],'native_accepted_children':children,'couple_meals':number(couple[1])},'calculation':{'externally_ordered':sum(counts.values()),'basis':'adult packages + child packages + vendor boxes; staff excluded'},'unknown':[] if agreement else ['Guest workbook and declared order disagree. Resolve the discrepancy with the recorded kitchen/order owner; do not silently change the guarantee.'],'support':[ref,sr,cr,orr,*approvals,*[rows[k]['support'] for k in keys],*[x['support'] for x in declared[0]['rows']]],'native_support':native_refs,'native_agreement':bool(agreement),'source_effective_date':meta[3]+', '+meta[4]}
    f=result['facts'];result['answer']=f"The external order is {result['calculation']['externally_ordered']} meal portions: {f['adult_order']} adult meals (including the couple), {f['child_order']} child meals and {f['vendor_boxes']} vendor boxes. The caterer supplies its {f['internally_supplied_staff_meals']} staff meals within its staffing package; they do not add to that external order. Dietary variants are part of these plates, not extra meals."
    result['next_action']='Use this count when checking the recorded catering order. A change after the guarantee needs a recorded kitchen and budget decision. These are historical fictional orders, not a new order to send.'
    return result

def insurance(request,docs,original_request=None):
    if not ('cancellation insurance' in request.lower() and 'fee' in request.lower()):raise ValueError('Unsupported insurance/fee intent')
    plans=[]
    for d in docs:
        if any(t['headers'][:3]==['ID','Expense','Base plan'] for t in b.tables(d)):
            m,ref=b.one(d,r'Document (\w+)\. ([^.]+); current planning cutoff ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
            plans.append((d,m,ref))
    if len(plans)!=1:raise ValueError('Planning finance source missing or competing')
    d,m,ref=plans[0]
    decline,dr=b.one(d,r'Cancellation insurance was explicitly declined\.')
    fee,fr=b.one(d,r'The (\$[\d,.]+) license amount is a planning allowance\. As of ([A-Z][a-z]+ \d{1,2}), the appointment and actual (\d{4}) fee are not confirmed\.')
    liability,lr=b.one(d,r'The (\$[\d,.]+) insurance line is a liability-only allowance\.')
    if fee[2]!=m[3] or fee[3]!=m[4]:raise ValueError('Fee qualification period conflicts')
    closeouts=[]
    for c in docs:
        if any(t['headers']==['Measure','Amount'] for t in b.tables(c)):
            cm,cref=b.one(c,r'Fictional post-event working record\. Document (\w+)\. Written by ([^.]+) on ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
            follow,fref=b.one(c,r'This record follows the ([A-Z][a-z]+ \d{1,2}) plan rather than changing what was known at that cutoff\.')
            if cm[2]==m[2] and cm[4]==m[4] and follow[1]==m[3]:closeouts.append((c,cm,cref,fref))
    if len(closeouts)!=1:raise ValueError('Explicitly linked closeout missing/competing')
    c,cm,cref,fref=closeouts[0]
    preserved,pr=b.one(c,r'Cancellation coverage remained explicitly declined\.')
    used,ur=b.one(c,r'The ([A-Z][a-z]+ \d{1,2}) license work target was completed in this story and used the (\$[\d,.]+) allowance\. This later result does not make the appointment or (\d{4}) fee confirmed in the ([A-Z][a-z]+ \d{1,2}) documents\.')
    if used[2]!=fee[1] or used[3]!=fee[3] or used[4]!=fee[2]:raise ValueError('Later fee qualification conflicts')
    cert,cer=b.one(c,r'The couple.s insurance certificate was not acknowledged[^\n]+Cancellation coverage remained explicitly declined\.')
    # Presentation follows the person's words, not the adapter's example prefix.
    text=(original_request if original_request is not None else request).lower()
    fee_requested=bool(re.search(r'\b(?:fee|license)\b',text))
    coverage_requested=bool(re.search(r'\b(?:insurance|coverage)\b',text))
    coverage='Cancellation insurance was explicitly declined; the couple chose liability-only coverage.'
    fee_answer=f'The supplied records do not confirm the actual {fee[3]} marriage-license fee. The {fee[1]} is a planning allowance, not a confirmed government charge. The {m[3]}, {m[4]} plan leaves the fee unconfirmed. The {cm[3]}, {cm[4]} fictional closeout records using the allowance, but explicitly does not establish fee confirmation in that earlier plan. No independent actual-fee confirmation is supplied.'
    answer=fee_answer if fee_requested else coverage
    if fee_requested and coverage_requested:answer+=' '+coverage
    next_action=(f'To establish the actual {fee[3]} fee, obtain an authoritative issuing-office fee schedule effective for the relevant date, or an actual receipt or issuing-office confirmation identifying the license fee. These documents are not supplied here.' if fee_requested else 'The recorded cancellation-coverage choice is settled. The later record separately acknowledges the insurance certificate after a documented extension.')
    return {'request':request,'facts':{'cancellation_insurance':'EXPLICITLY_DECLINED','liability_allowance_cents':b.cents(liability[1]),'license_allowance_cents':b.cents(fee[1]),'actual_fee_confirmation':'NOT_SUPPLIED','planning_cutoff':m[3]+', '+m[4],'closeout_date':cm[3]+', '+cm[4]},'unknown':['Actual government fee for the scenario year is not confirmed by the supplied records. This is missing information, not a decision to avoid obtaining a license.'],'answer':answer,'next_action':next_action,'support':[ref,dr,fr,lr,cref,fref,pr,ur,cer],'native_used':False,'native_reason':'Guest and gift workbook has no insurance decision or government fee authority.'}

def followup_schedule(rows,as_of,year):
    """Order explicit task-date fields, not prose importance or inferred urgency."""
    events=[];unresolved=[]
    date=r'([A-Z][a-z]+ \d{1,2})(?:, (\d{4}))?'
    for row in rows:
        field=row['values']['Next date']
        pair=re.fullmatch('Due '+date+'; follow up '+date,field)
        single=re.fullmatch(r'(Review )?'+date+r'( onward)?',field)
        if pair:parts=[(pair[1],pair[2],'Due'),(pair[3],pair[4],'Follow up')]
        elif single:parts=[(single[2],single[3],'Review' if single[1] else ('Start from' if single[4] else 'Recorded action'))]
        else:unresolved.append(dict(row['values'],reason='Date wording is outside the supported explicit forms.'));continue
        try:parsed=[(b.date(text,int(explicit_year or year)),kind) for text,explicit_year,kind in parts]
        except ValueError:unresolved.append(dict(row['values'],reason='Invalid explicit calendar date.'));continue
        for day,kind in parsed:
            events.append({'date':day.isoformat(),'display_date':f'{day.strftime("%B")} {day.day}, {day.year}','kind':kind,'task':dict(row['values']),'support':row['support']})
    events.sort(key=lambda event:event['date'])
    first=events[0]['date'] if events else None
    return {'as_of':as_of,'ordering':'Recorded calendar dates only; ties are not ranked by importance. Missing years use the dated closeout year; no automatic year rollover.','events':events,'earliest_date':first,'earliest_actions':[e for e in events if e['date']==first],'unresolved_dates':unresolved}

def vendor_name_preparation(docs,vid,as_of,options):
    scope='followup:'+vid+':preparation-name';documents={};records=[]
    for role,name,support in options:
        doc=next(d for d in docs if d['path']==support['file_name'])
        ref={'path':doc['path'],'sha256':support['file_sha256'],'start':support['original_file_span'][0],'end':support['original_file_span'][1],'quote':support['quote']}
        at=ref['quote'].index(name);name_ref=dict(ref,start=ref['start']+len(ref['quote'][:at].encode()),end=ref['start']+len(ref['quote'][:at+len(name)].encode()),quote=name)
        documents[doc['path']]={'full_original_text':doc['text'],'whole_source':{'path':doc['path'],'sha256':doc['sha256'],'start':0,'end':len(doc['text'].encode()),'quote':doc['text']},'derived_from_unretrieved':[],'omissions':'Fictional supplied records do not establish real vendor identity or contact authority.'}
        claims=[{'field':field,'value':None,'basis':'unresolved','scope':scope,'evidence':[]} for field in ['effective_date','version','status','units','authority']]
        claims.append({'field':'preparation_name','value':name,'basis':'source_recorded_text','scope':scope,'evidence':[name_ref]})
        records.append({'id':vid+':'+role,'source_id':doc['path'],'label':name,'support':ref,'claims':claims})
    return {'vendor_id':vid,'contract':{'schema':'local-source-record/1','documents':documents,'records':records,'relations':[],'annotation_cost':{'basis':'Existing declared vendor-ID/name comparison; no inferred identity authority.'}},'assessment':{'id':scope,'status':'unresolved_material_conflict','diagnosed_by':'Existing source-backed follow-up handler','diagnosis_basis':'DECLARED_SAME_VENDOR_ID_DIFFERENT_NAMES_NOT_IDENTITY_AUTHORITY','field':'preparation_name','scope':scope,'reason':'The same recorded vendor ID has different names. Choose a name only for preparing this follow-up; neither source is declared authoritative.','relevance':'material_to_requested_work','compatibility':'unresolved','record_ids':[r['id'] for r in records]},'context':{'domain':'wedding-followup/'+vid,'scope':scope,'unit':'name_for_preparation_only','time_context':as_of}}

def followup(request,docs):
    if not ('celebration is finished' in request.lower() and 'vendor deliveries' in request.lower()):raise ValueError('Unsupported closeout intent')
    d,t,m,ref=table_document(docs,['Task','Owner','Next date','State and practical dependency'],r'Document (\w+)\. Fictional closeout meeting dated ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
    rows=[r for r in t['rows'] if r['values']['State and practical dependency'].startswith(('Open.','Open information item.','Open vendor deliverable;','Planned future check,'))]
    if len(rows)!=len(t['rows']):raise ValueError('Unknown task state: preserve instead of dropping')
    media,mr=b.one(d,r'(V\d+), ([^,\n]+), had previews due ([A-Z][a-z]+ \d{1,2}) and the full private gallery due ([A-Z][a-z]+ \d{1,2})\. (V\d+), ([^,\n]+), has the highlight film due ([A-Z][a-z]+ \d{1,2})\. The full gallery and film remain open on ([A-Z][a-z]+ \d{1,2})\.')
    if media[8]!=m[2]:raise ValueError('Deliverable open date differs from closeout')
    vendors=[];unknown=[];preparations=[];support=[ref,mr,*[r['support'] for r in rows]]
    for vid,name,due,kind in [(media[1],media[2],media[4],'Full private photo gallery'),(media[5],media[6],media[7],'Highlight film')]:
        orders=[]
        for o in docs:
            if not re.search(r'Document \w+\. Effective ([A-Z][a-z]+ \d{1,2}), (\d{4})\.',o['text']):continue
            for om,orf in b.matches(o,r'^## '+re.escape(vid)+r', (.+?) — (B\d+), \$[\d,]+$'):orders.append((o,om,orf))
        if len(orders)!=1:raise ValueError('Vendor identifier has missing/competing working orders')
        o,om,orf=orders[0];support.append(orf)
        # Exact date occurs in that declared vendor section; a date elsewhere cannot validate delivery.
        section=o['text'].split(orf['quote'],1)[1].split('\n## ',1)[0]
        if due not in section:raise ValueError('Closeout due date not supported by declared vendor section')
        start=o['text'].index(orf['quote']);support.append(b.support(o,start,start+len(orf['quote'])+len(section)))
        names_agree=om[1]==name
        if not names_agree:unknown.append(f'{vid} has different recorded names: {om[1]} in the working order; {name} in the closeout. Confirm the correct contact before following up. The identifier and delivery date agree; neither name is silently preferred.')
        if not names_agree:preparations.append(vendor_name_preparation(docs,vid,m[2]+', '+m[3],[('order-name',om[1],orf),('closeout-name',name,mr)]))
        vendors.append({'vendor_id':vid,'closeout_name':name,'order_name':om[1],'names_agree':names_agree,'delivery':kind,'due':due+', '+m[3],'state':'OPEN_AT_CLOSEOUT'})
    result={'request':request,'as_of':m[2]+', '+m[3],'tasks':[r['values'] for r in rows],'vendors':vendors,'unknown':unknown+['Marriage filing receipt/certified-copy delivery, unidentified gift giver and earring owner remain unconfirmed. No real later delivery or completion is recorded by this demonstration.'],'support':support,'native_used':False,'native_reason':'The dated closeout supplies the owned remaining list. Native guest/gift details remain available in the completed thank-you task; no invented vendor or legal fields.'}
    result['schedule']=followup_schedule(rows,b.date(m[2],int(m[3])).isoformat(),int(m[3]))
    result['preparation_name_conflicts']=preparations
    result['answer']='The wedding is over, but the closeout leaves a small owned list: finish gift notes, identify the uncredited gift giver privately, retain the unclaimed earring, confirm marriage-document return/copy steps, and receive the two promised media deliveries. '+ '; '.join(v['delivery']+' is due '+v['due'] for v in vendors)+'. Both were still open at '+result['as_of']+'.'
    result['next_action']='Use the recorded owners and dated actions below. Delivery due dates and follow-up dates are separate; “start from” is not a completion deadline. Keep unresolved dependencies visible and confirm the conflicting film-vendor name before contacting anyone. This is a historical local work list; it sends no messages and marks no tasks complete.'
    earliest=result['schedule']['earliest_actions']
    if earliest:
        result['answer']='The earliest recorded action date is '+earliest[0]['display_date']+': '+'; '.join(e['task']['Task']+' — '+e['task']['Owner'] for e in earliest)+'. This is calendar order, not a judgment of importance, and uses the '+result['as_of']+' closeout. '+result['answer']
    if result['schedule']['unresolved_dates']:result['unknown'].append('Some task date fields could not be interpreted; those tasks remain visible without a guessed date.')
    return result
