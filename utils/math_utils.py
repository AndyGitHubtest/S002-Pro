import pandas as pd
import numpy as np

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def get_robust_pullback_low(df: pd.DataFrame, breakout_idx: int, current_idx: int) -> float:
    start_idx = breakout_idx + 1
    end_idx = current_idx
    subset = df.iloc[start_idx : end_idx + 1]
    if len(subset) < 5:
        return subset[['open', 'close']].min(axis=1).min()
    
    # Fractal Low
    for i in range(2, len(subset) - 2):
        if (subset['low'].iloc[i] < subset['low'].iloc[i-1] and
            subset['low'].iloc[i] < subset['low'].iloc[i-2] and
            subset['low'].iloc[i] < subset['low'].iloc[i+1] and
            subset['low'].iloc[i] < subset['low'].iloc[i+2]):
            return subset['low'].iloc[i]
            
    return subset[['open', 'close']].min(axis=1).min()
