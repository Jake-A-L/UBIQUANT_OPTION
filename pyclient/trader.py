from common.phx_protocol import *
from common.phx_structs import *
from common.phx_definitions import *
from common.phx_trader_spi import CPhxFtdcTraderSpi
from common.phx_trader_api import CPhxFtdcTraderApi
from test.OrderManager import OrderManager
import time
import json
from collections import deque
from optparse import OptionParser
from random import randint, random
from test.OrderList import OrderList, OrderInfo, Snapshot
import threading
import copy
import pandas as pd
import math


class MyClient(CPhxFtdcTraderSpi):
    def __init__(self):
        super().__init__()
        self.serverHost = '127.0.0.1'
        self.serverOrderPort = 0
        self.serverQryPort = 0
        self.serverRtnPort = 0
        self.serverMDPort = 0
        self.nRequestID = 0
        self.orderRef = 0
        self.m_Token = ''
        self.m_UserID = None
        self.m_Passwd = '123456'
        self.m_LoginStatus = [False, False, False, False]
        self.query_status = False
        self.is_any_updated = False
        self.game_status = None
        self.ins2om = {}
        self.ins2index = {}
        self.instruments = []
        self.md_list = []  # array of md deque
        self.inst_num = 0
        self.market_data_updated = []
        self._background = []
        self.strategy_list = []
        self.switch = False
        self.strike_list = [50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74,
                            76, 78, 80, 83, 86, 89, 92, 95, 98, 101, 104, 107,
                            110, 114, 118, 122, 126, 130, 134, 138, 142, 146,
                            150]
        self.sem = threading.Semaphore(True)
        """
        Initiate API
        """
        self.m_pUserApi = CPhxFtdcTraderApi()

    def add_strategy(self,strategy):
        self.strategy = strategy


    def reset(self):
        """Reset function after each round"""
        for ins, om in self.ins2om.items():
            om.clear()
            self.md_list[self.ins2index[ins]].clear()
            self.market_data_updated[self.ins2index[ins]] = False

        self.is_any_updated = False

    def next_request_id(self):
        self.nRequestID += 1
        return self.nRequestID

    def next_order_ref(self):
        self.orderRef += 1
        return self.orderRef

    def OnFrontConnected(self):
        print("OnFrontConnected, Start to ReqUserLogin")
        self.ReqUserLogin()

    def ReqUserLogin(self):
        field = CPhxFtdcReqUserLoginField()
        field.UserID = self.m_UserID
        field.Password = self.m_Passwd
        ret = self.m_pUserApi.ReqUserLogin(field, PHX_LINK_TYPE_Order, self.next_request_id())
        print("ReqUserLogin Order (%s:%d) ret=%d" % (self.serverHost, self.serverOrderPort, ret))
        ret = self.m_pUserApi.ReqUserLogin(field, PHX_LINK_TYPE_Qry, self.next_request_id())
        print("ReqUserLogin Qry (%s:%d) ret=%d" % (self.serverHost, self.serverQryPort, ret))
        ret = self.m_pUserApi.ReqUserLogin(field, PHX_LINK_TYPE_Rtn, self.next_request_id())
        print("ReqUserLoginRtn  (%s:%d) ret=%d" % (self.serverHost, self.serverRtnPort, ret))
        ret = self.m_pUserApi.ReqUserLogin(field, PHX_LINK_TYPE_MD, self.next_request_id())
        print("ReqUserLogin MD (%s:%d) ret=%d" % (self.serverHost, self.serverMDPort, ret))

    def ReqUserLogout(self):
        field = CPhxFtdcReqUserLogoutField()
        field.UserID = self.m_UserID
        ret = self.m_pUserApi.ReqUserLogout(field, PHX_LINK_TYPE_Order, self.next_request_id())
        print("ReqUserLogout Order (%s:%d) ret=%d" % (self.serverHost, self.serverOrderPort, ret))
        ret = self.m_pUserApi.ReqUserLogout(field, PHX_LINK_TYPE_Qry, self.next_request_id())
        print("ReqUserLogout Qry (%s:%d) ret=%d" % (self.serverHost, self.serverQryPort, ret))
        ret = self.m_pUserApi.ReqUserLogout(field, PHX_LINK_TYPE_Rtn, self.next_request_id())
        print("ReqUserLogout Rtn  (%s:%d) ret=%d" % (self.serverHost, self.serverRtnPort, ret))
        ret = self.m_pUserApi.ReqUserLogout(field, PHX_LINK_TYPE_MD, self.next_request_id())

    def OnRspUserLogin(self, pRspUserLogin: CPhxFtdcRspUserLoginField, LinkType, ErrorID, nRequestID):
        print('OnRspUserLogin, data=%s, ErrorID=%d, ErrMsg=%s, nRequestID=%d' % (json.dumps(pRspUserLogin.__dict__), ErrorID, get_server_error(ErrorID), nRequestID))
        if ErrorID == 0:
            self.m_LoginStatus[LinkType] = True
            if pRspUserLogin.MaxOrderLocalID > self.orderRef:
                self.orderRef = pRspUserLogin.MaxOrderLocalID + 1

    def OnRspOrderInsert(self, pInputOrder: CPhxFtdcInputOrderField, ErrorID):
        if ErrorID != 0:
            print('OnRspOrderInsert, orderRef=%d, ErrorID=%d, ErrMsg=%s' % (pInputOrder.OrderLocalID, ErrorID, get_server_error(ErrorID)))
            if pInputOrder.InstrumentID not in self.ins2om:
                return
            om = self.ins2om[pInputOrder.InstrumentID]
            om.on_rsp_order_insert(pInputOrder.OrderLocalID)

    def OnRspOrderAction(self, pInputOrderAction: CPhxFtdcOrderActionField, ErrorID):
        if ErrorID != 0:
            print('OnRspOrderAction, orderRef=%d, ErrorID=%d, ErrMsg=%s' % (pInputOrderAction.OrderLocalID, ErrorID, get_server_error(ErrorID)))

    def OnRspQryTradingAccount(self, pTradingAccount: CPhxFtdcRspClientAccountField, ErrorID, nRequestID, bIsLast):
        print('OnRspQryTradingAccount, ErrorID=%d, ErrMsg=%s, bIsLast=%d' % (ErrorID, get_server_error(ErrorID), bIsLast))
        print(pd.Series(pTradingAccount.__dict__))

    def OnRspQryInstrument(self, pInstrument: CPhxFtdcRspInstrumentField, ErrorID, nRequestID, bIsLast):
        # print('OnRspQryInstrument, data=%s, ErrorID=%d, bIsLast=%d' % (json.dumps(pInstrument.__dict__), ErrorID, bIsLast))
        if pInstrument.InstrumentID not in self.ins2om:
            self.ins2om[pInstrument.InstrumentID] = OrderManager(pInstrument.InstrumentID)
            self.md_list.append(deque(maxlen=10))
            self.instruments.append(copy.copy(pInstrument))
            self.market_data_updated.append(False)
            self.ins2index[pInstrument.InstrumentID] = self.inst_num
            self.inst_num += 1
        if bIsLast:
            self.query_status = True
            print("total %d instruments" % self.inst_num)

    def OnRtnGameStatus(self, pGameStatus: CPhxFtdcGameStatusField):
        # print('OnRtnGameStatus, data=%s' % json.dumps(pGameStatus.__dict__))
        self.game_status = pGameStatus

    def OnRtnMarketData(self, pMarketData: CPhxFtdcDepthMarketDataField):
        #print(pMarketData.InstrumentID)
        if pMarketData.InstrumentID in self.ins2index:
            # print('OnRtnMarketData, data=%s' % json.dumps(pMarketData.__dict__))
            index = self.ins2index[pMarketData.InstrumentID]
            self.md_list[index].append(pMarketData)
            self.market_data_updated[index] = True
            self.is_any_updated = True

    def OnRtnOrder(self, pOrder: CPhxFtdcOrderField):
        if pOrder.InstrumentID not in self.ins2om:
            return
        om = self.ins2om[pOrder.InstrumentID]
        om.on_rtn_order(pOrder)

    def OnRtnTrade(self, pTrade: CPhxFtdcTradeField):
        # print('OnRtnTrade, data=%s' % json.dumps(pTrade.__dict__))
        if pTrade.InstrumentID not in self.ins2om:
            return
        om = self.ins2om[pTrade.InstrumentID]
        om.on_rtn_trade(pTrade)

    def OnErrRtnOrderInsert(self, pInputOrder: CPhxFtdcInputOrderField, ErrorID):
        if ErrorID != 0:
            print('OnErrRtnOrderInsert, orderRef=%d, ErrorID=%d, ErrMsg=%s' % (pInputOrder.OrderLocalID, pInputOrder.ExchangeErrorID, get_server_error(pInputOrder.ExchangeErrorID)))
            if pInputOrder.InstrumentID not in self.ins2om:
                return
            om = self.ins2om[pInputOrder.InstrumentID]
            om.on_rsp_order_insert(pInputOrder.OrderLocalID)

    def OnErrRtnOrderAction(self, pOrderAction: CPhxFtdcOrderActionField, ErrorID):
        if ErrorID != 0:
            print('OnErrRtnOrderAction, orderRef=%d, ErrorID=%d, ErrMsg=%s' % (pOrderAction.OrderLocalID, pOrderAction.ExchangeErrorID, get_server_error(pOrderAction.ExchangeErrorID)))

    def OnRspQryOrder(self, pOrder: CPhxFtdcOrderField, ErrorID, nRequestID, bIsLast):
        if pOrder is not None and ErrorID == 0:
            if pOrder.InstrumentID not in self.ins2om:
                return
            om = self.ins2om[pOrder.InstrumentID]
            om.insert_init_order(pOrder)
            om.on_rtn_order(pOrder)

        if bIsLast:
            self.query_status = True
            print("init order query over")

    def OnRspQryTrade(self, pTrade: CPhxFtdcTradeField, ErrorID, nRequestID, bIsLast):
        if pTrade is not None and ErrorID == 0:
            if pTrade.InstrumentID not in self.ins2om:
                return
            om = self.ins2om[pTrade.InstrumentID]
            om.on_rtn_trade(pTrade)

        if bIsLast:
            self.query_status = True
            print("init trade query over")

    def timeout_wait(self, timeout, condition=None):
        while timeout > 0:
            time.sleep(1)
            timeout -= 1
            if condition is None:
                if self.query_status:
                    return True
            elif isinstance(condition, list):
                if all(condition):
                    return True
        return False

    def Init(self):
        self.m_pUserApi.RegisterSpi(self)
        self.m_pUserApi.RegisterOrderFront(self.serverHost, self.serverOrderPort)
        self.m_pUserApi.RegisterQryFront(self.serverHost, self.serverQryPort)
        self.m_pUserApi.RegisterRtnFront(self.serverHost, self.serverRtnPort)
        self.m_pUserApi.RegisterMDFront(self.serverHost, self.serverMDPort)

        self.m_pUserApi.Init()
        if not self.timeout_wait(10, self.m_LoginStatus):
            return False

        print("OnRspUserLogin, all link ready")
        self.query_status = False
        ret = self.m_pUserApi.ReqQryInstrument(CPhxFtdcQryInstrumentField(), self.next_request_id())
        if (not ret) or (not self.timeout_wait(10)):
            print("ReqQryInstrument failed")
            return False

        self.query_status = False
        field = CPhxFtdcQryOrderField()
        field.InvestorID = self.m_UserID
        ret = self.m_pUserApi.ReqQryOrder(field, self.next_request_id())
        if (not ret) or (not self.timeout_wait(10)):
            print("ReqQryOrder failed")
            return False

        self.query_status = False
        field = CPhxFtdcQryTradeField()
        field.InvestorID = self.m_UserID
        ret = self.m_pUserApi.ReqQryTrade(field, self.next_request_id())
        if (not ret) or (not self.timeout_wait(10)):
            print("ReqQryTrade failed")
            return False
        """
        self._background = threading.Thread(target=self.background_thread)
        self._background.start()
        """
        if not self.timeout_wait(10):
            return False
        return True

    def random_direction(self):
        if randint(0, 1) == 0:
            return PHX_FTDC_D_Buy
        else:
            return PHX_FTDC_D_Sell

    def random_offset(self):
        if randint(0, 1) == 0:
            return PHX_FTDC_OF_Open
        else:
            return PHX_FTDC_OF_Close

    def send_input_order(self, order: OrderInfo):
        field = CPhxFtdcQuickInputOrderField()
        field.OrderPriceType = order.OrderPriceType
        field.OffsetFlag = order.OffsetFlag
        field.HedgeFlag = PHX_FTDC_HF_Speculation
        field.InstrumentID = order.InstrumentID
        field.Direction = order.Direction
        field.VolumeTotalOriginal = order.VolumeTotalOriginal
        field.TimeCondition = PHX_FTDC_TC_GFD
        field.VolumeCondition = PHX_FTDC_VC_AV
        if order.OrderPriceType == PHX_FTDC_OPT_LimitPrice:
            field.LimitPrice = order.LimitPrice
        field.OrderLocalID = order.OrderLocalID
        ret = self.m_pUserApi.ReqQuickOrderInsert(field, self.next_request_id())
       #print("QuickOrderInsert ", field, ret)

    def send_cancel_order(self, order: OrderInfo):
        field = CPhxFtdcOrderActionField()
        field.OrderSysID = order.OrderSysID
        field.InvestorID = self.m_UserID
        field.OrderLocalID = order.OrderLocalID
        ret = self.m_pUserApi.ReqOrderAction(field, self.next_request_id())
       # print("ActionOrder data=%s, ret=%d" % (json.dumps(field.__dict__), ret))

    def check_account(self):
        print("Check Account")
        field = CPhxFtdcQryClientAccountField()
        if self.m_pUserApi.all_connected:
            ret= self.m_pUserApi.ReqQryTradingAccount(field, self.next_request_id())
            if not ret:
                print("ReqQryTradingAccount failed")

    def check_position(self):
        print('Check Position')
        field = CPhxFtdcQryClientPositionField()
        if self.m_pUserApi.all_connected:
            ret = self.m_pUserApi.ReqQryInvestorPosition(field, self.next_request_id())
            if not ret:
                print("ReqQryClientPosition failed")
        else:
            print("Not Connected")

    def orders(self):
        print("Orders")
        field = CPhxFtdcQryOrderField()
        if self.m_pUserApi.all_connected:
            ret = self.m_pUserApi.ReqQryOrder(field, self.next_request_id())
            if not ret:
                print("ReqQryOrder failed")
        else:
            print("Not Connected")

    def get_instruments(self):
        field1 = CPhxFtdcQryInstrumentField()
        field2 = CPhxFtdcQryInstrumentStatusField()
        if self.m_pUserApi.all_connected:
            ret1 = self.m_pUserApi.ReqQryInstrument(field1,self.next_request_id())
            if not ret1:
                print("ReqQryInstrument failed")
            ret2 = self.m_pUserApi.ReqQryInstrumentStatus(field2, self.next_request_id())
            if not ret2:
                print("ReqQryInstrumentStatus failed")
        else:
            print("Not Connected")


    def convert_md(self,pMarketData:CPhxFtdcDepthMarketDataField):
        df_dict = {
            "LastPrice":[pMarketData.LastPrice], "LastVolume":[pMarketData.LastVolume], "ExchangeTime":[pMarketData.ExchangeTime], "InstrumentID":[pMarketData.InstrumentID],
            "BidPrice1":[pMarketData.BidPrice1], "BidVolume1":[pMarketData.BidVolume1], "AskPrice1":[pMarketData.AskPrice1], "AskVolume1":[pMarketData.AskVolume1],
            "BidPrice2":[pMarketData.BidPrice2], "BidVolume2":[pMarketData.BidVolume2], "AskPrice2":[pMarketData.AskPrice2], "AskVolume2":[pMarketData.AskVolume2],
            "BidPrice3":[pMarketData.BidPrice3], "BidVolume3":[pMarketData.BidVolume3], "AskPrice3":[pMarketData.AskPrice3], "AskVolume3":[pMarketData.AskVolume3],
            "BidPrice4":[pMarketData.BidPrice4], "BidVolume4":[pMarketData.BidVolume4], "AskPrice4":[pMarketData.AskPrice4], "AskVolume4":[pMarketData.AskVolume4],
            "BidPrice5":[pMarketData.BidPrice5], "BidVolume5":[pMarketData.BidVolume5], "AskPrice5":[pMarketData.AskPrice5], "AskVolume5":[pMarketData.AskVolume5]
        }
        return pd.DataFrame(df_dict)

    def download_md(self,ins_idx):
        pass

    def get_latest_md(self, ins_idx):
        if self.md_list[ins_idx]:
            return self.convert_md(self.md_list[ins_idx][-1])
        else:
            print("ins_idx %d no deep market data" % (ins_idx))
            return None

    def background_control(self):
        self.sem.acquire()
        print(self.switch)
        while self.switch:
            self.check_account()
            print(self._get_price(['UBIQ'])['UBIQ']['ask'])
            time.sleep(5)
            move = input("Add or Kill?")
            if move == 'c':
                self.clear()
                print("Position Cleared.")
            elif move == 'k':
                #Kill All Threads
                self.switch = False
            elif move == 'm':
                ids = input("ID?")
                ids = [int(idx) for idx in ids.split(",")]
                temp = []
                for id in ids:
                    if id < 73 and id >0:
                        try:
                            temp.append(client.get_latest_md(id))
                        except AttributeError:
                            print("{} No latest MD".format(id))
                    else:
                        print("Invalid ID")
                print(pd.concat(temp).T)
            self.sem.release()

    def background_interface(self):
        self._background.append(threading.Thread(target=self.background_run))
        self._background.append(threading.Thread(target=self.background_control))
        for t in self._background:
            t.start()
        for t in self._background:
            t.join()

    def background_run(self):
        while self.switch:
            self.sem.acquire()
            for f in self.strategy_list:
                f()
            self.sem.release()
            time.sleep(1.5)
        print("All Strategy Ended")


    def background_add(self,func):
        self.strategy_list.append(func)

    def simple(self):
        print("Running Simple")
        ins_i = 10
        test_data = self.md_list[self.ins2index[self.instruments[ins_i].InstrumentID]]
        if len(test_data) != 0:
            #print(test_data[-1])
            best_ask = test_data[-1].BidPrice1
            best_bid = test_data[-1].AskPrice1
            ins = self.instruments[ins_i]
            om = self.ins2om[ins.InstrumentID]
            order_buy = om.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Open, best_bid - 0.01,
                                             10)
            order_sell = om.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Sell, PHX_FTDC_OF_Open, best_ask + 0.01,10)
            self.send_input_order(order_buy)
            self.send_input_order(order_sell)

        self.market_data_updated[ins_i] = False  # reset flag
        self.is_any_updated = False  # reset flag


    def get_obligate(self):
        """获取当前有做市义务的合约"""
        FutureData = self.md_list[self.ins2index['UBIQ']]
        FutureMidPrice = 0.5 * (FutureData[-1].BidPrice1 + FutureData[-1].AskPrice1)  # 期货合约中间价
        [_lower, _upper] = [FutureMidPrice * 0.9, FutureMidPrice * 1.1]  # 义务合约strike的范围，期货价上下10%

        for i in range(len(self.strike_list)):
            if self.strike_list[i] < _lower * 10 <= self.strike_list[i + 1]:
                break
        for j in range(i, len(self.strike_list)):
            if self.strike_list[j] <= _upper * 10 < self.strike_list[j + 1]:
                break

        obligate_strike = ['%03d' % i for i in self.strike_list[i + 1:j + 1]]
        # print('future price', FutureMidPrice)
        return ['C' + _ for _ in obligate_strike] + ['P' + _ for _ in obligate_strike]  # 返回义务合约代码列表

    def get_price(self,ID):
        """获取合约当前最优买卖价"""
        best_price = {}
        for ins_id in ID:
            md_i = self.md_list[self.ins2index[ins_id]]
            if len(md_i) > 2:
                best_price[ins_id] = {'ask': md_i[-1].AskPrice1,
                                      'bid': md_i[-1].BidPrice1,
                                      'spread': md_i[-1].AskPrice1 - md_i[-1].BidPrice1,
                                      'mid_price': 0.5 * (md_i[-1].AskPrice1 + md_i[-1].BidPrice1)}
            else:
                best_price[ins_id] = {'ask': 0, 'bid': 0, 'spread': 0}
        return best_price  # 返回一个dictionary

    def _get_price(self,ID_list):
        """获取合约当前最优买卖价"""
        best_price = {}
        for ins_id in ID_list:
            md_i = self.md_list[self.ins2index[ins_id]]
            if len(md_i) > 2:  # 订单数量超过2条才开始计入
                best_price[ins_id] = {'ask': md_i[-1].AskPrice1,
                                      'ask_vol': md_i[-1].AskVolume1,
                                      'bid': md_i[-1].BidPrice1,
                                      'bid_vol': md_i[-1].BidVolume1,
                                      'spread': md_i[-1].AskPrice1 - md_i[-1].BidPrice1,
                                      'mid_price': 0.5 * (md_i[-1].AskPrice1 + md_i[-1].BidPrice1)}
            else:
                best_price[ins_id] = {'ask': 0, 'ask_vol': 0, 'bid': 0, 'bid_vol': 0, 'spread': 0, 'mid_price': 0}
        return best_price  # 返回一个dictionary


    def max_spread(self,ask_price):
        """计算义务合约最大有效价差"""
        if ask_price <= 0.1:
            return 0.005
        elif 0.1 < ask_price <= 0.2:
            return 0.01
        elif 0.2 < ask_price <= 0.5:
            return 0.025
        elif 0.5 < ask_price <= 1.0:
            return 0.05
        elif 1.0 < ask_price:
            return 0.08

    def get_effective_price(self, ID, dir):
        if dir == 'bid':
            orders = self.ins2om[ID].bid_list.get_orders()
            vol_count = 0
            for order in list(filter(lambda x: (x.Direction == PHX_FTDC_D_Buy and x.OffsetFlag == PHX_FTDC_OF_Open) or \
                                               (x.Direction == PHX_FTDC_D_Buy and x.OffsetFlag == PHX_FTDC_OF_Close),
                                     orders)):
                vol_count += (order.VolumeTotalOriginal - order.VolumeTraded)
                price = order.LimitPrice
                if vol_count >= 11:
                    break
            if vol_count < 11:
                return 0
            else:
                return price
        else:
            orders = self.ins2om[ID].ask_list.get_orders()
            vol = self.ins2om[ID].get_effective_long_trading_volume()
            if vol <= 10:
                return 0
            else:
                vol_count = 0
                for order in list(
                        filter(lambda x: (x.Direction == PHX_FTDC_D_Sell and x.OffsetFlag == PHX_FTDC_OF_Open) or \
                                         (x.Direction == PHX_FTDC_D_Sell and x.OffsetFlag == PHX_FTDC_OF_Close),
                               orders)):
                    vol_count += (order.VolumeTotalOriginal - order.VolumeTraded)
                    price = order.LimitPrice
                    if vol_count >= 11:
                        break
                if vol_count < 11:
                    return 0
                else:
                    return price

        # 以下为策略主体
    def parity(self):
        #print("Running Parity")
        ttm = self.game_status.CurrGameCycleLeftTime / 900
        for strike in self.strike_list:
            CallID = 'C' + '%03d' % strike
            PutID = 'P' + '%03d' % strike
            Opt_Future_Price = self._get_price(['UBIQ', CallID, PutID])
            # 在各个合约均有报价的情况下，判断call-put parity
            if Opt_Future_Price[CallID]['bid'] and Opt_Future_Price[CallID]['ask'] and \
                    Opt_Future_Price[PutID]['bid'] and Opt_Future_Price[PutID]['ask']:
                # C + K > S + P, 卖call，买future，put
                if (Opt_Future_Price[CallID]['bid'] + strike * math.exp(-0.5 * 0.0015 ** 2 * ttm)) > \
                        (Opt_Future_Price[PutID]['ask'] + Opt_Future_Price['UBIQ']['ask']) + 0.1:
                    vol = min(min(Opt_Future_Price[CallID]['bid_vol'],Opt_Future_Price[PutID]['ask_vol']),50)  # 取call，put最小的vol开仓
                    order_buy_put = self.ins2om[PutID].place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy,
                                                                          PHX_FTDC_OF_Open, vol)
                    order_buy_future = self.ins2om['UBIQ'].place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy,
                                                                              PHX_FTDC_OF_Open, vol)
                    order_sell_call = self.ins2om[CallID].place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell,
                                                                             PHX_FTDC_OF_Open, vol)
                    self.send_input_order(order_buy_put)
                    self.send_input_order(order_buy_future)
                    self.send_input_order(order_sell_call)
                # C + K < S + P, 买call，卖future，put
                elif (Opt_Future_Price[CallID]['ask'] + strike * math.exp(-0.5 * 0.0015 ** 2 * ttm)) < \
                        (Opt_Future_Price[PutID]['bid'] + Opt_Future_Price['UBIQ']['bid']) - 0.1:
                    vol = min(min(Opt_Future_Price[CallID]['ask_vol'], Opt_Future_Price[PutID]['bid_vol']),
                              50)  # 取call，put最小的vol开仓
                    order_sell_put = self.ins2om[PutID].place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell,
                                                                           PHX_FTDC_OF_Open, vol)
                    order_sell_future = self.ins2om['UBIQ'].place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell,
                                                                               PHX_FTDC_OF_Open, vol)
                    order_buy_call = self.ins2om[CallID].place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy,
                                                                            PHX_FTDC_OF_Open, vol)
                    self.send_input_order(order_sell_put)
                    self.send_input_order(order_sell_future)
                    self.send_input_order(order_buy_call)

            # self.market_data_updated[self.ins2index[CallID]] = False  # reset flag
            # self.market_data_updated[self.ins2index[PutID]] = False  # reset flag
        #
        self.is_any_updated = True  # reset flag

    def new_strat(self):
        obligateID = self.get_obligate()  # 当前有做市义务的合约ID列表
        # print('Instrument with obligation\n', obligateID)

        obligate_price = self.get_price(obligateID)  # 获取当前义务合约买卖价及价差,dictionary
        # print('the price are:\n', obligate_price)

        for insID in obligateID:
            MaxSpread = self.max_spread(obligate_price[insID]['ask'])

            if obligate_price[insID]['ask']:  # 当前市场订单非空

                if obligate_price[insID]['spread'] < MaxSpread:  # 市场价差小于有效价差
                    # 以中间价上下 0.5 * 最大有效价差 进行报价
                    MyAsk = obligate_price[insID]['ask']+.001# + 0.5 * MaxSpread
                    MyBid = obligate_price[insID]['bid']-.001# - 0.5 * MaxSpread
                    om_ins = self.ins2om[insID]
                    order_buy = om_ins.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Open, MyBid,
                                                         100)
                    order_sell = om_ins.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Sell, PHX_FTDC_OF_Open,
                                                          MyAsk, 100)
                    self.send_input_order(order_buy)
                    self.send_input_order(order_sell)

            self.market_data_updated[self.ins2index[insID]] = False  # reset flag
        self.is_any_updated = True  # reset flag

        calls_str = ['C' + '%03d' % i for i in self.strike_list]
        puts_str=['P' + '%03d' % i for i in self.strike_list]
        for strikes in [calls_str,puts_str]:
            for ind,ID in enumerate(strikes):
                if ind>1:
                    ID_A,ID_B,ID_C = strikes[ind-2],strikes[ind-1],ID
                    if len(self.md_list[self.ins2index[ID_A]]) * len(self.md_list[self.ins2index[ID_B]]) * len(
                            self.md_list[self.ins2index[ID_C]]) == 0:
                        continue
                    p_A = self.md_list[self.ins2index[ID_A]][-1].AskPrice1
                    p_B = self.md_list[self.ins2index[ID_B]][-1].BidPrice1
                    p_C = self.md_list[self.ins2index[ID_C]][-1].AskPrice1
                    [s_A, s_B, s_C] = [int(strikes[i][1:]) for i in [ind-2,ind-1,ind]]
                    if ((p_C-p_B)/(s_C-s_B))<((p_B-p_A)/(s_B-s_A)):
                        vol=min(100,min(self.md_list[self.ins2index[ID_A]][-1].AskVolume1,
                                        self.md_list[self.ins2index[ID_B]][-1].BidVolume1,
                                        self.md_list[self.ins2index[ID_A]][-1].AskVolume1))
                        om_A = self.ins2om[ID_A]
                        order = om_A.place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Open,vol)
                        self.send_input_order(order)
                        om_C = self.ins2om[ID_C]
                        order = om_C.place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Open,vol)
                        self.send_input_order(order)
                        om_B = self.ins2om[ID_B]
                        order = om_B.place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell, PHX_FTDC_OF_Open,vol)
                        self.send_input_order(order)
    def deep(self):
        deep_out_put = ['P056','P058','P060','P062','P064','P052','P054']
        deep_out_call = ['C150', 'C146', 'C142','C138','C134','C130','C126']
        deep = deep_out_put + deep_out_call
        for deepID in deep:
            order_sell_deep = self.ins2om[deepID].place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell,
                                                                     PHX_FTDC_OF_Open, 100)
            self.send_input_order(order_sell_deep)

    def clear(self):
        for om in self.ins2om.values():
            target = int(om.longOpenPosition / 100)
            for _ in range(target):
                order = om.place_market_order(self.next_order_ref(), PHX_FTDC_D_Sell, PHX_FTDC_OF_Close, 100)
                self.send_input_order(order)
            target = int(om.shortOpenPosition / 100)
            for _ in range(target):
                order = om.place_market_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Close, 100)
                self.send_input_order(order)

    def market_making(self):
        # # MyStrategy
        #print("Running MM")
        obligateID = self.get_obligate()  # 当前有做市义务的合约ID列表
        # print('Instrument with obligation\n', obligateID)
        obligate_price =self.get_price(obligateID)  # 获取当前义务合约买卖价及价差,dictionary
        # print('the price are:\n', obligate_price)

        for insID in obligateID:
            MaxSpread = self.max_spread(obligate_price[insID]['ask'])

            if obligate_price[insID]['ask']:  # 当前市场订单非空

                eff_ask=self.get_effective_price(insID,'ask')
                eff_bid=self.get_effective_price(insID,'bid')
                om_ins = self.ins2om[insID]
                MyAsk = obligate_price[insID]['ask'] + 0.5 * MaxSpread
                MyBid = obligate_price[insID]['bid'] - 0.5 * MaxSpread
                if eff_bid == 0 or eff_bid < MyBid:
                    eff_bid = obligate_price[insID]['bid']
                    order_buy = om_ins.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Buy, PHX_FTDC_OF_Open, eff_bid,
                                                         11)
                    self.send_input_order(order_buy)

                elif eff_ask == 0 or eff_ask > eff_bid + MaxSpread:
                    order_sell = om_ins.place_limit_order(self.next_order_ref(), PHX_FTDC_D_Sell, PHX_FTDC_OF_Open, obligate_price[insID]['ask']
                                                          , 11)
                    self.send_input_order(order_sell)


def start_game(client,resetted):
    if client.game_status is None or (not client.m_pUserApi.all_connected):
        print("server not started")
        time.sleep(1)
    elif client.game_status.GameStatus == 0:
        print("game not started, waitting for start")
        time.sleep(1)
    elif client.game_status.GameStatus == 1:
        resetted = False
        print("Ready to run strategy")
        #client.run_strategy()
        time.sleep(0.5)
    elif client.game_status.GameStatus == 2:
        print("game settling")
        time.sleep(1)
    elif client.game_status.GameStatus == 3:
        print("game settled, waiting for next round")
        if not resetted:
            client.reset()
            resetted = True
            print("client resetted")
        time.sleep(0.01)
    elif client.game_status.GameStatus == 4:
        print("game finished")


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-i", "--ip", dest="ip", help="server ip")
    parser.add_option("-p", "--port", dest="port", help="server ip")
    parser.add_option("-u", "--user_id", dest="user_id", help="user id")
    parser.add_option("-a", "--password", dest="password", help="password")
    (options, args) = parser.parse_args()
    server_ip = '127.0.0.1'
    order_port = 18023
    user_id = 3
    password = '123456'


    if options.ip:
        server_ip = options.ip
    if options.port:
        order_port = int(options.port)
    if options.user_id:
        user_id = int(options.user_id)
    if options.password:
        password = options.password

    client = MyClient()
    client.serverHost = server_ip
    client.serverOrderPort = order_port
    client.serverRtnPort = order_port + 1
    client.serverQryPort = order_port + 2
    client.serverMDPort = order_port + 3
    client.m_UserID = user_id
    client.m_Passwd = password
    #client.add_strategy(stg)
    thread_list = []
    while True:
        print("Next Action:")
        action = input('''
            Input 'start' to start game; Input 'md' to download market data; Input 'account' to query account; 
            Input 'position' to query position; Input 'kill' to kill strategy;Input 'out' to log out;
        ''')
        if action == 'quit':
            break
        elif action == 'start':
            if client.Init():
                print("init success")
                resetted = True
                start_game(client,resetted)
        elif action == 'check':
            resetted = True
            start_game(client,resetted)
        elif action == 'position':
            client.check_position()
        elif action == 'reset':
            client._background = []
            client.strategy_list = []
            print("Reset Finished.")
        elif action == 'md':
            #print(client.md_list)
            ids = input("ID?")
            if ids == 'all':
                for i in range(73):
                    temp = []
                    try:
                        temp.append(client.get_latest_md(id))
                    except AttributeError:
                        print("{} No latest MD".format(id))
                    else:
                        print("Invalid ID")
                    print(pd.concat(temp).T)
            else:
                ids = [int(idx) for idx in ids.split(",")]
                temp = []
                for id in ids:
                    if id < 73 and id >0:
                        try:
                            temp.append(client.get_latest_md(id))
                        except AttributeError:
                            print("{} No latest MD".format(id))
                    else:
                        print("Invalid ID")
                print(pd.concat(temp).T)
        elif action == 'account':
            client.check_account()
        elif action == 'order':
            client.orders()
        elif action == 'instrument':
            ins = client.get_instruments()
            # TBD
        elif action == 'clear':
            pass
        elif action == "run":
            strgy = input("Which strategy do you wish to apply?")
            #Add Strategy
            #client.background_add(client.parity)
            client.background_add(client.deep)
            client.background_add(client.new_strat)
            client.background_add(client.market_making)
            client.switch = True
            print("Start Trading")
            client.background_interface()
            #Add Control Thread

        elif action == 'out':
            client.ReqUserLogout()
        else:
            print("Invalid Token")
    else:
        print("init failed")
    print('Finished')

