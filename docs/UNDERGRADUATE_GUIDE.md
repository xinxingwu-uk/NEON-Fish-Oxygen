# Undergraduate researcher guide

This repository is designed for a **mentored undergraduate research experience**, not a black-box AI demonstration. The student should understand the aquatic-science question, data provenance, quality flags, sampling design and limits of inference.

## Learning objectives

By the end of the pilot exercise, the undergraduate should be able to explain why oxygen changes over time, extract environmental measurement summaries before field surveys, audit missing observations and sensor placement, interpret fish-community measures, and communicate uncertainty without inventing effects.

## Suggested six research tasks

| Task | Student deliverable | Research/mentoring focus |
|---|---|---|
| 1. Data provenance | Source table, product IDs, download log and exact study window | Data stewardship |
| 2. Metadata and quality control | Sensor-choice table, flag counts, hourly-coverage diagnostic | Measurement validity |
| 3. Fish-survey audit | Event counts, species/taxon groups, zero-count diagnostic | Biological definitions and sampling effort |
| 4. Match surveys to oxygen histories | Verified 7-, 14-, 30-day event-window table | Temporal alignment and reproducibility |
| 5. Interpret the figures | One-page results memo with appropriate caveats | Scientific communication |
| 6. Plan follow-up hypotheses | Pre-specified questions and controls, expanded site-year plan | Study design and responsible AI |

## Questions to discuss with the PI

1. Why is a survey event the analysis unit rather than each of the thousands of oxygen readings?
2. What changes if a fish species has only a zero-count row?
3. Why can a fish-rich site also have high mean DO without DO explaining richness?
4. What does 99.6% observed oxygen coverage tell us, and what does it **not** tell us?
5. Why must thresholds and validation groups be chosen before examining their relationship to the outcome?

**Research-integrity guidance:** Students should document code changes and retain earlier results as archival material. Correcting a biological variable definition constitutes a newly versioned analysis, not mere cosmetic cleanup. Do not interpret this pilot as evidence of a causal DO effect.
