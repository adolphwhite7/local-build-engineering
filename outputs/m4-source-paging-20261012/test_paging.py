"""Affected source paging checks; example files, no target or model access."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(P),str(P/'development')]
import wedding_request_app as module
from harness.retrieve import nominate_candidates
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
class Paging(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'operator').mkdir();(self.root/'source').mkdir()
  self.source=self.root/'source/notes.md';self.source.write_text('\n\n'.join(f'Programme record {i:02}: spare paper copies are beside desk {i:02}.' for i in range(13)))
  self.inventory=self.root/'operator/source_inventory.json'
  self.inventory.write_text(json.dumps({'documents':[{'document_id':'fixture','relative_path':'notes.md','utf8_bytes':self.source.stat().st_size,'sha256':sha(self.source)}]}))
  self.app=module.App.__new__(module.App);self.app.pending={};self.app.events=[];self.app.inventory_sha=sha(self.inventory)
  self.root_patch=patch.object(module,'ROOT',self.root);self.root_patch.start()
 def tearDown(self):self.root_patch.stop();self.tmp.cleanup()
 def search(self):return self.app.search_sources('programme')
 def test_all_pages_preserve_original_order_and_old_question_binding(self):
  with patch('harness.retrieve.nominate_candidates',wraps=nominate_candidates) as rank:
   first=self.search();context=first['inspection_context_id'];original=copy.deepcopy(self.app.pending[context]['all_candidates'])
   before=self.app.prepare_source_meaning(context,first['candidates'][0]['passage_id'],'Where are the copies?')
   second=self.app.page_sources(context,5);last=self.app.page_sources(second['inspection_context_id'],10);back=self.app.page_sources(last['inspection_context_id'],5)
   self.assertEqual(first['candidates']+second['candidates']+last['candidates'],original)
   self.assertEqual(len({r['passage_id'] for r in original}),13)
   self.assertEqual([len(x['candidates']) for x in [first,second,last]],[5,5,3]);self.assertEqual(back['candidates'],second['candidates'])
   self.assertEqual(rank.call_count,1)
   for result,offset,omitted in [(first,0,8),(second,5,8),(last,10,10)]:
    self.assertEqual(result['model_calls'],0);self.assertEqual(result['coverage']['page_offset'],offset);self.assertEqual(result['coverage']['not_displayed_due_limit'],omitted);self.assertFalse(result['coverage']['source_truncated']);self.assertFalse(result['meaning_checked'])
   self.assertEqual(last['pagination'],{'previous_offset':5,'next_offset':None})
   after=self.app.prepare_source_meaning(context,first['candidates'][0]['passage_id'],'Where are the copies?');self.assertEqual(before,after)
   later=self.app.prepare_source_meaning(second['inspection_context_id'],second['candidates'][0]['passage_id'],'Where are the copies?');self.assertEqual(later['coverage']['page_offset'],5)
   with self.assertRaisesRegex(ValueError,'Choose one paragraph'):self.app.prepare_source_meaning(context,second['candidates'][0]['passage_id'],'Where?')
 def test_bad_context_and_offsets_refuse_without_retained_provisional_context(self):
  first=self.search();context=first['inspection_context_id'];count=len(self.app.pending)
  for offset in [-1,13,True,'5',None]:self.assertEqual(self.app.page_sources(context,offset)['status'],'SOURCE_UNRESOLVED')
  self.assertEqual(self.app.page_sources('missing',5)['status'],'SOURCE_UNRESOLVED');self.assertEqual(len(self.app.pending),count)
 def test_inventory_drift_refuses_page(self):
  first=self.search();self.inventory.write_text(self.inventory.read_text()+' ');self.assertEqual(self.app.page_sources(first['inspection_context_id'],5)['status'],'SOURCE_UNRESOLVED');self.assertEqual(len(self.app.pending),1)
 def test_file_drift_refuses_page(self):
  first=self.search();self.source.write_text(self.source.read_text().replace('desk','door'));self.assertEqual(self.app.page_sources(first['inspection_context_id'],5)['status'],'SOURCE_UNRESOLVED');self.assertEqual(len(self.app.pending),1)
 def test_cached_paragraph_and_span_drift_refuse_page(self):
  for field,value in [('paragraph','invented text'),('piece_span',[0,1])]:
   first=self.search();context=first['inspection_context_id'];self.app.pending[context]['all_candidates'][5][field]=value
   before=len(self.app.pending);self.assertEqual(self.app.page_sources(context,5)['status'],'SOURCE_UNRESOLVED');self.assertEqual(len(self.app.pending),before)
 def test_no_matches_has_no_absence_claim_and_no_next_page(self):
  first=self.app.search_sources('absentuniquezz');self.assertEqual(first['candidates'],[]);self.assertEqual(first['pagination'],{'previous_offset':None,'next_offset':None});self.assertIn('does not establish',first['note'])
  self.assertEqual(self.app.page_sources(first['inspection_context_id'],0)['status'],'SOURCE_CANDIDATES')
  self.inventory.write_text(self.inventory.read_text()+' ');self.assertEqual(self.app.page_sources(first['inspection_context_id'],0)['status'],'SOURCE_UNRESOLVED')
if __name__=='__main__':
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(Paging);result=unittest.TextTestRunner(verbosity=2).run(suite)
 (Path(__file__).parent/'FOCUSED_CHECKS.json').write_text(json.dumps({'status':'PASS' if result.wasSuccessful() else 'FAIL','groups':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'example_files_only':True,'actual_model_calls':0,'target_operations':0},indent=2)+'\n')
 sys.exit(not result.wasSuccessful())
