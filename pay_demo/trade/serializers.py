# -*- coding: utf-8 -*-
import time
from rest_framework import serializers
from .models import OrderInfo
from pay_demo.utils.alipay import AliPay
from pay_demo.utils.wechat import WXPay

from django.conf import settings


class OrderSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(
        default=serializers.CurrentUserDefault()
    )

    pay_status = serializers.CharField(read_only=True)
    trade_no = serializers.CharField(read_only=True)
    order_sn = serializers.CharField(read_only=True)
    pay_time = serializers.DateTimeField(read_only=True)
    seller_id = serializers.DateTimeField(read_only=True)
    alipay_url = serializers.SerializerMethodField(read_only=True)
    wechat_url = ""

    def get_alipay_url(self, obj):
        alipay = AliPay(
            appid=settings.APPID,
            app_notify_url=settings.APP_NOTIFY_URL,
            app_private_key_path=settings.APP_PRIVATE_KEY,
            alipay_public_key_path=settings.ALIPAY_PUBLIC_KEY,  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            debug=settings.DEBUG,  # 默认False,
            return_url=settings.RETURN_URL
        )

        url = alipay.direct_pay(
            subject=obj.order_sn,
            out_trade_no=obj.order_sn,
            total_amount=obj.order_mount,
        )
        re_url = alipay.get_gateway(url)

        return re_url

    def get_wechat_url(self, obj):
        wxpay = WXPay(
            base_url=settings.WXPAY_BASE_URL,
            request_timeout=settings.WXPAY_REQUEST_TIMEOUT,
            appid=settings.WX_APPID,
            mch_id=settings.WXPAY_MCHID,
            pay_key=settings.WXPAY_KEY,
            notify_url=settings.WXPAY_NOTIFY_URL,
            apiclient_cert_path=settings.WXPAY_APICLIENT_CERT_PATH,
            apiclient_key_path=settings.WXPAY_APICLIENT_KEY_PATH,

        )

        data = wxpay.unified_order(
            out_trade_no=obj.order_sn,
            total_fee=obj.order_mount,
            body=obj.post_script,
            expire_seconds=2 * 60,
        )

        # 生成二维码


        return re_url

    def generate_order_sn(self):
        # 当前时间+userid+随机数
        from random import Random
        random_ins = Random()
        order_sn = "{time_str}{userid}{ranstr}".format(time_str=time.strftime("%Y%m%d%H%M%S"),
                                                       userid=self.context["request"].user.id,
                                                       ranstr=random_ins.randint(10, 99))

        return order_sn

    def validate(self, attrs):
        attrs["order_sn"] = self.generate_order_sn()
        return attrs

    class Meta:
        model = OrderInfo
        fields = "__all__"
