# S002 Strategy — Expert C (Quant Developer) Peer Review

## Review Date: 2026-04-07
## Files Reviewed: `core/strategy.py`, `core/signals.py`, `utils/math_utils.py`, `main.py`

---

## 1. LOOK-AHEAD BIAS — CRITICAL FINDINGS

### FINDING 1.1: Resample Logic — Partially Safe But Fragile [MEDIUM]
**Location:** `signals.py` lines 29-50

The code slices `history = df.iloc[:current_idx+1]` BEFORE resampling, which is correct — it prevents using future bars. Using `iloc[-2]` to grab the previous *completed* resampled candle is also the right pattern.

**However**, there are edge cases where this breaks:

- **Early data (first ~24 bars):** With only a few 5m bars, `resample('15min')` produces 1 or 2 candles. If `len(df_15m) < 2`, `iloc[-2]` raises `IndexError`. The `try/except` catches this, but the fallback (lines 55-60) uses *current* high + ATR multiples — which is NOT resistance levels, it's just an ATR fan. This silently changes the strategy behavior during early warmup.

- **Gap-filled data:** If the exchange has missing 5m candles (common in crypto), `resample('15min')` will produce NaN-filled candles for the missing periods. The `.dropna()` removes them, but this means `iloc[-2]` may skip back MORE than one 15m period, potentially pulling a stale resistance level from hours ago. The code has no awareness of how far back it's actually looking.

- **`closed='right'` ambiguity:** With `closed='right'`, a 5m bar at 00:05 falls into the 00:00-00:15 bucket. But if the data starts at 00:00, the first 15m candle may include bars from before the history slice. **Recommendation:** Add `origin='start'` or verify the timezone/index alignment.

### FINDING 1.2: `rolling_high` Precomputation — SAFE [OK]
**Location:** `signals.py` line 70

```python
self.df['rolling_high'] = self.df['high'].rolling(window=20).max().shift(1)
```
The `.shift(1)` correctly prevents look-ahead. When `check_signal(idx)` accesses `bar['rolling_high']`, it gets the max of the 20 bars *before* the current one. Correct.

### FINDING 1.3: ATR Precomputation — SAFE But Uses Simple Mean [LOW]
**Location:** `signals.py` line 69

```python
self.df['atr'] = calculate_atr(self.df, 14)
```
The engine reads `current_atr = df['atr'].iloc[i]` — this is precomputed on the full DataFrame, so no look-ahead. However, `calculate_atr` uses `.rolling(window=period).mean()` (SMA) instead of the standard Wilder EMA (`alpha = 1/period`). This is a known deviation from conventional ATR — not a bias, just a different calculation.

---

## 2. PERFORMANCE — CONCERNS FOR LONG BACKTESTS

### FINDING 2.1: Resample Called Every Bar — SEVERE [HIGH]
**Location:** `signals.py` lines 16-62

`get_resistance_levels()` is called on **every bar where a signal is checked**, and inside it performs **4 full resample operations** on the cumulative history:

```python
df_15m = history.resample('15min', ...)   # Full re-resample of ALL history
df_30m = history.resample('30min', ...)
df_1h  = history.resample('1h', ...)
df_2h  = history.resample('2h', ...)
```

For a 1-year backtest of 5m BTC data (~105K bars):
- Each iteration resamples an ever-growing DataFrame (from 100 to 105K rows)
- 4 resamples × 105K iterations = ~420K resample operations
- Each resample grows linearly with history size → **O(n²) total complexity**

This will take **minutes to hours** for a year-long backtest.

**Recommendation:** Pre-compute the resampled DataFrames ONCE at initialization:
```python
df_15m = df.resample('15min', ...).agg(...).shift(1)  # Shift to prevent look-ahead
# Then just: levels['TP2'] = df_15m['high'].iloc[current_idx]
```
Or maintain running rolling max windows instead of resampling.

### FINDING 2.2: Pending Orders List — Linear Scan [LOW]
**Location:** `strategy.py` lines 142-161

```python
for order in self.pending_orders:
    if bar['low'] <= order['limit_price']:
        ...
    for o in filled_orders:
        self.pending_orders.remove(o)  # O(n) list.remove()
```

For most strategies, pending orders will be ≤5, so this is negligible. But `list.remove()` is O(n) and calling it in a loop over filled orders adds unnecessary cost. Use a set or list comprehension filter.

### FINDING 2.3: String-based TP Level Names — AVOIDABLE [LOW]
**Location:** `strategy.py` lines 64-101

Every bar, for every position, the code iterates `self.tp_levels.items()` using string keys ('TP1', 'TP2', ...). Using integer indices or a fixed-size array would be faster. Again negligible for a few positions but adds up.

---

## 3. ROBUSTNESS — MULTIPLE ISSUES

### FINDING 3.1: No NaN Handling in Signal Logic [HIGH]
**Location:** `signals.py` lines 82-97

```python
if bar['close'] > bar['rolling_high']:
```

If `rolling_high` is NaN (first 20 bars + shift = first 21 bars), the comparison `bar['close'] > NaN` returns `False` in pandas, so this is silently safe. **But:**

```python
sl_price = consolidation_window[['open', 'close']].min(axis=1).min()
sl_price -= self.df['atr'].iloc[idx] * 0.5
```

If ATR is NaN (first 14 bars), `sl_price` becomes NaN. Then `risk_distance = bar['close'] - sl_price` → NaN. Then `risk_distance <= 0` → NaN, which is falsy, so it proceeds to construct a signal with NaN values. **This will create a position with NaN prices.**

The `idx < 30` warmup guard helps, but ATR warmup is 14 + rolling_high warmup is 21, so 30 is sufficient. However, the code doesn't explicitly validate that `signal['entry_price']`, `sl_price`, and TP levels are all finite numbers before creating a position.

### FINDING 3.2: No Validation of Resample Fallback Behavior [MEDIUM]
**Location:** `signals.py` lines 52-60

When resampling fails, the fallback creates ATR-multiple targets:
```python
levels['TP2'] = base + atr * 1.5  # base = current high
```

This means the **strategy behavior changes fundamentally** when resample fails — from "resistance-based TP" to "ATR-fan TP". The caller has no way to know this happened. At minimum, this should be logged with the symbol/time, and ideally the signal should be rejected rather than silently changed.

### FINDING 3.3: No Exchange API Failure Handling [HIGH]
**Location:** Entire codebase

The codebase has zero handling for:
- Missing data gaps (common in crypto)
- API rate limits or connection failures
- Stale data (no new bars for extended periods)
- Data timestamp misalignment

For a backtest on pre-loaded data this is fine, but this architecture will break immediately when adapted to live trading. The `SignalGenerator` and `S002Engine` have no concept of data health checks.

### FINDING 3.4: Hardcoded Symbol [MEDIUM]
**Location:** `strategy.py` line 187

```python
symbol = "BTC/USDT" 
```

The engine only supports one symbol. The `run()` method and `open_hybrid_position()` both hardcode BTC/USDT. The signal generator should pass the symbol through, or the engine should be multi-symbol aware.

### FINDING 3.5: Balance Never Decremented [CRITICAL]
**Location:** `strategy.py` lines 189, 128

```python
total_qty = (self.balance * self.config['risk_per_trade']) / signal['risk_distance']
```

The position size is calculated from `self.balance`, but `self.balance` is **never decremented** when positions are opened, and **never incremented** when positions are closed with PnL. This means:
- Position sizing is always based on the initial $10,000
- PnL from closed trades is never realized into the balance
- The engine cannot handle multiple concurrent positions with proper margin/risk management

The `trades_log` records PnL, but the balance is never updated. This is a fundamental backtest integrity issue.

### FINDING 3.6: No Fee/Slippage Model [MEDIUM]
**Location:** Entire codebase

There are no trading fees, no slippage, no funding rate considerations. For a 5m breakout strategy with 6 TP levels (many small partial closes), fees will be significant:
- 6 partial exits per position → 6× commission
- Hybrid entry (market + limit) → different fee tiers
- Binance maker fee ~0.02%, taker ~0.05%

For small TP moves (TP1 at 5m resistance), fees could eat the entire profit. The skill spec mentions "摩擦成本约 0.2%" but it's not modeled.

---

## 4. CODE QUALITY & STATE MANAGEMENT

### FINDING 4.1: S002Position State — Mostly Correct, One Bug [MEDIUM]
**Location:** `strategy.py` lines 38-103

The position state machine is reasonably well-structured:
- `remaining_qty` tracks unfilled quantity
- `tp_statuses` prevents double-triggering TPs
- `highest_price` and `trailing_stop_price` update correctly

**Bug: Trailing stop checks before TP checks** (lines 54-60 vs 64-101)

The update order is:
1. Stop Loss check
2. Time Stop check
3. **Trailing Stop check** (TP6)
4. **TP1-TP5 check**

If the bar's high hits TP5 AND the low hits the trailing stop, the trailing stop executes FIRST, closing the ENTIRE remaining position at the trailing stop price, skipping TP5's partial exit. The order should be: TP1-TP5 first (partial closes), THEN trailing stop (for what remains).

This is particularly relevant because the skill spec says: *"TP6 必须始终计算，不能等 TP5 走完"* — but the trailing should apply to `remaining_qty` AFTER TP partial fills are processed, not before.

### FINDING 4.2: TP Ratios Don't Sum to 1.0 [LOW]
**Location:** `strategy.py` lines 71-74

```python
tp_ratio_map = {
    'TP1': 0.35, 'TP2': 0.25, 'TP3': 0.20, 
    'TP4': 0.10, 'TP5': 0.05
}
# Sum = 0.95
```

TP1-TP5 total 95% of position. The remaining 5% is handled by TP6 (trailing). But the `close_qty = min(close_qty, self.remaining_qty)` safety check means if earlier TPs didn't fill (price didn't reach them), later TPs will try to close more than their ratio of the remaining amount. This is actually correct behavior, but the naming "ratio" is misleading — these are ratios of the ORIGINAL quantity, not remaining.

### FINDING 4.3: Pending Order State Inconsistency [MEDIUM]
**Location:** `strategy.py` lines 142-161

When a limit order fills, the code does:
```python
pos.remaining_qty += order['unfilled_qty']
```

But there's no check that the order hasn't expired. If a limit order sits for 1000 bars, it will still try to fill. In real trading, limit orders would have a TTL or be cancelled after a timeout. For backtesting, this may be intentional (wait forever for pullback), but it should be explicit.

### FINDING 4.4: No Concurrency Protection [LOW]
**Location:** `strategy.py` lines 164-171

```python
open_pos = []
for pos in self.positions:
    if pos.remaining_qty > 0:
        ...
        if pos.remaining_qty > 0:
            open_pos.append(pos)
self.positions = open_pos
```

If `pos.update()` closes the position (sets `remaining_qty = 0`), it's not appended to `open_pos`. Correct. But if `close_position` is called during update AND additional TPs are processed in the same bar, the `remaining_qty` could go negative before the `<= 0.0001` check. The safety `min(close_qty, self.remaining_qty)` helps, but the order of operations in `update()` means this could be tight.

### FINDING 4.5: `get_robust_pullback_low` is Imported But Unused [LOW]
**Location:** `signals.py` line 9

```python
from utils.math_utils import get_robust_pullback_low, calculate_atr
```

`get_robust_pullback_low` is imported but never called. Instead, `signals.py` uses a simple `min(axis=1).min()` approach (line 96). The skill spec explicitly requires Williams Fractal or body-low as the SL calculation — this code doesn't implement either. The fractal function exists in `math_utils.py` but is wired up incorrectly.

---

## 5. SUMMARY OF FINDINGS

| Priority | Finding | Impact | File |
|----------|---------|--------|------|
| **P0-CRITICAL** | Balance never updated — PnL not realized, sizing always from initial $10K | Backtest PnL is meaningless | strategy.py:128,189 |
| **P0-CRITICAL** | Trailing stop checked BEFORE TP partial fills — skips TP exits | Incorrect execution order | strategy.py:54-60 |
| **P0-CRITICAL** | No fee/slippage model — unrealistic for multi-TP strategy | Backtest overestimates returns | Entire codebase |
| **P1-HIGH** | Resample every bar — O(n²) for long backtests | Minutes→hours runtime | signals.py:29-50 |
| **P1-HIGH** | No NaN validation on signal prices — could create NaN positions | Silent corruption | signals.py:96-97 |
| **P1-HIGH** | No exchange/data failure handling | Will crash on live data | Entire codebase |
| **P2-MEDIUM** | Resample fallback silently changes strategy behavior | Inconsistent TP logic | signals.py:52-60 |
| **P2-MEDIUM** | Hardcoded BTC/USDT — not multi-symbol | Architecture limitation | strategy.py:187 |
| **P2-MEDIUM** | Pending orders have no expiry | Unrealistic for live trading | strategy.py:142-161 |
| **P2-MEDIUM** | Fractal SL function imported but not used | Doesn't match spec | signals.py:9,96 |
| **P3-LOW** | TP ratios sum to 0.95, not 1.0 | Cosmetic (5% goes to trailing) | strategy.py:71-74 |
| **P3-LOW** | String keys for TP levels — minor perf | Negligible | strategy.py:64 |
| **P3-LOW** | list.remove() in loop — minor perf | Negligible | strategy.py:161 |

---

## 6. RECOMMENDED FIX PRIORITY

### Phase 1 (Must fix before any backtest results are trusted):
1. **Update balance on open/close** — deduct cost on entry, add PnL on exit
2. **Add fee model** — minimum 0.05% taker + 0.02% maker
3. **Fix execution order** — process TP1-TP5 BEFORE trailing stop check
4. **Validate all prices are finite** before creating positions

### Phase 2 (Required for year-long backtests):
5. **Pre-compute resampled DataFrames** — eliminate O(n²) resample loop
6. **Add NaN guards** on all signal calculations

### Phase 3 (Required for live trading):
7. **Wire up `get_robust_pullback_low`** — replace simple min with fractal logic
8. **Add data health checks** — gap detection, stale data alerts
9. **Multi-symbol support** — remove hardcoded symbol
10. **Limit order TTL** — expire pending orders after N bars
