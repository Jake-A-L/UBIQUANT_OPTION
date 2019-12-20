from common.phx_protocol import *
from common.phx_structs import *
from common.phx_definitions import *
from common.phx_trader_spi import CPhxFtdcTraderSpi
from common.phx_trader_api import CPhxFtdcTraderApi
from test.OrderManager import OrderManager
from collections import deque
from optparse import OptionParser
from test.OrderList import OrderList, OrderInfo, Snapshot


class Strategy():
    def __init__(self):
        self.stg_dict = {}
