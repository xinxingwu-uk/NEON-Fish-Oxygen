# Archived pilot findings and provenance

**Status:** descriptive outputs recorded from an earlier execution of the user's notebook, dated 10 October 2026. These are **not** independently re-run results from the cleaned GitHub version. No raw sensor/fish CSV files are included in this repository.

## Recorded sample and processing counts

| Variable | Saved result |
|---|---:|
| Original sites | GUIL, BLUE, KING |
| Processed individual-fish rows | 2,799 |
| Bulk-count rows | 126 |
| Captured-fish survey events | 12 |
| Raw water-quality records read across positions | 1,707,840 |
| Selected sensor records before DO quality filtering | 1,006,560 |
| DO records after selection and quality filtering | 611,299 (60.7%) |
| Valid hourly medians after hourly coverage rule | 10,438 |
| Events with an adequate 7-day / 14-day / 30-day DO window | 8 / 8 / 7 |
| Model comparison | Skipped: 7 30-day events from 3 sites |

The **23** combined usable event–window pairs comprise repeated measurements of **the same 12 captured-fish survey events** with different window lengths; they are **not** 23 independent fish surveys.

## Figure interpretations

**Figure 1 — Environmental time series.** BLUE, 31 October 2023 survey. The preceding 30-day period has **717/720** valid hourly medians (**99.6%** coverage), a mean of approximately **8.87 mg/L**, and a range **7.37–11.18 mg/L**. Clear daily cycling is visible. The original image rounds the coverage subtitle to **100%**; the current plotting code uses **99.6%**. The reference of 5 mg/L is an exploratory screening value, not a universal fish health criterion.

**Figure 2 — Exploratory site comparisons.** There are seven usable 30-day fish–oxygen survey matches from three sites. Panel A compares observed fish-taxon richness to average DO. Panel B compares richness to **DO standard deviation**, not the fraction below 5 mg/L. Across these seven windows, **no valid hourly median was below 5 mg/L**. The displayed between-site association is descriptive and confounded by geographic setting, habitat, season, sampling effort and capture/detection differences. There are too few independent sites/events for reliable predictive claims.

**Sensitivity screening:** A saved median low-DO fraction of zero for 4, 5, and 6 mg/L reference levels must not be misread as *every* window containing zero hours below each reference. The stronger all-zero statement applies only to the **seven plotted 30-day windows below 5 mg/L**.

## Crucial richness caveat

The baseline aggregates each individually processed fish as 1 and bulk-capture counts as recorded. It groups by `siteID`, `eventID`, and `taxonID`, then computes richness as distinct taxon groups **without first removing groups whose total is zero**. Thus, an event's provisional observed richness can be overestimated if it has zero-only taxa.

The GitHub-cleaned edition preserves this legacy definition for transparency and adds a **diagnostic report** (`zero_count_taxon_audit.csv`) with no impact on the saved numbers. Before making biological conclusions or preparing a manuscript, check the diagnostic and, where necessary, undertake an explicitly labeled corrected analysis based on positive captures and protocol-consistent survey effort.

---
> An initial NEON pilot connected fish-survey events to quality-screened, high-frequency dissolved oxygen measurements at three stream sites. Seven of twelve captured-fish events satisfied the predefined completeness requirement for 30-day pre-survey oxygen windows. At the BLUE site, 717 of 720 preceding hourly medians were available (99.6% coverage), with concentrations ranging from 7.37 to 11.18 mg/L and exhibiting pronounced temporal variation. No hourly median fell below the exploratory 5 mg/L reference within the seven matched 30-day windows. These results demonstrate the technical feasibility of linking biological surveys to continuous oxygen measurements, while highlighting the need to expand site-year coverage, evaluate sampling comparability, and distinguish oxygen variability from location-related differences before testing ecological relationships.
