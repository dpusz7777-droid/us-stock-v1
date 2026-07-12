# -*- coding:utf-8 -*-
import json
import threading

from common import ws_util




class QuoteContext(ws_util.WSClientBase):


    def subscribe(self, topics):
        """
            行情订阅
            格式：行情类型+市场标识+股票代码
                Eg. ["rt.sz.000001", "ob.sh.600199", "tk.sh.600199"]
        """
        self.send(json.dumps({
            "op": ws_util.OP_SUB, 
            "topiclist": topics}
        ))

    def unsubscribe(self, topics):
        """
            行情取消订阅
            格式：行情类型+市场标识+股票代码
        """
        self.send(json.dumps({
            "op": ws_util.OP_UNSUB, 
            "topiclist": topics}
        ))

    def set_handler(self, func):
        """
            自定义业务接收函数 
            def func(topic, data): 
                pass
        """
        self.handler = func

    def start(self):
        self.run_thread = threading.Thread(target=self.run)
        self.run_thread.start()

    def stop(self):
        self.ws.close()

