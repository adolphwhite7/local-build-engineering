# Architecture walkthrough

## 1. Retrieve a bounded, identified source

[harness/retrieve.py](harness/retrieve.py) resolves root-relative file entries through configured roots. It validates file types, bounds reads by byte limits and decodes UTF-8 after those checks. It then splits documents into passages with original text and identity information.

Lexical scoring nominates passages to inspect. A high word-match score is not treated as a meaning judgment or proof that a passage answers the question.

## 2. Inspect and page without silently changing the evidence

The source-search methods in [development/wedding_request_app.py](development/wedding_request_app.py) construct an inspection context from the checked inventory. The context retains all original matches, the visible page, the search request and coverage counts.

`page_sources` selects a slice from that existing ordering. Before returning it, `_inspected_passage` checks the inventory, current file digest, paragraph text and span. Earlier page contexts remain available for the questions already bound to them. Failed checks return a visible unresolved state.

The [paging check](outputs/m4-source-paging-20261012/test_paging.py) creates thirteen synthetic paragraphs and verifies a five/five/three page sequence, backward navigation, source changes and invalid requests. Its test fixture constructs only the source-inspection part of the application; it does not pretend to boot the complete private workroom.

## 3. Prepare a narrow model question

[harness/tasks.py](harness/tasks.py) owns the prompt and response contracts. The source-inspection path prepares a question against one original paragraph, with selected sentence options and a binding that includes the question, inventory digest, file digest, paragraph digest and span.

The application accepts a caller through an explicit interface. It revalidates the prepared evidence before execution and again before accepting the response. The public source selection omits the original runtime transport and qualified local profiles; no private machine connection is configured here.

## 4. Check structure and attribution separately from meaning

[harness/check.py](harness/check.py) checks output shape, allowed judgments and supporting text. [m1/scorer.py](m1/scorer.py) supplies deterministic output-contract scoring and quotation normalization.

A matching quotation establishes that the words came from the specified passage. It does not establish entailment, currentness or overall factual correctness. The application therefore reports a proposed meaning judgment rather than converting quotation verification into factual acceptance.

[harness/model.py](harness/model.py) contains the local Ollama client. Its host is fixed to literal loopback, proxy use and redirects are disabled, and model/runtime errors remain explicit. It contains no model-download or daemon-management action. This component requires separately supplied runtime settings for actual use and is not exercised by the source-paging check.

## 5. Keep mechanical work in software

The development modules illustrate complementary work that does not require a language model:

- [budget_closeout.py](development/budget_closeout.py) reads declared finance formats, computes with exact cents and retains source references.
- [numeric_checker.py](development/numeric_checker.py) checks supported arithmetic expressions in an answer without rewriting that answer or deciding the underlying source meaning.
- [timeline.py](outputs/m4-operational-schedule-pair-20261011/timeline.py) performs same-day clock arithmetic over explicitly supplied ordered records and units.
- [record_adapter.py](outputs/m4-dated-source-contract-20261011/record_adapter.py) composes source-linked records while retaining supplied declarations and validation boundaries.
- [checked_view.py](development/checked_view.py) attaches independent calculation observations to presentation data, preserving original answers separately.

These modules intentionally work on bounded schemas. They are not general parsers of arbitrary prose or proof that every natural-language planning request can be completed.

## Tradeoffs and continuing work

The design favors traceable evidence and inspectable computations over broad autonomous action. Explicit schemas reduce ambiguity but require source preparation and limit what each component can handle. More checks around a model can reject unsupported results; they cannot make a weak semantic answer correct.

The runnable test provides concrete evidence for retrieval/paging behavior. The next product challenge is reliable useful meaning judgments through the full local workflow, evaluated on representative tasks. The repository keeps that challenge distinct from passing software checks.
