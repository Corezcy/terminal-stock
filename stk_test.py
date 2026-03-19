# -*- coding: utf-8 -*- 

import time
import os
import sys
import csv
import shutil
import unicodedata
from pathlib import Path
import requests
if os.name == 'nt':
    import msvcrt
else:
    import select
    import termios

mystock = {}
stock_codes = []
stocks = ''
url = "https://qt.gtimg.cn/q="
previous_data = {}  # Store previous stock data for comparison
previous_terminal_size = None
scroll_offset = 0
last_fetch_ts = 0.0
last_fetch_error = None
TTY_FD = None
TTY_OLD_SETTINGS = None
ALT_SCREEN_ACTIVE = False

ANSI_BOLD = '\033[1m'
ANSI_RESET = '\033[0m'


def normalize_stock_code(code):
    """Normalize stock code to formats like sh600000 / sz000001 / bj430047."""
    raw = str(code).strip().lower()
    if not raw:
        return ""

    if raw.startswith(("sh", "sz", "bj", "hk")):
        return raw

    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw

    digits = digits.zfill(6)
    if digits.startswith(("6", "9")):
        return f"sh{digits}"
    if digits.startswith(("0", "2", "3")):
        return f"sz{digits}"
    if digits.startswith(("4", "8")):
        return f"bj{digits}"
    return digits


def get_today_focus_csv_path():
    today = time.strftime("%Y%m%d", time.localtime())
    relative_path = Path(f"stock_changes_{today}") / f"stock_changes_summary_{today}_focus.csv"

    current_dir = Path(__file__).resolve().parent
    project_dir = current_dir.parent
    candidates = [
        current_dir / relative_path,
        project_dir / relative_path,
        project_dir / "AKShare" / relative_path,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_my_stock_codes(stock_file_path):
    my_codes = []
    seen_codes = set()
    mystock.clear()

    with open(stock_file_path, 'r', encoding='utf-8') as f:
        stock_list = f.read().split('\n')

    for item in stock_list:
        if item.startswith('#'):
            continue
        if item.strip() == '':
            continue

        item_list = item.split()
        if len(item_list) < 1:
            continue

        code = normalize_stock_code(item_list[0])
        if not code or code in seen_codes:
            continue

        seen_codes.add(code)
        my_codes.append(code)
        mystock[code] = (item_list[1], item_list[2]) if len(item_list) == 3 else None

    return my_codes


def load_focus_stock_codes():
    focus_codes = []
    seen_codes = set()
    focus_path = get_today_focus_csv_path()
    if not focus_path:
        return focus_codes

    with open(focus_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = normalize_stock_code(row.get("代码", ""))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            focus_codes.append(code)

    return focus_codes


def readData():
    global stocks, stock_codes

    current_dir = Path(__file__).resolve().parent
    stock_file_path = current_dir / 'my_stock.dat'

    try:
        my_codes = load_my_stock_codes(stock_file_path)
        focus_codes = load_focus_stock_codes()

        merged_codes = []
        seen_codes = set()

        # my_stock.dat 永远优先，focus 文件只补充未出现的代码
        for code in my_codes + focus_codes:
            if code and code not in seen_codes:
                seen_codes.add(code)
                merged_codes.append(code)

        stock_codes = merged_codes
        stocks = ",".join(stock_codes)

        if not stocks:
            print("未加载到任何股票代码，请检查 my_stock.dat 或当日 focus CSV")

    except FileNotFoundError:
        print(f"文件未找到: {stock_file_path}")
        print(f"当前工作目录: {os.getcwd()}")
    except Exception as e:
        print(f"读取文件时出错: {e}")


def getTime():
    return time.strftime('%Y-%m-%d %A %p %X', time.localtime(time.time()))


def text_display_width(text):
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return width


def fit_text(text, width):
    result = []
    current = 0
    for ch in str(text):
        ch_width = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if current + ch_width > width:
            break
        result.append(ch)
        current += ch_width
    return ''.join(result)


def align_text(text, width, align='left'):
    clipped = fit_text(text, width)
    pad = width - text_display_width(clipped)
    if pad <= 0:
        return clipped
    if align == 'right':
        return (' ' * pad) + clipped
    return clipped + (' ' * pad)


def get_terminal_width():
    try:
        return shutil.get_terminal_size(fallback=(120, 30)).columns
    except OSError:
        return 120


def get_terminal_height():
    try:
        return shutil.get_terminal_size(fallback=(120, 30)).lines
    except OSError:
        return 30


def setup_tty_input():
    global TTY_FD, TTY_OLD_SETTINGS
    if os.name == 'nt' or not sys.stdin.isatty():
        return

    TTY_FD = sys.stdin.fileno()
    TTY_OLD_SETTINGS = termios.tcgetattr(TTY_FD)
    new_settings = termios.tcgetattr(TTY_FD)
    new_settings[3] &= ~(termios.ICANON | termios.ECHO)
    new_settings[6][termios.VMIN] = 0
    new_settings[6][termios.VTIME] = 0
    termios.tcsetattr(TTY_FD, termios.TCSANOW, new_settings)


def restore_tty_input():
    if os.name == 'nt' or TTY_FD is None or TTY_OLD_SETTINGS is None:
        return
    termios.tcsetattr(TTY_FD, termios.TCSANOW, TTY_OLD_SETTINGS)


def read_key_nonblocking():
    if os.name == 'nt':
        if not msvcrt.kbhit():
            return None
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            _ = msvcrt.getwch()
            return None
        if ch == 'f':
            return 'PAGE_DOWN'
        if ch == 'b':
            return 'PAGE_UP'
        if ch == 'g':
            return 'TOP'
        if ch == 'G':
            return 'BOTTOM'
        if ch in ('q', 'Q'):
            return 'QUIT'
        return None

    if TTY_FD is None:
        return None
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None

    ch = sys.stdin.read(1)
    if ch == '\x1b':
        if select.select([sys.stdin], [], [], 0.001)[0]:
            _ = sys.stdin.read(1)
            if select.select([sys.stdin], [], [], 0.001)[0]:
                _ = sys.stdin.read(1)
                if select.select([sys.stdin], [], [], 0.001)[0]:
                    _ = sys.stdin.read(1)
        return None

    if ch == 'f':
        return 'PAGE_DOWN'
    if ch == 'b':
        return 'PAGE_UP'
    if ch == 'g':
        return 'TOP'
    if ch == 'G':
        return 'BOTTOM'
    if ch in ('q', 'Q'):
        return 'QUIT'
    return None


def handle_keys(total_rows, view_rows):
    global scroll_offset

    should_quit = False
    changed = False
    max_offset = max(total_rows - view_rows, 0)

    while True:
        key = read_key_nonblocking()
        if key is None:
            break

        if key == 'QUIT':
            should_quit = True
            break
        if key == 'PAGE_DOWN':
            step = max(view_rows - 1, 1)
            scroll_offset = min(scroll_offset + step, max_offset)
            changed = True
        elif key == 'PAGE_UP':
            step = max(view_rows - 1, 1)
            scroll_offset = max(scroll_offset - step, 0)
            changed = True
        elif key == 'TOP':
            scroll_offset = 0
            changed = True
        elif key == 'BOTTOM':
            scroll_offset = max_offset
            changed = True

    return should_quit, changed


def build_layout(max_width):
    all_specs = {
        'code': {'title': 'CODE', 'width': 10, 'min_width': 6, 'align': 'left'},
        'name': {'title': 'NAME', 'width': 12, 'min_width': 4, 'align': 'left'},
        'latest': {'title': 'LATEST', 'width': 10, 'min_width': 8, 'align': 'right'},
        'change': {'title': 'CHANGE', 'width': 9, 'min_width': 7, 'align': 'right'},
        'open': {'title': 'OPEN', 'width': 10, 'min_width': 7, 'align': 'right'},
        'high': {'title': 'HIGH', 'width': 10, 'min_width': 7, 'align': 'right'},
        'low': {'title': 'LOW', 'width': 10, 'min_width': 7, 'align': 'right'},
    }
    variants = [
        ['code', 'name', 'latest', 'change', 'open', 'high', 'low'],
        ['code', 'name', 'latest', 'change', 'open', 'high'],
        ['code', 'name', 'latest', 'change', 'open'],
        ['code', 'name', 'latest', 'change'],
        ['code', 'name', 'latest'],
        ['code', 'latest'],
        ['code'],
    ]

    def calc_total_width(layout):
        return sum(item['width'] for item in layout) + max(len(layout) - 1, 0) * 3

    for keys in variants:
        layout = [dict(all_specs[key], key=key) for key in keys]
        while calc_total_width(layout) > max_width:
            shrink_candidates = [item for item in layout if item['width'] > item['min_width']]
            if not shrink_candidates:
                break
            target = max(shrink_candidates, key=lambda item: (item['width'] - item['min_width'], item['width']))
            target['width'] -= 1
        if calc_total_width(layout) <= max_width:
            return layout

    return [dict(all_specs['code'], key='code', width=max(4, max_width), min_width=4)]


def render_plain_line(line, width):
    clipped = fit_text(line, width)
    return clipped + (' ' * max(width - text_display_width(clipped), 0))


def make_xueqiu_url(code):
    return f"https://xueqiu.com/S/{code}" if code else ""


def make_terminal_hyperlink(label, url):
    if not label or not url or not sys.stdout.isatty():
        return label
    # OSC 8 hyperlink (supported by iTerm2, modern terminals)
    return f"\033]8;;{url}\a{label}\033]8;;\a"


def format_row(row_data, layout, width, bold=False):
    parts = []
    for spec in layout:
        key = spec['key']
        if key == 'code':
            value = row_data['code']
        elif key == 'name':
            value = row_data['name']
        elif key == 'latest':
            value = f"{row_data['latest_price']:.2f}"
        elif key == 'change':
            value = row_data['change_pct']
        elif key == 'open':
            value = f"{row_data['open_price']:.2f}"
        elif key == 'high':
            value = f"{row_data['high_price']:.2f}"
        else:
            value = f"{row_data['low_price']:.2f}"
        parts.append(align_text(value, spec['width'], spec['align']))

    plain_line = render_plain_line(' | '.join(parts), width)
    code_text = str(row_data.get('code', ''))
    if code_text and plain_line.startswith(code_text):
        code_link = make_terminal_hyperlink(code_text, make_xueqiu_url(code_text))
        plain_line = f"{code_link}{plain_line[len(code_text):]}"

    if bold:
        return f"{ANSI_BOLD}{plain_line}{ANSI_RESET}"
    return plain_line


def parseQtData(data_line):
    """
    Parse qt.gtimg.cn API response data
    Format: v_sh000001="field1~field2~field3~..."
    Returns: dict with parsed fields
    """
    try:
        # Split by '=' to get the data part
        parts = data_line.split('=', 1)
        if len(parts) < 2:
            return None
            
        # Extract the data between quotes
        data_part = parts[1].strip().strip('"').strip(';')
        fields = data_part.split('~')
        
        if len(fields) < 36:  # Need at least 36 fields for our required data
            return None
            
        return {
            'code': parts[0].replace('v_', ''),  # Extract code from v_sh000001
            'name': fields[1],          # 合约名称 - field 2
            'contract_id': fields[2],   # 合约ID - field 3  
            'latest_price': fields[3],  # 最新价 - field 4
            'prev_close': fields[4],    # 昨收 - field 5
            'open_price': fields[5],    # 开盘价 - field 6
            'change_pct': fields[32],   # 涨跌幅 - field 33
            'high_price': fields[33],   # 最高价 - field 34
            'low_price': fields[34],    # 最低价 - field 35
        }
    except (IndexError, ValueError) as e:
        print(f"Error parsing data line: {e}")
        return None


def hide_cursor():
    """Hide cursor to reduce flicker"""
    sys.stdout.write('\033[?25l')
    sys.stdout.flush()


def show_cursor():
    """Show cursor"""
    sys.stdout.write('\033[?25h')
    sys.stdout.flush()


def enter_alternate_screen():
    global ALT_SCREEN_ACTIVE
    if not sys.stdout.isatty():
        return
    # 1049: switch to alternate buffer; preserve main scrollback/history.
    sys.stdout.write('\033[?1049h\033[2J\033[H')
    sys.stdout.flush()
    ALT_SCREEN_ACTIVE = True


def leave_alternate_screen():
    global ALT_SCREEN_ACTIVE
    if not ALT_SCREEN_ACTIVE or not sys.stdout.isatty():
        return
    sys.stdout.write('\033[?1049l')
    sys.stdout.flush()
    ALT_SCREEN_ACTIVE = False


def printStock(force_render=False):
    global previous_data, previous_terminal_size
    global scroll_offset, last_fetch_ts, last_fetch_error

    terminal_width = get_terminal_width()
    terminal_height = get_terminal_height()
    safe_width = max(terminal_width - 1, 8)
    layout = build_layout(safe_width)
    table_width = min(
        safe_width,
        sum(spec['width'] for spec in layout) + max(len(layout) - 1, 0) * 3,
    )
    # Keep one spare line to avoid terminal scroll on the last newline.
    view_rows = max(1, terminal_height - 5)  # header/separator/rows/time/status + 1 spare

    existing_rows = [previous_data[code] for code in stock_codes if code in previous_data]
    should_quit, input_changed = handle_keys(len(existing_rows), view_rows)
    if should_quit:
        return True

    size_changed = (
        previous_terminal_size is not None
        and previous_terminal_size != (terminal_width, terminal_height)
    )
    if size_changed:
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
    previous_terminal_size = (terminal_width, terminal_height)

    now = time.monotonic()
    should_fetch = force_render or (now - last_fetch_ts >= 1.0)
    if should_fetch:
        last_fetch_ts = now
        try:
            # 每次行情刷新重新读取：my_stock.dat + 当日汇总 CSV
            readData()
            if not stocks:
                previous_data = {}
                last_fetch_error = "未加载到股票代码，请检查 my_stock.dat 与当日 CSV"
            else:
                ctx = requests.get(url + stocks, timeout=10)
                ctx.encoding = "gb2312"
                data = ctx.text
                lines = data.replace(';', '\n').split('\n')
                current_data = {}

                for line in lines:
                    if not line.strip() or not line.startswith('v_'):
                        continue

                    stock_data = parseQtData(line.strip())
                    if not stock_data:
                        continue

                    try:
                        code = stock_data['code']
                        name = stock_data['name']
                        latest_price = float(stock_data['latest_price'])
                        prev_close = float(stock_data['prev_close'])
                        open_price = float(stock_data['open_price'])
                        high_price = float(stock_data['high_price'])
                        low_price = float(stock_data['low_price'])
                        change_pct_raw = stock_data['change_pct']

                        if latest_price == 0:
                            change_pct = "停牌"
                            latest_price = prev_close
                        else:
                            try:
                                change_val = float(change_pct_raw)
                                change_pct = f"{change_val:+.2f}%"
                            except ValueError:
                                change_pct = "N/A"

                        current_data[code] = {
                            'code': code,
                            'name': name,
                            'latest_price': latest_price,
                            'change_pct': change_pct,
                            'open_price': open_price,
                            'high_price': high_price,
                            'low_price': low_price,
                            'is_up': latest_price > prev_close,
                        }
                    except (ValueError, KeyError):
                        continue

                previous_data = current_data
                last_fetch_error = None
        except requests.RequestException as e:
            last_fetch_error = f"Network error: {e}"
        except Exception as e:
            last_fetch_error = f"Unexpected error: {e}"

    ordered_rows = [previous_data[code] for code in stock_codes if code in previous_data]
    max_offset = max(len(ordered_rows) - view_rows, 0)
    scroll_offset = min(max(scroll_offset, 0), max_offset)

    if not (force_render or size_changed or should_fetch or input_changed):
        return False

    start_index = scroll_offset
    end_index = min(start_index + view_rows, len(ordered_rows))
    visible_rows = ordered_rows[start_index:end_index]

    # Some consoles partially support ANSI; use full-screen clear + home
    # to avoid stale header lines when redrawing.
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()

    header_parts = [align_text(spec['title'], spec['width'], spec['align']) for spec in layout]
    header = render_plain_line(' | '.join(header_parts), table_width)
    separator = render_plain_line('-+-'.join(['-' * spec['width'] for spec in layout]), table_width)
    range_text = f"{start_index + 1}-{end_index}/{len(ordered_rows)}" if ordered_rows else "0/0"
    time_line = render_plain_line(f"Time: {getTime()} | View: {range_text}", table_width)
    print(header)
    print(separator)

    if visible_rows:
        for row_data in visible_rows:
            print(format_row(row_data, layout, table_width, bold=row_data['is_up']))
    else:
        print(render_plain_line("暂无可显示行情数据", table_width))
    print(time_line)

    if last_fetch_error:
        status = f"{last_fetch_error} | f/b:翻页 g/G:首尾 q:退出"
    else:
        status = "f/b:翻页  g/G:首尾  q:退出"
    print(render_plain_line(status, table_width))

    return False


if __name__ == '__main__':
    exit_code = 0
    exit_message = "\n程序已退出"
    try:
        enter_alternate_screen()
        setup_tty_input()
        hide_cursor()   # Hide cursor to reduce flicker
        
        while True:
            should_quit = printStock()
            if should_quit:
                break
            time.sleep(0.05)  # 高频轮询输入，低频拉行情由 printStock 内部控制
            
    except KeyboardInterrupt:
        pass
    except Exception as e:
        exit_code = 1
        exit_message = f"\n程序错误: {e}"
    finally:
        restore_tty_input()
        show_cursor()
        leave_alternate_screen()
        print(exit_message)
        sys.exit(exit_code)
