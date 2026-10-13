# FIFO Prefix Inference

Research code, measured synthetic results and reproduction instructions for exact
fixed-ledger FIFO parameter inference and timing certificates. This repository
does not contain the manuscript, the author's original proposal, downloaded
literature or internal review reports.

## Complete reproducibility package

Download [FIFO_reproduction_v1.zip](FIFO_reproduction_v1.zip) and extract it into a
new directory. The ZIP is self-contained: algorithms, test controls, locked
inputs, raw measurements, descriptive tables, finite verification evidence and
the complete exact-check transcript. Its README gives the saved-record checking
commands. The optional `source/` tree mirrors code for convenient inspection;
the ZIP remains the complete data-and-code entry point with its own manifest.

- Original comparison: 192 fixed inputs, three exact methods.
- Separate follow-up: 36 workflows, six repetitions, query-demand reversals kept.
- Exact evidence: full 302,369-line slice transcript and finite controls.
- `DATA_DICTIONARY.md`: field definitions, units and aggregation boundaries.
- ZIP SHA-256: `056a30f026bca973206d51169863066c9a01789faae92ff789288479a28b2051`.

The ZIP and measured code/data are unchanged from the verified private archive.
Its historical private-status notes predate the author's subsequent authorization
to expose this repository. This root README and `RIGHTS_STATUS.txt` supersede
those access-status notes only; they do not revise scientific records. No new
benchmark should overwrite the recorded acquisition.

## Scope and disclosure

The model assumes an initially empty immutable FIFO ledger, exact common time,
positive workloads and constant shared service scale and delay. This is an
algorithmic study, not a physical cloud-edge deployment or closed-loop robot test.
Timing reversals and incomplete earlier verification attempts are preserved.

Substantial OpenAI Codex assistance was used in literature work, problem and
algorithm development, experiment programming and execution, checking, figures
and manuscript preparation. The human author has confirmed scholarly review
and approval of the manuscript's content and boundaries. This statement does not
claim an independent human rerun of the experiments or external peer review.

The author authorized public access on 2026-10-14, without adding an open-source
or open-data licence. Public accessibility is not an MIT or CC BY licence.
See `RIGHTS_STATUS.txt`. No DOI, Zenodo integration, journal submission or
acceptance is claimed.
