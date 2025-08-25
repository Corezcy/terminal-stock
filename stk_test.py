# -*- coding: utf-8 -*- 

import time
import os
import platform
import sys
import requests

mystock = {}
stocks = ''
url = "https://qt.gtimg.cn/q="
previous_data = {}  # Store previous stock data for comparison
first_run = True


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'

    def disable(self):
        self.HEADER = ''
        self.OKBLUE = ''
        self.GREEN = ''
        self.YELLOW = ''
        self.RED = ''
        self.ENDC = ''

def readData():
    f = open('my_stock.dat', 'r')
    stockList = f.read().split('\n')
    global stocks, mystock
    for item in stockList:
        if item != '':
            itemList = item.split()
            stocks += itemList[0] + ','
            mystock[itemList[0]] = (itemList[1], itemList[2]) if len(itemList) == 3 else None
    stocks = stocks[:-1]
    f.close()


def getTime():
    return time.strftime('%Y-%m-%d %A %p %X', time.localtime(time.time()))


def highOrLow(a, b):
    return bcolors.RED if a >= b else bcolors.GREEN


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


def clear_screen():
    """Clear screen only once at startup"""
    sysstr = platform.system()
    if sysstr == 'Darwin' or sysstr == "Linux":
        os.system("clear")
    elif sysstr == 'Windows':
        os.system("cls")


def move_cursor_to_top():
    """Move cursor to top of terminal without clearing"""
    sys.stdout.write('\033[H')  # Move cursor to home position
    sys.stdout.flush()


def hide_cursor():
    """Hide cursor to reduce flicker"""
    sys.stdout.write('\033[?25l')
    sys.stdout.flush()


def show_cursor():
    """Show cursor"""
    sys.stdout.write('\033[?25h')
    sys.stdout.flush()


def printStock():
    global previous_data, first_run
    
    try:
        ctx = requests.get(url + stocks, timeout=10)
        ctx.encoding = "gb2312"
        data = ctx.text
        
        # Split by semicolon and newline
        lines = data.replace(';', '\n').split('\n')
        
        current_data = {}
        stock_lines = []
        
        # Parse all stock data first
        for line in lines:
            if not line.strip() or not line.startswith('v_'):
                continue
                
            stock_data = parseQtData(line.strip())
            if not stock_data:
                continue
                
            try:
                code = stock_data['code']
                name = stock_data['name'][:8]  # Limit name length for display
                latest_price = float(stock_data['latest_price'])
                prev_close = float(stock_data['prev_close'])
                open_price = float(stock_data['open_price'])
                high_price = float(stock_data['high_price'])
                low_price = float(stock_data['low_price'])
                change_pct = stock_data['change_pct']
                
                # Handle suspended trading
                if latest_price == 0:
                    change_pct = "停牌"
                    latest_price = prev_close
                else:
                    # Format change percentage
                    try:
                        change_val = float(change_pct)
                        change_pct = f"{change_val:+.2f}%"
                    except:
                        change_pct = "N/A"
                
                # Color coding based on price movement
                latest_color = highOrLow(latest_price, prev_close)
                open_color = highOrLow(open_price, prev_close)
                high_color = highOrLow(high_price, prev_close)
                low_color = highOrLow(low_price, prev_close)
                change_color = bcolors.RED if latest_price >= prev_close else bcolors.GREEN
                
                # Create formatted line
                stock_line = (
                    f"{bcolors.WHITE}{code:<12}{bcolors.ENDC} "
                    f"{bcolors.WHITE}{name:<12}{bcolors.ENDC} "
                    # f"{bcolors.WHITE}{prev_close:>10.2f}{bcolors.ENDC} "
                    # f"{open_color}{open_price:>10.2f}{bcolors.ENDC} "
                    # f"{high_color}{high_price:>10.2f}{bcolors.ENDC} "
                    # f"{low_color}{low_price:>10.2f}{bcolors.ENDC} "
                    f"{latest_color}{latest_price:>10.2f}{bcolors.ENDC} "
                    f"{change_color}{change_pct:>10s}{bcolors.ENDC}"
                )
                
                current_data[code] = stock_line
                stock_lines.append((code, stock_line))
                
            except (ValueError, KeyError) as e:
                print(f"Error processing stock {stock_data.get('code', 'unknown')}: {e}")
                continue
        
        # Move cursor to top instead of clearing screen
        if not first_run:
            move_cursor_to_top()
        
        # Print header and time
        time_str = bcolors.YELLOW + getTime() + bcolors.ENDC
        header = bcolors.WHITE + "CODE         NAME                 LATEST      CHANGE" + bcolors.ENDC
        separator = bcolors.WHITE + "=" * 100 + bcolors.ENDC
        
        print(f"{time_str:<120}")  # Fixed width to overwrite previous time
        print(f"{header:<120}")
        print(f"{separator:<120}")
        
        # Print stock data
        for code, stock_line in stock_lines:
            # Add padding to ensure line is fully overwritten
            padded_line = f"{stock_line:<120}"
            print(padded_line)
        
        # Clear any remaining lines from previous output
        if not first_run:
            # Print empty lines to clear any leftover content
            for _ in range(3):
                print(" " * 120)
        
        previous_data = current_data
        first_run = False
        
    except requests.RequestException as e:
        error_msg = f"{bcolors.RED}Network error: {e}{bcolors.ENDC}"
        print(f"{error_msg:<120}")
    except Exception as e:
        error_msg = f"{bcolors.RED}Unexpected error: {e}{bcolors.ENDC}"
        print(f"{error_msg:<120}")


if __name__ == '__main__':
    try:
        readData()
        clear_screen()  # Clear screen only once at startup
        hide_cursor()   # Hide cursor to reduce flicker
        
        while True:
            printStock()
            time.sleep(1)  # Slightly longer interval for smoother updates
            
    except KeyboardInterrupt:
        show_cursor()  # Show cursor before exit
        print(f"\n{bcolors.YELLOW}程序已退出{bcolors.ENDC}")
        sys.exit(0)
    except Exception as e:
        show_cursor()
        print(f"\n{bcolors.RED}程序错误: {e}{bcolors.ENDC}")
        sys.exit(1)
