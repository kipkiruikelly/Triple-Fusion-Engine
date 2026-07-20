import time
import logging
import threading
from datetime import datetime

log = logging.getLogger(__name__)

def start_manual_paper_engine(app):
    """Starts the background loop for manual paper trading order execution."""
    t = threading.Thread(target=_manual_paper_loop, args=(app,), daemon=True, name="manual-paper-engine")
    t.start()
    log.info("Started manual paper trading engine loop")

def _manual_paper_loop(app):
    # Only import yfinance inside the thread
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed, manual paper engine exiting.")
        return

    while True:
        try:
            with app.app_context():
                from extensions import db
                from models import UserPaperAccount, UserPaperOrder, UserPaperPosition
                
                # Get all pending orders and open positions to find which tickers we need to fetch
                pending_orders = UserPaperOrder.query.filter_by(status="pending").all()
                open_positions = UserPaperPosition.query.filter_by(status="open").all()
                
                tickers_needed = set([o.ticker for o in pending_orders] + [p.ticker for p in open_positions])
                
                if not tickers_needed:
                    time.sleep(10)
                    continue
                
                # Fetch live prices
                live_prices = {}
                for t in tickers_needed:
                    try:
                        # Attempt to get fast info last_price
                        tick = yf.Ticker(t)
                        price = float(tick.fast_info.last_price or 0)
                        if price > 0:
                            live_prices[t] = price
                    except Exception as e:
                        log.debug(f"Failed to fetch price for {t}: {e}")
                
                # Process pending orders
                for order in pending_orders:
                    price = live_prices.get(order.ticker)
                    if not price: continue
                    
                    fill = False
                    if order.order_type == "market":
                        fill = True
                    elif order.order_type == "limit":
                        if order.side == "buy" and price <= order.target_price:
                            fill = True
                        elif order.side == "sell" and price >= order.target_price:
                            fill = True
                    elif order.order_type == "stop":
                        if order.side == "buy" and price >= order.target_price:
                            fill = True
                        elif order.side == "sell" and price <= order.target_price:
                            fill = True
                            
                    if fill:
                        acc = UserPaperAccount.query.get(order.account_id)
                        
                        # Market close logic (pseudo market order)
                        # Find open positions for this ticker in opposite side to close
                        opposite_side = "sell" if order.side == "buy" else "buy"
                        existing_pos = UserPaperPosition.query.filter_by(
                            account_id=acc.id, ticker=order.ticker, status="open", side=opposite_side
                        ).first()
                        
                        cost = order.quantity * price
                        
                        # Apply slippage/commission simulation ($1 per trade roughly)
                        commission = 1.0
                        
                        if existing_pos:
                            # Closing an existing position
                            pnl = 0
                            if existing_pos.side == "buy": # we are selling to close
                                pnl = (price - existing_pos.entry_price) * existing_pos.quantity
                            else: # we are buying to close
                                pnl = (existing_pos.entry_price - price) * existing_pos.quantity
                                
                            existing_pos.status = "closed"
                            existing_pos.closed_at = datetime.utcnow()
                            existing_pos.current_price = price
                            existing_pos.realized_pnl = round(pnl - commission, 2)
                            
                            acc.balance += existing_pos.realized_pnl
                        else:
                            # Opening a new position
                            new_pos = UserPaperPosition(
                                account_id=acc.id, ticker=order.ticker, side=order.side,
                                quantity=order.quantity, entry_price=price, current_price=price,
                                sl=order.sl, tp=order.tp
                            )
                            db.session.add(new_pos)
                            acc.balance -= commission # Deduct commission from balance
                            
                        order.status = "filled"
                        order.filled_at = datetime.utcnow()
                
                # Process open positions for SL/TP
                for pos in open_positions:
                    price = live_prices.get(pos.ticker)
                    if not price: continue
                    
                    pos.current_price = price
                    
                    close = False
                    if pos.side == "buy":
                        if pos.sl and price <= pos.sl: close = True
                        if pos.tp and price >= pos.tp: close = True
                    else:
                        if pos.sl and price >= pos.sl: close = True
                        if pos.tp and price <= pos.tp: close = True
                        
                    if close:
                        acc = UserPaperAccount.query.get(pos.account_id)
                        pnl = 0
                        commission = 1.0
                        if pos.side == "buy":
                            pnl = (price - pos.entry_price) * pos.quantity
                        else:
                            pnl = (pos.entry_price - price) * pos.quantity
                            
                        pos.status = "closed"
                        pos.closed_at = datetime.utcnow()
                        pos.realized_pnl = round(pnl - commission, 2)
                        acc.balance += pos.realized_pnl
                
                # Update all active accounts equity
                accounts = UserPaperAccount.query.all()
                for acc in accounts:
                    open_pos = UserPaperPosition.query.filter_by(account_id=acc.id, status="open").all()
                    unrealized_pnl = 0.0
                    for p in open_pos:
                        curr = live_prices.get(p.ticker, p.current_price)
                        if p.side == "buy":
                            unrealized_pnl += (curr - p.entry_price) * p.quantity
                        else:
                            unrealized_pnl += (p.entry_price - curr) * p.quantity
                    acc.equity = acc.balance + unrealized_pnl
                
                db.session.commit()
                
        except Exception as e:
            log.error(f"Manual paper engine error: {e}")
            
        time.sleep(10)
