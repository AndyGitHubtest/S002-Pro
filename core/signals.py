import pandas as pd
import numpy as np
import sys
import os

# Add project root to path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.math_utils import get_robust_pullback_low, calculate_atr

def get_resistance_levels(df: pd.DataFrame, current_idx: int) -> dict:
    """
    Calculate Resistance Levels based on Multi-Timeframe Highs.
    Uses Resampling to approximate 15m, 30m, 1h, 2h highs from 5m data.
    """
    # We only look at history up to current_idx to avoid future leak
    history = df.iloc[:current_idx+1]
    
    levels = {}
    
    # 1. 5m Resistance (Local High before breakout)
    # Look back ~20 bars (approx 1.5 hours)
    window_5m = history['high'].rolling(window=20).max().iloc[-2] # -2 to ensure completed bar
    levels['TP1'] = window_5m 
    
    # Resample for higher timeframes
    try:
        # 15m (3 bars of 5m)
        df_15m = history.resample('15min', label='right', closed='right').agg({
            'high': 'max', 'low': 'min', 'open': 'first', 'close': 'last', 'volume': 'sum'
        }).dropna()
        levels['TP2'] = df_15m['high'].iloc[-2] # Previous completed candle high
        
        # 30m (6 bars of 5m)
        df_30m = history.resample('30min', label='right', closed='right').agg({
            'high': 'max', 'low': 'min', 'open': 'first', 'close': 'last', 'volume': 'sum'
        }).dropna()
        levels['TP3'] = df_30m['high'].iloc[-2]
        
        # 1h (12 bars of 5m)
        df_1h = history.resample('1h', label='right', closed='right').agg({
            'high': 'max', 'low': 'min', 'open': 'first', 'close': 'last', 'volume': 'sum'
        }).dropna()
        levels['TP4'] = df_1h['high'].iloc[-2]
        
        # 2h (24 bars of 5m)
        df_2h = history.resample('2h', label='right', closed='right').agg({
            'high': 'max', 'low': 'min', 'open': 'first', 'close': 'last', 'volume': 'sum'
        }).dropna()
        levels['TP5'] = df_2h['high'].iloc[-2]
        
    except Exception as e:
        # Fallback if not enough data for resampling
        print(f"Warning: Resampling failed ({e}). Using simple multiples.")
        base = history['high'].iloc[-1]
        atr = calculate_atr(history).iloc[-1]
        levels['TP2'] = base + atr * 1.5
        levels['TP3'] = base + atr * 3.0
        levels['TP4'] = base + atr * 5.0
        levels['TP5'] = base + atr * 7.0

    return levels

class SignalGenerator:
    def __init__(self, df: pd.DataFrame, config: dict):
        self.df = df
        self.config = config
        # Precompute indicators
        self.df['atr'] = calculate_atr(self.df, 14)
        self.df['rolling_high'] = self.df['high'].rolling(window=20).max().shift(1)
        
    def check_signal(self, idx: int) -> dict | None:
        """
        Check if a breakout signal exists at current index.
        Returns Signal dict or None.
        """
        if idx < 30: return None # Warmup
        
        bar = self.df.iloc[idx]
        
        # Simple Breakout Logic: Close > 20-period High
        if bar['close'] > bar['rolling_high']:
            # Confirm volume? (Optional)
            
            # 1. Calculate Stop Loss (Fractal Low)
            # We need to find the low of the pullback/consolidation BEFORE this breakout
            # Since this is a breakout, we look back for the recent swing low
            # Simple approach: Min of last N bars before the breakout bar
            # Robust approach: Use the math_utils function
            
            # We scan back to find the low of the consolidation range
            # A simple proxy for "Recent Low" is the lowest low in the last X bars
            consolidation_window = self.df.iloc[max(0, idx-50) : idx]
            
            # Use robust low finder
            sl_price = consolidation_window[['open', 'close']].min(axis=1).min()
            sl_price -= self.df['atr'].iloc[idx] * 0.5 # Buffer
            
            risk_distance = bar['close'] - sl_price
            if risk_distance <= 0: return None # Should not happen in breakout
            
            # 2. Calculate TP Levels
            tp_levels = get_resistance_levels(self.df, idx)
            
            # 3. Adjust TP1 to ensure Breakeven
            # TP1 must be at least Entry + Risk * 1.05
            min_tp1 = bar['close'] + (risk_distance * 1.05)
            if tp_levels.get('TP1', 0) < min_tp1:
                tp_levels['TP1'] = min_tp1
            
            # 4. Construct Signal
            return {
                'idx': idx,
                'type': 'breakout',
                'entry_price': bar['close'],
                'sl_price': sl_price,
                'risk_distance': risk_distance,
                'tp_levels': tp_levels,
                'limit_price': sl_price + risk_distance * 0.3 # Limit order for the 70% portion (near support)
            }
            
        return None
