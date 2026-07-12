# api-demo 

生产环境对接步骤请参考如下：
1、登录uSMART官网：https://www.usmart.hk/，点击右上角“注册/登录”
2、进入“个人中心” - “我的API”，获取生产对接的渠道号、公钥、私钥
3、接入demo下载链接：https://api-doc.usmart8.com/zh-cn/demo.html
4、API文档接口链接：https://api-doc.usmart8.com/zh-cn/

生产配置：
base_url_jy = "https://open-jy.usmartsg.com"
base_url_hq = "https://open-hz.usmartsg.com:8443"
quote_push_url = "wss://open-hz.yxzq.com:8443/wss/v1"
PUBLIC_KEY = 官网申请的公钥
PRIVATE_KEY = 官网申请的私钥
X_Channel = 官网申请的渠道号




配置示例
```
{
    # 域名配置
    "trade_host": "http://open-jy-uat.usmartsg.com",
    "quote_host": "https://open-hz-uat.usmartsg.com:8443",
    "ws_host": "wss://open-hz-uat.usmartsg.com:8443/wss/v1",
    "ws_origin": "https://open-hz-uat.usmartsg.com",
    # 默认用户配置
    "default_user": {
        "X-Lang": "1",
        "X-Channel": "914",
        "areaCode": "86",
        "phoneNumber": "15210372164",
        "login_password": "qwe123456",
        "trade_passwrod": "123456",
        "public_key": "",
        "private_key": ""
       },
    # 多用户配置
    "13750062348": {
        "X-Lang": "1",
        "X-Channel": "1000193854",
        "areaCode": "86",
        "phoneNumber": "13750062348",
        "login_password": "qwe123456",
        "trade_passwrod": "123456",
        "public_key": "",
        "private_key": ""
    }
}
```

config.json 配置项
- X-Channel 分配渠道号
- areaCode  手机区号
- phoneNumber  手机号
- login_password  登录密码
- public_key  公钥
- private_key 私钥

线上host配置
- "trade_host": "http://open-jy.usmartsg.com",
- "quote_host": "https://open-hz.usmartsg.com:8443",
- "ws_host": "wss://open-hz.usmartsg.com:8443/wss/v1",
- "ws_origin": "https://open-hz.usmartsg.com",

uat配置
- "trade_host": "http://open-jy-uat.usmartsg.com",
- "quote_host": "https://open-hz-uat.usmartsg.com:8443",
- "ws_host": "wss://open-hz-uat.yxzq.com/wss/v1",
- "ws_origin": "https://open-hz-uat.usmartsg.com",


文件说明 <br>
/api/trade.py 可自行按照文档添加接口 <br>
/api/quote_push.py 行情推送相关 <br>
example.py 例子 <br>

python版本：3.7.8

安装需要的包<br>
pip install -r ./requirements.txt

若出现 ModuleNotFoundError: No module named 'Crypto' 错误
可以手动将python安装目录下Lib/site-packages 下crypto文件夹名称改为Crypto

编辑器建议使用vscode或pycharm，不建议使用jupyter，因为jupyter使用项目路径不是当前文件夹路径，
会出现import错误的问题
