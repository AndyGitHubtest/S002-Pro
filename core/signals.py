import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.math_utils import get_robust_pullback_low, calculate_atr, calculate_fractal_low

class SignalGenerator:
    def __init__(self, df: pd.DataFrame, config: dict, symbol: str = "BTC/USDT"):
        self.df = df
        self.config = config
        self.symbol = symbol
        
        # --- Pre-compute all indicators (Vectorized) ---
        
        # 1. ATR
        self.df['atr'] = calculate_atr(self.df, 14)
        
        # 2. Breakout Signal Base (Rolling High)
        self.df['rolling_high'] = self.df['high'].rolling(window=20).max().shift(1)
        
        # 3. Pre-compute Fractal Lows for Stop Loss (v2.5)
        # Williams Fractal: 5-bar pattern (2 lower lows on each side)
        self.df['fractal_low'] = calculate_fractal_low(self.df)
        
        # 4. Resistance Levels (Pre-calculated Rolling Maxs)
        self.df['tp1_raw'] = self.df['high'].rolling(window=20).max().shift(1)
        self.df['tp2_raw'] = self.df['high'].rolling(window=48).max().shift(1)
        self.df['tp3_raw'] = self.df['high'].rolling(window=144).max().shift(1)
        self.df['tp4_raw'] = self.df['high'].rolling(window=288).max().shift(1)
        self.df['tp5_raw'] = self.df['high'].rolling(window=576).max().shift(1)

    def check_signal(self, idx: int) -> dict | None:
        """
        Fast O(1) signal check using pre-computed columns.
        """
        if idx < 30: return None
        
        # Access row data directly
        row = self.df.iloc[idx]
        
        # Validate data
        if pd.isna(row['close']) or pd.isna(row['rolling_high']) or pd.isna(row['atr']):
            return None
        if row['atr'] <= 0:
            return None
        
        # 1. Check Breakout
        if row['close'] > row['rolling_high']:
            
            # 2. Calculate Stop Loss using Fractal Low (v2.5)
            # Use pre-computed fractal low if available, else fall back to recent low
            fractal_sl = row['fractal_low']
            atr_buffer = row['atr'] * 1.5  # 1.5 ATR buffer per spec
            
            if pd.notna(fractal_sl):
                sl_price = fractal_sl - atr_buffer
            else:
                # Fallback: use recent consolidation low
                consolidation_window = self.df.iloc[max(0, idx-30) : idx]
                if len(consolidation_window) < 5:
                    return None
                sl_price = consolidation_window['low'].min() - atr_buffer
            
            risk_distance = row['close'] - sl_price
            if risk_distance <= 0 or pd.isna(risk_distance): 
                return None
            # Prevent extreme risk distances
            if risk_distance > row['close'] * 0.1:  # Max 10% stop
                return None
            
            # 3. Fetch Pre-computed TP Levels
            tp_levels = {
                'TP1': row['tp1_raw'],
                'TP2': row['tp2_raw'],
                'TP3': row['tp3_raw'],
                'TP4': row['tp4_raw'],
                'TP5': row['tp5_raw']
            }
            
            # 4. Sanitize TP Levels (Must be above entry and ordered)
            min_tp1 = row['close'] + (risk_distance * 1.05)
            
            # Apply Breakeven Floor
            for k, v in tp_levels.items():
                if np.isnan(v): 
                    # Fallback if not enough history
                    tp_levels[k] = row['close'] + risk_distance * int(k[-1])
                elif v < min_tp1:
                    tp_levels[k] = min_tp1 + (risk_distance * (int(k[-1]) - 1) * 0.5)

            # 5. Signal
            return {
                'idx': idx, 'type': 'breakout', 'entry_price': row['close'],
                'sl_price': sl_price, 'risk_distance': risk_distance,
                'tp_levels': tp_levels,
                'limit_price': sl_price + risk_distance * 0.3
            }
            
        return None
