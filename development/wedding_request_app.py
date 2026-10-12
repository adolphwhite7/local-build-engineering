"""Bounded request-family nomination and fresh source assembly. No model or cached answers."""
import copy,hashlib,importlib.util,json,re,uuid
from pathlib import Path
import budget_closeout as b, wedding_remaining as w, thank_you, thank_you_discovery as discovery, native_thank_you as native, checked_view
P=Path(__file__).resolve().parent.parent;ROOT=P/'example_workspace';O=P/'outputs/m4-six-task-local-20261011'
FAMILIES={'transport':'Approved late-return bus time and timing constraint','budget':'Unspent budget at the recorded October closeout; refundable hold separately','meals':'Total external guest/couple/vendor meal order; internal staff meals separately','insurance':'Cancellation coverage choice and unconfirmed actual license fee','followup':'Owned remaining work and dated photo/film deliveries','thankyou':'Countertop blender thank-you work item, giver, owner and target'}
CUES={'transport':r'\b(?:bus(?:es)?|shuttles?|late[- ]return|return trip|transport)\b','budget':r'\b(?:budget|unspent|money|funds left|remaining funds|spending|security hold|cash outflow|refundable deposit)\b','meals':r'\b(?:meal(?:s)?|plates?|portions?|caterer|catering|food order)\b','insurance':r'\b(?:insurance|coverage|marriage[- ]license|license fee|government fee)\b','followup':r'\b(?:follow[- ]?up|remaining work|still (?:due|open|needs doing)|unfinished|deliver(?:y|ies)|photo gallery|highlight film|after the celebration)\b','thankyou':r'\b(?:thank[- ]?you|thank you|blender|giver|correspondence)\b'}
ACTION=r'\b(?:what|when|how|who|which|did|does|can|is|are|explain|show|tell|prepare|count|calculate|give|summari[sz]e|identify|find|check)\b'
NEGATION=r"\b(?:not|no|never|except|without|instead|don['’]t|do not|can['’]t|isn['’]t|wasn['’]t)\b"
UNSUPPORTED=r'\b(?:book|send|buy|pay|publish|install|download|delete|change|modify|update|refund me|forecast|recommend|new guests?|vegan only|salmon only|September budget|February budget|real[- ]world|actual traffic|tomorrow|today)\b'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
BRIDGE=module('request_existing_callback',P/'outputs/m4-controller-view-integration-20261011/integrate.py')
TIMELINE=module('request_existing_timeline',P/'outputs/m4-operational-schedule-pair-20261011/timeline.py')
RECORDS=module('request_existing_records',P/'outputs/m4-dated-source-contract-20261011/record_adapter.py')
class App:
 def families(self):return dict(FAMILIES)
 def search_sources(self,request):
  """Inspect existing lexical nominations; never answer or choose a source."""
  from harness.retrieve import read_candidate_passages,nominate_candidates,DEFAULT_MAX_CANDIDATES
  from harness.check import source_preview
  if not isinstance(request,str) or not 1<=len(request.strip())<=2000:return {'status':'INVALID_REQUEST','answer':'Enter a source search of 1–2,000 characters.','model_calls':0}
  try:
   inventory_path=ROOT/'operator/source_inventory.json';raw=inventory_path.read_bytes()
   if hashlib.sha256(raw).hexdigest()!=self.inventory_sha:raise ValueError('Qualified source inventory changed')
   entries=json.loads(raw)['documents'];files={};expected={};sizes=[]
   for d in entries:
    key=d['document_id'];size=d['utf8_bytes']
    if key in files or type(size) is not int or size<=0:raise ValueError('Source identity or recorded byte limit is invalid')
    files[key]={'root':'source','path':d['relative_path']};expected[key]=d['sha256'];sizes.append(size)
   settings={'retrieval':{'roots':{'source':ROOT/'source'},'max_file_bytes':max(sizes),'max_total_bytes':sum(sizes)},'model':{'passage_chars':max(sizes),'max_passages':3}}
   passages=read_candidate_passages(list(files),{'files':files},settings)
   if {p['file_id'] for p in passages}!=set(files) or any(p['file_sha256']!=expected[p['file_id']] for p in passages):raise ValueError('Source content differs from the qualified inventory')
   if sha(inventory_path)!=self.inventory_sha:raise ValueError('Source inventory changed during the search')
   matches=[p for p in nominate_candidates(request,passages,len(passages)) if p['score']>0]
   all_rows=[dict(source_preview('',p,False),file_name=p['file_name'],word_match_score=p['score']) for p in matches];rows=all_rows[:DEFAULT_MAX_CANDIDATES]
   coverage={'searched_files':len(files),'excluded_files':0,'passages_read':len(passages),'word_matched_passages':len(matches),'displayed_passages':len(rows),'not_displayed_due_limit':len(matches)-len(rows),'display_limit':DEFAULT_MAX_CANDIDATES,'page_offset':0,'source_truncated':False}
   token=uuid.uuid4().hex;self.pending[token]={'kind':'source_inspection','request':request,'candidates':copy.deepcopy(rows),'all_candidates':all_rows,'coverage':copy.deepcopy(coverage),'inventory_sha256':self.inventory_sha}
   return self._source_page_result(token)
  except (ValueError,KeyError,TypeError,OSError) as e:return {'status':'SOURCE_UNRESOLVED','request':request,'answer':'Source search could not be completed: '+str(e),'model_calls':0}
 def _source_page_result(self,token):
  context=self.pending[token];coverage=copy.deepcopy(context['coverage']);offset=coverage['page_offset'];limit=coverage['display_limit'];total=coverage['word_matched_passages']
  result={'status':'SOURCE_CANDIDATES','request':context['request'],'inspection_context_id':token,'candidates':copy.deepcopy(context['candidates']),'coverage':coverage,'pagination':{'previous_offset':max(0,offset-limit) if offset else None,'next_offset':offset+limit if offset+limit<total else None},'meaning_checked':False,'model_calls':0,'answer':None,'source_binding':{'inventory_sha256':context['inventory_sha256'],'verified_source_files':coverage['searched_files']},'note':'These are word or filename matches from the original search, not judgments of relevance. Other matches can be browsed on later pages. No word matches does not establish that the information is absent.'}
  self.events.append(copy.deepcopy(result));return result
 def page_sources(self,inspection_context_id,offset):
  """Browse the original lexical snapshot; revalidate the offered page only."""
  token=None
  try:
   context=self.pending.get(inspection_context_id)
   if not context or context.get('kind')!='source_inspection':raise ValueError('The source search context is unavailable; repeat the search')
   parent=context.get('search_context_id',inspection_context_id);original=self.pending.get(parent)
   if not original or 'all_candidates' not in original:raise ValueError('The original source search is unavailable; repeat the search')
   total=len(original['all_candidates'])
   if type(offset) is not int or offset<0 or (offset>=total if total else offset!=0):raise ValueError('Choose an available source page')
   limit=original['coverage']['display_limit'];rows=copy.deepcopy(original['all_candidates'][offset:offset+limit]);coverage=dict(original['coverage'],page_offset=offset,displayed_passages=len(rows),not_displayed_due_limit=total-len(rows))
   token=uuid.uuid4().hex;self.pending[token]={'kind':'source_inspection','request':original['request'],'search_context_id':parent,'candidates':rows,'coverage':coverage,'inventory_sha256':original['inventory_sha256']}
   # Existing checker owns current inventory/file/paragraph/span verification.
   for row in rows:self._inspected_passage(token,row['passage_id'])
   if sha(ROOT/'operator/source_inventory.json')!=original['inventory_sha256']:raise ValueError('The inspected inventory changed')
   return self._source_page_result(token)
  except (ValueError,KeyError,TypeError,OSError) as e:
   if token:self.pending.pop(token,None)
   return {'status':'SOURCE_UNRESOLVED','answer':'Source page could not be displayed: '+str(e),'model_calls':0}
 def _inspected_passage(self,context_id,passage_id):
  from harness.retrieve import read_candidate_passages
  from harness.check import source_preview
  context=self.pending.get(context_id)
  if not context or context.get('kind')!='source_inspection':raise ValueError('The source inspection context is unavailable')
  rows=[r for r in context['candidates'] if r['passage_id']==passage_id]
  if len(rows)!=1:raise ValueError('Choose one paragraph from this source inspection')
  row=rows[0];raw=(ROOT/'operator/source_inventory.json').read_bytes()
  if hashlib.sha256(raw).hexdigest()!=context['inventory_sha256']:raise ValueError('The inspected inventory changed')
  entries=[d for d in json.loads(raw)['documents'] if d['document_id']==row['file_id']]
  if len(entries)!=1:raise ValueError('The inspected file identity changed')
  d=entries[0];size=d['utf8_bytes'];manifest={'files':{d['document_id']:{'root':'source','path':d['relative_path']}}};settings={'retrieval':{'roots':{'source':ROOT/'source'},'max_file_bytes':size,'max_total_bytes':size},'model':{'passage_chars':size,'max_passages':3}}
  matches=[p for p in read_candidate_passages([d['document_id']],manifest,settings) if p['passage_id']==passage_id]
  if len(matches)!=1:raise ValueError('The inspected paragraph changed')
  p=matches[0]
  if p['file_sha256']!=row['file_sha256'] or p['file_sha256']!=d['sha256'] or source_preview('',p,False)['paragraph']!=row['paragraph'] or p['piece_span']!=row['piece_span']:raise ValueError('The inspected source snapshot changed')
  if sha(ROOT/'operator/source_inventory.json')!=context['inventory_sha256']:raise ValueError('Inventory changed during the source check')
  return context,p
 def prepare_source_meaning(self,inspection_context_id,passage_id,question):
  from harness.tasks import _candidate_sentences,_meaning_prompt,MEANING_SCHEMA
  if not isinstance(question,str) or not 1<=len(question.strip())<=2000:raise ValueError('Enter one question of 1–2,000 characters about this paragraph')
  context,p=self._inspected_passage(inspection_context_id,passage_id);sentences=_candidate_sentences(p)
  binding={'question':question,'search_request':context['request'],'inventory_sha256':context['inventory_sha256'],'file_id':p['file_id'],'file_sha256':p['file_sha256'],'passage_id':passage_id,'paragraph_sha256':hashlib.sha256(p['original_paragraph'].encode()).hexdigest(),'piece_span':p['piece_span'],'coverage':copy.deepcopy(context['coverage'])}
  return {'request':question,'inspection_context_id':inspection_context_id,'passage_id':passage_id,'candidate':p,'source_snapshot':copy.deepcopy(next(r for r in context['candidates'] if r['passage_id']==passage_id)),'search_request':context['request'],'coverage':copy.deepcopy(context['coverage']),'inventory_sha256':context['inventory_sha256'],'inspection_binding':binding,'sentence_options':sentences,'messages':[{'role':'user','content':_meaning_prompt(question,p)}],'format_schema':MEANING_SCHEMA(sentences),'model_calls':0}
 def request_source_meaning(self,inspection_context_id,passage_id,question,caller):
  from harness.check import check_meaning_selection,source_preview
  result={'status':'MEANING_REFUSED','question':question,'model_attempted':False,'meaning_verified':False,'person_decision':None,'action_executed':False}
  try:
   prepared=self.prepare_source_meaning(inspection_context_id,passage_id,question);result.update(source_snapshot=prepared['source_snapshot'],search_request=prepared['search_request'],coverage=prepared['coverage'])
   reason=caller.availability(prepared)
   if reason:return dict(result,status='MEANING_UNAVAILABLE',answer='The configured model connection cannot accept this source question. The question remains unresolved.',availability_reason=reason)
   if self.prepare_source_meaning(inspection_context_id,passage_id,question)!=prepared:raise ValueError('Question or source snapshot changed before the call')
   result['model_attempted']=True
   def revalidate_before_execute():
    if self.prepare_source_meaning(inspection_context_id,passage_id,question)!=prepared:raise ValueError('Question or source snapshot changed during runtime preparation')
   try:
    if hasattr(caller,'meaning_response_checked'):response=caller.meaning_response_checked(prepared,revalidate_before_execute)
    else:response=caller.meaning_response(prepared)
   except Exception:return dict(result,model_attempted=getattr(caller,'model_attempted',True),answer='The controlled request could not be completed or its outcome is unavailable. No retry was made; the question remains unresolved.')
   result.update(raw_response=response['raw_response'],response_actor=response.get('actor','qualified_local_model'),done=response.get('done'),done_reason=response.get('done_reason'),call_bindings={k:response.get(k) for k in ('request_binding','admission_binding','qualified_contract_binding')})
   if self.prepare_source_meaning(inspection_context_id,passage_id,question)!=prepared:raise ValueError('Source snapshot changed before response intake')
   if response.get('done') is not True or response.get('done_reason')!='stop':return dict(result,status='MEANING_INCOMPLETE',answer='The response did not finish. No meaning judgment or supporting sentence is accepted.')
   try:raw=json.loads(response['raw_response']) if isinstance(response['raw_response'],str) else response['raw_response']
   except ValueError:return dict(result,answer='The original response is not valid structured output; it remains unaccepted.')
   checked=check_meaning_selection(raw,prepared['candidate'],prepared['sentence_options']);result['structure_and_source_check']=checked
   if not checked['valid']:return dict(result,answer='The proposed judgment or source selection is invalid: '+checked['reason'])
   result.update(status='MEANING_PROPOSAL',judgment=checked['judgment'],selected_sentence=checked['sentence'],source_preview=source_preview(checked['sentence'],prepared['candidate'],True),answer='This is a proposed model judgment and original source sentence, not verified meaning or a factual answer.');self.events.append(copy.deepcopy(result));return result
  except (ValueError,KeyError,TypeError,OSError) as e:return dict(result,answer='The source-meaning check remains unresolved: '+str(e))
 def prepare_model_nomination(self,request):
  from intent_nomination import prepare
  return prepare(self,request)
 def complete_model_nomination(self,prepared,response):
  from intent_nomination import complete
  return complete(self,prepared,response)
 def show_source_proposal(self,source,prepared,actual,model,kind,review=None,documents=None,requested_issues=None):
  """Present a retained judgment through the existing callback; never run or approve it."""
  import source_proposal as proposal
  raw=copy.deepcopy(actual['raw_model_proposal'])
  context={k:copy.deepcopy(prepared[k]) for k in ('established_constraints','recorded_unknowns','source_dates','temporal_limit')}
  if kind=='per_issue':requested_issues=prepared['requested_issues']
  issues=proposal.declared_issue_context(source['question'],context,[] if requested_issues is None else requested_issues)
  current=False;source_error=None
  try:
   docs=documents if documents is not None else {d['path']:d['text'] for d in self.verify()}
   if prepared['question']!=source['question'] or [x['text'] for x in prepared['sections']]!=[x['quote'] for x in source['evidence']]:raise ValueError('Supplied question or sections changed')
   for section in source['evidence']:
    a,z=section['original_file_span']
    proposal._binding.verify({'path':section['file_name'],'sha256':section['file_sha256'],'start':a,'end':z,'quote':section['quote']},docs)
   current=True
  except (ValueError,KeyError,TypeError) as error:source_error=str(error)
  if not current:resolved={'status':'REFUSED_SOURCE_CONTEXT_CHANGED','source_evidence':[],'meaning_verified':False,'person_decision':None}
  elif actual.get('done') is not True or actual.get('done_reason')!='stop':resolved={'status':'REFUSED_UNFINISHED_RESPONSE','source_evidence':[],'meaning_verified':False,'person_decision':None}
  elif kind=='next_step':resolved=proposal.assess_next_step(raw,source['evidence'],docs,context)
  elif kind=='approach':resolved=proposal.assess_proposal(raw,source['evidence'],docs)
  elif kind=='per_issue':resolved=proposal.assess_issues(raw,source['evidence'],docs,context,requested_issues,source['question'])
  else:raise ValueError('Unknown retained proposal contract')
  hashjson=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  review_matches=bool(review and review['response_binding']==hashjson(raw) and review['request_binding']==hashjson(prepared) and review['source_binding']==hashjson(source))
  value={'request':source['question'],'model':model,'kind':kind,'raw_model_proposal':raw,'resolution':resolved,'software_source_context':context,'source_current':current,'source_error':source_error,'all_supplied_sections':copy.deepcopy(source['evidence']),'original_documents':copy.deepcopy(source['documents']),'review':copy.deepcopy(review) if review_matches else None,'review_applies_to_current_context':review_matches and current,'meaning_verified':False,'person_decision':None,'action_executed':False,'retained_response':True,'new_model_calls':0}
  value['caller_declared_issues']=issues
  if kind=='per_issue':value['issue_declarations_in_original_input']=True
  if resolved['status']=='REFUSED_UNFINISHED_RESPONSE':value['response_finish_reason']=actual.get('done_reason')
  hook=BRIDGE.ViewExport(checked_view,model,[{}],'Retained source proposal; no model execution')
  hook({'status':'development_screen_complete','reports':[{'source_proposal':value}]})
  out={'status':'SAVED_SOURCE_PROPOSAL_VIEW','callback':hook.cards[0],'callbacks':hook.events,'html':checked_view.render_direct(hook.cards[0],model),'model_calls':0,'retained_response':True}
  self.events.append(copy.deepcopy(out));return out
 def __init__(self):
  self.pending={};self.events=[];self.inventory_sha=sha(ROOT/'operator/source_inventory.json');self.native_snapshot_path=P/'outputs/m4-thank-you-discovery-native-20261011/NATIVE_READ.json';self.native_sha=sha(self.native_snapshot_path)
  self.native=json.loads(self.native_snapshot_path.read_text());self.workbook=Path(self.native['path']);self.workbook_sha=self.native['sha256']
  self.couple=json.loads((O/'history-before-text-entry/FLOW_RECEIPT.json').read_text())['native_couple_meal_cells_read']
  # Freeze established source inventory + native evidence binding, not answer values.
  self.expected_inventory='6fd20b0d1b252e0ae6879c4cdc0e81b97de738165d5ae77fa065200ecb195350'
  if self.inventory_sha!=self.expected_inventory:raise ValueError('Qualified source inventory changed')
  qualified=json.loads((P/'outputs/m4-thank-you-discovery-native-20261011/REVIEW_BINDING.json').read_text())
  if qualified.get(str(self.native_snapshot_path))!=self.native_sha:raise ValueError('Qualified native snapshot changed')
  old_binding=json.loads((O/'history-before-text-entry/REVIEW_BINDING.json').read_text())
  if old_binding.get(str(O/'FLOW_RECEIPT.json'))!=sha(O/'history-before-text-entry/FLOW_RECEIPT.json'):raise ValueError('Qualified couple-cell capture changed')
  close=[]
  for d in self.verify():
   if any(t['headers']==['Measure','Amount'] for t in b.tables(d)):
    m,_=b.one(d,r'Fictional post-event working record\. Document (\w+)\. Written by ([^.]+) on ([A-Z][a-z]+ \d{1,2}), (\d{4})\.');close.append((m[3].split()[0].casefold(),m[4]))
  if len(close)!=1:raise ValueError('Recorded closeout period missing or competing')
  self.closeout_month,self.closeout_year=close[0]
 def verify(self):
  if sha(ROOT/'operator/source_inventory.json')!=self.inventory_sha or sha(self.workbook)!=self.workbook_sha or sha(self.native_snapshot_path)!=self.native_sha:raise ValueError('Source/native qualification changed; keep previous results separate')
  return b.inventory_read(ROOT/'operator/source_inventory.json',ROOT/'source')
 def clarify(self,request,reason,candidates=None):
  token=uuid.uuid4().hex;self.pending[token]={'request':request,'options':list(FAMILIES)}
  if len(self.pending)>128:self.pending.pop(next(iter(self.pending)))
  return {'status':'CLARIFICATION','request':request,'context_id':token,'reason':reason,'question':'Which one of these supported tasks should I do for your original request? Choose one; the selected scope is shown in full.','options':[{'value':k,'label':v} for k,v in FAMILIES.items()],'nominated_families':candidates or [],'model_calls':0,'assembled':False}
 def clarify_gift(self,request):
  # Label words nominate records only; the person must confirm a supported match.
  self.verify()
  entities=[{'id':native.value(x['Gift ID']),'label':native.value(x['Gift'])} for x in self.native['tables']['Gifts']]
  explicit=set(re.findall(r'\bF\d+\b',request))
  query=set(discovery.normalized(request).split())-{'gift','item','thank','you','work','prepare','the','a','for','and','who','what','is'}
  matches=[x for x in entities if (x['id'] in explicit if explicit else query & set(discovery.normalized(x['label']).split()))]
  supported=[x for x in matches if discovery.normalized(x['label'])=='countertop blender']
  if explicit and (len(matches)!=1 or explicit!={matches[0]['id']}):supported=[]
  options=[];token=None
  if len(supported)==1:
   gift=supported[0];found=discovery.source_discovery(gift['id'],ROOT/'operator/source_inventory.json',ROOT/'source')
   if not found['packet'] or found['candidates']!=[gift]:raise ValueError('Gift nomination source/native identity disagrees')
   token=uuid.uuid4().hex;self.pending[token]={'request':request,'options':['thankyou'],'gift':gift}
   options=[{'value':'thankyou','label':gift['label']+' — '+gift['id']}]
  return {'status':'CLARIFICATION','clarification_kind':'gift','request':request,'context_id':token,'reason':'The gift reference needs confirmation; matching words do not establish which gift you mean.','question':('Is this the recorded gift you mean? Only this gift has a supported thank-you workflow here.' if options else 'No supported gift matches this reference, or the supplied gift IDs conflict. Enter one recorded gift name or ID; this workflow currently supports the countertop blender.'),'options':options,'nominated_families':['thankyou'],'model_calls':0,'assembled':False}
 def route(self,request):
  text=request.casefold().strip();found=[k for k,pattern in CUES.items() if re.search(pattern,text)]
  # Compound original meal request mentions vendors; only delivery vocabulary nominates followup.
  if re.search(NEGATION,text):return None,'The wording includes a negative or exclusion; I will not guess which task you intended.',found
  if re.search(UNSUPPORTED,text):return None,'That wording includes an action or scope this read-only workroom does not support. You can choose a supported information task instead.',found
  if len(found)!=1:return None,'Several task families match, or none does. I need one specific supported task.',found
  if not re.search(ACTION,text):return None,'The topic is recognizable, but the work you want is unspecified.',found
  k=found[0]
  outside={'transport':r'\b(?:cost|price|fare|fee|capacity|seats?|how many buses|driver|phone|address)\b',
   'budget':r'\b(?:unpaid|owed|owing|who (?:paid|contributed)|per[- ]guest|estimate|refund to|tax rate)\b',
   'meals':r'\b(?:cost|price|ingredients?|recipes?|safety|donation|leftovers?)\b',
   'insurance':r'\b(?:provider|insurer|premium|cost|price|claim|exclusions?|policy terms)\b',
   'followup':r'\b(?:testimonial|review wording|write|draft|contract terms)\b',
   'thankyou':r'\b(?:write|compose|wording|return window|price|value|cost)\b'}
  if re.search(outside[k],text):return None,'The topic matches, but that requested detail/action is outside this existing task. Choose its precise supported scope or another listed task.',found
  if k=='transport' and not re.search(r'\b(?:late|early|earlier|return|approved|timing|turnaround|departure|depart|time|trip)\b',text):return None,'This handler supports the approved late-return time and timing constraint. The requested transport detail is unspecified.',found
  if k=='budget' and (any(month.casefold() in text and month.casefold()!=self.closeout_month for month in b.MONTHS) or 'before' in text or any(year!=self.closeout_year for year in re.findall(r'\b20\d{2}\b',text))):return None,'This handler supports the recorded closeout balance. A different date or earlier planning balance needs a separately supported scope.',found
  if k=='meals' and re.search(r'\b(?:vegan|vegetarian|gluten|allerg\w*|ingredients?|recipes?)\b',text):return None,'This handler supports the total external order, not a dietary subset or ingredient judgment.',found
  if k=='meals' and not re.search(r'\b(?:how many|total|count|number|portions|order)\b',text):return None,'This handler supports the total external meal order, not a new dietary or menu judgment.',found
  if k=='budget' and not re.search(r'\b(?:left|remain\w*|unspent|closeout|after|hold|outflow|deposit)\b',text):return None,'Specify the recorded closeout balance/hold task rather than general budgeting.',found
  if k=='thankyou':
   gifts=discovery.entity_candidates(request,[{'id':native.value(x['Gift ID']),'label':native.value(x['Gift'])} for x in self.native['tables']['Gifts']])
   if len(gifts)!=1:return None,'GIFT_REFERENCE',found
   if set(re.findall(r'\bF\d+\b',request))-{gifts[0][0]}:return None,'GIFT_REFERENCE',found
   if discovery.normalized(gifts[0][1])!=discovery.normalized('countertop blender'):return None,'GIFT_REFERENCE',found
  return k,None,found
 def submit(self,request=None,context_id=None,choice=None):
  if context_id is not None:
   context=self.pending.get(context_id)
   if not context or choice not in context.get('options',[]):return {'status':'INVALID_REPLY','answer':'That reply does not match an open clarification. Submit a new request or choose one of the offered options.','assembled':False,'model_calls':0}
   request=context['request'];family=choice;resolution={'context_id':context_id,'original_request':request,'chosen_scope':FAMILIES[family]}
   if 'gift' in context:resolution['selected_record']=copy.deepcopy(context['gift'])
  else:
   if not isinstance(request,str) or not 1<=len(request.strip())<=2000:return {'status':'INVALID_REQUEST','answer':'Enter one request of 1–2,000 characters.','assembled':False,'model_calls':0}
   for old in [key for key,value in self.pending.items() if 'gift' in value]:self.pending.pop(old)
   family,reason,found=self.route(request)
   if reason=='GIFT_REFERENCE':
    try:return self.clarify_gift(request)
    except (ValueError,KeyError,TypeError) as e:return {'status':'SOURCE_UNRESOLVED','request':request,'answer':'Gift records could not be verified: '+str(e),'assembled':False,'model_calls':0}
   if reason:return self.clarify(request,reason,found)
   resolution=None
  try:
   docs=self.verify();result=self.assemble(family,request,docs,selected_scope=resolution is not None,selected_gift=resolution.get('selected_record') if resolution else None);self.verify()
   report={'answer':result['answer'],'raw_response':result['answer'],'support':[{'quote':r['quote']} for r in result['support']],'support_status':'EXACT_ATTRIBUTION_ONLY','work_item':result}
   hook=BRIDGE.ViewExport(checked_view,'Software',[{}],'Request family nomination / verified current source assembly');hook({'status':'development_screen_complete','reports':[report]});assert hook.cards[0]['work_item']==result
   out={'status':'RESULT','request':request,'family':family,'scope':FAMILIES[family],'resolution':resolution,'result':result,'callback':hook.cards[0],'callbacks':hook.events,'execution_id':uuid.uuid4().hex,'assembled':True,'model_calls':0,'source_binding':{'inventory_sha256':self.inventory_sha,'workbook_sha256':self.workbook_sha,'verified_source_files':len(docs)},'cached_answer_used':False}
   if context_id:self.pending.pop(context_id)
   self.events.append(copy.deepcopy(out));return out
  except (ValueError,KeyError,TypeError) as e:return {'status':'SOURCE_UNRESOLVED','request':request,'answer':'The source-backed task could not be completed: '+str(e),'assembled':False,'model_calls':0}
 def assemble(self,family,request,docs,selected_scope=False,selected_gift=None):
  # Thin typed-family adapters satisfy retained handlers' input grammar; not exact-question/case matching.
  if family=='budget':
   months=[]
   for d in docs:
    if any(t['headers']==['Measure','Amount'] for t in b.tables(d)):
     m,_=b.one(d,r'Fictional post-event working record\. Document (\w+)\. Written by ([^.]+) on ([A-Z][a-z]+ \d{1,2}), (\d{4})\.');months.append(m[3].split()[0])
   if len(months)!=1:raise ValueError('Closeout month missing or competing')
   normalized='At the '+months[0]+' closeout. User request: '+request;r=b.assemble(normalized,docs)
   if not r.get('calculations'):raise ValueError('Budget source fields unresolved')
   r['request']=request;r['handler_input_normalization']=normalized;r['answer']=b.explain(r);r['next_action']='Decide the use of unspent funds together. This creates no payment or purchase.';return r
  if family in ['meals','insurance','followup']:
   normal={'meals':'externally ordered meal portions','insurance':'cancellation insurance and fee','followup':'celebration is finished; vendor deliveries'}[family]+'\nUser request: '+request
   n=copy.deepcopy(self.native);n['couple_meals']=self.couple
   r=w.meals(normal,docs,n) if family=='meals' else (w.insurance(normal,docs,original_request=request) if family=='insurance' else w.followup(normal,docs))
   for conflict in r.get('preparation_name_conflicts',[]):
    contract=conflict.pop('contract');conflict['composition']=RECORDS.compose(contract,list(contract['documents']))
   r['request']=request;r['handler_input_normalization']=normal;return r
  if family=='transport':return transport(request,docs)
  if family=='thankyou':
   # Clarification selects the existing gift; direct entry names its label or exact ID.
   normalized=('Selected gift: '+selected_gift['id']) if selected_gift else (('Selected supported scope: '+FAMILIES['thankyou']) if selected_scope else request)
   found=discovery.source_discovery(normalized,ROOT/'operator/source_inventory.json',ROOT/'source')
   if not found['packet']:raise ValueError('Gift source discovery unresolved')
   result=native.joined(normalized,self.native);prose=thank_you.assemble(found['packet'])
   for key in ['gift','gift_id','credited_giver','correspondence_id','group_id','owner_id','status_record','received','recorded_target','draft_date','approval_date','sent_date']:
    if prose['fields'].get(key)!=result['fields'].get(key):raise ValueError('Native/derived gift fields disagree')
   r=copy.deepcopy(result);r['request']=request;r['handler_input_normalization']=normalized;r['date_calculation']['receipt_plus_days']=r['date_calculation']['computed_due'];r['support']=[{'file_name':x['file_name'],'file_sha256':x['file_sha256'],'original_file_span':x['original_file_span'],'quote':x['text']} for x in found['packet']['blocks']];r['answer']=thank_you.presentation(r,found['packet']['blocks'])['answer'];r['next_action']=r['fields']['recorded_next_action'];r['personal_context_page']='../m4-local-personal-reply-20261011/index.html';return r
  raise ValueError('Unsupported family')

def transport(request,docs):
 candidates=[]
 for d in docs:
  for t in b.tables(d):
   if t['headers']==['Ride','Bus A IDs','Bus B IDs','Total']:candidates.append((d,t))
 if len(candidates)!=1:raise ValueError('Driver packet missing or competing')
 d,t=candidates[0];m,ref=b.one(d,r'On (\d{4}-\d\d-\d\d), the couple approved the current (\d\d:\d\d) late departure, superseding (\d\d:\d\d)\.')
 gap,gr=b.one(d,r'This is (\d+) \+ (\d+) \+ (\d+) \+ (\d+) = (\d+) minutes\.')
 early,er=b.one(d,r'The same two buses take the early (\d+) riders at (\d\d:\d\d), reach HOT\d+ at a planned (\d\d:\d\d)')
 ranges=[int(gap[i]) for i in [1,2,3,4]];facts={'start':early[2],'scope':'same_evening_no_unprovided_delays','steps':[{'label':label,'duration':v,'unit':'minutes',**({'checkpoint':'second_group_departure'} if i==3 else {})} for i,(label,v) in enumerate(zip(['First group travels to hotel','First group unloads','Same buses return to venue','Late group boards'],ranges))]}
 # Final one-way duration is explicitly the working travel allowance in the original packet.
 travel,tr=b.one(d,r'The working (\d+)-minute one-way allowance gives (\d+) minutes of driving')
 facts['steps'].append({'label':'Late group travels to hotel','duration':int(travel[1]),'unit':'minutes','checkpoint':'second_group_arrival'});calc=TIMELINE.calculate(facts)
 cp={s['checkpoint']:s['ends'] for s in calc['steps'] if s['checkpoint']}
 if sum(ranges)!=int(gap[5]) or cp['second_group_departure']!=m[2]:raise ValueError('Declared approved time and calculated sequence disagree')
 approved=[]
 for a in docs:
  for am,ar in b.matches(a,r'On October 8, Morgan and Jordan approved a (\d\d:\d\d) late departure\.[^\n]+'):
   if am[1]==m[2]:approved.append(ar)
 if len(approved)!=1:raise ValueError('Named owner approval missing or competing')
 return {'request':request,'facts':facts,'calculation':calc,'support':[ref,gr,er,tr,*approved,*[x['support'] for x in t['rows']]],'unknown':['Actual route, traffic, vehicle/driver and loading details remain unverified. These are fictional planning allowances.'],'answer':f"Use the approved {m[2]} late departure, not the superseded {m[3]} proposal. The same buses need {sum(ranges)} minutes from the {early[2]} early departure through late boarding. Software computes hotel arrival at {cp['second_group_arrival']} on the stated one-way allowance.",'next_action':'Use the recorded revised driver plan; verify actual route and vehicle details before real use. No bus is booked or dispatched.'}
