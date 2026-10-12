"""Offline saved-attempt replay through unchanged development controllers and view hook.

No generation adapter is imported. Recorded attempt counts remain historical.
"""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRIOR = ROOT / 'outputs/m4-wedding-saved-results-presentation-20261011'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SavedAttempts:
    """Supply exact captured stages, never a live/fake model or new interpretation."""
    def __init__(self, planner, saved):
        self.planner = planner
        self.records = saved['attempts']
        self.position = 0

    def __call__(self, index, stage, bindings, error, seconds):
        if self.position >= len(self.records):
            raise ValueError('No saved attempt; generation fallback forbidden')
        record = self.records[self.position]
        packet = self.planner.PACKETS[index]
        if (record['case_id'], record['stage'], record['correction_error']) != (packet['id'], stage, error):
            raise ValueError('Saved attempt order does not match controller request')
        if record['request_sha256'] != self.planner.request_sha(packet, stage, bindings, error):
            raise ValueError('Saved request does not match unchanged controller/planner')
        if json.loads(record['raw_body'])['model'] != self.planner.SETTINGS['model']['tag']:
            raise ValueError('Saved model identity mismatch')
        self.position += 1
        return copy.deepcopy(record)


class ViewExport:
    """A persist callback bridge: export actual completed controller reports."""
    def __init__(self, adapter, model, notes, origin):
        self.adapter, self.model, self.notes, self.origin = adapter, model, notes, origin
        self.events, self.cards = [], None

    def __call__(self, result):
        self.events.append({'status': result['status'], 'report_count': len(result['reports'])})
        if result['status'] != 'development_screen_complete':
            return  # Partial/intermediate data cannot masquerade as complete output.
        if len(result['reports']) != len(self.notes):
            raise ValueError('Completed report count does not match view annotations')
        self.cards = [self.adapter.adapt(report, self.model, note, self.origin)
                      for report, note in zip(result['reports'], self.notes)]


def replay_model(model, short, adapter, annotations):
    source = HERE / 'controller-source' / short
    planner = load('saved_' + short + '_planner', source / 'planner.py')
    previous = sys.modules.get('planner')
    sys.modules['planner'] = planner
    try:
        controller = load('saved_' + short + '_controller', source / 'controller.py')
    finally:
        if previous is None:
            del sys.modules['planner']
        else:
            sys.modules['planner'] = previous
    captured = ROOT / f'outputs/m4-{short}-wedding-execution-20261011/run-output/controller-receipts/batch.json'
    saved = json.loads(captured.read_text())
    feed = SavedAttempts(planner, saved)
    hook = ViewExport(adapter, model, [q['models'][model] for q in annotations['questions']],
                      f'raw/{short}-wedding-batch.json')
    result = controller.run(feed, hook)
    if feed.position != len(saved['attempts']) or hook.cards is None:
        raise ValueError('Replay incomplete; no presentation exported')
    if result['reports'] != saved['reports'] or result['attempts'] != saved['attempts']:
        raise ValueError('Controller reconstructed output differs from captured reports')
    return hook.cards, {'model': model, 'mode': 'OFFLINE_SAVED_ATTEMPTS_NOT_GENERATION',
                        'saved_attempts_consumed': feed.position, 'new_model_calls': 0,
                        'original_report_count': len(result['reports']),
                        'all_reports_equal_original': True, 'all_attempts_equal_original': True,
                        'persist_events': hook.events, 'view_export_called_by_controller': True,
                        'recorded_source_counts_not_new_calls': result['counts'],
                        'source_batch_sha256': sha(captured),
                        'controller_sha256': sha(source / 'controller.py'),
                        'planner_sha256': sha(source / 'planner.py')}


def main():
    if (HERE / 'INTEGRATION_OUTCOME.json').exists():
        raise SystemExit('Integration outcome already exists; preserve this settled run.')
    bindings = json.loads((HERE / 'PRESERVATION_BINDINGS.json').read_text())
    for name, expected in bindings.items():
        if sha(ROOT / name) != expected:
            raise ValueError('Frozen input changed: ' + name)
    adapter = load('preserved_local_view_adapter', PRIOR / 'adapter.py')
    notes = json.loads((PRIOR / 'annotations.json').read_text())
    outputs, outcomes = {}, []
    for model, short in adapter.MODELS.items():
        outputs[model], outcome = replay_model(model, short, adapter, notes)
        outcomes.append(outcome)
    # Later software improvements remain captured evidence, not controller replay.
    original_data = json.loads((PRIOR / 'view-data.json').read_text())
    data = copy.deepcopy(original_data)
    for index, question in enumerate(data['questions']):
        question['cards'] = [outputs[model][index] for model in adapter.MODELS]
    if data != original_data:
        raise ValueError('Integrated view data differs from preserved presentation')
    raw = HERE / 'raw'; raw.mkdir()
    for f in (PRIOR / 'raw').glob('*.json'):
        (raw / f.name).write_bytes(f.read_bytes())
    (HERE / 'view-data.json').write_text(json.dumps(data, indent=2) + '\n')
    page = adapter.render(data)
    if page != (PRIOR / 'index.html').read_text():
        raise ValueError('Integrated presentation changed; visual reuse cannot be claimed')
    (HERE / 'index.html').write_text(page)
    for name, expected in bindings.items():
        if sha(ROOT / name) != expected:
            raise ValueError('Frozen input changed after integration: ' + name)
    imported = sorted(name for name in sys.modules if any(x in name.lower() for x in ['ollama', 'diagnostic', 'harness.model', 'urllib.request']))
    if imported:
        raise ValueError('Unexpected generation/network import: ' + str(imported))
    outcome = {'controllers': outcomes, 'original_questions': 6, 'original_model_results': 12,
               'later_saved_software_results_preserved': 2, 'model_calls': 0, 'network_calls': 0,
               'controller_replay_not_model_replay': True,
               'whole_view_data_equal_prior': True, 'html_byte_identical': sha(HERE / 'index.html') == sha(PRIOR / 'index.html'),
               'page_sha256': sha(HERE / 'index.html'), 'visual_evidence_reused_from': str(PRIOR),
               'arithmetic_warning_policy': 'Existing six-task computations/refusals retained. Separate one-call arithmetic warning and raw answer remain outside this view, unchanged.',
               'original_inputs_unchanged': len(bindings), 'forbidden_imports_detected': imported,
               'production_or_default_integration': False}
    (HERE / 'INTEGRATION_OUTCOME.json').write_text(json.dumps(outcome, indent=2) + '\n')
    print(json.dumps({'model_calls': 0, 'saved_attempt_records': sum(x['saved_attempts_consumed'] for x in outcomes),
                      'controller_reports': 12, 'page_byte_identical': outcome['html_byte_identical']}))


if __name__ == '__main__':
    main()
