# CV lines and interview kit: Production Deferment Analytics

## CV project line (pick 3)
**Production Deferment & Well Performance Analytics** · SQL, Python, SciPy · [GitHub link]
* Built a layered **SQL** warehouse over 22K daily production records and operator logs; fixed IDs, duplicates, impossible values and 21 free-text downtime reasons with auditable SQL rules and 6 automated **SQL data tests**.
* Quantified 1.1M bbl of deferred oil with window functions (**gaps-and-islands**, Pareto running totals, `LAG`, `RANK`, `NTILE`); found 23% of lost oil had no recorded cause, a low-cost process fix.
* Applied **Statistics**: Arps decline-curve forecasting flagged all 3 wells with a developing problem (no false flags); **difference-in-differences** with bootstrap CI showed a treatment campaign added +12.9% oil, where a naive before/after said +8.5%.
* Delivered findings as a one-page report for non-technical stakeholders with clear recommendations.

## 45-second pitch
"Operations always ask three questions: where are we losing oil, which wells need attention, and did
what we spent money on actually work? I answered all three from daily production reports and downtime
logs. The cleaning and the main analysis are in SQL, so they're auditable. The first surprise was that a
quarter of lost oil had no reason logged at all, which is a process fix, not a data-science fix. Then I
used decline curves to catch wells drifting below their expected rate, and a control-group comparison to
show a chemical treatment worked about 50% better than a simple before/after suggested."

## Questions you should be able to answer
| Question | Answer |
|---|---|
| Explain gaps-and-islands. | Consecutive dates minus their row number give a constant value inside each streak, so I `GROUP BY` that constant to get one row per downtime event. |
| How do you define potential and deferment? | Potential = latest well-test rate (as-of join). Deferment = potential × hours offline / 24. |
| Why normalise rate by uptime before decline fitting? | Otherwise downtime looks like reservoir decline and the forecast is wrong. |
| Why difference-in-differences? | Wells decline anyway, so before/after under-states the uplift. Untreated wells over the same dates show what would have happened without treatment. |
| Why bootstrap plus two tests with only 8 wells? | Small sample: the bootstrap gives an error bar without assuming normality, and Mann-Whitney is the non-parametric check. |
| Limits? | Treatment wells weren't randomly chosen in real life (selection bias), so ideally match controls on rate and water cut. Potential from monthly tests lags real changes. Data here is synthetic. |
| How would this look in Foundry? | Clean tables become datasets; Well / DowntimeEvent / WellTest become Ontology objects; the Pareto and watchlist go into a Workshop dashboard; an Action lets operators classify unlogged events. |
