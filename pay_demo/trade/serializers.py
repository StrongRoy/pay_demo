# -*- coding: utf-8 -*-
import time
from rest_framework import serializers
from .models import OrderInfo
from pay_demo.utils.alipay import AliPay
from config.settings.local import ALIPAY_PUBLIC_KEY, APP_PRIVATE_KEY, APPID, APP_NOTIFY_URL, RETURN_URL, DEBUG


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

    def get_alipay_url(self, obj):
        alipay = AliPay(
            appid=APPID,
            app_notify_url=APP_NOTIFY_URL,
            app_private_key_path=APP_PRIVATE_KEY,
            alipay_public_key_path=ALIPAY_PUBLIC_KEY,  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            debug=DEBUG,  # 默认False,
            return_url=RETURN_URL
        )

        url = alipay.direct_pay(
            subject=obj.order_sn,
            out_trade_no=obj.order_sn,
            total_amount=obj.order_mount,
        )
        re_url = alipay.get_gateway(url)

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
