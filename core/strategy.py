import pandas as pd
import numpy as np
import uuid

class S002Position:
    """
    Represents a single open position in S002.
    Manages internal state: entry, SL, TP levels, time limit, trailing stop.
    """
    def __init__(self, symbol: str, entry_price: float, stop_price: float, 
                 quantity: float, risk_distance: float, entry_time: pd.Timestamp,
                 tp_levels: dict, config: dict):
        self.id = str(uuid.uuid4())
        self.symbol = symbol
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.quantity = quantity  # Target quantity
        self.remaining_qty = quantity  # Filled quantity
        self.entry_time = entry_time
        self.risk_distance = risk_distance
        
        # Config
        self.config = config
        self.max_hold_bars_unprofitable = config.get('max_hold_bars_unprofitable', 144)
        
        # TP Levels
        # { 'TP1': price, 'TP2': price, ..., 'TP6': None (trailing) }
        self.tp_levels = tp_levels
        self.tp_statuses = {k: False for k in tp_levels.keys()}
        
        # State
        self.tp1_triggered = False
        self.highest_price = entry_price
        self.hold_bars = 0
        self.trailing_stop_price = stop_price  # Initial SL is the trailing stop floor
        self.trailing_atr_mult = config.get('trailing_atr_mult', 2.0)

    def update(self, bar: pd.Series, current_atr: float):
        """Update position state with new bar data. Returns list of executed trades."""
        trades = []
        self.hold_bars += 1
        self.highest_price = max(self.highest_price, bar['high'])
        
        # 1. Check Stop Loss (Hard Stop)
        if bar['low'] <= self.stop_price: # Use Low to check stop hit
            return self.close_position(self.stop_price, 'STOP_LOSS', self.remaining_qty, trades)

        # 2. Check Time Limit (Only if not profitable/TP1 not hit)
        if not self.tp1_triggered and self.hold_bars > self.max_hold_bars_unprofitable:
            return self.close_position(bar['close'], 'TIME_STOP', self.remaining_qty, trades)

        # 3. Check Trailing Stop (TP6)
        # Logic: Trailing Stop should generally only tighten AFTER TP1 (Breakeven)
        if self.tp1_triggered:
            new_trailing = self.highest_price - (current_atr * self.trailing_atr_mult)
            if new_trailing > self.trailing_stop_price:
                self.trailing_stop_price = new_trailing
            
            if bar['low'] <= self.trailing_stop_price:
                return self.close_position(self.trailing_stop_price, 'TRAILING_STOP', self.remaining_qty, trades)

        # 4. Check Take Profits (TP1 - TP5)
        # TP6 is handled by trailing stop logic above
        for tp_name, tp_price in self.tp_levels.items():
            if tp_name == 'TP6' or tp_price is None:
                continue
            
            if not self.tp_statuses[tp_name]:
                if bar['high'] >= tp_price: # Use High to check TP hit
                    # Determine quantity to close
                    tp_ratio_map = {
                        'TP1': 0.35, 'TP2': 0.25, 'TP3': 0.20, 
                        'TP4': 0.10, 'TP5': 0.05
                    }
                    
                    close_qty = self.quantity * tp_ratio_map.get(tp_name, 0)
                    close_qty = min(close_qty, self.remaining_qty) # Safety
                    
                    if close_qty > 0.0001:
                        self.tp_statuses[tp_name] = True
                        trades.append({
                            'symbol': self.symbol,
                            'type': 'TP',
                            'level': tp_name,
                            'price': tp_price,
                            'qty': close_qty,
                            'pnl': (tp_price - self.entry_price) * close_qty
                        })
                        self.remaining_qty -= close_qty
                        
                        # Iron Rule: If TP1 triggered, move SL to Breakeven
                        if tp_name == 'TP1':
                            self.tp1_triggered = True
                            be_price = self.entry_price * 1.0005 
                            if be_price > self.stop_price:
                                self.stop_price = be_price
                                self.trailing_stop_price = be_price 
                                
                        if self.remaining_qty <= 0.0001:
                            # Fully closed
                            return trades

        return trades

    def close_position(self, price: float, reason: str, qty: float, trades: list):
        pnl = (price - self.entry_price) * qty
        trades.append({
            'symbol': self.symbol,
            'type': 'EXIT',
            'level': reason,
            'price': price,
            'qty': qty,
            'pnl': pnl
        })
        self.remaining_qty = 0
        return trades


class S002Engine:
    """
    Main Backtest Engine.
    Iterates through data, manages positions, executes signals.
    """
    def __init__(self, config: dict):
        self.config = config
        self.positions: list[S002Position] = []
        self.pending_orders = [] # For Hybrid Entry (Limit orders)
        self.balance = 10000.0  # Start balance
        self.trades_log = []
        
    def run(self, df: pd.DataFrame, signal_generator=None):
        """
        Run backtest on OHLCV dataframe.
        signal_generator: An instance of SignalGenerator.
        """
        for i in range(100, len(df)):  # Skip warmup
            bar = df.iloc[i]
            current_atr = df['atr'].iloc[i]
            
            # 1. Check Pending Orders (Hybrid Entry)
            filled_orders = []
            for order in self.pending_orders:
                # If low of current bar <= limit_price, order fills
                # Note: In a real bar, if low <= limit, we assume we got filled at limit
                if bar['low'] <= order['limit_price']:
                    print(f"[{df.index[i]}] Limit Order FILLED @ {order['limit_price']}")
                    
                    pos = next((p for p in self.positions if p.id == order['pos_id']), None)
                    if pos:
                        pos.remaining_qty += order['unfilled_qty']
                        self.trades_log.append({
                            'symbol': pos.symbol,
                            'type': 'LIMIT_FILL',
                            'price': order['limit_price'],
                            'qty': order['unfilled_qty'],
                            'pnl': 0
                        })
                    filled_orders.append(order)
            
            for o in filled_orders:
                self.pending_orders.remove(o)

            # 2. Update existing positions
            open_pos = []
            for pos in self.positions:
                if pos.remaining_qty > 0:
                    trades = pos.update(bar, current_atr)
                    self.trades_log.extend(trades)
                    if pos.remaining_qty > 0:
                        open_pos.append(pos)
            self.positions = open_pos
            
            # 3. Check for New Signals
            if signal_generator:
                signal = signal_generator.check_signal(i)
                if signal:
                    self.open_hybrid_position(signal, df.index[i])

        return self.trades_log

    def open_hybrid_position(self, signal: dict, entry_time: pd.Timestamp):
        """
        Logic:
        1. Instantly fill 30% at current price (Market).
        2. Place Limit Order for 70% at `limit_price`.
        """
        symbol = "BTC/USDT" 
        entry_price = signal['entry_price']
        total_qty = (self.balance * self.config['risk_per_trade']) / signal['risk_distance']
        
        instant_qty = total_qty * 0.30
        limit_qty = total_qty * 0.70
        
        # Create Position with 30% filled
        pos = S002Position(
            symbol=symbol,
            entry_price=entry_price,
            stop_price=signal['sl_price'],
            quantity=total_qty, # This is the TARGET size
            risk_distance=signal['risk_distance'],
            entry_time=entry_time,
            tp_levels=signal['tp_levels'],
            config=self.config
        )
        
        # Initial fill
        pos.remaining_qty = instant_qty
        self.positions.append(pos)
        
        self.trades_log.append({
            'symbol': symbol,
            'type': 'MARKET_FILL',
            'price': entry_price,
            'qty': instant_qty,
            'pnl': 0
        })
        
        # Place Pending Limit Order
        self.pending_orders.append({
            'pos_id': pos.id,
            'limit_price': signal['limit_price'],
            'unfilled_qty': limit_qty
        })
        
        print(f"[{entry_time}] SIGNAL: Entry @ {entry_price}, SL @ {signal['sl_price']}")
        print(f"           Instant 30% ({instant_qty:.2f}), Limit 70% @ {signal['limit_price']}")
