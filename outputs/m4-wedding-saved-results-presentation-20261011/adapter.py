"""Saved-result view adapter: capture fields remain separate from review annotations."""
import hashlib
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODELS = {'Llama': 'llama', 'DeepSeek': 'deepseek'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt(report, model, note, origin, later=False):
    # Reusable boundary: a saved report plus separately owned annotations.
    required = {'question', 'answer', 'copied_support', 'coverage', 'calculations'}
    if not required <= report.keys():
        raise ValueError('Incomplete saved report')
    return {'model': model, 'question': report['question'], 'answer': report['answer'],
            'support': report['copied_support'], 'calculations': report['calculations'],
            'scope': report['scope'], 'coverage': report['coverage'],
            'model_selections': report['model_role_assignments'],
            'model_judgments': report['model_relationship_judgments'],
            'software_bindings': report.get('software_record_bindings'),
            'check_error': report.get('calculation_error'),
            'attribution_recorded': report['attribution_valid'],
            'review_annotation': note, 'origin': origin,
            'phase': 'Later saved software assembly' if later else 'Original six-question result'}


def build_data():
    annotations = json.loads((HERE / 'annotations.json').read_text())
    data = {'questions': [], 'inputs': {}, 'models': list(MODELS)}
    batches = {}
    raw = HERE / 'raw'; raw.mkdir(exist_ok=True)
    for model, short in MODELS.items():
        for phase in ['wedding', 'intent']:
            name = f'outputs/m4-{short}-{phase}-execution-20261011/run-output/controller-receipts/batch.json'
            path = ROOT / name
            data['inputs'][name] = digest(path)
            batches[(model, phase)] = json.loads(path.read_text())
            (raw / f'{short}-{phase}-batch.json').write_bytes(path.read_bytes())
    for index, meta in enumerate(annotations['questions']):
        cards = []
        for model in MODELS:
            report = batches[(model, 'wedding')]['reports'][index]
            cards.append(adapt(report, model, meta['models'][model],
                               f'raw/{MODELS[model]}-wedding-batch.json'))
        if cards[0]['question'] != cards[1]['question']:
            raise ValueError('Models answered different questions')
        later = []
        if index == 5:
            for model in MODELS:
                report = batches[(model, 'intent')]['reports'][1]
                later.append(adapt(report, model, annotations['later_gift'][model],
                                   f'raw/{MODELS[model]}-intent-batch.json', True))
        data['questions'].append({'number': index + 1, 'title': meta['title'],
                                  'question': cards[0]['question'], 'dates': meta['dates'],
                                  'cards': cards, 'later': later})
    return data


def e(value):
    return html.escape(str(value), quote=True)


def paragraph(text, cls=''):
    return f'<p class="{cls}">{e(text)}</p>'


def card(v):
    note = v['review_annotation']
    calc = v['calculations']
    # This is display-only. No new calculations or semantic verdicts occur here.
    checks = '<dl>' + ''.join(f'<dt>{e(k.replace("_", " ").capitalize())}</dt><dd>{e(val)}</dd>' for k, val in calc.items()) + '</dl>' if calc else paragraph(note['checks'])
    quotes = ''
    for s in v['support']:
        source = next((f for f in v['coverage'].get('all_read_source_files', []) if f['relative_path'] == s['file_name']), {})
        title = source.get('full_original_text', '').split('\n', 1)[0].lstrip('# ').strip() or s['file_name'].split('/')[-1].replace('_', ' ')
        quotes += '<section class="source"><h5>' + e(title) + '</h5><blockquote>' + e(s['text']) + '</blockquote></section>'
    coverage = v['coverage']
    coverage_text = 'The models received only the displayed excerpts for this saved answer. Other paragraphs, linked full records and the original spreadsheet were not included. These excerpts cannot establish what is absent from the full repository.'
    return f'''<div class="shell"><article class="model-card" data-model="{e(v['model'])}">
    <div class="card-top"><h3>{e(v['model'])}</h3><span class="status {e(note['tone'])}">{e(note['status'])}</span></div>
    <p class="phase">{e(v['phase'])}</p>
    <h4>Saved answer</h4><div class="answer">{''.join(paragraph(t) for t in v['answer'])}</div>
    <h4>What this result means</h4>{paragraph(note['meaning'])}
    <h4>What remains unknown or incomplete</h4>{paragraph(note['unknown'])}
    <div class="next"><h4>Next step</h4>{paragraph(note['next'])}</div>
    <details><summary>Calculations and record checks</summary><div class="detail-body">
    {checks}{paragraph(note['check_limits'], 'small')}
    {paragraph('Quoted support was checked against the selected original passages in the saved experiment and its review. That establishes copying, not correct interpretation.', 'small')}
    </div></details>
    <details><summary>Dated support and coverage</summary><div class="detail-body">
    {paragraph(note['source_dates'], 'date-note')}{quotes}
    <h5>What was selected and omitted</h5>{paragraph(coverage_text)}
    {paragraph('Spreadsheet-related passages are saved text views of selected records. The software did not read the original workbook.', 'small')}
    </div></details></article></div>'''


def render(data):
    css = (HERE / 'style.css').read_text()
    nav = ''.join(f'<a href="#question-{q["number"]}">{q["number"]}: {e(q["title"])}</a>' for q in data['questions'])
    sections = ''
    for q in data['questions']:
        later = ''
        if q['later']:
            later = '<section class="later"><h3>Later saved software improvement</h3>' + paragraph('A separate two-question experiment joined existing records in software. The original results above remain unchanged. These later answers were already saved; no model ran for this page.') + '<div class="models">' + ''.join(card(c) for c in q['later']) + '</div></section>'
        sections += f'''<section id="question-{q['number']}" class="question">
        <div class="question-heading"><span class="eyebrow">Question {q['number']} of 6</span><h2>{e(q['title'])}</h2>
        {paragraph(q['question'], 'person-question')}{paragraph(q['dates'], 'date-note')}</div>
        <div class="models">{''.join(card(c) for c in q['cards'])}</div>{later}</section>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
    <title>Six wedding questions · Saved local results</title><style>{css}</style></head><body>
    <a class="skip" href="#question-1">Skip to the questions</a><main>
    <header><span class="eyebrow">Local model development</span><h1>Six questions.<br>See what each answer delivers.</h1>
    <p class="intro">Compare Llama and DeepSeek's saved answers, their supporting records, and the work still needed.</p>
    <div class="replay">Development replay of saved results · fictional wedding records · captured October 11, 2026.<br>This page is not a live product. Opening it makes no model call and takes no action.</div></header>
    <nav aria-label="Jump to a question">{nav}</nav>
    <section class="orientation"><h2>How to read this page</h2><p>Each model keeps its own original answer. “What this result means” is a separate review of that saved answer. Expand support to read the dated passages; expand checks to see saved calculations and matching results. A correct quote or calculation does not settle the meaning of an answer.</p></section>
    {sections}<footer><h2>What should improve next?</h2><p>The highest-impact missing capability is dependable assembly of the right dated records before asking the model to interpret them. Wrong record choices prevented several useful answers. A common adapter should carry source dates, exact record relationships, omissions and unresolved meaning through to this view.</p>
    <p>The next actual code boundary is the saved-report adapter used here: it takes an answer, support, calculations, coverage and separately owned review notes. It currently reads captured reports. Connecting that same contract to the existing development controller's output is the next integration boundary; this page does not change the controller or defaults.</p>
    <p>A product decision remains: how much review the person should do when an answer is partial or unsupported. This replay recommends making the useful evidence visible and asking for the smallest missing clarification. It does not infer approval to draft or send a personal note.</p>
    <p class="small">No model winner is established. Whole-repository retrieval, native spreadsheet ingestion and usefulness to an actual person remain untested. M4 remains open; M5 remains paused. This replay changes no acceptance requirements.</p></footer>
    </main></body></html>'''


if __name__ == '__main__':
    data = build_data()
    (HERE / 'view-data.json').write_text(json.dumps(data, indent=2) + '\n')
    (HERE / 'index.html').write_text(render(data))
    (HERE / 'INPUT_BINDINGS.json').write_text(json.dumps(data['inputs'], indent=2) + '\n')
    print('Local data and self-contained page built; no generation or network.')
