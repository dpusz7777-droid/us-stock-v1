# -*- coding: utf-8 -*-
import time
import random
import base64

from Crypto.Hash import MD5
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Signature.pkcs1_15 import PKCS115_SigScheme


charset = "utf-8"




class EncryptUtil:


    def __init__(self, pub_key_str, pri_key_str):
        self.public_key = ("-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----" % pub_key_str).encode(charset)
        self.private_key = ("-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----" % pri_key_str).encode(charset)
        # self.private_key = ("-----BEGIN PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----" % pub_key_str).encode(charset)
        # self.public_key = ("-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----" % pri_key_str).encode(charset)

    def rsa_encrypt(self, data):
        """PKCS#8"""
        pub_key = RSA.import_key(self.public_key)
        cipher_rsa = PKCS1_v1_5.new(pub_key)
        encrypted = cipher_rsa.encrypt(data.encode(charset))
        return base64.urlsafe_b64encode(encrypted).decode(charset)

    def md5_with_rsa(self, content):
        """MD5withRSA"""
        pri_key = RSA.import_key(self.private_key)
        signer = PKCS115_SigScheme(pri_key)
        m = MD5.new(content.encode(charset))
        return signer.sign(m)

    def sign_to_b64str(self, content):
        signature = self.md5_with_rsa(content)
        return base64.b64encode(signature).decode(charset)

    def sign_with_urlsafe_b64str(self, content):
        signature = self.md5_with_rsa(content)
        return base64.urlsafe_b64encode(signature).decode(charset)

    def gen_serialno_str(self):
        """generate length 19 unique str"""
        return str(int(time.time() * 10**6)) + str(random.randint(0, 999)).zfill(3)

    def gen_unix_time_str(self, lens=10):
        return str(int(time.time() * 10**(lens-10)))


