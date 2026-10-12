"""Development-only view hook; preserve answers and attach independent arithmetic checks."""
import copy
import html
import json
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

numeric = load('development_numeric_checker', HERE / 'numeric_checker.py')
base = load('unchanged_saved_view', PROJECT / 'outputs/m4-wedding-saved-results-presentation-20261011/adapter.py')
MODELS = base.MODELS

def checked(value):
    result = copy.deepcopy(value)
    text = result.get('answer')
    segments = text if isinstance(text, list) else [text]
    checks = [numeric.check_answer(segment) for segment in segments]
    result['numeric_check'] = {
        'status': 'NUMERIC_CLAIM_INCONSISTENT' if any(c['status'] == 'NUMERIC_CLAIM_INCONSISTENT' for c in checks)
                  else 'RECOGNIZED_CLAIMS_CONSISTENT' if any(c['claims'] for c in checks) else 'UNRESOLVED',
        'segments': checks, 'answer_repaired': False,
        'meaning_established': False,
    }
    return result

def adapt(report, model, note, origin, later=False):
    # This is the existing ViewExport callback's adapter entry point.
    if 'source_proposal' in report:
        return copy.deepcopy(report)
    if {'raw_response','support','support_status'} <= report.keys():
        return checked(report)
    return checked(base.adapt(report, model, note, origin, later))

def calculation_note(value):
    check = value['numeric_check']
    lines = []
    for segment in check['segments']:
        for claim in segment['claims']:
            expression = ' + '.join(str(n) for n in claim['terms'])
            if claim['status'] == 'NUMERIC_CLAIM_INCONSISTENT':
                lines.append(f'The written sum is {expression} = {claim["computed_total"]}; the answer says {claim["claimed_total"]}.')
            else:
                lines.append(f'The addition agrees: {expression} = {claim["computed_total"]}.')
    if not lines:
        lines.append('No supported addition statement was found to check. This does not establish that the answer is correct.')
    else:
        lines.append('This checks addition only. The relevance, units and governing source of these numbers still need to be established.')
    title = 'Calculation contradiction found' if check['status'] == 'NUMERIC_CLAIM_INCONSISTENT' else 'Calculation check'
    return '<section class="source numeric-check" role="status"><h4>' + html.escape(title) + '</h4>' + ''.join('<p>' + html.escape(t) + '</p>' for t in lines) + '</section>'

def card(value):
    original = base.card(value)
    marker = '<h4>Saved answer</h4>'
    if original.count(marker) != 1:
        raise ValueError('Answer presentation boundary changed')
    return original.replace(marker, calculation_note(value) + marker, 1)

def render(data):
    page = base.render(data)
    for question in data['questions']:
        for value in question['cards'] + question.get('later', []):
            original = base.card(value)
            if original not in page:
                raise ValueError('Expected answer card missing')
            page = page.replace(original, card(value), 1)
    return page.replace("The next actual code boundary is the saved-report adapter used here: it takes an answer, support, calculations, coverage and separately owned review notes. It currently reads captured reports. Connecting that same contract to the existing development controller's output is the next integration boundary; this page does not change the controller or defaults.", 'These saved answers now pass through the existing development display callback. Software checks supported written addition before showing each answer, preserving the original text and source checks. This local replay does not establish which source governs or make a new model answer correct.', 1)

def render_direct(value, model):
    """Render a fresh checked callback result; no repeated check or answer transcription."""
    if 'source_proposal' in value:
        return proposal_card(value['source_proposal'])
    support = ''.join('<blockquote>' + html.escape(s['quote']) + '</blockquote>' for s in value['support'])
    status = ('Copied support matches the supplied source word for word. That does not establish correct interpretation.'
              if value['support_status'] == 'EXACT_ATTRIBUTION_ONLY' else
              'Copied support could not be fully matched word for word to the supplied sources.')
    page = '<article class="model-card"><h3>' + html.escape(model) + '</h3>' + calculation_note(value)
    page += '<h4>Original answer</h4><p>' + html.escape(value['answer']) + '</p><h4>Source check</h4><p>' + status + '</p>' + support + '</article>'
    return page


def proposal_card(value):
    """Show provenance and recorded review separately from an unapproved suggestion."""
    esc=html.escape
    detail=lambda title,text:'<details><summary>'+esc(title)+'</summary><pre>'+esc(text)+'</pre></details>'
    context=value['software_source_context'];resolution=value['resolution']
    page='<article class="model-card" data-source-proposal><h3>'+esc(value['model'])+' — saved response</h3>'
    page+='<p>This displays a retained development response. No new model run or action occurs, and no person’s decision is recorded.</p><h4>Original question</h4><p>'+esc(value['request'])+'</p>'
    if not value['source_current']:
        message='The current source could not be verified against what this response used. The original supplied context below is historical; the suggestion cannot be rechecked against current documents.'
    elif resolution['status']=='REFUSED_UNFINISHED_RESPONSE' and value['raw_model_proposal']=='':
        message=('The model reached its output limit without delivering a final answer. No model answer is available.' if value.get('response_finish_reason')=='length' else
                 'The model did not deliver a final answer. No model answer is available.')
        message+=' The supplied source information remains available for inspection; it is not a model answer.'
    elif resolution['status']=='REFUSED_UNFINISHED_RESPONSE':message='The response did not finish. It is shown as unfinished text, not a complete suggestion.'
    elif value['kind']=='per_issue':message='Each declared issue is accounted for below. A response field or matching source does not prove that the issue was answered correctly or completely.'
    elif resolution['status']=='REFUSED' and resolution.get('source_attribution_verified'):
        message='The response repeated a valid source reference and failed its original format rule. Each referenced passage is shown once for inspection. The failure remains; this does not make the advice correct or usable.'
    elif resolution['status']=='REFUSED':message='The response could not be attached to valid source selections. Keep its original wording separate from a usable recommendation.'
    else:message='The selected passages match the original source exactly. This checks attachment only; it does not establish that every claim is supported or that the suggestion is correct.'
    page+='<p role="status" data-proposal-status>'+esc(message)+'</p><section data-source-context><h4>Information supplied by the software</h4><p>These constraints, unanswered questions and dates were supplied before the model answered. They are not new facts inferred by the model.</p>'
    for key,title in [('established_constraints','Supplied constraints'),('recorded_unknowns','Unanswered questions')]:
        page+='<h5>'+title+'</h5><ul>'+''.join('<li>'+esc(x)+'</li>' for x in context[key])+'</ul>'
    page+='<h5>Dates stated by the sources</h5><ul>'+''.join('<li>'+esc(name)+': '+esc(date)+'</li>' for name,date in context['source_dates'].items())+'</ul><p>'+esc(context['temporal_limit'])+'</p></section>'
    issues=value.get('caller_declared_issues',[])
    if issues:
        provenance=('These explicit divisions were in the original model input; the model was asked for a separate response to each. They were not extracted by the model.' if value.get('issue_declarations_in_original_input') else
                    'They were added after the original run and were not in the original model input. They were not extracted by the model. This saved response was asked for one next step, not a separate answer to each issue.')
        page+='<section data-requested-issues><h4>Separate issues in the request</h4><p>The calling software explicitly supplied these divisions and context references. '+provenance+' Keeping each issue visible does not prove it was answered. The recorded review still concerns the original response and input.</p>'
        for issue in issues:
            page+='<section data-requested-issue><h5>'+esc(issue['request_text'])+'</h5><p>No automatic judgment has established whether the model answered this issue.</p>'
            for key,title in [('established_constraints','Supplied constraints for this issue'),('recorded_unknowns','Unanswered questions for this issue')]:
                page+='<h6>'+title+'</h6><ul>'+''.join('<li>'+esc(x)+'</li>' for x in issue[key])+'</ul>'
            page+='</section>'
        page+='</section>'
    page+='<section data-model-suggestion><h4>Original model suggestion</h4><p>The wording below is preserved, including any generated labels. It is not a registered task or an instruction that has been executed.</p>'
    raw=value['raw_model_proposal']
    if isinstance(raw,dict):
        if value['kind']=='per_issue':
            if resolution.get('schema_conformant') is False:
                page+='<p data-issue-contract-failure>This response failed the required structure or left a declared issue unanswered. Any fields or passages shown below remain available for inspection; this is not a complete usable result.</p>'
            for row in resolution.get('issue_responses',[]):
                item=row['resolution'];page+='<section data-issue-response><h5>'+esc(row['request_text'])+'</h5>'
                page+='<p>'+('A response field is present; its meaning and completeness are unverified.' if row['response_present'] else 'No response was supplied for this issue. It remains unanswered.')+'</p>'
                if item['status']=='UNVERIFIED_SOURCE_BOUND_PROPOSAL':
                    for key,title in [('next_step','Proposed check'),('justification','The model’s explanation')]:page+='<h6>'+title+'</h6><p>'+esc(item['raw_model_proposal'][key])+'</p>'
                else:page+='<p>'+esc(item.get('reason','This issue response remains refused.'))+'</p>'
                for section in item['source_evidence']:page+=detail('Selected original passage — '+section['id']+' — '+section['file_name'],section['quote'])
                page+='</section>'
        elif resolution['status']=='UNVERIFIED_SOURCE_BOUND_PROPOSAL':
            for key,title in [('next_step','Suggested next step'),('justification','The model’s explanation'),('approach','Suggested preparation approach'),('tradeoff','The model’s tradeoff explanation')]:
                if isinstance(raw.get(key),str):page+='<h5>'+title+'</h5><p>'+esc(raw[key])+'</p>'
        else:page+='<p>This refused response is retained for inspection, not presented as a usable step.</p>'
        page+=detail('Inspect the original response structure',json.dumps(raw,ensure_ascii=False,indent=2))
    elif raw=='':page+='<p data-no-final-answer>No final answer was delivered. Nothing has been reconstructed from internal reasoning.</p>'
    else:page+='<pre>'+esc(raw)+'</pre>'
    page+='</section>'
    page+='<section data-recorded-review><h4>Recorded independent review</h4>'
    review=value['review']
    if review:
        page+='<p>'+esc(review['actor'])+' read this original response and its sources. This recorded assessment is separate from the automatic source-attachment check.</p>'
        if not value['review_applies_to_current_context']:page+='<p>The original review is historical; it does not approve the current source context.</p>'
        page+='<p>'+esc(review['summary'])+'</p>'+detail('Read the full recorded review',review.get('original_text',''))
    else:page+='<p>No matching independent review is available for this response and input. A review of a different response is not applied.</p>'
    page+='</section><section data-selected-sources><h4>Passages selected by the model</h4>'
    for section in resolution['source_evidence']:
        page+='<details data-selected-section="'+esc(section['id'])+'"><summary>'+esc(section['id']+' — '+section['file_name'])+'</summary><pre>'+esc(section['quote'])+'</pre></details>'
    if not resolution['source_evidence']:
        if value['kind']=='per_issue' and any(row['resolution']['source_evidence'] for row in resolution.get('issue_responses',[])):
            page+='<p>The selected original passages are shown with each issue response above. This does not establish that every claim is supported.</p>'
        else:page+='<p>No valid selected passages are attached.</p>'
    page+='</section><section data-supplied-sources><h4>All original information supplied to the model</h4><p>This includes passages the model did not select. Showing them here does not add them to its citations.</p>'
    for section in value['all_supplied_sections']:page+=detail(section['id']+' — '+section['file_name'],section['quote'])
    for name,text in value['original_documents'].items():page+=detail('Full original source — '+name,text)
    return page+'</section></article>'

def direct_card(presentation, model):
    value = checked(presentation)
    return value, render_direct(value, model)
