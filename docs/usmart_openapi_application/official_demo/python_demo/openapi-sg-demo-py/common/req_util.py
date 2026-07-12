# -*- coding: utf-8 -*-
import json
import requests
import os
from common.utils import EncryptUtil






class RequestUtil:


    def __init__(self, trade_host, quote_host, X_Lang, X_Channel, areaCode, 
                phoneNumber, login_password, trade_passwrod, public_key, private_key, X_Type):
        self.token = None
        self.trade_host = trade_host
        self.quote_host = quote_host
        self.X_Lang = X_Lang
        self.X_Channel = X_Channel
        self.areaCode = areaCode
        self.phoneNumber = phoneNumber
        self.login_password = login_password
        self.trade_passwrod = trade_passwrod
        self.X_Type = X_Type
        self.encryptUtil = EncryptUtil(public_key, private_key)

    def login(self):
        """账号密码登录接口"""
        api = '/user-server-sg/open-api/login'
        params = {
            "phoneNumber": self.encryptUtil.rsa_encrypt(self.phoneNumber),
            "password": self.encryptUtil.rsa_encrypt(self.login_password),
            "areaCode": self.areaCode,
        }
        
        res = self.post_with_sign_by_trade(api, params)
        code = res.get('code')
        if code != 0:
            print("request login fail: ", res)
            return None

        token = res['data']['token']
        self.token = token
        return token

    def post_with_sign_by_trade(self, api, params, headers={}):
        """交易接口请求"""
        header = {
            'Content-type': 'application/json; charset=utf-8',
            'X-Lang': self.X_Lang,
            'X-Channel': self.X_Channel,
            'X-Sign': self.encryptUtil.sign_to_b64str(json.dumps(params)),
            'Authorization': self.token
        }
        header.update(headers)

        url = self.trade_host + api
        res = requests.post(url, data=json.dumps(params), headers=header, timeout=5)
        ret = json.loads(res.text)
        return ret

    def post_with_sign_by_quote(self, api, params, headers={}):
        """行情接口请求"""
        header = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": self.token,
            "X-Channel": self.X_Channel,
            "X-Lang": self.X_Lang,
            "X-Request-Id": self.encryptUtil.gen_serialno_str(),
            "X-Time": self.encryptUtil.gen_unix_time_str(10)
        }
        header.update(headers)

        params_str = json.dumps(params)
        rowContent = header["Authorization"] + header["X-Channel"] + header["X-Lang"] + header["X-Request-Id"] + header["X-Time"] + params_str
        header["X-Sign"] = self.encryptUtil.sign_with_urlsafe_b64str(rowContent)

        url = self.quote_host + api
        res = requests.post(url, data=params_str, headers=header, timeout=5)
        if res.status_code != 200:
            return res
        ret = json.loads(res.text)
        return ret

