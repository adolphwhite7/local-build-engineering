"""Bounded declared finance-table/statement grammar, exact cents, source provenance.

Role mappings are software schema knowledge, not model discovery of arbitrary prose.
No known scenario amounts, record IDs or source paths choose the answer.
"""
import copy,datetime,hashlib,json,re
from decimal import Decimal
from pathlib import Path
MONTHS={name:i for i,name in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
MONEY=r'\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?'

def cents(text):
    if not re.fullmatch(MONEY,text):raise ValueError('Amount must be exact dollar-denominated cents')
    return int(Decimal(text[1:].replace(',',''))*100)

def usd(value):return f'${Decimal(value)/100:,.2f}'

def date(text,year):
    m=re.fullmatch(r'([A-Z][a-z]+) (\d{1,2})',text)
    if not m or m[1] not in MONTHS:raise ValueError('Unsupported explicit date')
    return datetime.date(year,MONTHS[m[1]],int(m[2]))

def inventory_read(inventory_path,source_root):
    inventory=json.loads(Path(inventory_path).read_text());root=Path(source_root).resolve();docs=[]
    for d in inventory['documents']:
        rel=Path(d['relative_path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Inventory path escapes source root')
        path=root/rel
        if path.is_symlink():raise ValueError('Source symlink not admitted')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=d['sha256']:raise ValueError('Inventory hash mismatch: '+str(rel))
        docs.append({'path':str(rel),'document_id':d['document_id'],'sha256':d['sha256'],'bytes_read':len(raw),'text':raw.decode('utf-8')})
    return docs

def support(doc,start,end):
    text=doc['text'];quote=text[start:end]
    return {'file_name':doc['path'],'document_id':doc['document_id'],'file_sha256':doc['sha256'],'original_file_span':[len(text[:start].encode()),len(text[:end].encode())],'quote':quote}

def matches(doc,pattern):
    return [(m,support(doc,m.start(),m.end())) for m in re.finditer(pattern,doc['text'],re.M)]

def one(doc,pattern):
    hits=matches(doc,pattern)
    if len(hits)!=1:raise ValueError('Declared field is missing or ambiguous: '+pattern)
    return hits[0]

def tables(doc):
    lines=doc['text'].splitlines(keepends=True);offset=0;current=None;out=[]
    for line in lines:
        plain=line.strip()
        if plain.startswith('|') and plain.endswith('|'):
            cells=[c.strip() for c in plain[1:-1].split('|')]
            if all(re.fullmatch(r':?-+:?',c) for c in cells):pass
            elif current is None:current={'headers':cells,'rows':[]};out.append(current)
            else:
                if len(cells)!=len(current['headers']):raise ValueError('Uneven declared table')
                current['rows'].append({'values':dict(zip(current['headers'],cells)),'support':support(doc,offset,offset+len(line.rstrip('\r\n')))})
        else:current=None
        offset+=len(line)
    return out

def select(request,docs):
    requested=re.findall(r'At the ([A-Z][a-z]+) closeout',request)
    if len(requested)!=1 or requested[0] not in MONTHS:raise ValueError('Requested closeout period is not explicit in supported grammar')
    closeouts=[];plans=[]
    for doc in docs:
        ts=tables(doc)
        if any(t['headers']==['Measure','Amount'] and {'Final expense total','Funding and ceiling','Final unspent funds'}<={r['values']['Measure'] for r in t['rows']} for t in ts):
            m,ref=one(doc,r'Fictional post-event working record\. Document (\w+)\. Written by ([^.]+) on ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
            if m[3].split()[0]==requested[0]:closeouts.append((doc,ts,m,ref))
        if any(t['headers'][:3]==['ID','Expense','Base plan'] for t in ts):
            m,ref=one(doc,r'Document (\w+)\. ([^.]+); current planning cutoff ([A-Z][a-z]+ \d{1,2}), (\d{4})\.')
            plans.append((doc,ts,m,ref))
    if len(closeouts)!=1:raise ValueError('Requested explicit finance closeout missing or competing; no newest-file selection')
    close,ct,cm,cr=closeouts[0]
    follow,fr=one(close,r'This record follows the ([A-Z][a-z]+ \d{1,2}) plan rather than changing what was known at that cutoff\.')
    plans=[x for x in plans if x[2][3]==follow[1] and x[2][4]==cm[4] and x[2][2]==cm[2]]
    if len(plans)!=1:raise ValueError('Explicit prior plan/owners/date relationship missing or competing')
    plan,pt,pm,pr=plans[0];year=int(cm[4]);closedate=date(cm[3],year);plandate=date(pm[3],year)
    if plandate>=closedate:raise ValueError('Planning/closeout period order conflicts')
    settled,sr=one(close,r'The cost ledger is settled through ([A-Z][a-z]+ \d{1,2})\.')
    if date(settled[1],year)!=closedate:raise ValueError('Declared settlement period conflicts')
    for doc in [plan,close]:
        if not re.search(r'All example amounts are inclusive USD\.|Every amount is inclusive illustrative USD\.',doc['text']):raise ValueError('Declared inclusive USD units unavailable')
    return {'close':close,'close_tables':ct,'plan':plan,'plan_tables':pt,'year':year,'close_date':closedate,'plan_date':plandate,'owners':cm[2],'period_support':[cr,pr,fr,sr]}

def assemble(request,docs):
    result={'request':request,'status':'USEFUL_PARTIAL_SOURCE_BACKED_BUDGET','facts':{},'calculations':{},'unknown':[],'support':[],'model_reasoning_credit':False}
    try:
        s=select(request,docs);close=s['close'];plan=s['plan'];year=s['year'];refs=list(s['period_support'])
        rows=[r for t in s['plan_tables'] if t['headers'][:3]==['ID','Expense','Base plan'] for r in t['rows']]
        if not rows:raise ValueError('No base expense records')
        identifiers=[r['values']['ID'] for r in rows]
        if len(set(identifiers))!=len(identifiers):raise ValueError('Duplicate base expense IDs')
        base=[]
        for r in rows:
            v=r['values'];paidcols=[k for k in v if k.startswith('Paid by ')]
            if len(paidcols)!=1 or date(paidcols[0][8:],year)!=s['plan_date']:raise ValueError('Base paid column period conflicts')
            amount=cents(v['Base plan']);paid=cents(v[paidcols[0]]);remaining=cents(v['Remaining'])
            if amount-paid!=remaining or paid>amount:raise ValueError('Base paid/remaining amount inconsistent')
            base.append({'id':v['ID'],'label':v['Expense'],'base_cents':amount,'paid_at_plan_cents':paid,'remaining_at_plan_cents':remaining,'support':r['support']})
        summarytables=[t for t in s['close_tables'] if t['headers']==['Measure','Amount']]
        if len(summarytables)!=1:raise ValueError('Competing final summaries')
        summary={}
        for r in summarytables[0]['rows']:
            v=r['values'];label=v['Measure']
            if label in summary:raise ValueError('Duplicate final measure')
            summary[label]={'text':v['Amount'],'support':r['support']}
        ceiling=cents(summary['Funding and ceiling']['text']);expense_recorded=cents(summary['Final expense total']['text']);unspent_recorded=cents(summary['Final unspent funds']['text'])
        ceilingm,ceilref=one(plan,r"The couple's ceiling is ("+MONEY+r')\.')
        if cents(ceilingm[1])!=ceiling:raise ValueError('Plan/closeout ceiling conflicts')
        result['support']=refs+[ceilref]+[v['support'] for v in summary.values()]
        result['facts'].update(currency='USD',closeout_date=s['close_date'].isoformat(),planning_date=s['plan_date'].isoformat(),record_owners=s['owners'],ceiling_cents=ceiling,recorded_final_expense_cents=expense_recorded)
        additiontables=[t for t in s['close_tables'] if t['headers']==['Addition','Budget link','Purpose and authority','Final amount','Fictional payment']]
        if len(additiontables)!=1:raise ValueError('Approved additions missing or competing')
        approval_total=None;approval_dates=[]
        # Actual owner approval/acknowledgment, not coordinator authority or timestamp ranking.
        ackrefs=[]
        for owner in s['owners'].split(' and '):
            first=owner.split()[0]
            am,ar=one(close,re.escape(first)+r"'s recorded (?:approval|acknowledgment): “([^”]+)”")
            if 'recorded approval:' in am[0]:
                approved=re.fullmatch(r'Yes to the [^.]+ and the ('+MONEY+r') total\.[\s\S]+',am[1])
                if not approved:raise ValueError('Owner approval is outside supported positive declaration grammar')
                approval_total=cents(approved[1])
            elif not am[1].startswith('Agreed.'):raise ValueError('Owner acknowledgment is outside supported positive declaration grammar')
            headings=list(re.finditer(r'^## ([A-Z][a-z]+ \d{1,2}):[^\n]+',close['text'][:am.start()],re.M))
            if not headings:raise ValueError('Approval section date missing')
            approval_dates.append(date(headings[-1][1],year))
            ackrefs.append(ar)
        if len(set(approval_dates))!=1:raise ValueError('Owners approval dates differ')
        additions=[];declared_total=None
        for r in additiontables[0]['rows']:
            v=r['values']
            if v['Addition']=='Total':
                if declared_total is not None:raise ValueError('Duplicate additions total')
                if not re.fullmatch(r'\w+ approved additions',v['Purpose and authority']):raise ValueError('Addition total approval declaration missing')
                declared_total=cents(v['Final amount']);refs.append(r['support']);continue
            linked=re.findall(r'\b[A-Z]+\d+\b',v['Budget link'])
            if len(linked)!=1 or linked[0] not in identifiers:raise ValueError('Addition/base relationship missing or competing')
            am=re.search(r'([A-Z][a-z]+ \d{1,2}) approval$',v['Purpose and authority'])
            if not am or date(am[1],year)!=approval_dates[0] or date(am[1],year)>s['close_date']:raise ValueError('Addition approval date unresolved')
            payment=date(v['Fictional payment'],year)
            if payment<date(am[1],year) or payment>s['close_date']:raise ValueError('Addition payment period conflicts')
            additions.append({'id':v['Addition'],'base_id':linked[0],'amount_cents':cents(v['Final amount']),'approved':date(am[1],year).isoformat(),'paid':payment.isoformat(),'support':r['support']})
        if len({r['id'] for r in additions})!=len(additions):raise ValueError('Duplicate addition IDs')
        base_total=sum(r['base_cents'] for r in base);added=sum(r['amount_cents'] for r in additions)
        if declared_total!=added or approval_total!=added:raise ValueError('Recorded additions total disagrees')
        basekeys=[k for k in summary if re.fullmatch(r'Original base plan, all \d+ lines',k)]
        if len(basekeys)!=1 or int(re.search(r'\d+',basekeys[0])[0])!=len(base) or cents(summary[basekeys[0]]['text'])!=base_total:raise ValueError('Base count/total disagrees with closeout')
        if base_total+added!=expense_recorded or ceiling-expense_recorded!=unspent_recorded:raise ValueError('Final expense/remaining total disagreement')
        payments,paidref=one(close,r'All remaining base payments were recorded on their scheduled dates\.')
        funding,fundref=one(close,r'making ('+MONEY+r') received in total\.')
        if cents(funding[1])!=ceiling:raise ValueError('Funding receipt and ceiling differ; do not equate available cash')
        result['facts'].update(base_records=base,approved_additions=additions,base_payments_recorded_complete=True,funding_received_cents=cents(funding[1]))
        result['calculations'].update(base_expense_cents=base_total,approved_additions_cents=added,final_expense_cents=base_total+added,unspent_cents=ceiling-(base_total+added),planning_paid_cents=sum(r['paid_at_plan_cents'] for r in base),planning_remaining_expenses_cents=sum(r['remaining_at_plan_cents'] for r in base))
        refs += [ceilref,paidref,fundref]+ackrefs+[r['support'] for r in base+additions]+[v['support'] for v in summary.values()]
        result['support']=refs
        # Positive declared hold facts; unavailable/competing facts do not become semantic verdicts.
        holdpattern=r'The ('+MONEY+r') venue security hold was paid ([A-Z][a-z]+ \d{1,2}) and returned in full on ([A-Z][a-z]+ \d{1,2})\.'
        holdhits=matches(close,holdpattern)
        if len(holdhits)!=1:
            result['unknown'].append('A unique explicit full hold-return/payment record was not established; temporary cash and returned-hold effect are unresolved.')
            result['clarification']='Was the venue security hold returned in full, and on what date?'
            return result
        hm,hr=holdhits[0];hold=cents(hm[1]);paid=date(hm[2],year);returned=date(hm[3],year)
        if paid>returned or returned>s['close_date']:raise ValueError('Hold payment/return dates conflict with closeout')
        holdsummary=summary.get('Security hold returned in full')
        if not holdsummary or holdsummary['text']!=hm[1]+', excluded from expense total':raise ValueError('Hold-return/expense-exclusion declaration conflicts')
        peak,peakref=one(close,r'cash outflow temporarily reached ('+MONEY+r')\.')
        if cents(peak[1])!=expense_recorded+hold:raise ValueError('Recorded gross temporary outflow disagrees')
        result['facts'].update(refundable_hold_cents=hold,hold_paid=paid.isoformat(),hold_returned=returned.isoformat(),hold_return_status='EXPLICITLY_RETURNED_IN_FULL',hold_treatment='EXPLICITLY_EXCLUDED_FROM_EXPENSE_TOTAL')
        result['calculations'].update(gross_temporary_outflow_cents=expense_recorded+hold,peak_funds_remaining_cents=ceiling-(expense_recorded+hold),returned_hold_net_cash_cents=expense_recorded+hold-hold,returned_hold_net_effect_cents=hold-hold)
        result['support'] += [hr,peakref]
        result['status']='USEFUL_SOURCE_BACKED_BUDGET_CLOSEOUT'
    except (ValueError,KeyError) as error:
        result['unknown'].append(str(error))
    return result

def explain(item):
    c=item['calculations'];f=item['facts'];parts=[]
    if 'unspent_cents' in c:
        parts.append('At the recorded '+f['closeout_date']+' closeout, '+usd(c['unspent_cents'])+' remains unspent: '+usd(f['ceiling_cents'])+' funding and ceiling minus '+usd(c['final_expense_cents'])+' final expenses.')
        parts.append('Final expenses comprise '+usd(c['base_expense_cents'])+' from the base expense records plus '+usd(c['approved_additions_cents'])+' approved additions. The earlier '+f['planning_date']+' paid and remaining figures describe the planning snapshot, not final spending.')
    if 'gross_temporary_outflow_cents' in c:
        parts.append('The '+usd(f['refundable_hold_cents'])+' security hold was paid '+f['hold_paid']+' and returned in full '+f['hold_returned']+'. It temporarily raised total cash outflow to '+usd(c['gross_temporary_outflow_cents'])+', leaving '+usd(c['peak_funds_remaining_cents'])+' while outstanding. After its return, net cash used is '+usd(c['returned_hold_net_cash_cents'])+'. The hold has zero lasting cash effect and is excluded from expenses; subtracting its refund again from final expenses would count the return twice.')
    if not parts and 'ceiling_cents' in f:
        parts.append('The selected closeout records state a '+usd(f['ceiling_cents'])+' ceiling and '+usd(f['recorded_final_expense_cents'])+' final expense total, but their full composition is unresolved; no remaining-money calculation is asserted.')
    parts+=['Unresolved: '+x for x in item['unknown']]
    if not parts:parts=['No reliable complete budget composition was established. Known source records remain available.']
    return ' '.join(parts)
