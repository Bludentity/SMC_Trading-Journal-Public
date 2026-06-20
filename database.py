"""Database layer for trades and settings."""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import pytz

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Text, Float, select, insert, update, delete, text
)
from sqlalchemy.exc import OperationalError, IntegrityError, InternalError
from urllib.parse import urlparse, urlunparse, quote

load_dotenv()

EAT = pytz.timezone("Africa/Nairobi")

DEFAULT_PAIRS = ["XAUUSD", "EURUSD"]
DEFAULT_TIMEFRAMES = ["1D", "4H", "30M", "15M"]
DEFAULT_MODULES = [
    "[Bullish] Inducement Sweep (Liquidity Taken Below)",
    "[Bearish] Inducement Sweep (Liquidity Taken Above)",
    "[Bullish] Engineering Liquidity Sweep (Lows)",
    "[Bearish] Engineering Liquidity Sweep (Highs)",
    "Decisional Order Block (OB) Mitigation",
    "Decisional Order Flow (OF) Mitigation",
    "Extreme Order Block (OB) Mitigation",
    "Extreme Order Flow (OF) Mitigation",
    "Origin Order Block (OB) Mitigation",
    "Bullish Fair Value Gap (bFVG)",
    "Bearish Fair Value Gap (bFVG)",
    "Fibonacci Optimal Entry Zone (0.5 - 0.62)",
]
DEFAULT_LEVELS = [
    "Upper Limit",
    "Lower Limit",
    "Mean Threshold / Middle Limit",
    "0.5 Fibonacci Level",
    "0.62 Fibonacci Level",
    "Fib Mid-Threshold",
]

_METADATA = MetaData()
_ENGINE = None


def _append_sslmode_if_needed(url: str) -> str:
    if not url:
        return url
    low = url.lower()
    if ("postgres" in low or "postgresql" in low) and "sslmode" not in low:
        return url + ("&sslmode=require" if "?" in url else "?sslmode=require")
    return url


def _sanitize_db_url(url: str) -> str:
    try:
        p = urlparse(url)
        # only handle netloc with username:password@host
        if p.username and p.password:
            # quote the password if it contains unsafe characters or spaces
            pwd = p.password
            if any(c.isspace() for c in pwd) or '@' in pwd or ':' in pwd or '%' in pwd:
                enc = quote(pwd, safe='')
                # rebuild netloc
                user = p.username
                host = p.hostname or ''
                port = f":{p.port}" if p.port else ''
                netloc = f"{user}:{enc}@{host}{port}"
                new = p._replace(netloc=netloc)
                return urlunparse(new)
    except Exception:
        pass
    return url


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    db_url = os.environ.get("DATABASE_URL")
    if getattr(sys, 'frozen', False):
        # Try loading .env from custom SMC_BASE_DIR first, then exe dir
        candidates = []
        smc_base = os.environ.get('SMC_BASE_DIR')
        if smc_base:
            candidates.append(os.path.join(smc_base, '.env'))
        # check common install location under Program Files
        prog = os.environ.get('ProgramFiles') or r'C:\Program Files'
        candidates.append(os.path.join(prog, 'SMC_Journal', '.env'))
        # finally check the executable directory (onefile temp dir)
        candidates.append(os.path.join(os.path.dirname(sys.executable), '.env'))
        for dot in candidates:
            try:
                if os.path.exists(dot):
                    load_dotenv(dot)
                    db_url = os.environ.get('DATABASE_URL')
                    break
            except Exception:
                pass

    try:
        if db_url:
            db_url = _sanitize_db_url(db_url)
            db_url = _append_sslmode_if_needed(db_url)
            try:
                eng = create_engine(db_url, pool_pre_ping=True)
                with eng.connect() as c:
                    pass
                _ENGINE = eng
                return _ENGINE
            except OperationalError as e:
                # Log connection failure to a writable errors.log when frozen
                try:
                    if getattr(sys, 'frozen', False):
                        smc_base = os.environ.get('SMC_BASE_DIR')
                        if smc_base:
                            data_dir = smc_base
                        else:
                            local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
                            data_dir = os.path.join(local, 'SMC_Journal')
                        os.makedirs(data_dir, exist_ok=True)
                        elog = os.path.join(data_dir, 'errors.log')
                        with open(elog, 'a', encoding='utf-8') as ef:
                            ef.write(f"[DB CONNECT ERROR] {str(e)}\n")
                except Exception:
                    pass
                # fall back to sqlite
    except OperationalError:
        pass

    if getattr(sys, 'frozen', False):
        # Prefer SMC_BASE_DIR for sqlite storage when frozen, else LocalAppData
        base = os.environ.get('SMC_BASE_DIR')
        if not base:
            local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
            base = os.path.join(local, 'SMC_Journal')
        os.makedirs(base, exist_ok=True)
    else:
        base = os.getcwd()
    sqlite_path = os.path.join(base, 'smc_backtest.db')
    eng = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})
    _ENGINE = eng
    return _ENGINE


# Table definitions
pairs = Table('pairs', _METADATA, Column('pair_name', String, primary_key=True))

timeframes = Table('timeframes', _METADATA, Column('tf_name', String, primary_key=True))

entry_modules = Table('entry_modules', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('module_name', String, unique=True, nullable=False))

reversal_levels = Table('reversal_levels', _METADATA,
                        Column('id', Integer, primary_key=True, autoincrement=True),
                        Column('level_name', String, unique=True, nullable=False))

trades = Table('trades', _METADATA,
               Column('id', Integer, primary_key=True, autoincrement=True),
               Column('pair', String, nullable=False),
               Column('timeframe', String, nullable=False),
               Column('direction', String, nullable=False),
               Column('session', String),
               Column('execution_time_eat', String, nullable=False),
               Column('entry_modules', Text, nullable=False),
               Column('dynamic_entry_zones', Text),
               Column('actual_reversal_zone', Text),
               Column('actual_reversal_custom', Text),
               Column('reversal_level', Text),
               Column('outcome', String, nullable=False),
               Column('exact_entry_price', Float),
               Column('exact_sl_price', Float),
               Column('exact_tp_price', Float),
               Column('planned_sl_pips', Float, nullable=False),
               Column('planned_tp_pips', Float, nullable=False),
               Column('planned_rr', Float, nullable=False),
               Column('net_r', Float, nullable=False),
               Column('actual_mae_pips', Float),
               Column('actual_mfe_pips', Float),
               Column('sl_placement_desc', Text),
               Column('tp_placement_desc', Text),
               Column('entry_reversal_notes', Text),
               Column('notes', Text),
               Column('created_at', String, nullable=False),
               )

webhook_queue = Table('webhook_queue', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('payload', Text, nullable=False),
                      Column('received_at', String, nullable=False),
                      Column('status', String, nullable=False, default='pending'))


# New table for storing screenshots attached to trades (backwards-compatible)
trade_screenshots = Table('trade_screenshots', _METADATA,
                          Column('id', Integer, primary_key=True, autoincrement=True),
                          Column('trade_id', Integer, nullable=False),
                          Column('filename', String, nullable=False),
                          Column('created_at', String, nullable=False))

# Remote (blob) screenshot storage
trade_screenshots_blob = Table('trade_screenshots_blob', _METADATA,
                               Column('id', Integer, primary_key=True, autoincrement=True),
                               Column('trade_id', Integer, nullable=False),
                               Column('filename', String, nullable=False),
                               Column('data', Text, nullable=False),
                               Column('created_at', String, nullable=False))


def init_db():
    eng = _get_engine()
    _METADATA.create_all(eng)

    # seeds: each insert is idempotent and uses a safe strategy to avoid aborted transactions
    try:
        for p in DEFAULT_PAIRS:
            try:
                with eng.begin() as conn:
                    conn.execute(insert(pairs).values(pair_name=p))
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    with eng.begin() as conn:
                        conn.execute(insert(pairs).values(pair_name=p))
                except Exception:
                    pass

        for t in DEFAULT_TIMEFRAMES:
            try:
                with eng.begin() as conn:
                    conn.execute(insert(timeframes).values(tf_name=t))
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    with eng.begin() as conn:
                        conn.execute(insert(timeframes).values(tf_name=t))
                except Exception:
                    pass

        for m in DEFAULT_MODULES:
            try:
                with eng.begin() as conn:
                    conn.execute(insert(entry_modules).values(module_name=m))
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    with eng.begin() as conn:
                        conn.execute(insert(entry_modules).values(module_name=m))
                except Exception:
                    pass

        for lv in DEFAULT_LEVELS:
            try:
                with eng.begin() as conn:
                    conn.execute(insert(reversal_levels).values(level_name=lv))
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    with eng.begin() as conn:
                        conn.execute(insert(reversal_levels).values(level_name=lv))
                except Exception:
                    pass
    except Exception:
        try:
            eng.dispose()
        except Exception:
            pass


# Utility
def now_eat_str():
    return datetime.now(EAT).strftime("%Y-%m-%d %H:%M:%S")


def compute_net_r(outcome, planned_rr):
    try:
        planned_rr = float(planned_rr)
    except Exception:
        planned_rr = 0.0
    if outcome == 'Win':
        return float(planned_rr)
    if outcome == 'Loss':
        return -1.0
    return 0.0


# Settings: pairs/timeframes/modules/levels
def get_pairs():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(pairs.c.pair_name).order_by(pairs.c.pair_name)).fetchall()
        return [r[0] for r in rows]


def add_pair(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(pairs).values(pair_name=name))
        except IntegrityError:
            pass
    return name


def delete_pair(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.pair == name).limit(1)).fetchone()
        if r:
            return False, 'Pair is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(pairs).where(pairs.c.pair_name == name))
    return True, None


def get_timeframes():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(timeframes.c.tf_name).order_by(timeframes.c.tf_name)).fetchall()
        return [r[0] for r in rows]


def add_timeframe(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(timeframes).values(tf_name=name))
        except IntegrityError:
            pass
    return name


def delete_timeframe(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.timeframe == name).limit(1)).fetchone()
        if r:
            return False, 'Timeframe is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(timeframes).where(timeframes.c.tf_name == name))
    return True, None


def get_entry_modules():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(entry_modules.c.id, entry_modules.c.module_name).order_by(entry_modules.c.id)).fetchall()
        return [dict(id=r[0], module_name=r[1]) for r in rows]


def add_entry_module(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=name))
        except IntegrityError:
            pass
    return name


def delete_entry_module(module_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(entry_modules.c.module_name).where(entry_modules.c.id == module_id)).fetchone()
        if not row:
            return False, 'Module not found.'
        modname = row[0]
        rows = conn.execute(select(trades.c.entry_modules)).fetchall()
        for t in rows:
            try:
                if modname in json.loads(t[0] or '[]'):
                    return False, 'Module is referenced by existing trades and cannot be deleted.'
            except Exception:
                pass
        conn.execute(delete(entry_modules).where(entry_modules.c.id == module_id))
    return True, None


def get_reversal_levels():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(reversal_levels.c.id, reversal_levels.c.level_name).order_by(reversal_levels.c.id)).fetchall()
        return [dict(id=r[0], level_name=r[1]) for r in rows]


def add_reversal_level(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(reversal_levels).values(level_name=name))
        except IntegrityError:
            pass
    return name


def delete_reversal_level(level_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(reversal_levels.c.level_name).where(reversal_levels.c.id == level_id)).fetchone()
        if not row:
            return False, 'Level not found.'
        conn.execute(delete(reversal_levels).where(reversal_levels.c.id == level_id))
    return True, None


# Trades
def insert_trade(data):
    modules = json.dumps(data['entry_modules']) if isinstance(data['entry_modules'], list) else data['entry_modules']
    zones = json.dumps(data.get('dynamic_entry_zones')) if isinstance(data.get('dynamic_entry_zones'), dict) else (data.get('dynamic_entry_zones') or '{}')
    net_r = compute_net_r(data['outcome'], data['planned_rr'])
    eat_time = data.get('execution_time') or now_eat_str()

    def _f(key):
        v = data.get(key)
        try:
            return float(v) if v not in (None, '') else None
        except Exception:
            return None

    eng = _get_engine()
    with eng.begin() as conn:
        res = conn.execute(insert(trades).values(
            pair=data['pair'].upper(),
            timeframe=data['timeframe'],
            direction=data['direction'],
            session=data.get('session') or None,
            execution_time_eat=eat_time,
            entry_modules=modules,
            dynamic_entry_zones=zones,
            actual_reversal_zone=data.get('actual_reversal_zone') or None,
            actual_reversal_custom=data.get('actual_reversal_custom') or None,
            outcome=data['outcome'],
            exact_entry_price=_f('exact_entry_price'),
            exact_sl_price=_f('exact_sl_price'),
            exact_tp_price=_f('exact_tp_price'),
            planned_sl_pips=float(data['planned_sl_pips']),
            planned_tp_pips=float(data['planned_tp_pips']),
            planned_rr=float(data['planned_rr']),
            net_r=net_r,
            actual_mae_pips=_f('actual_mae_pips'),
            actual_mfe_pips=_f('actual_mfe_pips'),
            sl_placement_desc=data.get('sl_placement_desc') or None,
            tp_placement_desc=data.get('tp_placement_desc') or None,
            entry_reversal_notes=data.get('entry_reversal_notes') or None,
            notes=data.get('notes') or None,
            created_at=now_eat_str(),
        ))
        try:
            return int(res.inserted_primary_key[0])
        except Exception:
            return None


def update_trade(trade_id, data: dict):
    """Update allowed trade fields using SQLAlchemy update. Returns True on success."""
    allowed = {
        'pair', 'timeframe', 'direction', 'session', 'execution_time_eat',
        'entry_modules', 'dynamic_entry_zones', 'actual_reversal_zone', 'actual_reversal_custom',
        'reversal_level',
        'outcome', 'exact_entry_price', 'exact_sl_price', 'exact_tp_price',
        'planned_sl_pips', 'planned_tp_pips', 'planned_rr', 'net_r',
        'actual_mae_pips', 'actual_mfe_pips', 'sl_placement_desc', 'tp_placement_desc',
        'entry_reversal_notes', 'notes'
    }
    to_update = {k: v for k, v in data.items() if k in allowed}
    if not to_update:
        return False
    # compute net_r if outcome or planned_rr changed
    if 'outcome' in to_update or 'planned_rr' in to_update:
        outcome = to_update.get('outcome')
        planned_rr = to_update.get('planned_rr')
        # fetch existing values if missing
        existing = get_trade(trade_id) or {}
        outcome = outcome if outcome is not None else existing.get('outcome')
        planned_rr = planned_rr if planned_rr is not None else existing.get('planned_rr')
        try:
            to_update['net_r'] = compute_net_r(outcome, planned_rr)
        except Exception:
            to_update['net_r'] = 0.0

    eng = _get_engine()
    # normalize certain fields to storage format
    if 'entry_modules' in to_update:
        if isinstance(to_update['entry_modules'], list):
            to_update['entry_modules'] = json.dumps(to_update['entry_modules'])
        else:
            to_update['entry_modules'] = to_update['entry_modules'] or '[]'
    if 'dynamic_entry_zones' in to_update:
        v = to_update['dynamic_entry_zones']
        if isinstance(v, dict):
            to_update['dynamic_entry_zones'] = json.dumps(v)
        elif isinstance(v, str):
            to_update['dynamic_entry_zones'] = v or '{}'
        else:
            to_update['dynamic_entry_zones'] = '{}'

    with eng.begin() as conn:
        conn.execute(update(trades).where(trades.c.id == trade_id).values(**to_update))
    return True


def get_all_trades():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(trades).order_by(trades.c.id.desc())).fetchall()
        out = []
        for r in res:
            out.append(dict(r._mapping))
        return out


def get_trade(trade_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(trades).where(trades.c.id == trade_id)).fetchone()
        return dict(row._mapping) if row else None


def delete_trade(trade_id):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(delete(trades).where(trades.c.id == trade_id))


def delete_trades_bulk(ids):
    """Delete multiple trades in a single transaction."""
    if not ids:
        return 0
    eng = _get_engine()
    with eng.begin() as conn:
        res = conn.execute(delete(trades).where(trades.c.id.in_(ids)))
        try:
            return res.rowcount if hasattr(res, 'rowcount') else 0
        except Exception:
            return 0


# Webhook queue
def queue_webhook(payload_str):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(insert(webhook_queue).values(payload=payload_str, received_at=now_eat_str(), status='pending'))


def get_pending_webhooks():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(webhook_queue).where(webhook_queue.c.status == 'pending').order_by(webhook_queue.c.id.desc())).fetchall()
        return [dict(r._mapping) for r in res]


def dismiss_webhook(wid):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(update(webhook_queue).where(webhook_queue.c.id == wid).values(status='dismissed'))


def insert_screenshot(trade_id, filename):
    eng = _get_engine()
    try:
        with eng.begin() as conn:
            conn.execute(insert(trade_screenshots).values(trade_id=trade_id, filename=filename, created_at=now_eat_str()))
    except OperationalError as e:
        if 'no such table' in str(e).lower():
            try:
                init_db()
            except Exception:
                pass
            with _get_engine().begin() as conn:
                conn.execute(insert(trade_screenshots).values(trade_id=trade_id, filename=filename, created_at=now_eat_str()))
        else:
            raise


def insert_screenshot_blob(trade_id, filename, b64data):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(insert(trade_screenshots_blob).values(trade_id=trade_id, filename=filename, data=b64data, created_at=now_eat_str()))


def delete_screenshot_by_id(sid):
    """Delete screenshot by id from either local table or blob table. Returns True if deleted."""
    eng = _get_engine()
    with eng.begin() as conn:
        # try local table first
        row = conn.execute(select(trade_screenshots).where(trade_screenshots.c.id == sid)).fetchone()
        if row:
            fname = row._mapping.get('filename')
            conn.execute(delete(trade_screenshots).where(trade_screenshots.c.id == sid))
            # remove file if exists
            try:
                base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
                path = os.path.join(base, 'uploads', fname)
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            return True

        # try blob table
        brow = conn.execute(select(trade_screenshots_blob).where(trade_screenshots_blob.c.id == sid)).fetchone()
        if brow:
            conn.execute(delete(trade_screenshots_blob).where(trade_screenshots_blob.c.id == sid))
            return True
    return False


def get_screenshots(trade_id):
    eng = _get_engine()
    try:
        out = []
        with eng.connect() as conn:
            rows = conn.execute(select(trade_screenshots).where(trade_screenshots.c.trade_id == trade_id).order_by(trade_screenshots.c.id.desc())).fetchall()
            for r in rows:
                m = dict(r._mapping)
                m['storage'] = 'local'
                out.append(m)
            # include remote blobs
            try:
                brow = conn.execute(select(trade_screenshots_blob).where(trade_screenshots_blob.c.trade_id == trade_id).order_by(trade_screenshots_blob.c.id.desc())).fetchall()
                for r in brow:
                    m = dict(r._mapping)
                    m['storage'] = 'remote'
                    out.append(m)
            except Exception:
                pass
        return out
    except OperationalError as e:
        if 'no such table' in str(e).lower():
            try:
                init_db()
            except Exception:
                pass
            eng2 = _get_engine()
            out2 = []
            with eng2.connect() as conn:
                rows = conn.execute(select(trade_screenshots).where(trade_screenshots.c.trade_id == trade_id).order_by(trade_screenshots.c.id.desc())).fetchall()
                for r in rows:
                    m = dict(r._mapping)
                    m['storage'] = 'local'
                    out2.append(m)
                try:
                    brow = conn.execute(select(trade_screenshots_blob).where(trade_screenshots_blob.c.trade_id == trade_id).order_by(trade_screenshots_blob.c.id.desc())).fetchall()
                    for r in brow:
                        m = dict(r._mapping)
                        m['storage'] = 'remote'
                        out2.append(m)
                except Exception:
                    pass
            return out2
        raise


def get_screenshot_blob(sid):
    eng = _get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(select(trade_screenshots_blob).where(trade_screenshots_blob.c.id == sid)).fetchone()
            return dict(row._mapping) if row else None
    except OperationalError as e:
        if 'no such table' in str(e).lower():
            try:
                init_db()
            except Exception:
                pass
            with _get_engine().connect() as conn:
                row = conn.execute(select(trade_screenshots_blob).where(trade_screenshots_blob.c.id == sid)).fetchone()
                return dict(row._mapping) if row else None
        raise


# Ensure tables exist on import (helps frozen exe that may run from different CWD)
try:
    _METADATA.create_all(_get_engine())
except Exception:
    try:
        # best-effort: ignore failures during import time
        pass
    except Exception:
        pass


# CSV import & AI export utilities
IMPORT_PLACEHOLDER_MODULE = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_LEVEL = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_SESSION = "London"
IMPORT_PLACEHOLDER_TF = "IMPORT"


def _clean(val):
    if val is None:
        return ""
    return val.strip().replace("\ufeff", "").strip()


def _clean_num(val):
    if val is None:
        return ""
    return str(val).strip().replace(",", "").replace("$", "").replace("%", "").replace("\ufeff", "").strip()


def _parse_float(val, default=0.0):
    try:
        return float(_clean_num(str(val)))
    except (ValueError, TypeError):
        return default


def _to_eat(dt_str):
    dt_str = _clean(dt_str)
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return pytz.utc.localize(dt).astimezone(EAT).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return now_eat_str()


def _get_col(row, key, default=""):
    key_low = key.strip().lower()
    for k, v in row.items():
        if k.strip().lower() == key_low:
            return v if v is not None else default
    return default


def _ensure_import_placeholders():
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=IMPORT_PLACEHOLDER_MODULE))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(reversal_levels).values(level_name=IMPORT_PLACEHOLDER_LEVEL))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(timeframes).values(tf_name=IMPORT_PLACEHOLDER_TF))
        except IntegrityError:
            pass


def _trade_exists(conn, pair, direction, eat_time):
    r = conn.execute(select(trades.c.id).where(
        (trades.c.pair == pair) & (trades.c.direction == direction) & (trades.c.execution_time_eat == eat_time)
    ).limit(1)).fetchone()
    return r is not None


def _detect_format(headers):
    h = [x.strip().lower() for x in headers]
    if any("trade #" in x or "trade#" in x for x in h):
        return "strategy"
    if "side" in h and "fill price" in h:
        return "replay"
    return "unknown"


def _parse_strategy(rows):
    groups = {}
    for row in rows:
        for k in row:
            if "trade" in k.lower() and ("#" in k or "num" in k.lower()):
                groups.setdefault(_clean(row[k]), []).append(row)
                break

    trades_out = []
    for num, group_rows in groups.items():
        entry_row = next((r for r in group_rows if "entry" in _get_col(r, "type", "").lower()), None)
        exit_row = next((r for r in group_rows if "exit" in _get_col(r, "type", "").lower()), None)
        if not entry_row:
            continue

        direction = "Bullish" if "long" in _get_col(entry_row, "type", "").lower() else "Bearish"
        pair = _get_col(entry_row, "symbol", "UNKNOWN").strip().split(".")[0].upper() or "UNKNOWN"
        eat_time = _to_eat(
            _get_col(entry_row, "date/time", "") or
            _get_col(entry_row, "datetime", "") or
            _get_col(entry_row, "time", "")
        )

        entry_px = _parse_float(_get_col(entry_row, "price", "0"))
        exit_px = _parse_float(_get_col(exit_row, "price", "0")) if exit_row else None
        contracts = _parse_float(_get_col(entry_row, "contracts", "1"), 1.0)

        mfe = abs(_parse_float(_get_col(exit_row or entry_row, "run-up", "0")))
        mae = abs(_parse_float(_get_col(exit_row or entry_row, "drawdown", "0")))

        profit = _parse_float(_get_col(exit_row or entry_row, "profit", "0"))
        prof_pct = _parse_float(
            _get_col(exit_row or entry_row, "profit %", None) or
            _get_col(exit_row or entry_row, "profit(%)", "0")
        )

        outcome = "Win" if profit > 0 else ("Loss" if profit < 0 else "Break-Even")
        planned_rr = round(abs(prof_pct) / 100, 4) if prof_pct != 0 else round(abs(profit), 2)
        net_r = compute_net_r(outcome, planned_rr)

        trades_out.append({
            "pair": pair, "direction": direction, "eat_time": eat_time,
            "entry_px": entry_px,
            "exact_sl_px": exit_px if outcome == "Loss" else None,
            "exact_tp_px": exit_px if outcome == "Win" else None,
            "outcome": outcome, "planned_rr": planned_rr, "net_r": net_r,
            "mae": mae if mae > 0 else None,
            "mfe": mfe if mfe > 0 else None,
            "notes": (
                f"TV Strategy Import | Entry: {entry_px} | Exit: {exit_px} | "
                f"Contracts: {contracts} | Profit: {profit} | Profit%: {prof_pct}"
            ),
        })
    return trades_out


def _parse_replay(rows):
    from collections import defaultdict
    open_positions = defaultdict(list)
    trades_out = []

    for row in rows:
        side = _clean(_get_col(row, "side", "")).lower()
        symbol = _get_col(row, "symbol", "UNKNOWN").strip().split(".")[0].upper()
        qty = _parse_float(_get_col(row, "qty", "1"), 1.0)
        price = _parse_float(_get_col(row, "fill price", "0"))
        pnl = _parse_float(_get_col(row, "p&l", None) or _get_col(row, "pnl", "0"))
        eat_t = _to_eat(_get_col(row, "time", "") or _get_col(row, "date/time", ""))

        if side in ("buy", "long"):
            open_positions[symbol].append({"price": price, "qty": qty, "time": eat_t})

        elif side in ("sell", "short") and open_positions[symbol]:
            entry = open_positions[symbol].pop(0)
            profit_pts = price - entry["price"]
            effective = pnl if pnl != 0 else profit_pts
            outcome = "Win" if effective > 0 else ("Loss" if effective < 0 else "Break-Even")
            rr = round(abs(profit_pts / max(entry["price"] * 0.001, 0.0001)), 4)

            trades_out.append({
                "pair": symbol, "direction": "Bullish",
                "eat_time": entry["time"],
                "entry_px": entry["price"],
                "exact_sl_px": price if outcome == "Loss" else None,
                "exact_tp_px": price if outcome == "Win" else None,
                "outcome": outcome, "planned_rr": rr, "net_r": compute_net_r(outcome, rr),
                "mae": None, "mfe": None,
                "notes": (
                    f"TV Replay Import | Entry: {entry['price']} | Exit: {price} | "
                    f"Qty: {qty} | P&L: {pnl}"
                ),
            })
    return trades_out


def import_tradingview_csv(content):
    import csv, io
    _ensure_import_placeholders()
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return 0, 0, ["CSV file is empty or unreadable."]

    fmt = _detect_format(reader.fieldnames or [])
    if fmt == "strategy":
        parsed = _parse_strategy(rows)
    elif fmt == "replay":
        parsed = _parse_replay(rows)
    else:
        return 0, 0, ["Unrecognised CSV format. Expected Strategy Tester or Replay Trading export."]

    inserted, skipped, errors = 0, 0, []
    eng = _get_engine()
    with eng.begin() as conn:
        for t in parsed:
            conn.execute(insert(pairs).values(pair_name=t['pair']))
            if _trade_exists(conn, t['pair'], t['direction'], t['eat_time']):
                skipped += 1
                continue
            try:
                conn.execute(insert(trades).values(
                    pair=t['pair'],
                    timeframe=IMPORT_PLACEHOLDER_TF,
                    direction=t['direction'],
                    session=IMPORT_PLACEHOLDER_SESSION,
                    execution_time_eat=t['eat_time'],
                    entry_modules=json.dumps([IMPORT_PLACEHOLDER_MODULE]),
                    dynamic_entry_zones='{}',
                    actual_reversal_zone=None,
                    actual_reversal_custom=None,
                    outcome=t['outcome'],
                    exact_entry_price=t.get('entry_px'),
                    exact_sl_price=t.get('exact_sl_px'),
                    exact_tp_price=t.get('exact_tp_px'),
                    planned_sl_pips=0.0,
                    planned_tp_pips=0.0,
                    planned_rr=t['planned_rr'],
                    net_r=t['net_r'],
                    actual_mae_pips=t.get('mae'),
                    actual_mfe_pips=t.get('mfe'),
                    sl_placement_desc=None,
                    tp_placement_desc=None,
                    entry_reversal_notes=None,
                    notes=t.get('notes'),
                    created_at=now_eat_str(),
                ))
                inserted += 1
            except Exception as e:
                errors.append(str(e))
    return inserted, skipped, errors


def generate_ai_export(ids=None):
    # if ids provided, fetch only those trades in the given order; otherwise all
    if ids:
        eng = _get_engine()
        with eng.connect() as conn:
            rows = conn.execute(select(trades).where(trades.c.id.in_(ids)).order_by(trades.c.id.asc())).fetchall()
            trades_all = [dict(r._mapping) for r in rows]
    else:
        trades_all = get_all_trades()
    if not trades_all:
        return "No trades recorded yet."

    records = []
    for t in reversed(trades_all):
        try:
            modules = json.loads(t.get('entry_modules') or '[]')
        except Exception:
            modules = []
        modules_str = ", ".join(modules) if modules else "N/A"

        try:
            zones_raw = json.loads(t.get('dynamic_entry_zones') or '{}')
            zones_str = "; ".join([f"{mod}: {lvl}" for mod, lvl in zones_raw.items() if lvl and lvl != 'N/A']) or 'N/A'
        except Exception:
            zones_str = 'N/A'

        reversal = t.get('actual_reversal_custom') or t.get('actual_reversal_zone') or 'N/A'

        eat_display = t.get('execution_time_eat') or 'N/A'
        if isinstance(eat_display, str) and len(eat_display) > 8:
            try:
                eat_display = datetime.strptime(eat_display, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M EAT")
            except Exception:
                pass

        def _v(key, default='N/A'):
            val = t.get(key)
            return str(val) if val is not None else default

        records.append(
            f"RECORD_{t['id']}: "
            f"ID: {t['id']} | Pair: {t['pair']} | TF: {t['timeframe']} | Dir: {t['direction']} | "
            f"Session: {t.get('session') or 'N/A'} | Time: {eat_display} | "
            f"Modules: [{modules_str}] | Entry_Zones: [{zones_str}] | "
            f"Reversal_Zone: {reversal} | "
            f"Entry_Px: {_v('exact_entry_price')} | SL_Px: {_v('exact_sl_price')} | TP_Px: {_v('exact_tp_price')} | "
            f"P_SL: {_v('planned_sl_pips')} | P_TP: {_v('planned_tp_pips')} | P_RR: {_v('planned_rr')} | "
            f"Outcome: {t['outcome']} | Net_R: {t['net_r']} | "
            f"MAE: {_v('actual_mae_pips')} | MFE: {_v('actual_mfe_pips')} | "
            f"SL_Desc: {_v('sl_placement_desc')} | TP_Desc: {_v('tp_placement_desc')} | "
            f"Entry_Notes: {_v('entry_reversal_notes')} | Final_Notes: {_v('notes')}"
        )

    return """[AI DATA DICTIONARY HEADER START]
This dataset contains advanced, professional backtesting trade execution logs utilizing Smart Money Concepts (SMC) and institutional order flow mechanics. Use this exact schema definition dictionary to parse, model, and analyze the data records below:

PRIMARY STRUCTURAL ENTITIES & FIELD LOGIC:
- 'Trade_ID': A unique, auto-incremented integer identifying the trade chronicle index.
- 'Asset_Pair': The financial asset ticker being backtested (e.g., XAUUSD, EURUSD), dynamic from settings configuration.
- 'Timeframe': The precise execution or directional bias chart timeframe (e.g., 4H, 15M, 1M).
- 'Direction': The order framework style. Restricted to 'BUY' (Long market positions) or 'SELL' (Short market positions).
- 'Trading_Session': The specific regional market liquidity block when entry was activated ('Asian', 'London', 'New York').
- 'Execution_Time_EAT': The explicit execution timestamp hardcoded and normalized to East African Time (EAT / UTC+3).
- 'SMC_Entry_Modules': A multi-selected array of mechanical execution criteria checked by the trader to justify entry validation (e.g., [Decisional OB, Inducement Sweep]).
- 'Dynamic_Entry_Zones': A breakdown mapping out exactly where the trader entered relative to each checked Entry Module (e.g., Entering at the 'Upper Limit' of the Decisional OB while simultaneously hitting the 'Mean Threshold' of the Extreme OF).
- 'Actual_Reversal_Zone': The true, physical structural landmark where the market exhausted its price expansion/drawdown and printed its real pivot point before moving toward targets. Compare this directly to 'Dynamic_Entry_Zones' to study structural front-running, drawdown overextensions, and zone failures.
- 'Exact_Entry_Price': The literal float execution entry rate digit. Used to cross-reference if the trade interacted with institutional whole numbers, key psychological round figures (.000, .500), or institutional quarters (.250, .750).
- 'Exact_Stop_Loss_Price': The exact protective invalidation price point.
- 'Exact_Take_Profit_Price': The exact planned objective target price point.
- 'Planned_SL_Pips': The total calculated mathematical pip distance from entry to stop loss.
- 'Planned_TP_Pips': The total calculated mathematical pip distance from entry to take profit.
- 'Planned_RR_Ratio': The raw calculated risk-to-reward ratio metric planned prior to execution (e.g., 1:4.5).
- 'Trade_Outcome': The definitive manual resolution of the position. Restricted to 'Win', 'Loss', or 'Break-Even'.
- 'Net_R_Gain_Loss': The automated statistical performance return value based strictly on outcome (A 'Loss' = -1.0R, 'Break-Even' = 0.0R, 'Win' = full positive Planned_RR value).
- 'Max_Adverse_Excursion_MAE': The maximum drawdown in pips experienced during the life of the trade. Mandatory for wins to evaluate entry optimization.
- 'Max_Favorable_Excursion_MFE': The maximum profit expansion in pips reached before invalidation. Mandatory for losses to analyze exit greed optimization.
- 'SL_Placement_Desc': Qualitative structural explanation outlining the logic of where the protective order was positioned.
- 'TP_Placement_Desc': Qualitative structural explanation outlining the logic of where the target objective was positioned.
- 'Entry_Reversal_Notes': Tape-reading observations made in real-time regarding candle signatures, reaction momentum, or zone mitigation nuances exactly during the entry window.
- 'Final_Outcome_Notes': Macro retrospective comments logging psychology, mistakes, or key takeaways after the trade fully resolved.

Analyze these records globally to extract edge patterns, structural performance anomalies, structural placement safety margins, and win-rate optimizations based on these descriptions.
[AI DATA DICTIONARY HEADER END]

---
[RAW DATA RECORDS FOLLOW]
""" + "\n".join(records) + "\n\n[DATASET RECORD END]\n---"
"""Database layer: SQLAlchemy Core, dual DB routing (Postgres if DATABASE_URL, else local SQLite).

- Loads .env automatically via python-dotenv
- Ensures sslmode=require appended for Postgres if missing
- Uses SQLAlchemy Core to avoid param marker differences
"""
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import pytz

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, Text, Float, select, insert, update, delete, text
)
from sqlalchemy.exc import OperationalError, IntegrityError, InternalError

# Load local .env if present
load_dotenv()

EAT = pytz.timezone("Africa/Nairobi")

DEFAULT_PAIRS = ["XAUUSD", "EURUSD"]
DEFAULT_TIMEFRAMES = ["1D", "4H", "30M", "15M"]
DEFAULT_MODULES = [
    "[Bullish] Inducement Sweep (Liquidity Taken Below)",
    "[Bearish] Inducement Sweep (Liquidity Taken Above)",
    "[Bullish] Engineering Liquidity Sweep (Lows)",
    "[Bearish] Engineering Liquidity Sweep (Highs)",
    "Decisional Order Block (OB) Mitigation",
    "Decisional Order Flow (OF) Mitigation",
    "Extreme Order Block (OB) Mitigation",
    "Extreme Order Flow (OF) Mitigation",
    "Origin Order Block (OB) Mitigation",
    "Bullish Fair Value Gap (bFVG)",
    "Bearish Fair Value Gap (bFVG)",
    "Fibonacci Optimal Entry Zone (0.5 - 0.62)",
]
DEFAULT_LEVELS = [
    "Upper Limit",
    "Lower Limit",
    "Mean Threshold / Middle Limit",
    "0.5 Fibonacci Level",
    "0.62 Fibonacci Level",
    "Fib Mid-Threshold",
]

_METADATA = MetaData()
_ENGINE = None


def _append_sslmode_if_needed(url: str) -> str:
    if not url:
        return url
    low = url.lower()
    if ("postgres" in low or "postgresql" in low) and "sslmode" not in low:
        return url + ("&sslmode=require" if "?" in url else "?sslmode=require")
    return url


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    db_url = os.environ.get("DATABASE_URL")
    # If running as a frozen exe, allow .env next to exe
    if getattr(sys, 'frozen', False):
        dot = os.path.join(os.path.dirname(sys.executable), '.env')
        if os.path.exists(dot):
            load_dotenv(dot)
            db_url = os.environ.get('DATABASE_URL')

    try:
        if db_url:
            db_url = _append_sslmode_if_needed(db_url)
            eng = create_engine(db_url, pool_pre_ping=True)
            # quick smoke test
            with eng.connect() as c:
                pass
            _ENGINE = eng
            return _ENGINE
    except OperationalError:
        # connection failed; fall back to sqlite
        pass

    # Local sqlite fallback (in cwd or next to exe when frozen)
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.getcwd()
    sqlite_path = os.path.join(base, 'smc_backtest.db')
    eng = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})
    _ENGINE = eng
    return _ENGINE


# Table definitions
pairs = Table('pairs', _METADATA, Column('pair_name', String, primary_key=True))

timeframes = Table('timeframes', _METADATA, Column('tf_name', String, primary_key=True))

entry_modules = Table('entry_modules', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('module_name', String, unique=True, nullable=False))

reversal_levels = Table('reversal_levels', _METADATA,
                        Column('id', Integer, primary_key=True, autoincrement=True),
                        Column('level_name', String, unique=True, nullable=False))

trades = Table('trades', _METADATA,
               Column('id', Integer, primary_key=True, autoincrement=True),
               Column('pair', String, nullable=False),
               Column('timeframe', String, nullable=False),
               Column('direction', String, nullable=False),
               Column('session', String),
               Column('execution_time_eat', String, nullable=False),
               Column('entry_modules', Text, nullable=False),
               Column('dynamic_entry_zones', Text),
               Column('actual_reversal_zone', Text),
               Column('actual_reversal_custom', Text),
               Column('reversal_level', Text),
               Column('outcome', String, nullable=False),
               Column('exact_entry_price', Float),
               Column('exact_sl_price', Float),
               Column('exact_tp_price', Float),
               Column('planned_sl_pips', Float, nullable=False),
               Column('planned_tp_pips', Float, nullable=False),
               Column('planned_rr', Float, nullable=False),
               Column('net_r', Float, nullable=False),
               Column('actual_mae_pips', Float),
               Column('actual_mfe_pips', Float),
               Column('sl_placement_desc', Text),
               Column('tp_placement_desc', Text),
               Column('entry_reversal_notes', Text),
               Column('notes', Text),
               Column('created_at', String, nullable=False),
               )

webhook_queue = Table('webhook_queue', _METADATA,
                      Column('id', Integer, primary_key=True, autoincrement=True),
                      Column('payload', Text, nullable=False),
                      Column('received_at', String, nullable=False),
                      Column('status', String, nullable=False, default='pending'))


def init_db():
    eng = _get_engine()
    _METADATA.create_all(eng)
    # Dispose pooled connections so subsequent seed inserts get fresh connections.
    try:
        eng.dispose()
    except Exception:
        pass

    # seeds - run each insert in its own transaction so a single failed statement
    # doesn't abort the entire seed block (which can happen on Postgres).
    try:
        # pairs
        for p in DEFAULT_PAIRS:
            def _do_pair_insert():
                with eng.connect() as conn:
                    if eng.dialect.name == 'postgresql':
                        conn2 = conn.execution_options(isolation_level='AUTOCOMMIT')
                        conn2.execute(text("INSERT INTO pairs (pair_name) VALUES (:pair_name) ON CONFLICT DO NOTHING"), {'pair_name': p})
                    else:
                        conn.execute(insert(pairs).values(pair_name=p))

            try:
                _do_pair_insert()
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    _do_pair_insert()
                except Exception:
                    pass
            except Exception:
                pass

        # timeframes
        for t in DEFAULT_TIMEFRAMES:
            def _do_tf_insert():
                with eng.connect() as conn:
                    if eng.dialect.name == 'postgresql':
                        conn2 = conn.execution_options(isolation_level='AUTOCOMMIT')
                        conn2.execute(text("INSERT INTO timeframes (tf_name) VALUES (:tf_name) ON CONFLICT DO NOTHING"), {'tf_name': t})
                    else:
                        conn.execute(insert(timeframes).values(tf_name=t))

            try:
                _do_tf_insert()
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    _do_tf_insert()
                except Exception:
                    pass
            except Exception:
                pass

        # entry modules
        for m in DEFAULT_MODULES:
            def _do_mod_insert():
                with eng.connect() as conn:
                    if eng.dialect.name == 'postgresql':
                        conn2 = conn.execution_options(isolation_level='AUTOCOMMIT')
                        conn2.execute(text("INSERT INTO entry_modules (module_name) VALUES (:module_name) ON CONFLICT DO NOTHING"), {'module_name': m})
                    else:
                        conn.execute(insert(entry_modules).values(module_name=m))

            try:
                _do_mod_insert()
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    _do_mod_insert()
                except Exception:
                    pass
            except Exception:
                pass

        # reversal levels
        for lv in DEFAULT_LEVELS:
            def _do_lv_insert():
                with eng.connect() as conn:
                    if eng.dialect.name == 'postgresql':
                        conn2 = conn.execution_options(isolation_level='AUTOCOMMIT')
                        conn2.execute(text("INSERT INTO reversal_levels (level_name) VALUES (:level_name) ON CONFLICT DO NOTHING"), {'level_name': lv})
                    else:
                        conn.execute(insert(reversal_levels).values(level_name=lv))

            try:
                _do_lv_insert()
            except IntegrityError:
                pass
            except InternalError:
                try:
                    eng.dispose()
                except Exception:
                    pass
                try:
                    _do_lv_insert()
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        # Swallow unexpected seeding errors to avoid crashing the launcher; app will still run.
        try:
            eng.dispose()
        except Exception:
            pass


# Utility
def now_eat_str():
    return datetime.now(EAT).strftime("%Y-%m-%d %H:%M:%S")


def compute_net_r(outcome, planned_rr):
    try:
        planned_rr = float(planned_rr)
    except Exception:
        planned_rr = 0.0
    if outcome == 'Win':
        return float(planned_rr)
    if outcome == 'Loss':
        return -1.0
    return 0.0


# Settings: pairs/timeframes/modules/levels
def get_pairs():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(pairs.c.pair_name).order_by(pairs.c.pair_name)).fetchall()
        return [r[0] for r in rows]


def add_pair(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(pairs).values(pair_name=name))
        except IntegrityError:
            pass
    return name


def delete_pair(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.pair == name).limit(1)).fetchone()
        if r:
            return False, 'Pair is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(pairs).where(pairs.c.pair_name == name))
    return True, None


def get_timeframes():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(timeframes.c.tf_name).order_by(timeframes.c.tf_name)).fetchall()
        return [r[0] for r in rows]


def add_timeframe(name):
    name = name.strip().upper()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(timeframes).values(tf_name=name))
        except IntegrityError:
            pass
    return name


def delete_timeframe(name):
    eng = _get_engine()
    with eng.begin() as conn:
        r = conn.execute(select(trades.c.id).where(trades.c.timeframe == name).limit(1)).fetchone()
        if r:
            return False, 'Timeframe is referenced by existing trades and cannot be deleted.'
        conn.execute(delete(timeframes).where(timeframes.c.tf_name == name))
    return True, None


def get_entry_modules():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(entry_modules.c.id, entry_modules.c.module_name).order_by(entry_modules.c.id)).fetchall()
        return [dict(id=r[0], module_name=r[1]) for r in rows]


def add_entry_module(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=name))
        except IntegrityError:
            pass
    return name


def delete_entry_module(module_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(entry_modules.c.module_name).where(entry_modules.c.id == module_id)).fetchone()
        if not row:
            return False, 'Module not found.'
        modname = row[0]
        rows = conn.execute(select(trades.c.entry_modules)).fetchall()
        for t in rows:
            try:
                if modname in json.loads(t[0] or '[]'):
                    return False, 'Module is referenced by existing trades and cannot be deleted.'
            except Exception:
                pass
        conn.execute(delete(entry_modules).where(entry_modules.c.id == module_id))
    return True, None


def get_reversal_levels():
    eng = _get_engine()
    with eng.connect() as conn:
        rows = conn.execute(select(reversal_levels.c.id, reversal_levels.c.level_name).order_by(reversal_levels.c.id)).fetchall()
        return [dict(id=r[0], level_name=r[1]) for r in rows]


def add_reversal_level(name):
    name = name.strip()
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(reversal_levels).values(level_name=name))
        except IntegrityError:
            pass
    return name


def delete_reversal_level(level_id):
    eng = _get_engine()
    with eng.begin() as conn:
        row = conn.execute(select(reversal_levels.c.level_name).where(reversal_levels.c.id == level_id)).fetchone()
        if not row:
            return False, 'Level not found.'
        conn.execute(delete(reversal_levels).where(reversal_levels.c.id == level_id))
    return True, None


# Trades
def insert_trade(data):
    modules = json.dumps(data['entry_modules']) if isinstance(data['entry_modules'], list) else data['entry_modules']
    zones = json.dumps(data.get('dynamic_entry_zones')) if isinstance(data.get('dynamic_entry_zones'), dict) else (data.get('dynamic_entry_zones') or '{}')
    net_r = compute_net_r(data['outcome'], data['planned_rr'])
    eat_time = data.get('execution_time') or now_eat_str()

    def _f(key):
        v = data.get(key)
        try:
            return float(v) if v not in (None, '') else None
        except Exception:
            return None

    eng = _get_engine()
    with eng.begin() as conn:
        res = conn.execute(insert(trades).values(
            pair=data['pair'].upper(),
            timeframe=data['timeframe'],
            direction=data['direction'],
            session=data.get('session') or None,
            execution_time_eat=eat_time,
            entry_modules=modules,
            dynamic_entry_zones=zones,
            actual_reversal_zone=data.get('actual_reversal_zone') or None,
            actual_reversal_custom=data.get('actual_reversal_custom') or None,
            outcome=data['outcome'],
            exact_entry_price=_f('exact_entry_price'),
            exact_sl_price=_f('exact_sl_price'),
            exact_tp_price=_f('exact_tp_price'),
            planned_sl_pips=float(data['planned_sl_pips']),
            planned_tp_pips=float(data['planned_tp_pips']),
            planned_rr=float(data['planned_rr']),
            net_r=net_r,
            actual_mae_pips=_f('actual_mae_pips'),
            actual_mfe_pips=_f('actual_mfe_pips'),
            sl_placement_desc=data.get('sl_placement_desc') or None,
            tp_placement_desc=data.get('tp_placement_desc') or None,
            entry_reversal_notes=data.get('entry_reversal_notes') or None,
            notes=data.get('notes') or None,
            created_at=now_eat_str(),
        ))
        try:
            return int(res.inserted_primary_key[0])
        except Exception:
            return None


def get_all_trades():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(trades).order_by(trades.c.id.desc())).fetchall()
        out = []
        for r in res:
            out.append(dict(r._mapping))
        return out


def get_trade(trade_id):
    eng = _get_engine()
    with eng.connect() as conn:
        row = conn.execute(select(trades).where(trades.c.id == trade_id)).fetchone()
        return dict(row._mapping) if row else None


def delete_trade(trade_id):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(delete(trades).where(trades.c.id == trade_id))


# Webhook queue
def queue_webhook(payload_str):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(insert(webhook_queue).values(payload=payload_str, received_at=now_eat_str(), status='pending'))


def get_pending_webhooks():
    eng = _get_engine()
    with eng.connect() as conn:
        res = conn.execute(select(webhook_queue).where(webhook_queue.c.status == 'pending').order_by(webhook_queue.c.id.desc())).fetchall()
        return [dict(r._mapping) for r in res]


def dismiss_webhook(wid):
    eng = _get_engine()
    with eng.begin() as conn:
        conn.execute(update(webhook_queue).where(webhook_queue.c.id == wid).values(status='dismissed'))


# CSV import & AI export utilities
IMPORT_PLACEHOLDER_MODULE = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_LEVEL = "Imported (Pending SMC Review)"
IMPORT_PLACEHOLDER_SESSION = "London"
IMPORT_PLACEHOLDER_TF = "IMPORT"


def _clean(val):
    if val is None:
        return ""
    return val.strip().replace("\ufeff", "").strip()


def _clean_num(val):
    if val is None:
        return ""
    return str(val).strip().replace(",", "").replace("$", "").replace("%", "").replace("\ufeff", "").strip()


def _parse_float(val, default=0.0):
    try:
        return float(_clean_num(str(val)))
    except (ValueError, TypeError):
        return default


def _to_eat(dt_str):
    dt_str = _clean(dt_str)
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return pytz.utc.localize(dt).astimezone(EAT).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return now_eat_str()


def _get_col(row, key, default=""):
    key_low = key.strip().lower()
    for k, v in row.items():
        if k.strip().lower() == key_low:
            return v if v is not None else default
    return default


def _ensure_import_placeholders():
    eng = _get_engine()
    with eng.begin() as conn:
        try:
            conn.execute(insert(entry_modules).values(module_name=IMPORT_PLACEHOLDER_MODULE))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(reversal_levels).values(level_name=IMPORT_PLACEHOLDER_LEVEL))
        except IntegrityError:
            pass
        try:
            conn.execute(insert(timeframes).values(tf_name=IMPORT_PLACEHOLDER_TF))
        except IntegrityError:
            pass


def _trade_exists(conn, pair, direction, eat_time):
    r = conn.execute(select(trades.c.id).where(
        (trades.c.pair == pair) & (trades.c.direction == direction) & (trades.c.execution_time_eat == eat_time)
    ).limit(1)).fetchone()
    return r is not None


def _detect_format(headers):
    h = [x.strip().lower() for x in headers]
    if any("trade #" in x or "trade#" in x for x in h):
        return "strategy"
    if "side" in h and "fill price" in h:
        return "replay"
    return "unknown"


def _parse_strategy(rows):
    groups = {}
    for row in rows:
        for k in row:
            if "trade" in k.lower() and ("#" in k or "num" in k.lower()):
                groups.setdefault(_clean(row[k]), []).append(row)
                break

    trades_out = []
    for num, group_rows in groups.items():
        entry_row = next((r for r in group_rows if "entry" in _get_col(r, "type", "").lower()), None)
        exit_row = next((r for r in group_rows if "exit" in _get_col(r, "type", "").lower()), None)
        if not entry_row:
            continue

        direction = "Bullish" if "long" in _get_col(entry_row, "type", "").lower() else "Bearish"
        pair = _get_col(entry_row, "symbol", "UNKNOWN").strip().split(".")[0].upper() or "UNKNOWN"
        eat_time = _to_eat(
            _get_col(entry_row, "date/time", "") or
            _get_col(entry_row, "datetime", "") or
            _get_col(entry_row, "time", "")
        )

        entry_px = _parse_float(_get_col(entry_row, "price", "0"))
        exit_px = _parse_float(_get_col(exit_row, "price", "0")) if exit_row else None
        contracts = _parse_float(_get_col(entry_row, "contracts", "1"), 1.0)

        mfe = abs(_parse_float(_get_col(exit_row or entry_row, "run-up", "0")))
        mae = abs(_parse_float(_get_col(exit_row or entry_row, "drawdown", "0")))

        profit = _parse_float(_get_col(exit_row or entry_row, "profit", "0"))
        prof_pct = _parse_float(
            _get_col(exit_row or entry_row, "profit %", None) or
            _get_col(exit_row or entry_row, "profit(%)", "0")
        )

        outcome = "Win" if profit > 0 else ("Loss" if profit < 0 else "Break-Even")
        planned_rr = round(abs(prof_pct) / 100, 4) if prof_pct != 0 else round(abs(profit), 2)
        net_r = compute_net_r(outcome, planned_rr)

        trades_out.append({
            "pair": pair, "direction": direction, "eat_time": eat_time,
            "entry_px": entry_px,
            "exact_sl_px": exit_px if outcome == "Loss" else None,
            "exact_tp_px": exit_px if outcome == "Win" else None,
            "outcome": outcome, "planned_rr": planned_rr, "net_r": net_r,
            "mae": mae if mae > 0 else None,
            "mfe": mfe if mfe > 0 else None,
            "notes": (
                f"TV Strategy Import | Entry: {entry_px} | Exit: {exit_px} | "
                f"Contracts: {contracts} | Profit: {profit} | Profit%: {prof_pct}"
            ),
        })
    return trades_out


def _parse_replay(rows):
    from collections import defaultdict
    open_positions = defaultdict(list)
    trades_out = []

    for row in rows:
        side = _clean(_get_col(row, "side", "")).lower()
        symbol = _get_col(row, "symbol", "UNKNOWN").strip().split(".")[0].upper()
        qty = _parse_float(_get_col(row, "qty", "1"), 1.0)
        price = _parse_float(_get_col(row, "fill price", "0"))
        pnl = _parse_float(_get_col(row, "p&l", None) or _get_col(row, "pnl", "0"))
        eat_t = _to_eat(_get_col(row, "time", "") or _get_col(row, "date/time", ""))

        if side in ("buy", "long"):
            open_positions[symbol].append({"price": price, "qty": qty, "time": eat_t})

        elif side in ("sell", "short") and open_positions[symbol]:
            entry = open_positions[symbol].pop(0)
            profit_pts = price - entry["price"]
            effective = pnl if pnl != 0 else profit_pts
            outcome = "Win" if effective > 0 else ("Loss" if effective < 0 else "Break-Even")
            rr = round(abs(profit_pts / max(entry["price"] * 0.001, 0.0001)), 4)

            trades_out.append({
                "pair": symbol, "direction": "Bullish",
                "eat_time": entry["time"],
                "entry_px": entry["price"],
                "exact_sl_px": price if outcome == "Loss" else None,
                "exact_tp_px": price if outcome == "Win" else None,
                "outcome": outcome, "planned_rr": rr, "net_r": compute_net_r(outcome, rr),
                "mae": None, "mfe": None,
                "notes": (
                    f"TV Replay Import | Entry: {entry['price']} | Exit: {price} | "
                    f"Qty: {qty} | P&L: {pnl}"
                ),
            })
    return trades_out


def import_tradingview_csv(content):
    import csv, io
    _ensure_import_placeholders()
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return 0, 0, ["CSV file is empty or unreadable."]

    fmt = _detect_format(reader.fieldnames or [])
    if fmt == "strategy":
        parsed = _parse_strategy(rows)
    elif fmt == "replay":
        parsed = _parse_replay(rows)
    else:
        return 0, 0, ["Unrecognised CSV format. Expected Strategy Tester or Replay Trading export."]

    inserted, skipped, errors = 0, 0, []
    eng = _get_engine()
    with eng.begin() as conn:
        for t in parsed:
            conn.execute(insert(pairs).values(pair_name=t['pair']))
            if _trade_exists(conn, t['pair'], t['direction'], t['eat_time']):
                skipped += 1
                continue
            try:
                conn.execute(insert(trades).values(
                    pair=t['pair'],
                    timeframe=IMPORT_PLACEHOLDER_TF,
                    direction=t['direction'],
                    session=IMPORT_PLACEHOLDER_SESSION,
                    execution_time_eat=t['eat_time'],
                    entry_modules=json.dumps([IMPORT_PLACEHOLDER_MODULE]),
                    dynamic_entry_zones='{}',
                    actual_reversal_zone=None,
                    actual_reversal_custom=None,
                    outcome=t['outcome'],
                    exact_entry_price=t.get('entry_px'),
                    exact_sl_price=t.get('exact_sl_px'),
                    exact_tp_price=t.get('exact_tp_px'),
                    planned_sl_pips=0.0,
                    planned_tp_pips=0.0,
                    planned_rr=t['planned_rr'],
                    net_r=t['net_r'],
                    actual_mae_pips=t.get('mae'),
                    actual_mfe_pips=t.get('mfe'),
                    sl_placement_desc=None,
                    tp_placement_desc=None,
                    entry_reversal_notes=None,
                    notes=t.get('notes'),
                    created_at=now_eat_str(),
                ))
                inserted += 1
            except Exception as e:
                errors.append(str(e))
    return inserted, skipped, errors



