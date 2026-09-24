# Prediction costs: official documentation and sensitivity

Checked 2026-09-17. Existing strategy: initial external capital 100 USDT only; base stake and recovery profit target 0.5; UD after prior DOWN; withdraw 50 profits; wait four new UDUD candles after withdrawal; recycle reserves after failure if at least 100 remains. No strategy increase to 1 or 1.5 was authorized or applied.

## Execution preflight comes first

Predict.fun minimum order is 1 USDT. Binance MARKET minimum is approximately 1.5 USDT, depth dependent; its exemption for LIMIT does not establish exemption from the provider's 1 USDT minimum. Therefore the unchanged 0.5 stake fails documented-minimum preflight. No real quote/order was requested. Actual account-specific limit exceptions unavailable. A preflight-blocked run submits zero trades and leaves initial cash untouched; it is not an observed historical trading return.

## Published fees

Binance directs users to Predict.fun fees. Makers have zero trading fee; this does not mean any limit order is a maker or will fill. Takers: raw USDT-equivalent fee = 0.02 * min(p,1-p) * gross shares, before any verified discount. At 0.50 this is 2% of trade notional. Binance's wallet reference gives BUY fee units as shares, SELL fees as USDT. Sensitivity therefore deducts BUY fee shares from purchased shares; a 0.5 budget at 0.50 buys 1 gross share, loses 0.02 shares to fee, receives 0.98 net shares. Win profit 0.48, loss 0.50. Next recovery stakes are recalculated using net proceeds, not fixed doubling. No double subtraction of the fee from cash or the final return. Fee reporting at entry is valuation, not an extra cash debit.

The quoted 2% is the current published undiscounted provider schedule, not verified for every August market/account. Referral discount eligibility and actual fee rounding remain unavailable. API feeRateBps default alone was NOT treated as sufficient proof of actual fee. Actual signed quote overrides assumptions.

## Conditional sensitivity (minimum order deliberately ignored)

| Assumption | Ending total assets U | Net PnL U | Stops before month end |
|---|---:|---:|---|
| Original fixed 0.50 / zero fees | 1131.50 | +1031.50 | No |
| Fixed 0.50 / published taker schedule | 57.47 | -42.53 | Aug 12 17:20 UTC |
| Assumed 0.505 / published taker schedule | 82.86 | -17.14 | Aug 12 16:15 UTC |
| Assumed 0.51 / published taker schedule | 98.30 | -1.70 | Aug 12 12:00 UTC |

Adverse entry prices represent total hypothetical spread/slippage relative to 0.50, not observed historical quotes and not extra fees on top of another slippage charge. Results are not monotonic because stake sizing, winning-round reset, withdrawal threshold and UDUD re-entry change the trade path. This is not evidence that slippage helps.

Fee-only scenario: 3028 counted non-flat trades, 11 sequence failures, no external replenishment, total assets 57.474. Fee shares valued at their entry prices sum to about 111.30 USDT; this cannot simply be subtracted from the earlier gross-profit result, because the strategy path changed. Original and updated runs do not execute the same trades.

## Costs and constraints still unavailable

- Bid/ask spread, order-book depth, size-dependent market impact, partial fills, queue priority, cancellations, quote expiry, network latency: require historical Prediction books and order events. No invented fill probabilities.
- MARKET FOK versus LIMIT GTC: unfilled orders must not become positions; late fills can affect the period and restart logic. No actual fill replay available.
- Binance advertises sponsored trading and settlement gas. Do not add arbitrary gas charges or assume this covers every API route, withdrawal destination or historical period. Internal reserve accounting incurs no modeled network transaction. Actual external transfer/withdrawal costs remain unavailable.
- Redemption delay and liquidity locked while resolving: winning payout cannot be used before claim. Binance distinguishes ended versus resolved. No verified per-round settlement/claim timestamps, so immediate recycling is still optimistic.
- Price markets use Chainlink BTC/USDT reports, not Binance spot candle colours. Flat is a distinct resolution; the exact user's market payout mapping is unverified. Existing refund-on-flat proxy remains a hypothetical assumption and is not verified as a product rule.
- 90% anticipated rollover and 95% early sale need actual bid/depth and sell fees. Neither simulated from OHLC. Funding/margin fees are not automatically borrowed from futures products.
- Fee discounts, yield/rebates, exact share tick/rounding, local infrastructure costs: not fabricated or included as a fixed known amount.

All these are limitations of an incomplete historical execution dataset, not quantities that can honestly be added into one exact 'all costs' number. Current findings already invalidate calling the previous +1031.5 an executable result. Further claims require product IDs, quotes, eligibility/minimum validation and historical execution data.

## Official sources

- Binance overview, fees, sponsored gas, fills and settlement phases: https://www.binance.com/en/learn/binance-wallet-prediction-markets
- Provider fees and minimum (linked by Binance): https://docs.predict.fun/the-basics/predict-fees-and-limits
- Binance trade API, MARKET minimum, FOK/GTC and quotes: https://developers.binance.com/en/docs/catalog/web3-wallet-prediction-trading/api/rest-api/trade
- Binance quote-unit reference: https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-agentic-wallet/references/prediction.md
- Price-market resolution: https://docs.predict.fun/developers/chainlink-price-markets
- Transfer reference (route-specific values still required): https://developers.binance.com/en/docs/catalog/web3-wallet-prediction-trading/api/rest-api/transfer

Reproduce: `.venv/bin/python -m binance_quant.prediction_costs`. 24 related tests passed, including net shares/fee valuation, recovery sizing, reserve accounting and no external additions. Results: cost_sensitivity.json; preflight: cost_execution_preflight.json. No real trades or transfers were made. Same August data has repeatedly been used to tune rules and is not an independent validation.
