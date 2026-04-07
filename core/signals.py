import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.math_utils import get_robust_pullback_low, calculate_atr

class SignalGenerator:
    def __init__(self, df: pd.DataFrame, config: dict):
        self.df = df
        self.config = config
        
        # --- Pre-compute all indicators (Vectorized) ---
        # This avoids O(N) calculations inside the loop
        
        # 1. ATR
        self.df['atr'] = calculate_atr(self.df, 14)
        
        # 2. Breakout Signal Base (Rolling High)
        # Lookback 20 bars (approx 1.5 hours for 5m)
        self.df['rolling_high'] = self.df['high'].rolling(window=20).max().shift(1)
        
        # 3. Resistance Levels (Pre-calculated Rolling Maxs)
        # TP1: Local High (20 bars)
        # TP2: 4h High (48 bars)
        # TP3: 12h High (144 bars)
        # TP4: 24h High (288 bars)
        # TP5: 48h High (576 bars)
        
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
            
            # 2. Calculate Stop Loss (Dynamic based on recent consolidation)
            consolidation_window = self.df.iloc[max(0, idx-50) : idx]
            if len(consolidation_window) < 5:
                return None
                
            # Simple fast approximation: min of lows
            sl_price = consolidation_window['low'].min() - row['atr'] * 0.5
            
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
