"""Local generic evidence composition; no autonomous prose classification."""
import copy
import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('retained_source_binding', ROOT / 'outputs/m4-typed-source-records-20261011/source_records.py')
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)


def validate_claim(claim, sources):
    basis = claim['basis']
    if basis not in ('source_recorded_text', 'developer_confirmation', 'unresolved'):
        raise ValueError('Unknown claim basis')
    refs = claim['evidence']
    texts = [binding.verify(ref, sources) for ref in refs]
    if basis == 'unresolved':
        if claim['value'] is not None:
            raise ValueError('Unresolved value must remain unknown')
    elif not refs:
        raise ValueError('Declared value requires exact evidence')
    elif basis == 'source_recorded_text':
        if not isinstance(claim['value'], str) or claim['value'] not in texts:
            raise ValueError('Source-recorded value must be an exact quotation')
    elif not claim.get('confirmed_by'):
        raise ValueError('Interpreted field requires disclosed confirming owner')
    if not claim.get('scope'):
        raise ValueError('Claim scope required; no whole-document status inference')


def compose(contract, source_ids):
    """Explicit ID composition, preserving all history/conflicts, never ranking."""
    if contract['schema'] != 'local-source-record/1':
        raise ValueError('Unsupported schema')
    docs = contract['documents']
    if len(source_ids) != len(set(source_ids)):
        raise ValueError('Duplicate requested source')
    if any(key not in docs for key in source_ids):
        raise ValueError('Requested source unavailable')
    sources = {key: doc['full_original_text'] for key, doc in docs.items()}
    for key, doc in docs.items():
        binding.verify(doc['whole_source'], sources)
        if doc['whole_source']['path'] != key or doc['whole_source']['quote'] != sources[key]:
            raise ValueError('Full source binding mismatch')
    records = contract['records']
    ids = [record['id'] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate record identity')
    for record in records:
        binding.verify(record['support'], sources)
        if record['source_id'] != record['support']['path']:
            raise ValueError('Record source identity mismatch')
        if not {'effective_date', 'version', 'status', 'units', 'authority'} <= {c['field'] for c in record['claims']}:
            raise ValueError('Missing required field must be explicitly unresolved')
        for claim in record['claims']:
            validate_claim(claim, sources)
    for relation in contract['relations']:
        if relation['from'] not in ids or relation['to'] not in ids:
            raise ValueError('Relationship target unavailable')
        validate_claim(relation['declaration'], sources)
    selected = [record for record in records if record['source_id'] in source_ids]
    included = {record['id'] for record in selected}
    relations = copy.deepcopy(contract['relations'])
    for relation in relations:
        relation['both_endpoints_included'] = relation['from'] in included and relation['to'] in included
    return {'documents': {key: copy.deepcopy(docs[key]) for key in source_ids},
            'records': copy.deepcopy(selected), 'relations': relations,
            'not_included_source_ids': [key for key in docs if key not in source_ids],
            'meaning_authority_currentness': 'NOT_AUTOMATICALLY_DETERMINED',
            'selection_basis': 'CALLER_SUPPLIED_SOURCE_IDS_NOT_AUTONOMOUS_RETRIEVAL',
            'annotation_cost': copy.deepcopy(contract['annotation_cost']),
            'model_calls': 0}
