# -*- coding:utf-8 -*-
import os
import json
import time
import queue
import base64
import websocket
import threading
from threading import RLock

from common import req_util


OP_AUTH   = "auth"
OP_PING   = "ping"
OP_PONG   = "pong"
OP_SUB    = "sub"
OP_UNSUB  = "unsub"
OP_UPDATE = "update"


config = {}
with open(os.environ['API_DEMO_HOMEPATH']+'/conf/config.json', 'r') as f:
        config = json.load(f)



class WSClientBase:


    def __init__(self, token, ws_host=config["ws_host"], ws_origin=config["ws_origin"]):
        self.ws_host = ws_host
        self.ws_origin = ws_origin
        self.token = token
        self._isrun = False
        self.auth_flag = False
        self._q = queue.Queue()
        self._lock = RLock()
        self._wait = []
        self.ws = websocket.WebSocketApp(self.ws_host,
                    on_message = lambda ws,msg: self.on_message(ws, msg),
                    on_error   = lambda ws,msg: self.on_error(ws, msg),
                    on_close   = lambda ws: self.on_close(ws),
                    on_open    = lambda ws: self.on_open(ws))

    def on_open(self, ws):
        """打开连接做鉴权"""
        ws.send(json.dumps({
            "op": OP_AUTH,
            "accessToken": self.token
        }))

    def on_message(self, ws, msg):
        recv = json.loads(msg)

        if recv.get('code', 0) != 0:
            print('fail, reply:%s' % recv)

        # 服务端心跳
        if recv["op"] == "ping":
            ws.send(json.dumps({
                "op": OP_PONG
            }))

        # 服务端认证成功
        if recv["op"] == "auth":
            if recv["code"] == 0:
                print('auth success')
                self.auth_flag = True

        # 服务端行情推送数据
        if recv["op"] == "update": 
            data = base64.b64decode(recv["data"]).decode("utf-8")
            self.handler(recv["topic"], data)

        if recv["op"] == "offline":
            print("force offline")
            ws.close()

    def on_error(self, ws, error):
        print('error:', type(error), error)

    def on_close(self, ws):
        self._isrun = False
        self._q.put("close")
        print("ws client closed")

    def run(self):
        self._isrun = True
        websocket.enableTrace(False)
        threading.Thread(target=self.op).start()
        self.ws.run_forever(origin=self.ws_origin)

    def send(self, s):
        self._lock.acquire()
        self._q.put(s)
        self._lock.release()

    def op(self):
        """独立线程处理订阅/取消订阅等操作"""
        while True:
            s = self._q.get()
            if not self._isrun:
                break
            # 需要鉴权通过
            if self.auth_flag:
                while self._wait:
                    wait_s = self._wait.pop()
                    self.ws.send(wait_s)
                self.ws.send(s)
            # 延迟操作
            else:
                self._lock.acquire()
                if self._q.empty():
                    self._q.put(s)
                else:
                    self._wait.insert(0, s)
                self._lock.release()
                time.sleep(1)

    def handler(self, topic, data):
        """业务处理"""
        print(topic, data)



