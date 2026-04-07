import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.math_utils import get_robust_pullback_low, calculate_atr

def get_resistance_levels(df: pd.DataFrame, current_idx: int) -> dict:
    """
    Calculate Resistance Levels based on Rolling Max Highs.
    v2.1: Replaces resample logic with rolling max for structural resistance.
    """
    history = df.iloc[:current_idx+1]
    
    levels = {}
    
    # 1. 5m Resistance (Local High, ~1.5h lookback)
    levels['TP1'] = history['high'].rolling(window=20).max().iloc[-2] 
    
    try:
        # 2. 4h Resistance (60 bars lookback for 5m)
        levels['TP2'] = history['high'].rolling(window=60).max().iloc[-1]
        
        # 3. 12h Resistance (144 bars lookback)
        levels['TP3'] = history['high'].rolling(window=144).max().iloc[-1]
        
        # 4. 24h Resistance (288 bars lookback)
        levels['TP4'] = history['high'].rolling(window=288).max().iloc[-1]
        
        # 5. 48h Resistance (576 bars lookback) - Used for TP5/TP6 base
        levels['TP5'] = history['high'].rolling(window=576).max().iloc[-1]
        
    except Exception as e:
        # Fallback if not enough data
        atr = calculate_atr(history).iloc[-1]
        base = history['high'].iloc[-1]
        levels['TP2'] = base + atr * 2.0
        levels['TP3'] = base + atr * 4.0
        levels['TP4'] = base + atr * 6.0
        levels['TP5'] = base + atr * 8.0

    return levels

class SignalGenerator:
    def __init__(self, df: pd.DataFrame, config: dict):
        self.df = df
        self.config = config
        self.df['atr'] = calculate_atr(self.df, 14)
        self.df['rolling_high'] = self.df['high'].rolling(window=20).max().shift(1)
        
    def check_signal(self, idx: int) -> dict | None:
        if idx < 30: return None
        
        bar = self.df.iloc[idx]
        
        # Breakout Logic
        if bar['close'] > bar['rolling_high']:
            
            # 1. Calculate Stop Loss
            consolidation_window = self.df.iloc[max(0, idx-50) : idx]
            sl_price = consolidation_window[['open', 'close']].min(axis=1).min()
            sl_price -= self.df['atr'].iloc[idx] * 0.5
            
            risk_distance = bar['close'] - sl_price
            if risk_distance <= 0: return None
            
            # 2. Calculate TP Levels
            tp_levels = get_resistance_levels(self.df, idx)
            
            # 3. Ensure TP1 Breakeven
            min_tp1 = bar['close'] + (risk_distance * 1.05)
            if tp_levels.get('TP1', 0) < min_tp1:
                tp_levels['TP1'] = min_tp1
                
            # Ensure TP2 is above TP1
            if tp_levels.get('TP2', 0) <= min_tp1:
                tp_levels['TP2'] = min_tp1 + (risk_distance * 1.5)

            # 4. Signal
            return {
                'idx': idx, 'type': 'breakout', 'entry_price': bar['close'],
                'sl_price': sl_price, 'risk_distance': risk_distance,
                'tp_levels': tp_levels,
                'limit_price': sl_price + risk_distance * 0.3 # Limit near support
            }
            
        return None
