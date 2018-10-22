# -*- coding: utf-8 -*-
# Created by richie at 2018/10/19


import json
import time
import requests
import qrcode
from io import BytesIO

from datetime import datetime, timedelta
from django.conf import settings
from .compat import urljoin
from .exceptions import CertError, ResultCodeFail, ReturnCodeFail, SignError, WXPayError
from .utils import dict_to_xml, gen_random_str, md5, now_str, xml_to_dict


class WXPay(object):
    """微信支付类"""

    def __init__(self, base_url, request_timeout,
                 appid,  mch_id, pay_key, notify_url,
                 apiclient_cert_path, apiclient_key_path,sandbox=False):

        self.base_url = base_url
        self.request_timeout = request_timeout

        self.appid = appid
        self.sandbox = sandbox
        self.mch_id = mch_id
        self.key = pay_key
        self.notify_url = notify_url

        self.apiclient_cert_path = apiclient_cert_path
        self.apiclient_key_path = apiclient_key_path


    def _post(self, path, data, use_cert=False, check_result=True):
        """添加发送签名
        处理返回结果成dict, 并检查签名
        """
        r = self._post_resp(path, data, use_cert)
        xml = r.text
        data = xml_to_dict(xml)
        # 使用证书的接口不检查sign
        if check_result:
            check_sign = not use_cert
            self.check_data(data, check_sign)
        return data

    def _post_resp(self, path, data, use_cert=False):
        """post发送请求，返回requests.Response对象"""
        base_data = dict(
            appid=self.appid,
            mch_id=self.mch_id,
            nonce_str=gen_random_str()
        )
        if path == '/mmpaymkttransfers/sendredpack':
            del base_data['appid']
        data.update(base_data)

        data['sign'] = self.get_sign(data)

        xml_data = dict_to_xml(data).encode('utf-8')
        if use_cert:
            if not (self.apiclient_cert_path and self.apiclient_key_path):
                raise CertError()
            apiclient_cert = (self.apiclient_cert_path,
                              self.apiclient_key_path)
        else:
            apiclient_cert = None

        if self.sandbox:
            path = '/sandboxnew' + path

        url = urljoin(self.base_url, path)

        r = requests.post(url, data=xml_data, timeout=self.request_timeout,
                          cert=apiclient_cert)
        if r.encoding == 'ISO-8859-1':
            r.encoding = 'UTF-8'
        return r

    def get_sign(self, data):
        """生成签名"""
        # 签名步骤一: 按字典序排序参数
        items = sorted(data.items(), key=lambda x: x[0])
        # items.sort(key=lambda x: x[0])
        s = '&'.join('{0}={1}'.format(key, value) for key, value in items)
        # 签名步骤二: 在string后加入KEY
        s = '{0}&key={1}'.format(s, self.key)
        # 签名步骤三: MD5加密
        result = md5(s)
        # 签名步骤四: 所有字符转为大写
        return result.upper()

    def unified_order(self, out_trade_no, total_fee, body, expire_seconds, detail=None, attach=None,
                      notify_url=None, trade_type='JSAPI', product_id=None, openid=None):
        """`统一下单
        <https://pay.weixin.qq.com/wiki/doc/api/app.php?chapter=9_1>`_

        :params out_trade_no: 商户订单号
        :params total_fee: 总金额，单位为分
        :params ip: 用户端实际ip
        :params body: 商品描述
        :params expire_seconds: 订单失效时间,最短失效时间间隔必须大于5分钟
        :params notify_url: 微信支付异步通知回调地址, 默认使用WXPAY_NOTIFY_URL的配置
        :params trade_type: JSAPI，NATIVE，APP, 默认值为JSAPI
        :params product_id: trade_type=NATIVE时（即扫码支付），此参数必传。此参数为二维码中包含的商品ID，商户自行定义。
        :params openid: 用户openid, trade_type为JSAPI时需要
        :rtype: dict
        """
        path = '/pay/unifiedorder'
        now = datetime.now()
        time_start = now.strftime('%Y%m%d%H%M%S')
        time_expire = (now + timedelta(seconds=expire_seconds)) \
            .strftime('%Y%m%d%H%M%S')

        data = dict(
            body=body,
            notify_url=notify_url or self.notify_url,
            out_trade_no=out_trade_no,
            spbill_create_ip=settings.WXPAY_SPBILL_CREATE_IP,
            total_fee=total_fee,
            trade_type=trade_type,
            time_start=time_start,
            time_expire=time_expire
        )

        if trade_type == 'JSAPI':
            if not openid:
                raise WXPayError('微信内支付需要openid')
            data['openid'] = openid
        if trade_type == 'NATIVE':
            if not product_id:
                raise WXPayError('微信扫码支付需要product_id')
            data['product_id'] = product_id

        if not detail:
            data['detail'] = detail
        if not attach:
            data['attach'] = attach

        result = self._post(path, data)

        if result['return_code'] != 'SUCCESS':
            msg = '统一下单错误, msg-{0},\ndata-{1}' \
                .format(result['return_msg'], json.dumps(data))
            raise WXPayError(msg)

        return result

    def query_order(self, out_trade_no=None, transaction_id=None):
        """`查询订单
        <https://pay.weixin.qq.com/wiki/doc/api/app/app.php?chapter=9_2&index=4>`_
        """
        path = '/pay/orderquery'
        if not (transaction_id or out_trade_no):
            raise WXPayError('查询订单需要transaction_id or out_trade_no')
        data = dict()
        if transaction_id:
            data['transaction_id'] = transaction_id
        else:
            data['out_trade_no'] = out_trade_no

        return self._post(path, data)

    def query_refund(self, out_trade_no):
        """`查询退款
        <https://pay.weixin.qq.com/wiki/doc/api/jsapi.php?chapter=9_5>`_
        """
        path = '/pay/refundquery'
        data = dict(
            out_trade_no=out_trade_no,
        )
        return self._post(path, data)

    def close_order(self, out_trade_no):
        """`关闭订单
        <https://pay.weixin.qq.com/wiki/doc/api/app.php?chapter=9_3&index=5>`_
        """
        path = '/pay/closeorder'
        data = dict(out_trade_no=out_trade_no)
        return self._post(path, data)

    def refund(self, out_trade_no, out_refund_no, total_fee, refund_fee):
        """`退款 <https://pay.weixin.qq.com/wiki/doc/api/jsapi.php?chapter=9_4>`_
        """
        path = '/secapi/pay/refund'
        data = dict(
            out_trade_no=out_trade_no,
            out_refund_no=out_refund_no,
            total_fee=total_fee,
            refund_fee=refund_fee,
        )
        return self._post(path, data, use_cert=True)

    def send_redpack(self, mch_billno, send_name, re_openid, total_amount,
                     wishing, client_ip, act_name, remark):
        """发红包

        :params mch_billno: 商户订单号
        :params send_name: 商户名称
        :params re_openid: 用户openid
        :params total_amount: 付款金额
        :params wishing: 红包祝福语
        :params client_ip: 调用接口的机器IP地址
        :params act_name: 活动名称
        :params remark: 备注信息
        """
        path = '/mmpaymkttransfers/sendredpack'
        data = dict(
            wxappid=self.appid,
            mch_billno=mch_billno,
            send_name=send_name,
            re_openid=re_openid,
            total_amount=total_amount,
            total_num=1,
            wishing=wishing,
            client_ip=client_ip,
            act_name=act_name,
            remark=remark
        )
        return self._post(path, data, use_cert=True, sendredpack=True)

    def get_redpack_info(self, mch_billno):
        """查询红包信息
        :param mch_billno: 商户订单号
        """
        path = '/mmpaymkttransfers/gethbinfo'
        data = dict(
            mch_billno=mch_billno,
            bill_type='MCHT'
        )
        return self._post(path, data, use_cert=True)

    def download_bill(self, bill_date, bill_type='ALL'):
        """`现在对账单 <https://pay.weixin.qq.com/wiki/doc/api/jsapi.php?chapter=9_6>`_

        :params bill_date: 下载对账单的日期，格式：20140603
        :params bill_type: ALL, SUCCESS, REFUND, RECHARGE_REFUND
        :return: response.Response对象
        """
        path = '/pay/downloadbill'
        data = dict(
            bill_date=bill_date,
            bill_type=bill_type,
        )
        return self._post_resp(path, data)

    def get_sign_key(self):
        """获取验签秘钥，沙箱环境下有效"""
        path = '/sandboxnew/pay/getsignkey'
        data = dict()
        return self._post(path, data, check_result=False)

    def get_app_prepay_data(self, prepay_id):
        """返回给客户端的prepay数据

        :params prepay_id: :meth:`unified_order` 接口获取到的prepay_id
        :return: prepay data
        :rtype: dict
        """
        data = dict(
            appid=self.appid,
            noncestr=gen_random_str,
            package='Sign=WXPay',
            partnerid=self.mch_id,
            prepayid=prepay_id,
            timestamp=str(int(time.time()))
        )
        data['sign'] = self.get_sign(data)
        return data

    def get_jsapi_prepay_data(self, prepay_id):
        """返回给公众号的prepay数据

        :params prepay_id: :meth:`unified_order` 接口获取到的prepay_id
        :return: prepay data
        :rtype: dict
        """
        data = dict(
            appId=self.appid,
            timeStamp=str(int(time.time())),
            nonceStr=gen_random_str(),
            package='prepay_id={0}'.format(prepay_id),
            signType='MD5',
        )
        data['paySign'] = self.get_sign(data)
        return data

    def check_sign(self, data):
        """检查微信支付回调签名是否正确"""
        if 'sign' not in data:
            return False
        tmp_data = data.copy()
        del tmp_data['sign']
        sign = self.get_sign(tmp_data)
        return data['sign'] == sign

    @staticmethod
    def notify_response(return_code='SUCCESS', return_msg='OK'):
        """通知结果的返回"""
        return dict_to_xml(return_code=return_code, return_msg=return_msg)

    def check_data(self, data, check_sign=True):
        """检查请求结果或者支付通知数据的正确性
        如果结果不合法会抛出一个WXPayError的子类

        :params data: xml转化成的dict数据
        :return: no return
        :raises ReturnCodeFail: return_code FAIL
        :raises ResultCodeFail: result_code FAIL
        :raises SignError: 签名错误

        例如处理支付回调用法::

            data = xml_to_dict(xml)
            try:
                wxpay.check_data(data)
            except SignError:
                return wxpay.notify_response('FAIL', '签名错误')
            except WXPayError:
                logger.error('微信支付数据错误', exc_info=True)
                return wxpay.notify_response('FAIL', '数据错误')

            do something handle trade
            ...

            return wxpay.notify_response()
        """
        if data['return_code'] == 'FAIL':
            raise ReturnCodeFail(data['return_msg'])
        elif data['result_code'] == 'FAIL':
            raise ResultCodeFail(data['err_code'], data['err_code_des'])
        elif check_sign and not self.check_sign(data):
            raise SignError()


    def get_WX_QR_code(self,data):
        if data['code_url']:
            res_info = data['code_url']
            # 如果成功获得支付链接，则写入一条订单记录
            # todo：自己的后台逻辑
        else:
            res_info = "二维码失效"  # 获取url失败，则二维码信息为失效

            # 根据res_info生成二维码，使用qrcode模块
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=1
        )
        qr.add_data(res_info)  # 二维码所含信息
        img = qr.make_image()  # 生成二维码图片
        byte_io = BytesIO()
        img.save(byte_io, 'PNG')  # 存入字节流
        byte_io.seek(0)
        return http.send_file(byte_io, mimetype='image/png')

