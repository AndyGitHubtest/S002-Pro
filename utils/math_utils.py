import pandas as pd
import numpy as np

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_fractal_low(df: pd.DataFrame, window: int = 2) -> pd.Series:
    """
    Calculate Williams Fractal Low (bullish fractal).
    A fractal low forms when a low is lower than N bars before and after.
    Default window=2 means 5-bar fractal (2+1+2).
    """
    lows = df['low']
    
    # Check if current low is lower than N bars before and after
    is_fractal = pd.Series(True, index=df.index)
    
    for i in range(1, window + 1):
        is_fractal &= (lows < lows.shift(i))      # Lower than i bars before
        is_fractal &= (lows < lows.shift(-i))     # Lower than i bars after
    
    # Return the fractal low value where pattern forms, else NaN
    fractal = pd.Series(np.nan, index=df.index)
    fractal[is_fractal] = lows[is_fractal]
    
    # Forward fill to get the most recent fractal low at each point
    # Use shift(1) to ensure no lookahead bias
    return fractal.shift(1).ffill()

def get_robust_pullback_low(df: pd.DataFrame, breakout_idx: int, current_idx: int) -> float:
    """Get robust pullback low using Fractal or fallback to body low."""
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
