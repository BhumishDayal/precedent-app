# Numbers

Everything here comes from running Precedent on Backblaze's public drive stats for 1 Jan to 30 Jun 2026.
`python -m precedent.engine` regenerates the tables; the backtest results are also in `data/samples/backtest*.json`.

## The fleet

- 363,548 drives across 83 models over 181 days, with 2,552 failures.
- 80% of failed drives showed a SMART warning first (2,048 of 2,552). So did 9% of drives that kept working
  (33,315 of 360,996), which is why a warning on its own says so little.
- 18,342 warning events have a known outcome. In the test window, 7.7% of warned drives failed within 30 days.

## Definitions

- **Warning:** the set of non-zero SMART counters (5, 187, 188, 197, 198) changes, or its severity bucket moves up.
  Buckets are on the largest raw count: low < 8, mid < 100, high >= 100.
- **Identical:** same model and same pattern, for example `TOSHIBA MG10ACA20TE · 5+197+198:high`.
- **Died:** Backblaze recorded a failure within 30 days.
- **Circular:** any pattern with SMART 187. Backblaze replaces drives once 187 is non-zero, so "187 then failed" partly
  predicts itself. Circular patterns are excluded from every headline number below.

## Backtest

Thresholds are learned only from warnings whose 30-day outcome was known before 19 Apr 2026. They are tested on the
4,427 non-circular warnings from 19 Apr to 29 Jun.

| | Checks a person does | Failures caught | Checks that were real |
|---|---|---|---|
| Check every warning | 4,427 | 342 | 7.7% |
| Urgent page (at least 15 identical, at least 25% died) | 43 | 20 | 47% (6x) |
| Morning swap list (at least 10 identical, at least 10% died) | 595 | 164 | 28% (3.6x) |

- The swap list needs 87% fewer checks and still catches 48% of failures.
- Urgent pages cut interruptions by 99%, and about half the drives paged about die within a month. Recall is low by
  design (6%); the swap list is the coverage tier.
- At 15 minutes per check, the swap list saves (4,427 minus 595) × 15 min, about 958 hours over the 10 weeks.
- Calibration in the test window: predicted 10 to 20% became 22% actual, 20 to 30% became 43%, 30 to 40% became
  58%, and 40%+ became 49%. The ranking holds, and the estimates run conservative.
- Warnings late in the window only count once their outcome is known, which slightly favours drives that died.

## Pooled history

Each Backblaze datacenter stands in for one customer: Atlas GPU Cloud (phx1), Beacon Storage (sac0), Cedar Compute
(sac2), Delta Colo (iad1), Ember AI (ams5) and Fjord Cloud (yyz1). The names are made up. The same thresholds and
held-out months were run twice: once with each customer using only its own history, once pooled.

| | Each customer alone | Pooled |
|---|---|---|
| Urgent pages: failures caught | 12 of 33 paged (36%) | 20 of 43 (47%) |
| Morning swap list: failures caught | 85 of 306 (28%) | 164 of 595 (28%), 1.9x more caught |
| Warnings with too little history to decide (urgent rule) | 33% | 14% |

## The demo drive

WDC WUH722222ALE6L4, serial 1QHPN2VX, at sac2 › vault 3016 › pod 17 › slot 14 (Cedar Compute).

- Healthy from 1 Jan to 28 May 2026. On 29 May one reading shows `197:high`.
- 59 identical drives, 26 of them failed within 30 days (44%), so Precedent pages.
- Cedar Compute alone has 11 identical drives (5 failed), which is below the 15-drive minimum. The pooled 59 come
  from all six customers.
- The drive failed on 9 June, 11 days after the alert.
- The text it sends: "WDC WUH722222ALE6L4 drive 1QHPN2VX just showed 197:high. 59 drives like this, 26 died within
  30 days. Reply 1 to swap, 2 to wait, 3 to see them."
- `python -m precedent.collector --replay 1QHPN2VX --live --speed 2` streams its real readings from 8 May and stops
  when Precedent decides to act, about 11 seconds in.

`scripts/e2e.py` defaults to an earlier example, TOSHIBA MG10ACA20TE 44H0B01BV4MJ (27 identical drives, 13 failed).

## Strongest patterns (non-circular)

| Model | Pattern | Warnings | Died |
|---|---|---|---|
| WDC WUH722222ALE6L4 | `5+197:high` | 26 | 14 (54%) |
| TOSHIBA MG10ACA20TE | `5+197+198:high` | 28 | 14 (50%) |
| WDC WUH722222ALE6L4 | `197:high` | 60 | 27 (45%) |
| TOSHIBA MG08ACA16TA | `5+197:high` | 50 | 21 (42%) |
| TOSHIBA MG08ACA16TA | `5:low` | 1,079 | 12 (1%) |

The last row is where Precedent stays quiet.

## Keewano

- 12,111 warned drives and about 172k events ingested. Decisions are written back as they happen.
- `keewano/precedent.lua` rebuilds the precedent table inside Keewano (263 model and pattern rows).
- `keewano/at_risk.lua` scored 10,939 still-running warned drives in 1.8 s, ranked by the failure rate of their
  latest warning. The top one was TOSHIBA MG07ACA14TA `5+197:high`, where 11 of 15 similar drives failed (73%).

## Latency

Measured in-process in dry-run: telemetry to verdict has a median of 8.3 ms, verdict to page started is about 9 ms
plus Dial's network time, and an event reaches the browser over SSE in about 16 ms.

## Darwin (11 Oct)

- Anonymous search for "file a warranty return" on a TOSHIBA drive returned 1 candidate agent in 4.2 to 6.0 s over
  four searches. Its status was `needs_input` ("Do you have the order code?"), and the top match,
  `submit_complaint`, was not ready.
- With an API key, searching for a WD drive warranty return returns `no_match`. A colocation remote-hands search
  returns OCOLO with no connection methods.
- Finding the part works: "find a supplier for enterprise HDD replacement" completes with agents that find a
  replacement part and request supplier quotes. Precedent runs this after a replace decision and when the technician
  texts "order the part".
- No agent can file a drive RMA or book remote hands end to end yet. Precedent already holds the serial, model,
  location and failure evidence such an agent would need.
- The manual baseline (a person finding the vendor's RMA flow) hasn't been timed, so there's no minutes-saved figure.

## Sparta

Verified against a local Sparta world (sparta_worlds 0.9.0-beta.5, Zendesk profile). A scenario injects a 500 on
ticket creation; the ticket step retries and recovers, and a replay returns the same ticket. An expired key stops
cleanly instead of retrying. The result is one ticket and no duplicates.
