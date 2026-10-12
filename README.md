# Local Build Engineering

Python engineering for a local-first AI workroom: bounded document retrieval, source-linked answers, deterministic calculations, and explicit handling of incomplete or unsupported results.

The project explores a practical question: how much useful work can reliable software around a small local model perform on limited hardware? The architecture gives code responsibility for file access, source identity, structured output, record joins and arithmetic. A model can propose a narrow meaning judgment; a person retains the decision about its usefulness.

This repository presents actual implementation from an ongoing engineering project, including a runnable synthetic source-paging check. It is a selected source showcase, rather than the complete workroom installation.

## Start with these files

| Engineering concern | Implementation |
| --- | --- |
| Bounded file access and paragraph retrieval | [harness/retrieve.py](harness/retrieve.py) |
| Response structure and source quotation checks | [harness/check.py](harness/check.py) |
| Fixed task orchestration and narrow meaning requests | [harness/tasks.py](harness/tasks.py) |
| Local-only model client and failure handling | [harness/model.py](harness/model.py) |
| Search, paging and question-to-source binding | [development/wedding_request_app.py](development/wedding_request_app.py) |
| Exact monetary calculations with source references | [development/budget_closeout.py](development/budget_closeout.py) |
| Independent arithmetic checking | [development/numeric_checker.py](development/numeric_checker.py) |
| Runnable paging and source-drift checks | [test_paging.py](outputs/m4-source-paging-20261012/test_paging.py) |

The [architecture walkthrough](ARCHITECTURE.md) explains the data flow and design choices. The planning-domain module names and names embedded in those schemas reflect fictional development scenarios used to exercise the components; their source documents and captured results are not part of this repository.

## Run the focused example

From a terminal in the root of this repository, with Python 3.9 or newer available, run:

```sh
python3 -B outputs/m4-source-paging-20261012/test_paging.py
```

This check uses the Python standard library. It creates temporary synthetic notes and an inventory, then exercises the real retrieval and paging methods. It does not call a model, start a server, install packages or read an existing personal document collection.

A successful run reports six passing test groups and `OK`. It also writes an ignored `FOCUSED_CHECKS.json` beside the test. The checks cover:

- Original match order across pages and backward navigation.
- Stable question bindings for earlier pages, with page-specific selection checks.
- Refusal of invalid context identifiers and offsets.
- Detection of changed inventory, source-file contents, cached paragraphs and spans.
- No-match wording that distinguishes an empty search result from proof that information does not exist.

This verifies those software behaviors. It does not measure model answer quality or establish end-to-end product acceptance.

## What the source demonstrates

**Evidence stays attached to its origin.** File digests, paragraph identities, original spans and source snapshots accompany candidate passages. Paging retains the original ranking while rechecking the source. A question prepared against one paragraph cannot silently become a question about another.

**Different checks have different meanings.** Response validation can confirm structure and quotation attribution. Those checks do not prove that an answer is true, current, complete or supported in meaning. The code keeps that distinction visible.

**Calculations remain inspectable.** Finance and scheduling components work on declared schemas and units. An arithmetic checker can attach a warning to an answer without silently rewriting the model's original words.

**Failure is an explicit outcome.** Changed sources, unavailable callers, incomplete responses and invalid outputs produce unresolved states rather than an invented successful result.

## Current development boundary

The broader project has exercised real local models and an interactive workroom, but useful semantic performance is still under development. Its current milestone remains open. This source export is suitable for code review and the focused test above; it is not a production-readiness claim.

The full workroom requires additional runtime profiles, source inventories, evaluation inputs and local integration records that are intentionally outside this showcase. Directly constructing the full `App` or running historical replay entry points requires those absent inputs. No end-to-end launch command is advertised here.

The optional workbook adapter in `development/native_thank_you.py` uses `openpyxl` when its workbook-reading function is called. It is not needed for the advertised paging test. The included model client is source for inspection; the focused test does not instantiate or contact a live model.

## Source presentation

This selection comes from a reviewed October 12, 2026 development snapshot. Two export adaptations remove a workstation-specific source path and defer the optional workbook import until use. Component and dated source paths are retained so a reviewer can follow the real implementation rather than a rewritten demonstration. Operational handoffs, runtime transport, model weights, source corpora, credentials and captured answers are excluded.

The project was developed through Adolph White Jr.'s AI-assisted engineering workflow. This repository presents the resulting architecture and source without attributing every line to manual authorship or replacing the original development history.
